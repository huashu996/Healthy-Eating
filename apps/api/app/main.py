import asyncio
import hashlib
import hmac
import io
import csv
import json
import mimetypes
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import available_timezones, ZoneInfo

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from . import config, db, jobs, schemas, diet, diet_day
from .security import SafeError, context_bundle, digest

SECRET = secrets.token_bytes(32)
RATES = defaultdict(deque)
ALIASES = {"profile/facts":"facts", "diet/meals":"meals", "diet/preferences":"diet_preferences", "diet/feedback":"feedback", "diet/uploads":"health_uploads", "diet/checkins":"body_checkins", "diet/days":"diet_days"}


@asynccontextmanager
async def lifespan(_app):
    db.init()
    yield


app = FastAPI(title="拾序 · 饮食健康", version="0.1.0", lifespan=lifespan, docs_url="/api/docs")


def signed_token(value):
    return hmac.new(SECRET, value.encode(), hashlib.sha256).hexdigest()


def response_error(request, code, message, status=400, retryable=False):
    return JSONResponse({"schema_version": "1.0", "code": code, "message": message, "retryable": retryable,
                         "details_safe": {}, "request_id": getattr(request.state, "request_id", db.uid())}, status_code=status)


@app.middleware("http")
async def guard(request, call_next):
    request.state.request_id = db.uid()
    host = request.headers.get("host", "")
    allowed = {f"127.0.0.1:{config.PORT}", f"localhost:{config.PORT}", "testserver", "127.0.0.1:5173", "localhost:5173"}
    if host not in allowed:
        return response_error(request, "host_forbidden", "不接受此 Host", 403)
    origin = request.headers.get("origin")
    allowed_origins = {config.ORIGIN, f"http://localhost:{config.PORT}", "http://127.0.0.1:5173", "http://localhost:5173"}
    if origin and origin not in allowed_origins:
        return response_error(request, "origin_forbidden", "跨来源请求被拒绝", 403)
    if request.headers.get("sec-fetch-site") == "cross-site":
        return response_error(request, "cross_site", "跨站请求被拒绝", 403)
    try:
        content_length = int(request.headers.get("content-length", "0") or "0")
    except ValueError:
        return response_error(request, "invalid_length", "无效的请求大小", 400)
    if content_length < 0 or content_length > config.MAX_UPLOAD + 100000:
        return response_error(request, "body_too_large", "请求超过大小限制", 413)
    path = request.url.path
    if request.method in ("POST", "PATCH", "PUT"):
        # Bound streamed/chunked bodies too, before multipart or JSON parsing allocates memory.
        chunks, length = [], 0
        maximum = config.MAX_UPLOAD + 100000 if path == "/api/v1/assets" else 200000
        async for chunk in request.stream():
            length += len(chunk)
            if length > maximum:
                return response_error(request, "body_too_large", "请求超过大小限制", 413)
            chunks.append(chunk)
        request._body = b"".join(chunks)
    exempt = path in ("/api/v1/session", "/api/v1/health") or not path.startswith("/api/v1/")
    if not exempt:
        cookie = request.cookies.get("pdp_session", "")
        pieces = cookie.split(".")
        if len(pieces) != 2 or not hmac.compare_digest(pieces[1], signed_token(pieces[0])):
            return response_error(request, "session_required", "本地会话已过期，请重新加载", 401)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), pieces[0]):
                return response_error(request, "csrf_required", "缺少有效的本地会话校验", 403)
            bucket = RATES[pieces[0]]
            stamp = time.monotonic()
            while bucket and stamp - bucket[0] > 60:
                bucket.popleft()
            if len(bucket) >= 90:
                return response_error(request, "rate_limited", "操作过于频繁，请稍后重试", 429, True)
            bucket.append(stamp)
    response = await call_next(request)
    response.headers.update({"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                             "X-Frame-Options": "DENY", "Cache-Control": "no-store",
                             "Content-Security-Policy": "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"})
    return response


@app.exception_handler(SafeError)
async def safe_error(request, exc):
    return response_error(request, exc.code, exc.message, exc.status, exc.retryable)


@app.exception_handler(db.Conflict)
async def conflict(request, exc):
    return response_error(request, "version_conflict", str(exc), 409)


@app.exception_handler(KeyError)
async def missing(request, _exc):
    return response_error(request, "not_found", "记录不存在或已删除", 404)


@app.exception_handler(ValidationError)
@app.exception_handler(RequestValidationError)
async def validation(request, exc):
    fields = ", ".join(".".join(map(str, e["loc"])) or e["msg"] for e in exc.errors())
    return response_error(request, "validation_error", "请检查输入字段：" + fields, 422)


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return response_error(request, "http_error", "请求路径或方法无效", exc.status_code)


@app.exception_handler(Exception)
async def unexpected(request, _exc):
    return response_error(request, "internal_error", "本地服务遇到错误；敏感内容未写入响应", 500)


@app.get("/api/v1/session")
def session():
    value = secrets.token_urlsafe(32)
    response = JSONResponse({"csrf_token": value, "schema_version": "1.0"})
    response.set_cookie("pdp_session", value + "." + signed_token(value), httponly=True, samesite="strict", max_age=86400)
    return response


@app.get("/api/v1/health")
def health():
    with db.connect() as con:
        heartbeat = con.execute("SELECT value FROM runtime WHERE key='worker_heartbeat'").fetchone()
    stamp = heartbeat[0] if heartbeat else None
    online = bool(stamp and (datetime.now(timezone.utc) - datetime.fromisoformat(stamp)).total_seconds() < 100)
    return {"schema_version": "1.0", "status": "ok", "database": "ok", "worker": "online" if online else "offline", "worker_heartbeat": stamp}


@app.get("/api/v1/settings")
def read_settings():
    return db.settings()


@app.patch("/api/v1/settings")
def update_settings(value: schemas.SettingsPatch):
    # Legacy clients may submit their old clocks; diet now has one fixed settlement.
    value = value.model_copy(update={"daily_time": "07:00", "evening_time": "07:00", "evening_enabled": False, "schedule_enabled": False, "weekly_enabled": False, "agent_enabled": False, "public_sources_enabled": False, "timezone": "Asia/Shanghai", "timezone_confirmed": True})
    with db.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        previous = con.execute("SELECT version FROM settings WHERE id=1").fetchone()[0]
        if previous != value.version:
            raise db.Conflict("设置已经更新，请重新加载")
        if value.schedule_enabled and not value.timezone_confirmed:
            raise SafeError("timezone_unconfirmed", "启用调度前请确认时区")
        con.execute("UPDATE settings SET data=?,version=version+1 WHERE id=1", (db.encode(value.model_dump(exclude={"version"})),))
        db.audit(con, "settings.updated", "settings", {"version": previous + 1})
    return db.settings()


@app.get("/api/v1/timezones")
def timezones():
    return sorted(available_timezones())




@app.get("/api/v1/dashboard")
def dashboard():
    with db.connect() as con:
        reports = [db.unpack(row) for row in con.execute("SELECT * FROM reports WHERE mode='live' ORDER BY created_at DESC LIMIT 8")]
        active = con.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running','awaiting_permission')").fetchone()[0]
        counts = {r["kind"]: r["n"] for r in con.execute("SELECT kind,COUNT(*) n FROM records WHERE deleted_at IS NULL GROUP BY kind")}
    return {"counts": counts, "reports": reports, "active_jobs": active, "health": health()}


@app.get("/api/v1/permissions")
def read_grants():
    with db.connect() as con:
        return {"items": [dict(r) for r in con.execute("SELECT * FROM grants ORDER BY created_at DESC")]}




@app.delete("/api/v1/permissions/{identifier}")
def revoke(identifier: str):
    with db.connect() as con:
        con.execute("UPDATE grants SET revoked_at=? WHERE id=?", (db.now(), identifier))
        db.audit(con, "permission.revoked", identifier)
    return {"revoked": True, "notice": "停止后续访问；已发送至外部 provider 的内容无法由本机撤回。"}






@app.get("/api/v1/jobs")
def list_jobs(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    with db.connect() as con:
        rows = con.execute("SELECT * FROM jobs ORDER BY scheduled_at DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return {"items": [db.unpack(r) for r in rows], "total": con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]}




@app.get("/api/v1/jobs/{identifier}")
def get_job(identifier: str):
    with db.connect() as con:
        return db.unpack(con.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone())


@app.post("/api/v1/jobs/{identifier}/cancel")
def cancel(identifier: str):
    with db.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT status FROM jobs WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise KeyError(identifier)
        if row[0] not in jobs.TERMINAL:
            con.execute("UPDATE jobs SET cancel_requested=1,status='cancelled',finished_at=? WHERE id=?", (db.now(), identifier))
            jobs.event(con, identifier, "cancelled")
    return get_job(identifier)


@app.get("/api/v1/jobs/{identifier}/events")
async def job_events(identifier: str, request: Request, after: int = 0):
    get_job(identifier)
    try:
        sequence = max(after, int(request.headers.get("last-event-id", "0")))
    except ValueError:
        raise SafeError("invalid_event_id", "事件编号必须为整数")

    async def stream():
        nonlocal sequence
        for _ in range(60):
            if await request.is_disconnected():
                break
            with db.connect() as con:
                rows = con.execute("SELECT * FROM job_events WHERE job_id=? AND sequence>? ORDER BY sequence", (identifier, sequence)).fetchall()
                status = con.execute("SELECT status FROM jobs WHERE id=?", (identifier,)).fetchone()[0]
            for row in rows:
                sequence = row["sequence"]
                yield f"id: {sequence}\nevent: {row['type']}\ndata: {db.encode(db.unpack(row))}\n\n"
            if status in jobs.TERMINAL or status == "awaiting_permission":
                break
            yield ": heartbeat\n\n"
            await asyncio.sleep(1)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@app.get("/api/v1/reports")
def list_reports(module: str | None = None, limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0)):
    with db.connect() as con:
        where, args = ("WHERE module=? AND mode='live'", [module]) if module else ("WHERE mode='live'", [])
        rows = con.execute(f"SELECT * FROM reports {where} ORDER BY created_at DESC LIMIT ? OFFSET ?", args + [limit, offset]).fetchall()
        return {"items": [db.unpack(r) for r in rows], "total": con.execute(f"SELECT COUNT(*) FROM reports {where}", args).fetchone()[0]}


@app.get("/api/v1/reports/{identifier}")
def get_report(identifier: str):
    with db.connect() as con:
        return db.unpack(con.execute("SELECT * FROM reports WHERE id=?", (identifier,)).fetchone())


@app.get("/api/v1/diet/recommendations")
def recommendations():
    from . import diet_cycle
    return diet_cycle.recommendations()




@app.get("/api/v1/diet/overview")
def diet_overview():
    return diet.overview()


@app.get("/api/v1/diet/weekly")
def weekly():
    return diet.week_review(diet_day.current_diet_day())


@app.get("/api/v1/diet/history")
def diet_calendar(month: str | None = None):
    from . import diet_calendar
    return diet_calendar.calendar(month)


@app.get("/api/v1/diet/history/{day}")
def diet_calendar_day(day: str):
    from . import diet_calendar
    return diet_calendar.day_detail(day)


@app.get("/api/v1/diet/body-metrics")
def body_metrics():
    return {"items": [r for r in db.records("facts", 1000)["items"] if r["data"]["category"] == "health"]}


@app.post("/api/v1/diet/recommendations/{identifier}/feedback", status_code=201)
def recommendation_feedback(identifier: str, value: schemas.Mutation):
    data = schemas.Feedback.model_validate({**value.data, "recommendation_ref": identifier}).model_dump()
    return db.save_record("feedback", "diet", data)
















@app.post("/api/v1/assets", status_code=201)
async def upload(file: UploadFile = File(...), module: schemas.Module = Form(...), project_id: str | None = Form(None)):
    raw = await file.read(config.MAX_UPLOAD + 1)
    await file.close()
    if len(raw) > config.MAX_UPLOAD:
        raise SafeError("file_too_large", "单个文件上限为12MB", 413)
    if project_id:
        raise SafeError("project_forbidden", "饮食独立版不接受跨项目资料", 403)
    name = Path(file.filename or "upload").name
    extension = Path(name).suffix.lower()
    extraction = None
    if extension in (".jpg", ".jpeg", ".png", ".webp"):
        try:
            Image.MAX_IMAGE_PIXELS = 25_000_000
            picture = Image.open(io.BytesIO(raw))
            expected = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}[extension]
            expected_mime = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}[expected]
            if picture.width * picture.height > 25_000_000 or picture.format != expected or file.content_type != expected_mime:
                raise ValueError()
            picture.load()
            out = io.BytesIO()
            picture.convert("RGB").save(out, format="JPEG", quality=92)
            raw, extension, mime = out.getvalue(), ".jpg", "image/jpeg"
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            raise SafeError("invalid_image", "图片损坏、格式不符或像素过大")
    else:
        raise SafeError("unsupported_file", "支持 JPG、PNG、WebP 图片，以及计划模块的 PDF、Word、UTF-8 文本")
    identifier = db.uid()
    key = identifier + extension
    (config.DATA / "assets" / key).write_bytes(raw)
    with db.connect() as con:
        con.execute("INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?)", (identifier, key, mime, len(raw), digest(raw), module, project_id, db.now(), name))
        db.audit(con, "asset.imported", identifier, {"module": module, "size": len(raw)})
    return {"id": identifier, "mime": mime, "sha256": digest(raw), "exif_removed": mime.startswith("image/"), "extraction": extraction}


@app.get("/api/v1/assets/{identifier}")
def asset(identifier: str):
    with db.connect() as con:
        row = con.execute("SELECT * FROM assets WHERE id=?", (identifier,)).fetchone()
    if not row:
        raise KeyError(identifier)
    path = (config.DATA / "assets" / row["storage_key"]).resolve()
    if not path.is_relative_to((config.DATA / "assets").resolve()) or not path.is_file():
        raise KeyError(identifier)
    return FileResponse(path, media_type=row["mime"])




@app.delete("/api/v1/assets/{identifier}")
def delete_asset(identifier: str):
    with db.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT * FROM assets WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise KeyError(identifier)
        if con.execute("SELECT id FROM records WHERE deleted_at IS NULL AND data LIKE ? LIMIT 1", (f"%{identifier}%",)).fetchone():
            raise SafeError("asset_in_use", "请先移除使用此附件的记录，避免破坏现有资料", 409)
        if con.execute("SELECT 1 FROM revisions v JOIN records r ON r.id=v.record_id WHERE r.kind='food_products' AND v.data LIKE ? LIMIT 1", (f"%{identifier}%",)).fetchone():
            raise SafeError("asset_in_use", "食品标签历史版本仍引用此原图，不能删除", 409)
        path = (config.DATA / "assets" / row["storage_key"]).resolve()
        if not path.is_relative_to((config.DATA / "assets").resolve()):
            raise SafeError("asset_path", "附件路径无效")
        con.execute("DELETE FROM assets WHERE id=?", (identifier,))
        path.unlink(missing_ok=True)
        db.audit(con, "asset.deleted", identifier)
    return {"deleted": True}








@app.get("/api/v1/export")
def export_data(format: str = "json"):
    with db.connect() as con:
        data = {"schema_version": "1.0", "exported_at": db.now(), "records": [db.unpack(r) for r in con.execute("SELECT * FROM records WHERE deleted_at IS NULL")],
                "reports": [db.unpack(r) for r in con.execute("SELECT * FROM reports")]}
    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "module", "kind", "version", "updated_at", "data_json"])
        for row in data["records"]:
            writer.writerow([row[k] for k in ("id", "module", "kind", "version", "updated_at")] + [db.encode(row["data"])])
        return StreamingResponse(iter([("\ufeff" + output.getvalue()).encode("utf-8")]), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="personal-platform.csv"'})
    if format == "markdown":
        content = "# 个人数字平台导出\n\n" + "\n\n".join(f"## {row['kind']} · {row['id']} · v{row['version']}\n\n```json\n{json.dumps(row['data'], ensure_ascii=False, indent=2)}\n```" for row in data["records"])
        return StreamingResponse(iter([content.encode("utf-8")]), media_type="text/markdown", headers={"Content-Disposition": 'attachment; filename="personal-platform.md"'})
    return JSONResponse(data, headers={"Content-Disposition": 'attachment; filename="personal-platform.json"'})


@app.get("/api/v1/audit")
def audit_log():
    with db.connect() as con:
        return {"items": [dict(r) for r in con.execute("SELECT * FROM audit_events ORDER BY created_at DESC LIMIT 100")]}


@app.get("/api/v1/search")
def search(q: str = Query(min_length=1, max_length=100)):
    with db.connect() as con:
        rows = con.execute("SELECT * FROM records WHERE deleted_at IS NULL AND data LIKE ? ORDER BY updated_at DESC LIMIT 30", ("%" + q.replace("%", "").replace("_", "") + "%",)).fetchall()
    return {"items": [db.unpack(r) for r in rows]}


def validate_refs(kind, data):
    if kind == "meals":
        from .food_catalog import validate_meal_refs
        validate_meal_refs(data.get("product_refs", []))
    if data.get("project_id"):
        raise SafeError("project_forbidden", "饮食独立版不接受跨项目资料", 403)
    if kind == "body_checkins":
        today = datetime.now(ZoneInfo(db.settings()["timezone"])).date().isoformat()
        if data["measured_on"] > today:
            raise SafeError("future_measurement", "测量记录日期不能在未来", 422)
    if kind == "diet_days" and data["date"] > diet_day.current_diet_day().isoformat():
        # Future training and dish requests are plans, never completed logs.
        has_training_plan = (data.get("training_status") in ("unknown", "training", "rest")
                             and bool(data.get("training_source", "").strip()))
        has_dish_request = bool(data.get("dish_requests"))
        has_pantry_constraint = bool(data.get("pantry_constraints"))
        future_plan_only = ((has_training_plan or has_dish_request or has_pantry_constraint)
                            and not data.get("finished")
                            and not data.get("exercise", "").strip())
        if not future_plan_only:
            raise SafeError("future_measurement", "未来饮食日仅可保存有明确来源的训练安排、点菜意向或按日库存约束，不能记为已训练或全天完成", 422)
    project_id = data.get("project_id")
    if kind in ("diet_preferences", "style_preferences"):
        for ref in data.get("support_ids", []):
            db.get_record(ref, "meals" if kind == "diet_preferences" else "samples")
    if project_id:
        raise SafeError("project_forbidden", "饮食独立版不接受跨项目资料", 403)
    if kind == "observations":
        instrument = db.get_record(data["instrument_id"], "instruments")
        if data["currency"] != instrument["data"]["currency"]:
            raise SafeError("currency_mismatch", "币种与证券登记不一致；禁止隐式折算")
    asset_ids = data.get("assets", []) + ([data["asset_id"]] if data.get("asset_id") else [])
    with db.connect() as con:
        for identifier in asset_ids:
            asset_row = con.execute("SELECT * FROM assets WHERE id=?", (identifier,)).fetchone()
            if not asset_row or asset_row["module"] != schemas.MODULES[kind] or asset_row["project_id"] != project_id:
                raise SafeError("asset_forbidden", "附件不属于此模块或项目", 403)


def mount_crud(path, kind):
    def listing(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), project_id: str | None = None):
        return db.records(kind, limit, offset, project_id)

    def create(value: schemas.Mutation):
        data = schemas.MODELS[kind].model_validate(value.data).model_dump(mode="json")
        if kind == "meals":
            data = diet_day.assign_diet_date(data)
        validate_refs(kind, data)
        module = {"health": "diet", "finance": "finance", "aesthetics": "aesthetics", "basic": "plans", "career": "plans", "project": "plans"}[data["category"]] if kind == "facts" else schemas.MODULES[kind]
        return db.save_record(kind, module, data, project_id=data.get("project_id"))

    def patch(identifier: str, value: schemas.Mutation):
        old = db.get_record(identifier, kind)
        if value.version is None:
            raise SafeError("version_required", "修改必须包含记录版本", 428)
        data = schemas.MODELS[kind].model_validate({**old["data"], **value.data}).model_dump(mode="json")
        if kind == "meals":
            try:
                data = diet_day.assign_diet_date(data, existing=old)
            except ValueError as error:
                raise SafeError("diet_date_immutable", str(error), 409) from error
        if data.get("project_id") != old["project_id"]:
            raise SafeError("project_immutable", "不可把现有材料移动到其他项目")
        if kind == "facts" and data["category"] != old["data"]["category"]:
            raise SafeError("category_immutable", "资料类别决定权限范围，请新建目标类别记录后删除旧记录")
        validate_refs(kind, data)
        return db.save_record(kind, schemas.MODULES[kind], data, identifier, value.version)

    def remove(identifier: str, version: int):
        with db.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            old = db.get_record(identifier, kind, con)
            if old["version"] != version:
                raise db.Conflict("删除前请重新加载最新版本")
            ids = [identifier] + [r[0] for r in con.execute("SELECT id FROM records WHERE project_id=?", (identifier,))]
            for rid in ids:
                con.execute("UPDATE records SET deleted_at=?,data='{}',version=version+1 WHERE id=?", (db.now(), rid))
                con.execute("DELETE FROM revisions WHERE record_id=?", (rid,))
                con.execute("UPDATE grants SET revoked_at=? WHERE scope=?", (db.now(), rid))
                con.execute("UPDATE jobs SET cancel_requested=1,status='cancelled' WHERE status NOT IN ('succeeded','partial','failed','cancelled') AND input LIKE ?", (f"%{rid}%",))
                con.execute("UPDATE reports SET data=?,status='partial' WHERE data LIKE ?", (db.encode({"summary": "引用资料已删除，报告内容已清除"}), f"%{rid}%"))
            db.audit(con, "record.deleted", identifier, {"related_count": len(ids)})
        return {"deleted": True, "notice": "本地资料版本已清除；已有备份和外部副本需另行管理。"}

    def versions(identifier: str):
        db.get_record(identifier, kind)
        with db.connect() as con:
            return {"items": [db.unpack(r) for r in con.execute("SELECT * FROM revisions WHERE record_id=? ORDER BY version DESC", (identifier,))]}

    app.add_api_route("/api/v1/" + path, listing, methods=["GET"], name="list_" + kind)
    app.add_api_route("/api/v1/" + path, create, methods=["POST"], status_code=201, name="create_" + kind)
    app.add_api_route("/api/v1/" + path + "/{identifier}", patch, methods=["PATCH"], name="patch_" + kind)
    app.add_api_route("/api/v1/" + path + "/{identifier}", remove, methods=["DELETE"], name="delete_" + kind)
    app.add_api_route("/api/v1/" + path + "/{identifier}/versions", versions, methods=["GET"], name="versions_" + kind)


for route, record_kind in ALIASES.items():
    mount_crud(route, record_kind)


from .external_api import register
register(app)
from .food_catalog import register as register_food_catalog
register_food_catalog(app)

# Append-only explicit daily target overrides.
from . import diet_targets
diet_targets.register(app)
from . import diet_target_review
diet_target_review.register(app)

@app.get("/{path:path}")
def frontend(path: str):
    if path.startswith("api/"):
        raise KeyError(path)
    root = (config.ROOT / "apps/web/dist").resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise KeyError(path)
    if path and target.is_file():
        return FileResponse(target, media_type=mimetypes.guess_type(target)[0])
    if not (root / "index.html").exists():
        return JSONResponse({"message": "前端尚未构建，请运行 npm --prefix apps/web run build"}, status_code=503)
    return FileResponse(root / "index.html")
