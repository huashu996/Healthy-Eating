import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config


def now():
    return datetime.now(timezone.utc).astimezone(timezone.utc).isoformat()


def uid():
    return uuid.uuid4().hex


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


@contextmanager
def connect(*, track_mirror=True):
    config.directories()
    con = sqlite3.connect(config.DATA / "database/platform.sqlite3", timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=15000")
    touched = set()
    def note_write(action, table, _column, _database, _trigger):
        if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE) and table in {"records", "reports", "settings"}:
            touched.add(table)
        return sqlite3.SQLITE_OK
    if track_mirror:
        con.set_authorizer(note_write)
    committed_source_write = False
    try:
        yield con
        if track_mirror and touched and con.total_changes:
            from . import diet_mirror
            diet_mirror.mark_dirty(con)
            committed_source_write = True
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    if committed_source_write:
        from . import diet_mirror
        diet_mirror.after_commit()


def init():
    with connect(track_mirror=False) as con:
        con.execute("PRAGMA journal_mode=WAL")
        for file in sorted((config.ROOT / "apps/api/migrations").glob("*.sql")):
            con.executescript(file.read_text(encoding="utf-8"))
        defaults = dict(timezone=config.CONFIG["timezone"], timezone_confirmed=config.CONFIG["timezone_confirmed"],
                        public_sources_enabled=config.CONFIG["public_sources_enabled"],
                        agent_enabled=config.CONFIG["agent_enabled"], locale="zh-CN", reduced_motion=False,
                        schedule_enabled=False, daily_time="07:00", evening_enabled=False,
                        evening_time="07:00", weekly_enabled=False, onboarding_done=False)
        con.execute("INSERT OR IGNORE INTO settings(id,version,data) VALUES (1,1,?)", (encode(defaults),))


def settings():
    with connect() as con:
        row = con.execute("SELECT * FROM settings WHERE id=1").fetchone()
        return dict(json.loads(row["data"]), version=row["version"], data_root=str(config.DATA))


def unpack(row):
    if row is None:
        raise KeyError("记录不存在或已删除")
    result = dict(row)
    for key in ("data", "input", "result", "payload"):
        if key in result and result[key] is not None:
            result[key] = json.loads(result[key])
    return result


def get_record(identifier, kind=None, con=None):
    if con is None:
        with connect() as c:
            return get_record(identifier, kind, c)
    row = con.execute("SELECT * FROM records WHERE id=? AND deleted_at IS NULL", (identifier,)).fetchone()
    item = unpack(row)
    if kind and item["kind"] != kind:
        raise KeyError("记录类型不匹配")
    return item


def records(kind, limit=100, offset=0, project_id=None):
    query = "FROM records WHERE kind=? AND deleted_at IS NULL"
    args = [kind]
    if project_id:
        query += " AND project_id=?"
        args.append(project_id)
    with connect() as con:
        count = con.execute("SELECT COUNT(*) " + query, args).fetchone()[0]
        rows = con.execute("SELECT * " + query + " ORDER BY updated_at DESC,id LIMIT ? OFFSET ?",
                           args + [limit, offset]).fetchall()
        return {"items": [unpack(r) for r in rows], "total": count, "limit": limit, "offset": offset}


def audit(con, action, target, metadata=None):
    con.execute("INSERT INTO audit_events VALUES(?,?,?,?,?)", (uid(), action, target, encode(metadata or {}), now()))


def save_record(kind, module, data, identifier=None, version=None, project_id=None):
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        stamp = now()
        if identifier:
            old = get_record(identifier, kind, con)
            if old["version"] != version:
                raise Conflict("资料已在其他窗口更新，请重新加载后再修改")
            newversion = old["version"] + 1
            con.execute("UPDATE records SET data=?,version=?,updated_at=? WHERE id=?",
                        (encode(data), newversion, stamp, identifier))
        else:
            identifier, newversion = uid(), 1
            con.execute("INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,NULL)",
                        (identifier, kind, module, project_id, 1, encode(data), stamp, stamp, "live"))
        con.execute("INSERT INTO revisions VALUES(?,?,?,?)", (identifier, newversion, encode(data), stamp))
        audit(con, "record.saved", identifier, {"kind": kind, "version": newversion})
        return get_record(identifier, con=con)


class Conflict(Exception):
    pass
