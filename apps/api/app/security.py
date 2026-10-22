import hashlib
from . import db
CATEGORY_MODULES = {"health": {"diet"}}

class SafeError(Exception):
    def __init__(self, code, message, status=400, retryable=False):
        self.code, self.message, self.status, self.retryable = code, message, status, retryable
        super().__init__(message)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def context_bundle(job, provider="codex", require_grant=True):
    result = []
    references = job["input"].get("context_refs", [])
    if not isinstance(references, list) or len(references) > 30:
        raise SafeError("bad_context", "上下文引用过多或格式错误")
    with db.connect() as con:
        for ref in references:
            item = db.get_record(ref["id"], con=con)
            if item["version"] != ref["version"]:
                raise SafeError("context_changed", "资料已修改，请重新预览并创建任务", 409)
            permitted = CATEGORY_MODULES[item["data"]["category"]] if item["kind"] == "facts" else {item["module"]}
            if job["module"] not in permitted:
                raise SafeError("context_forbidden", "该模块无权读取此资料", 403)
            project = item["id"] if item["kind"] == "projects" else item["project_id"]
            if project and project != job["input"].get("project_id"):
                raise SafeError("project_forbidden", "不能读取其他项目材料", 403)
            if require_grant:
                grants = con.execute("SELECT g.id FROM grants g JOIN grant_versions v ON v.grant_id=g.id WHERE module=? AND provider=? AND purpose=? AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at>?) AND (once_job IS NULL OR once_job=?) AND scope=? AND v.record_version=? AND v.project_id IS ?",
                                     (job["module"], provider, job["operation"], db.now(), job["id"], item["id"], item["version"], project)).fetchall()
                if not grants:
                    raise SafeError("permission_required", "私人资料尚未授权给此 provider 和用途", 403)
            result.append({"id": item["id"], "version": item["version"], "kind": item["kind"], "data": item["data"]})
    return result
