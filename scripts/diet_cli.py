#!/usr/bin/env python3
"""Diet batch runner. No listener, model provider, or scheduler is started.
Mirror compatibility commands are disabled and never send data.
The standalone exporter can create a local read-only snapshot.

Every command emits one JSON value. Errors go to stderr (exit 2; conflict 3).
Ingest input: {channel, message_id, images: [absolute paths], meal: {...},
              analysis?: MealVisionOutput}.
Meal.assets is managed by the CLI. In optional analysis, source_ids may be []
(or omitted); the CLI binds it to the committed meal. An ingest is immutable
by channel/message_id; add analysis later using the same input or `analysis`.
Standalone `analysis --input` accepts the complete AnalysisWrite API envelope,
including version, image_refs, idempotency_key and analysis. It never guesses
versions or nutrition. Run `--help` for all commands.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from datetime import date, datetime, timezone
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import sys
import tempfile
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image, UnidentifiedImageError  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from app import config, db, schemas, food_catalog, diet_day, diet_planning  # noqa: E402
from app.external_api import AnalysisWrite  # noqa: E402
from app.main import app  # noqa: E402

BACKUP_FORMAT = "diet-dot-data-backup"


class CLIError(Exception):
    def __init__(self, code: str, message: str, status: int = 2):
        super().__init__(message)
        self.code, self.status = code, status


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CLIError("invalid_json", "JSON contains duplicate keys")
        result[key] = value
    return result


def read_json(path: Path, *, max_bytes: int = 200_000) -> dict:
    if path.stat().st_size > max_bytes:
        raise CLIError("input_too_large", "JSON input exceeds its permitted size")
    def reject_constant(_value):
        raise CLIError("invalid_json", "JSON values must be finite")
    result = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs,
                        parse_constant=reject_constant)
    if not isinstance(result, dict):
        raise CLIError("invalid_json", "Expected a JSON object")
    return result


def api(client: TestClient, method: str, path: str, **kwargs):
    response = client.request(method, path, **kwargs)
    payload = response.json()
    if response.status_code >= 400:
        raise CLIError(payload.get("code", "api_error"), payload.get("message", "API request failed"),
                       3 if response.status_code == 409 else 2)
    return payload


@contextmanager
def local_client():
    # ASGI transport is entirely in-process. Lifespan only initializes SQLite.
    with TestClient(app, raise_server_exceptions=False) as client:
        session = api(client, "GET", "/api/v1/session")
        client.headers["x-csrf-token"] = session["csrf_token"]
        yield client


@contextmanager
def batch_lock():
    config.directories()
    lock = config.DATA / "runtime/diet-cli.lock"
    with lock.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def fsync_dir(path: Path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def safe_asset_path(root: Path, key: str) -> Path:
    if not isinstance(key, str) or not key or Path(key).name != key or key in (".", "..") or "\\" in key:
        raise CLIError("unsafe_path", "Invalid asset storage path")
    base = root / "assets"
    path = base / key
    if base.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(base.resolve()):
        raise CLIError("unsafe_path", "Symlink or escaping asset path")
    return path


def verified_asset(root: Path, asset: dict) -> Path:
    path = safe_asset_path(root, asset["storage_key"])
    if not path.is_file() or path.stat().st_size != asset["size"] or sha(path.read_bytes()) != asset["sha256"]:
        raise CLIError("asset_changed", "Stored asset is missing or its hash changed", 3)
    return path


def normalize_image(path_string: str) -> dict:
    if not isinstance(path_string, str) or not Path(path_string).is_absolute():
        raise CLIError("invalid_image_path", "Image paths must be absolute")
    path = Path(path_string)
    if not path.is_file():
        raise CLIError("invalid_image_path", "Image file does not exist")
    if path.stat().st_size > config.MAX_UPLOAD:
        raise CLIError("file_too_large", "Each image must be at most 12 MB")
    with path.open("rb") as stream:
        original = stream.read(config.MAX_UPLOAD + 1)
    if len(original) > config.MAX_UPLOAD:
        raise CLIError("file_too_large", "Each image must be at most 12 MB")
    expected = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}.get(path.suffix.lower())
    if expected is None:
        raise CLIError("invalid_image", "Supported image formats: JPG, PNG, WebP")
    try:
        # Exactly the original upload API's format, pixel limit and EXIF removal.
        Image.MAX_IMAGE_PIXELS = 25_000_000
        with Image.open(io.BytesIO(original)) as picture:
            if picture.width * picture.height > 25_000_000 or picture.format != expected:
                raise ValueError()
            picture.load()
            out = io.BytesIO()
            picture.convert("RGB").save(out, format="JPEG", quality=92)
        raw = out.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise CLIError("invalid_image", "Image is damaged, mismatched, or too large") from exc
    digest = sha(raw)
    return {"original_sha256": sha(original), "sha256": digest, "raw": raw,
            "id": sha(("diet-cli:asset:" + digest).encode())[:32],
            "storage_key": "cli-" + digest + ".jpg", "original_name": path.name}


def write_asset(image: dict):
    path = safe_asset_path(config.DATA, image["storage_key"])
    if path.exists():
        if sha(path.read_bytes()) != image["sha256"]:
            raise CLIError("asset_changed", "Content-addressed asset has different bytes", 3)
        return
    fd, temporary = tempfile.mkstemp(prefix=".cli-tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(image["raw"])
            stream.flush()
            os.fsync(stream.fileno())
        # No existing file is replaced. All CLI writers hold the batch lock.
        os.link(temporary, path)
        fsync_dir(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def fault_point(_name: str):
    """Test seam for crash/retry checks; production deliberately does nothing."""


def ingest(client: TestClient, payload: dict) -> dict:
    unknown = set(payload) - {"channel", "message_id", "images", "meal", "analysis", "received_at"}
    if unknown or not {"channel", "message_id", "images", "meal"} <= payload.keys():
        raise CLIError("invalid_ingest", "Required fields: channel, message_id, images, meal; optional: analysis, received_at")
    for field in ("channel", "message_id"):
        if not isinstance(payload[field], str) or not payload[field].strip() or len(payload[field]) > 1000:
            raise CLIError("invalid_ingest", "channel and message_id must be nonempty strings, at most 1000 characters")
    if not isinstance(payload["images"], list) or len(payload["images"]) > 6:
        raise CLIError("invalid_ingest", "images must be a list of at most six absolute paths")
    if not isinstance(payload["meal"], dict) or "assets" in payload["meal"]:
        raise CLIError("invalid_ingest", "meal must be an object; its assets are managed by the CLI")
    base_meal = schemas.Meal.model_validate(payload["meal"]).model_dump(mode="json")
    if payload.get("received_at") is not None:
        received = diet_day.aware_datetime(payload["received_at"])
        if base_meal.get("received_at") and diet_day.aware_datetime(base_meal["received_at"]) != received:
            raise CLIError("invalid_ingest", "Message and meal received_at must agree")
        base_meal["received_at"] = received.isoformat()
    # Derived values are assigned only after checking the original receipt.
    # New absent defaults must not change pre-boundary idempotency fingerprints.
    for field in ("diet_date", "received_at"):
        if base_meal.get(field) is None:
            base_meal.pop(field, None)
    food_catalog.validate_meal_refs(base_meal.get("product_refs", []))
    if not base_meal.get("product_refs"):
        # Keep fingerprints of pre-catalogue ingests unchanged on replay.
        base_meal.pop("product_refs", None)
    token = sha(canonical([payload["channel"], payload["message_id"]]).encode())
    key, meal_id = "cli:ingest:" + token, sha(("diet-cli:meal:" + token).encode())[:32]
    images = [normalize_image(path) for path in payload["images"]]
    # Repeated copies of the same image in a message are one asset/reference.
    images = list({image["original_sha256"]: image for image in images}.values())
    fingerprint = sha(canonical({"meal": base_meal, "images": [i["original_sha256"] for i in images]}).encode())
    analysis = payload.get("analysis")
    if analysis is not None:
        if not isinstance(analysis, dict):
            raise CLIError("invalid_analysis", "analysis must be a MealVisionOutput object")
        if analysis.get("source_ids") not in (None, [], [meal_id]):
            raise CLIError("invalid_citations", "Ingest analysis must refer only to the new meal")
        analysis = schemas.MealVisionOutput.model_validate({**analysis, "source_ids": [meal_id]}).model_dump(mode="json")
    with db.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        prior = con.execute("SELECT value FROM runtime WHERE key=?", (key,)).fetchone()
        if prior:
            receipt = json.loads(prior["value"])
            if receipt["request_sha256"] != fingerprint:
                raise CLIError("idempotency_conflict", "This channel/message_id already has different meal or image content", 3)
            meal = db.get_record(receipt["meal_id"], "meals", con)
            if meal["version"] != receipt["version"] or sha(canonical(meal["data"]).encode()) != receipt["meal_sha256"]:
                raise CLIError("version_conflict", "The ingested meal was subsequently edited; use its current version explicitly", 3)
            assets = []
            for ref in receipt["image_refs"]:
                row = con.execute("SELECT * FROM assets WHERE id=?", (ref["id"],)).fetchone()
                if not row or row["sha256"] != ref["sha256"]:
                    raise CLIError("asset_changed", "Ingested asset no longer matches", 3)
                verified_asset(config.DATA, dict(row))
                assets.append(ref)
            reused = True
        else:
            assets = []
            for image in images:
                row = con.execute("SELECT * FROM assets WHERE sha256=? AND module='diet' AND project_id IS NULL ORDER BY created_at,id LIMIT 1", (image["sha256"],)).fetchone()
                if row:
                    verified_asset(config.DATA, dict(row))
                    asset_id = row["id"]
                else:
                    write_asset(image)
                    asset_id = image["id"]
                    con.execute("INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?)", (
                        asset_id, image["storage_key"], "image/jpeg", len(image["raw"]), image["sha256"],
                        "diet", None, db.now(), image["original_name"]))
                    db.audit(con, "asset.imported", asset_id, {"module": "diet", "size": len(image["raw"]), "provider": "cli"})
                if asset_id not in {ref["id"] for ref in assets}:
                    assets.append({"id": asset_id, "sha256": image["sha256"]})
            data = schemas.Meal.model_validate(diet_day.assign_diet_date({**base_meal, "assets": [a["id"] for a in assets]})).model_dump(mode="json")
            stamp = db.now()
            # Original create API has no idempotency parameter. Atomic insertion
            # mirrors db.save_record, including version, revision and audit.
            con.execute("INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,NULL)",
                        (meal_id, "meals", "diet", None, 1, db.encode(data), stamp, stamp, "live"))
            con.execute("INSERT INTO revisions VALUES(?,?,?,?)", (meal_id, 1, db.encode(data), stamp))
            db.audit(con, "record.saved", meal_id, {"kind": "meals", "version": 1})
            receipt = {"schema_version": 1, "request_sha256": fingerprint, "meal_id": meal_id,
                       "version": 1, "meal_sha256": sha(canonical(data).encode()), "image_refs": assets}
            con.execute("INSERT INTO runtime(key,value) VALUES(?,?)", (key, db.encode(receipt)))
            db.audit(con, "cli.message_ingested", meal_id, {"receipt_key": key})
            meal, reused = db.get_record(meal_id, "meals", con), False
            fault_point("before_ingest_commit")
    fault_point("after_ingest_commit")
    result = {"meal": meal, "image_refs": assets, "reused": reused}
    if analysis is not None:
        result["analysis"] = api(client, "POST", f"/api/v1/diet/meals/{meal_id}/analysis", json={
            "version": receipt["version"], "image_refs": assets,
            "idempotency_key": "cli:message:" + token + ":analysis:v1", "analysis": analysis})
        fault_point("after_analysis_commit")
    return result


def source_files() -> dict:
    paths = [ROOT / "config.json", ROOT / "requirements.lock", ROOT / "scripts/diet_cli.py", ROOT / "scripts/diet_mirror_export.py",
             ROOT / "apps/api/app/diet_policy.json", ROOT / "SKILL.md"]
    paths += list((ROOT / "apps/api/app").glob("*.py"))
    paths += list((ROOT / "apps/api/migrations").glob("*.sql"))
    paths += list((ROOT / "apps/api/app/data").glob("*"))
    paths += list((ROOT / "apps/api/app/recipe_seeds").glob("*.json"))
    return {str(path.relative_to(ROOT)): sha(path.read_bytes()) for path in sorted(paths)}


def ensure_new_destination(path: Path):
    if path.exists() or path.is_symlink():
        raise CLIError("destination_exists", "Destination must be a completely new path; existing data is never overwritten", 3)
    if not path.parent.is_dir():
        raise CLIError("missing_parent", "Destination parent directory must already exist")


def integrity(con: sqlite3.Connection):
    if con.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise CLIError("database_corrupt", "SQLite integrity check failed")
    if con.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise CLIError("database_corrupt", "SQLite foreign-key check failed")


def readonly_db(path: Path, *, immutable: bool = False):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro" + ("&immutable=1" if immutable else ""), uri=True, timeout=15)


def backup(output: Path) -> dict:
    ensure_new_destination(output)
    stage = Path(tempfile.mkdtemp(prefix=".diet-backup-", dir=output.parent))
    try:
        (stage / "database").mkdir()
        (stage / "assets").mkdir()
        destination = stage / "database/platform.sqlite3"
        # Hold a writer reservation throughout snapshot + asset copying. API
        # deletes acquire this same SQLite lock before removing asset files.
        with db.connect() as guard:
            guard.execute("BEGIN IMMEDIATE")
            with closing(readonly_db(config.DATA / "database/platform.sqlite3")) as source, closing(sqlite3.connect(destination)) as snapshot:
                source.backup(snapshot)
                snapshot.execute("PRAGMA journal_mode=DELETE")
                integrity(snapshot)
                asset_rows = snapshot.execute("SELECT storage_key,size,sha256 FROM assets ORDER BY id").fetchall()
                versions = [r[0] for r in snapshot.execute("SELECT version FROM schema_migrations ORDER BY version")]
                for storage_key, size, digest in asset_rows:
                    path = verified_asset(config.DATA, {"storage_key": storage_key, "size": size, "sha256": digest})
                    shutil.copyfile(path, stage / "assets" / storage_key)
        for folder in ("reference_materials", "planning_audits"):
            source_dir = config.DATA / folder
            if source_dir.exists():
                if source_dir.is_symlink() or any(p.is_symlink() for p in source_dir.rglob("*")):
                    raise CLIError("unsafe_path", "Private reference data contains a symlink")
                shutil.copytree(source_dir, stage / folder)
        files = {str(path.relative_to(stage)): {"sha256": sha(path.read_bytes()), "size": path.stat().st_size}
                 for path in sorted(stage.rglob("*")) if path.is_file()}
        manifest = {"format": BACKUP_FORMAT, "version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
                    "files": files, "schema_versions": versions, "source_files": source_files(),
                    "restore_contract": {"source_included": False, "requires_matching_source": True,
                                         "target_must_not_exist": True,
                                         "contents": "SQLite snapshot (including receipts/revisions/audit), database-listed assets, reference material index/originals and planning audits. Obtain the matching source bundle separately."}}
        (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for path in stage.rglob("*"):
            if path.is_file():
                os.chmod(path, 0o600)
                with path.open("rb") as stream:
                    os.fsync(stream.fileno())
        fsync_dir(stage / "database")
        fsync_dir(stage / "assets")
        fsync_dir(stage)
        ensure_new_destination(output)
        # mkdir claims the destination without replacing a racing writer's path.
        output.mkdir(mode=0o700)
        for child in stage.iterdir():
            os.rename(child, output / child.name)
        stage.rmdir()
        fsync_dir(output)
        fsync_dir(output.parent)
        return {"backup": str(output.resolve()), "files": len(files), "source_included": False,
                "manifest_sha256": sha((output / "manifest.json").read_bytes())}
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def validate_backup(bundle: Path) -> dict:
    if bundle.is_symlink() or not bundle.is_dir() or (bundle / "manifest.json").is_symlink():
        raise CLIError("unsafe_path", "Backup must be a real directory with a regular manifest")
    manifest = read_json(bundle / "manifest.json", max_bytes=64 * 1024 * 1024)
    if manifest.get("format") != BACKUP_FORMAT or manifest.get("version") != 1:
        raise CLIError("invalid_backup", "Unsupported backup format")
    files = manifest.get("files")
    if not isinstance(files, dict) or "database/platform.sqlite3" not in files:
        raise CLIError("invalid_backup", "Backup is missing its database")
    for relative, info in files.items():
        parts = PurePosixPath(relative).parts
        if (relative != "database/platform.sqlite3" and not (len(parts) == 2 and parts[0] == "assets") and not (len(parts) >= 2 and parts[0] in ("reference_materials", "planning_audits"))) or any(p in (".", "..") for p in parts) or "\\" in relative or str(PurePosixPath(relative)) != relative:
            raise CLIError("unsafe_path", "Manifest contains an invalid relative path")
        path = bundle / relative
        if any((bundle / Path(*parts[:i])).is_symlink() for i in range(1, len(parts) + 1)) or not path.resolve().is_relative_to(bundle.resolve()):
            raise CLIError("unsafe_path", "Manifest refers to a symlink or escaping path")
        if not isinstance(info, dict) or not path.is_file() or path.stat().st_size != info.get("size") or sha(path.read_bytes()) != info.get("sha256"):
            raise CLIError("hash_mismatch", "Backup file is missing, truncated, or has a hash mismatch")
    actual = set()
    for path in bundle.rglob("*"):
        if path.is_symlink():
            raise CLIError("unsafe_path", "Backup contains a symlink")
        if path.is_file():
            actual.add(str(path.relative_to(bundle)))
    if actual != set(files) | {"manifest.json"}:
        raise CLIError("invalid_backup", "Backup contains files absent from the manifest")
    if manifest.get("source_files") != source_files():
        raise CLIError("source_mismatch", "Restore requires the matching application source bundle; source hashes differ", 3)
    with closing(readonly_db(bundle / "database/platform.sqlite3", immutable=True)) as con:
        integrity(con)
        expected = {"database/platform.sqlite3"}
        for key, size, digest in con.execute("SELECT storage_key,size,sha256 FROM assets"):
            verified_asset(bundle, {"storage_key": key, "size": size, "sha256": digest})
            expected.add("assets/" + key)
        if expected != {f for f in files if not f.startswith(("reference_materials/", "planning_audits/"))}:
            raise CLIError("invalid_backup", "Manifest assets do not match the database snapshot")
        versions = [r[0] for r in con.execute("SELECT version FROM schema_migrations ORDER BY version")]
        if versions != manifest.get("schema_versions"):
            raise CLIError("invalid_backup", "Schema versions do not match the snapshot")
    return manifest


def restore(bundle: Path, target: Path) -> dict:
    ensure_new_destination(target)
    manifest = validate_backup(bundle)
    stage = Path(tempfile.mkdtemp(prefix=".diet-restore-", dir=target.parent))
    claimed = False
    try:
        for relative, info in manifest["files"].items():
            path = stage / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(bundle / relative, path)
            os.chmod(path, 0o600)
            if sha(path.read_bytes()) != info["sha256"]:
                raise CLIError("hash_mismatch", "Backup changed while restoring")
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
        for name in ("assets", "exports", "backups", "runtime", "agent-work"):
            (stage / name).mkdir(exist_ok=True)
        # Verify the staged copy again before publishing any data to target.
        with closing(readonly_db(stage / "database/platform.sqlite3", immutable=True)) as con:
            integrity(con)
        for directory in stage.iterdir():
            if directory.is_dir():
                fsync_dir(directory)
        fsync_dir(stage)
        ensure_new_destination(target)
        target.mkdir(mode=0o700)
        claimed = True
        for child in stage.iterdir():
            os.rename(child, target / child.name)
        stage.rmdir()
        fsync_dir(target)
        fsync_dir(target.parent)
        return {"restored": str(target.resolve()), "files": len(manifest["files"]), "verified": True}
    except Exception:
        # Only remove the new directory this invocation created, never a prior one.
        if claimed:
            shutil.rmtree(target)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    result.add_argument("--data-root", type=Path, help="Data directory (default: PDP_DATA_ROOT or config.json)")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("health", help="Read original health and disabled-provider status")
    commands.add_parser("overview", help="Read original diet overview")
    commands.add_parser("target-review-status", help="Read 15-day due state")
    commands.add_parser("target-review-context", help="Read evidence for dot review; no write")
    for name in ("target-review-enable", "target-review-commit"):
        commands.add_parser(name).add_argument("--input", type=Path, required=True)
    commands.add_parser("targets", help="Read persistent user target versions")
    target_set = commands.add_parser("target-set", help="Append an explicitly authorized dated user target; no menu generation")
    target_set.add_argument("--input", type=Path, required=True)
    prepare = commands.add_parser("mirror-prepare", help="Disabled compatibility command; no hosted transport")
    prepare.add_argument("--refresh", action="store_true")
    acknowledge = commands.add_parser("mirror-ack", help="Disabled compatibility command; no hosted transport")
    acknowledge.add_argument("--input", type=Path, required=True)
    commands.add_parser("mirror-status", help="Read mirror status only; no initialization, projection, network or retry")
    mirror = commands.add_parser("mirror-sync", help="Disabled compatibility command; no hosted transport")
    mirror.add_argument("--token-stdin", action="store_true", help="Ignored compatibility flag; do not provide credentials")
    mirror.add_argument("--refresh", action="store_true", help="Ignored compatibility flag")
    mirror.add_argument("--verify-receiver", action="store_true", help="Ignored compatibility flag")
    settlement = commands.add_parser("settle", help="Idempotent original daily settlement")
    settlement.add_argument("--date", type=date.fromisoformat, default=None, help="YYYY-MM-DD, default current diet day (Asia/Shanghai 07:00 boundary)")
    settlement.add_argument("--score-only", action="store_true", help="Deprecated: rejected; scores settle only in the 07:00 morning workflow")
    ctx = commands.add_parser("planning-context", help="Read actual persistent software skill, profile and two food libraries; no external model call")
    ctx.add_argument("--date", type=date.fromisoformat, required=True)
    preview = commands.add_parser("plan-preview", help="Read-only quantified menu built from persistent context")
    preview.add_argument("--date", type=date.fromisoformat, required=True)
    publish = commands.add_parser("publish-candidate", help="Strict source/target/context validated parent-agent menu writeback; append-only")
    publish.add_argument("--input", type=Path, required=True)
    verify = commands.add_parser("validate-plan", help="Validate structured candidate per-item sources, sums and target tolerances; no publication")
    verify.add_argument("--input", type=Path, required=True)
    remaining = commands.add_parser("revise-remaining", help="Explicitly version a remaining-day proposal; never changes actual intake")
    remaining.add_argument("--input", type=Path, required=True)
    ingestion = commands.add_parser("ingest", help="Ingest one message and up to six images idempotently")
    ingestion.add_argument("--input", type=Path, required=True)
    analysis = commands.add_parser("analysis", help="Write complete AnalysisWrite envelope using original API")
    analysis.add_argument("--meal-id", required=True)
    analysis.add_argument("--input", type=Path, required=True)
    products = commands.add_parser("food-match", help="Exact personal product name/alias match; ambiguity requires confirmation")
    products.add_argument("--query", default="")
    products.add_argument("--brand", default=None)
    save_product = commands.add_parser("food-save", help="Idempotently save a label product/revision; does not record consumption")
    save_product.add_argument("--input", type=Path, required=True)
    save_product.add_argument("--product-id", default=None)
    product_versions = commands.add_parser("food-versions", help="Read all retained revisions of a saved food label")
    product_versions.add_argument("--product-id", required=True)
    calculation = commands.add_parser("food-calculate", help="Calculate a pinned product version and evidenced quantity; no intake write")
    calculation.add_argument("--input", type=Path, required=True)
    export = commands.add_parser("backup", help="New backup directory: consistent SQLite + assets + source manifest")
    export.add_argument("--output", type=Path, required=True)
    recovery = commands.add_parser("restore", help="Verify and restore data into a completely new directory")
    recovery.add_argument("--input", type=Path, required=True, help="Backup directory")
    recovery.add_argument("--target", type=Path, required=True, help="New data directory; must not exist")
    return result


def run(args) -> dict:
    if args.command == "restore":
        return restore(args.input.absolute(), args.target.absolute())
    if args.data_root is not None:
        config.DATA = args.data_root.resolve()
    if args.command in {"mirror-status", "mirror-sync", "mirror-prepare", "mirror-ack"}:
        from app import diet_mirror
        if args.command == "mirror-status":
            return diet_mirror.status()
        if args.command == "mirror-prepare":
            return diet_mirror.prepare_platform_sync(refresh=args.refresh)
        if args.command == "mirror-ack":
            return diet_mirror.acknowledge_platform(read_json(args.input))
        token = None  # Disabled distribution never consumes credentials.
        return diet_mirror.synchronize(token=token, refresh=args.refresh, verify_receiver=args.verify_receiver)
    with batch_lock(), local_client() as client:
        if args.command == "health":
            return {**api(client, "GET", "/api/v1/health"), "providers": api(client, "GET", "/api/v1/providers"),
                    "data_root": str(config.DATA), "transport": "in_process"}
        if args.command == "overview":
            return api(client, "GET", "/api/v1/diet/overview")
        if args.command.startswith("target-review-"):
            from app import diet_target_review
            operation = args.command.removeprefix("target-review-")
            return {"status": diet_target_review.status, "context": diet_target_review.context}[operation]() if operation in ("status", "context") else getattr(diet_target_review, "enable" if operation == "enable" else "commit")(read_json(args.input))
        if args.command == "targets":
            return api(client, "GET", "/api/v1/diet/targets")
        if args.command == "target-set":
            return api(client, "POST", "/api/v1/diet/target-override", json=read_json(args.input))
        if args.command == "planning-context":
            return diet_planning.context(args.date)
        if args.command == "plan-preview":
            from app import diet_cycle
            return diet_cycle.build(args.date.isoformat(), "Asia/Shanghai", force=True)
        if args.command == "publish-candidate":
            return diet_planning.publish_candidate(read_json(args.input, max_bytes=10_000_000))
        if args.command == "validate-plan":
            data = read_json(args.input, max_bytes=10_000_000)
            return diet_planning.validate_current_plan(data)
        if args.command == "revise-remaining":
            data = read_json(args.input)
            allowed = {"expected_report_id", "skipped_meals", "remaining_meals", "training_status", "reason", "idempotency_key", "now"}
            if set(data) - allowed or not (allowed - {"now"}) <= set(data):
                raise CLIError("invalid_replan", "Explicit current report, skipped/remaining meals, training status, reason and idempotency key required")
            if data["training_status"] not in ("unknown", "training", "rest") or not isinstance(data["reason"], str) or not data["reason"].strip():
                raise CLIError("invalid_replan", "Training status and user instruction are required")
            return diet_planning.revise_remaining(**data)
        if args.command == "settle":
            day = args.date or diet_day.current_diet_day()
            return api(client, "POST", "/api/v1/diet/settle", json={"target_date": day.isoformat(), "mode": "score_only" if args.score_only else "morning_0700"})
        if args.command == "ingest":
            return ingest(client, read_json(args.input))
        if args.command == "analysis":
            value = AnalysisWrite.model_validate(read_json(args.input)).model_dump(mode="json")
            if not args.meal_id.isalnum():
                raise CLIError("invalid_meal_id", "Meal ID must be an alphanumeric record identifier")
            return api(client, "POST", f"/api/v1/diet/meals/{args.meal_id}/analysis", json=value)
        if args.command == "food-match":
            return api(client, "GET", "/api/v1/diet/food-products", params={"query": args.query, **({"brand": args.brand} if args.brand else {})})
        if args.command == "food-save":
            value = food_catalog.ProductWrite.model_validate(read_json(args.input)).model_dump(mode="json")
            if args.product_id and not args.product_id.isalnum():
                raise CLIError("invalid_product_id", "Product ID must be alphanumeric")
            return api(client, "PATCH" if args.product_id else "POST", "/api/v1/diet/food-products" + ("/" + args.product_id if args.product_id else ""), json=value)
        if args.command == "food-versions":
            if not args.product_id.isalnum():
                raise CLIError("invalid_product_id", "Product ID must be alphanumeric")
            return api(client, "GET", f"/api/v1/diet/food-products/{args.product_id}/versions")
        if args.command == "food-calculate":
            value = schemas.FoodProductUse.model_validate(read_json(args.input)).model_dump(mode="json")
            return api(client, "POST", "/api/v1/diet/food-products/calculate", json=value)
        if args.command == "backup":
            return backup(args.output.absolute())
    raise CLIError("unknown_command", "Unknown command")


def main(argv=None) -> int:
    try:
        args = parser().parse_args(argv)
        result = run(args)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except db.Conflict as exc:
        error, code = {"code": "conflict", "message": str(exc)}, 3
    except CLIError as exc:
        error, code = {"code": exc.code, "message": str(exc)}, exc.status
    except (ValidationError, ValueError, TypeError, KeyError):
        # Do not echo the full input or sensitive validation values.
        error, code = {"code": "invalid_input", "message": "Invalid JSON, schema fields, or referenced record"}, 2
    except (OSError, sqlite3.Error):
        error, code = {"code": "storage_error", "message": "Local file or database operation failed"}, 2
    print(json.dumps({"error": error}, ensure_ascii=False), file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
