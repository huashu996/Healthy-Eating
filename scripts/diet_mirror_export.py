#!/usr/bin/env python3
"""Read-only, allowlisted snapshot adapter for the private diet viewer.

Run with the diet project's Python environment. This imports its existing read
models, never its API application/lifespan, migrations, workers or providers.
Source files are only read. A private temporary copy of SQLite (+ WAL, if any)
avoids even SQLite shared-memory bookkeeping against the master database.
No personal snapshot is written unless --output is explicitly supplied.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime, time, timezone
from decimal import Decimal
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from typing import Any
from zoneinfo import ZoneInfo

NUTRIENTS = ("kcal", "protein_g", "fat_g", "carbs_g")
MAX_SAFE_INTEGER = 2**53 - 1
SITE_ROOT = Path(__file__).resolve().parents[1]
SENSITIVE_TEXT = re.compile(
    r"https?://|(?:sediment|file|library|codex)://|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|"
    r"(?:^|[\s\"'(])/(?:workspace|home|root|tmp|Users|var)/|[A-Za-z]:[\\/]|"
    r"\b(?:Bearer\s+\S+|sk-[A-Za-z0-9_-]+|(?:libfile|file|library|asset|report|meal)_[A-Za-z0-9_-]{12,})|"
    r"\b[0-9a-f]{24,}\b|\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


class ExportError(Exception):
    """The public message is deliberately fixed and contains no source values."""


def as_map(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def safe_text(value: Any, limit: int = 3000) -> str:
    if not isinstance(value, str) or SENSITIVE_TEXT.search(value):
        return ""
    return "".join(c for c in value if c in "\n\t" or ord(c) >= 32)[:limit]


# Public source citations are allowed only in menu rationale, never arbitrary
# links, URL query strings, bearer links or private source identifiers.
RATIONALE_PUBLIC_URLS = frozenset({
    "https://ods.od.nih.gov/factsheets/Omega3FattyAcids-HealthProfessional/",
    "https://ods.od.nih.gov/factsheets/VitaminC-HealthProfessional/",
    "https://ods.od.nih.gov/factsheets/Calcium-HealthProfessional/",
    "https://ods.od.nih.gov/factsheets/ExerciseAndAthleticPerformance-HealthProfessional/",
    "https://ods.od.nih.gov/factsheets/WYNTK-Consumer/",
    "https://www.who.int/news-room/fact-sheets/detail/healthy-diet",
})

def safe_rationale(value: Any) -> str:
    if not isinstance(value, str): return ""
    urls = re.findall(r"https?://[^\s]+", value)
    if any(url not in RATIONALE_PUBLIC_URLS for url in urls): return ""
    scrubbed = value
    for url in urls: scrubbed = scrubbed.replace(url, "PUBLIC_REFERENCE")
    if SENSITIVE_TEXT.search(scrubbed): return ""
    return "".join(c for c in value if c in "\n\t" or ord(c) >= 32)[:3000]


def safe_texts(value: Any, limit: int = 40) -> list[str]:
    return [text for item in as_list(value)[:limit] if (text := safe_text(item))]


def number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0 or value > MAX_SAFE_INTEGER:
        return None
    return int(value) if value == int(value) else value


def count(value: Any) -> int:
    result = number(value)
    return result if isinstance(result, int) else 0


def nutrients(value: Any, *, ranges: bool = False) -> dict:
    value = as_map(value)
    result = {}
    for key in NUTRIENTS:
        if not ranges:
            result[key] = number(value.get(key))
            continue
        item = as_map(value.get(key))
        low, high = number(item.get("low")), number(item.get("high"))
        if low is None or high is None or low > high:
            result[key] = None
        else:
            result[key] = {"low": low, "high": high}
            if "coverage" in item:
                result[key]["coverage"] = count(item["coverage"])
    return result


def iso_day(value: Any) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def iso_stamp(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            return None
        return stamp.isoformat()
    except ValueError:
        return None


def project_day(raw: dict, *, detail: bool = False) -> dict:
    raw = as_map(raw)
    day = iso_day(raw.get("date"))
    if day is None:
        raise ExportError("Source returned an invalid dietary date.")
    score = number(raw.get("score"))
    # The calendar read model alone decides whether a stored score is valid.
    if raw.get("score_status") != "saved" or score is None or score > 100:
        score = None
    estimate = number(raw.get("estimated_score")) if raw.get("score_status") == "estimated" else None
    if estimate is not None and (estimate > 100 or raw.get("pending_changes") or raw.get("is_future") or not count(raw.get("meals")) or raw.get("analyzed") != raw.get("meals")):
        estimate = None
    display_score = score if score is not None else estimate
    def parts(value):
        return [{"key": safe_text(p.get("key"), 80), "name": safe_text(p.get("name"), 80), "points": p.get("points") if isinstance(p.get("points"), (int,float)) and not isinstance(p.get("points"), bool) and -100 <= p["points"] <= 100 else None, "maximum": number(p.get("maximum")) or 0, "reason": safe_text(p.get("reason"), 600)} for p in as_list(value) if isinstance(p, dict)]
    result = {
        "date": day, "meals": count(raw.get("meals")), "analyzed": count(raw.get("analyzed")),
        "finished": raw.get("finished") is True, "totals": nutrients(raw.get("totals"), ranges=True),
        "target": nutrients(raw.get("target")), "score": score,
        "score_status": "saved" if score is not None else "estimated" if estimate is not None else "unscored",
        "estimated_score": estimate, "estimated_components": parts(raw.get("estimated_components")) if estimate is not None else [],
        "estimate_notice": safe_text(raw.get("estimate_notice"), 600) if estimate is not None else "",
        "score_band": ("green" if display_score >= 85 else "yellow" if display_score >= 70 else "red") if display_score is not None and raw.get("score_scope") != "recorded_partial" else "neutral",
        "score_maximum": number(raw.get("score_maximum", 100)) if score is not None else None,
        "score_coverage_pct": number(raw.get("score_coverage_pct", 100)) if score is not None else 0,
        "score_scope": safe_text(raw.get("score_scope", "recorded_full") if score is not None else "unavailable", 80),
        "state": safe_text(raw.get("state"), 160), "pending_changes": raw.get("pending_changes") is True,
        "is_future": raw.get("is_future") is True,
        "score_version": safe_text(raw.get("score_version"), 100) or None,
        "score_method": safe_text(raw.get("score_method")),
        "components": parts(raw.get("components")),
        "score_limitations": safe_texts(raw.get("score_limitations")),
    }
    if detail:
        result["entries"] = []
        for item in as_list(raw.get("entries")):
            item = as_map(item)
            result["entries"].append({
                "title": safe_text(item.get("title"), 300), "meal_type": safe_text(item.get("meal_type"), 100),
                "eaten_at": iso_stamp(item.get("eaten_at")), "eaten_fraction": number(item.get("eaten_fraction")),
                "nutrition": nutrients(item.get("nutrition"), ranges=True),
            })
    return result


def project_menu(overview: dict) -> dict:
    plan = as_map(as_map(overview).get("daily_plan"))
    data = as_map(plan.get("data"))
    menu = as_map(data.get("next_meal"))
    preview = data.get("plan_mode") == "test_preview"
    result = {
        "available": bool(menu), "title": safe_text(menu.get("title"), 300),
        "reference_date": iso_day(menu.get("reference_date") or data.get("target_date")),
        "plan_mode": safe_text(data.get("plan_mode"), 80), "plan_scope": safe_text(menu.get("plan_scope"), 80),
        "valid_for_use": bool(menu) and menu.get("valid_for_use") is True and not preview,
        "quantification_status": safe_text(menu.get("quantification_status"), 100),
        "reason": safe_rationale(menu.get("reason_summary") or menu.get("reason")),
        "caveat": safe_text(menu.get("caveat")), "recipes": [],
        "daily_nutrition": nutrients(menu.get("daily_nutrition")),
    }
    if menu.get("stale_reason_code") == "target_mismatch":
        result.update(available=False, valid_for_use=False, recipes=[],
                      daily_nutrition=nutrients({}), reason=safe_text(menu.get("stale_reason")),
                      quantification_status="stale")
        return result
    for recipe in as_list(menu.get("recipes")):
        recipe = as_map(recipe)
        steps = safe_texts(recipe.get("steps"))
        if not steps and (preparation := safe_text(recipe.get("preparation"))):
            steps = [preparation]
        result["recipes"].append({
            "meal_type": safe_text(recipe.get("meal_type"), 100),
            "title": safe_text(recipe.get("dish_title") or recipe.get("title"), 300),
            "items": [{
                "name": safe_text(as_map(item).get("name"), 300),
                "quantity_g": number(as_map(item).get("quantity")) if as_map(item).get("unit") == "g" else None,
                "state": safe_text(as_map(item).get("weight_basis"), 1000),
                "nutrition": nutrients(as_map(item).get("nutrition")),
            } for item in as_list(recipe.get("items"))],
            "nutrition": nutrients(recipe.get("nutrition")), "steps": steps,
            "why": safe_text(recipe.get("why") or recipe.get("reason")),
        })
    return result


def project_profile(overview: dict) -> dict:
    """Only the three existing profile tiles; never export health-state objects."""
    metrics = as_map(as_map(overview).get("current_metrics"))
    result = {}
    for destination, source in (("height_cm", "身高"), ("weight_kg", "体重"), ("body_fat_pct", "体脂率")):
        value = metrics.get(source)
        if isinstance(value, str):
            text = value.strip()
            value = float(text) if re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)", text) else None
        result[destination] = number(value)
    return result


def project_payload(overview: dict, calendars: list[dict], details: dict[str, dict], today: str) -> dict:
    """A positive allowlist, never recursive removal from a raw app response."""
    if iso_day(today) is None or today not in details:
        raise ExportError("Source did not provide the current dietary day.")
    days = {key: project_day(value, detail=True) for key, value in sorted(details.items()) if iso_day(key)}
    current = days[today]
    return {
        "timezone": "Asia/Shanghai", "rollover_hour": 7, "today": today,
        "profile": project_profile(overview),
        "body_measurements": {key: [{"date": p["date"], "value": p["value"], "recorded_at": p["recorded_at"]} for p in as_map(overview.get("body_measurements")).get(key, []) if iso_day(p.get("date")) and number(p.get("value")) is not None] for key in ("weight", "body_fat")},
        "overview": {
            "date": today, "meals_count": current["meals"], "analyzed_count": current["analyzed"],
            "finished": current["finished"], "totals": current["totals"], "target": current["target"],
        },
        "menu": project_menu(overview),
        "months": [{
            "month": safe_text(month.get("month"), 7), "first_weekday": count(month.get("first_weekday")),
            "recorded_days": count(month.get("recorded_days")),
            "days": [project_day(day) for day in as_list(month.get("days"))],
        } for month in calendars],
        "days": days,
    }


def canonical(value: Any) -> str:
    """JSON.stringify-compatible canonical JSON for the ASCII-keyed contract.

    Python emits 1.0 and zero-padded exponents; JavaScript emits 1 and 1e-7.
    Normalize those forms and its fixed-point interval before hashing.
    """
    if value is None or isinstance(value, (str, bool, int)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Nonfinite number")
        if value == 0:
            return "0"
        if 1e-6 <= abs(value) < 1e21:
            fixed = format(Decimal(str(value)), "f")
            return fixed.rstrip("0").rstrip(".") if "." in fixed else fixed
        mantissa, exponent = repr(value).lower().split("e")
        mantissa = mantissa.removesuffix(".0")
        exponent_int = int(exponent)
        return mantissa + "e" + ("+" if exponent_int >= 0 else "-") + str(abs(exponent_int))
    if isinstance(value, list):
        return "[" + ",".join(canonical(item) for item in value) + "]"
    if isinstance(value, dict):
        if any(not isinstance(key, str) or not key.isascii() for key in value):
            raise ValueError("Contract keys must be ASCII strings")
        return "{" + ",".join(canonical(key) + ":" + canonical(value[key]) for key in sorted(value)) + "}"
    raise ValueError("Unsupported JSON value")


def content_hash(payload: dict) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return canonical(value).encode("utf-8")


def stat_fingerprint(paths: list[Path]) -> tuple:
    return tuple((str(path), path.stat().st_dev, path.stat().st_ino, path.stat().st_size, path.stat().st_mtime_ns)
                 for path in paths)


def database_paths(database: Path) -> list[Path]:
    return [path for path in (database, Path(str(database) + "-wal"), Path(str(database) + "-journal")) if path.exists()]


@contextmanager
def readonly_copy(database: Path):
    """Never open the source with SQLite, including its potentially writable SHM."""
    if not database.is_file():
        raise ExportError("Source database is unavailable.")
    with tempfile.TemporaryDirectory(prefix="diet-export-") as directory:
        target = Path(directory) / "platform.sqlite3"
        for _attempt in range(3):
            paths = database_paths(database)
            before = stat_fingerprint(paths)
            # A hot rollback journal needs recovery, which is not an export action.
            if any(path.name.endswith("-journal") and path.stat().st_size for path in paths):
                raise ExportError("Source database requires recovery before export.")
            for path in paths:
                destination = Path(str(target) + str(path)[len(str(database)):])
                with destination.open("wb") as stream:
                    os.chmod(destination, 0o600)
                    with path.open("rb") as source:
                        while chunk := source.read(1024 * 1024):
                            stream.write(chunk)
            after_paths = database_paths(database)
            if paths == after_paths and before == stat_fingerprint(after_paths):
                break
            for path in Path(directory).iterdir():
                path.unlink()
        else:
            raise ExportError("Source changed while reading; retry after its current write finishes.")
        con = sqlite3.connect(target.as_uri() + "?mode=ro", uri=True, timeout=15)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only=ON")
        con.execute("BEGIN")
        try:
            yield con, max(item[4] for item in before), before
        finally:
            con.rollback()
            con.close()


@contextmanager
def source_models(project: Path, connection: sqlite3.Connection, data_root: Path | None = None):
    """Patch before importing diet read models and prohibit initialization."""
    prior_bytecode, prior_path = sys.dont_write_bytecode, list(sys.path)
    prior_modules = {key: value for key, value in sys.modules.items() if key == "app" or key.startswith("app.")}
    for key in prior_modules:
        del sys.modules[key]
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(project / "apps/api"))
    originals = []
    try:
        config = importlib.import_module("app.config")
        db = importlib.import_module("app.db")
        config.DATA = data_root or project / json.loads((project / "config.json").read_text(encoding="utf-8"))["data_root"]

        @contextmanager
        def connect():
            yield connection

        def denied(*_args, **_kwargs):
            raise ExportError("Source write or initialization attempted during export.")

        for module, name, replacement in ((db, "connect", connect), (db, "init", denied), (config, "directories", denied)):
            originals.append((module, name, getattr(module, name)))
            setattr(module, name, replacement)
        yield (db, importlib.import_module("app.diet"), importlib.import_module("app.diet_calendar"),
               importlib.import_module("app.diet_day"))
    finally:
        for module, name, original in originals:
            setattr(module, name, original)
        for key in list(sys.modules):
            if key == "app" or key.startswith("app."):
                del sys.modules[key]
        sys.modules.update(prior_modules)
        sys.path[:] = prior_path
        sys.dont_write_bytecode = prior_bytecode


def source_timestamp(connection: sqlite3.Connection, mtime_ns: int) -> datetime:
    stamps = [datetime.fromtimestamp(mtime_ns / 1_000_000_000, timezone.utc)]
    for table, column in (("records", "updated_at"), ("records", "deleted_at"), ("reports", "created_at")):
        for row in connection.execute(f'SELECT "{column}" FROM "{table}" WHERE module=\'diet\''):
            stamp = iso_stamp(row[0])
            if stamp:
                stamps.append(datetime.fromisoformat(stamp).astimezone(timezone.utc))
    return max(stamps)


def snapshot_version(source_updated_at: datetime, today: str) -> int:
    boundary = datetime.combine(date.fromisoformat(today), time(7), ZoneInfo("Asia/Shanghai"))
    latest = max(source_updated_at.astimezone(timezone.utc), boundary.astimezone(timezone.utc))
    delta = latest - datetime(1970, 1, 1, tzinfo=timezone.utc)
    result = (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
    if not 0 < result <= MAX_SAFE_INTEGER:
        raise ExportError("Source version is outside the supported range.")
    return result


def export_snapshot(source_project: Path | str, *, data_root: Path | str | None = None,
                    revision: int | None = None, source_updated_at: str | datetime | None = None) -> dict:
    project = Path(source_project).resolve(strict=True)
    config = json.loads((project / "config.json").read_text(encoding="utf-8"))
    data = Path(data_root).resolve(strict=True) if data_root is not None else (project / config["data_root"]).resolve(strict=True)
    database = (data / "database/platform.sqlite3").resolve(strict=True)
    if revision is not None and (isinstance(revision, bool) or not isinstance(revision, int) or not 0 < revision <= MAX_SAFE_INTEGER):
        raise ExportError("Source revision is outside the supported range.")
    if isinstance(source_updated_at, datetime):
        source_updated_at = source_updated_at.isoformat()
    if source_updated_at is not None and not iso_stamp(source_updated_at):
        raise ExportError("Source timestamp must include a timezone.")
    with readonly_copy(database) as (connection, mtime_ns, fingerprint):
        updated = datetime.fromisoformat(source_updated_at).astimezone(timezone.utc) if source_updated_at else source_timestamp(connection, mtime_ns)
        with source_models(project, connection, data) as (_db, diet, calendar, day_model):
            if day_model.TIMEZONE != "Asia/Shanghai" or day_model.ROLLOVER_HOUR != 7:
                raise ExportError("Source day-boundary policy differs from the viewer contract.")
            today, actual_meals, _reports = calendar._load()
            first = min([today] + [day_model.meal_diet_date(meal) for meal in actual_meals])
            month = first.replace(day=1)
            calendars, details = [], {}
            while month <= today:
                view = calendar.calendar(month.strftime("%Y-%m"))
                calendars.append(view)
                for day in view["days"]:
                    # Future cells are neutral; no detail or projected intake exists.
                    if day["date"] <= today.isoformat():
                        details[day["date"]] = calendar.day_detail(day["date"])
                month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
            overview = diet.overview()  # Also applies the source's stale-menu rules.
            # Calendar target is authoritative and excludes preview targets.
            payload = project_payload(overview, calendars, details, today.isoformat())
            if day_model.current_diet_day() != today:
                raise ExportError("Dietary day changed during export; retry.")
        if stat_fingerprint(database_paths(database)) != fingerprint:
            raise ExportError("Source changed during export; retry.")
        return {
            "schema_version": 1, "snapshot_version": revision if revision is not None else snapshot_version(updated, today.isoformat()),
            "content_hash": content_hash(payload), "source_updated_at": updated.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(), "payload": payload,
        }


def write_snapshot(snapshot: dict, output: Path, source_project: Path) -> None:
    target = output.resolve()
    if target.is_relative_to(SITE_ROOT) or target.is_relative_to(source_project.resolve()):
        raise ExportError("Snapshot output must be outside the Site and source project.")
    if output.is_symlink() or not target.parent.is_dir():
        raise ExportError("Snapshot output must have an existing private parent directory.")
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, prefix=".diet-snapshot-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            os.chmod(temporary, 0o600)
            stream.write(canonical(snapshot) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-project", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, help="Explicit source data root, for the source outbox integration")
    parser.add_argument("--revision", type=int, help="Durable revision assigned by the source transaction")
    parser.add_argument("--source-updated-at", help="Timezone-aware timestamp assigned by the source transaction")
    parser.add_argument("--output", type=Path, help="Explicit private runtime path outside both projects; otherwise stdout")
    args = parser.parse_args(argv)
    try:
        snapshot = export_snapshot(args.source_project, data_root=args.data_root, revision=args.revision,
                                   source_updated_at=args.source_updated_at)
        if args.output:
            write_snapshot(snapshot, args.output, args.source_project)
        else:
            sys.stdout.write(canonical(snapshot) + "\n")
        return 0
    except Exception:
        # Do not expose raw source exceptions, paths, SQL or nutrition in logs.
        sys.stderr.write("Diet export failed; source was not modified. Check the read-only adapter and source availability.\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
