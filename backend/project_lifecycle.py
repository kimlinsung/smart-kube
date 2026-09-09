"""Shared, authorized project deletion for HTTP and conversational tools."""
from __future__ import annotations

import json
import os
import shutil

from . import audit, db, k8s_client
from .config import UPLOAD_DIR
from .archive_paths import resolve_archive



class ProjectError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def validate_ids(ids, kind):
    if not isinstance(ids, list) or not 1 <= len(ids) <= 50:
        raise ProjectError("请选择 1 到 50 项")
    if kind not in {"experiment", "workspace"}:
        raise ProjectError("未知项目类型")
    for value in ids:
        valid = (type(value) is int and value > 0) if kind == "experiment" else (
            isinstance(value, str) and len(value) == 32
            and all(c in "0123456789abcdef" for c in value)
        )
        if not valid:
            raise ProjectError("项目 ID 格式不正确")
    return list(dict.fromkeys(ids))


def delete_project(user, project_id, kind="experiment", source_ip="unknown", upload_root=None):
    with db.project_lifecycle_lock:
        workspace = None
        if kind == "workspace":
            workspace = db.get_paper_workspace(project_id, include_details=False)
            if not workspace:
                raise ProjectError("工作区不存在", 404)
            exp_id = workspace["experiment_id"]
        else:
            exp_id = project_id
        exp = db.get_experiment(exp_id)
        if not exp:
            raise ProjectError("实验不存在", 404)
        if exp["user_id"] != user["id"] and user.get("role") != "admin":
            raise ProjectError("仅所有者或管理员可以删除", 403)
        with db.cursor() as cur:
            active = cur.execute(
                "SELECT 1 FROM execution_tasks WHERE experiment_id=? "
                "AND status IN ('queued','running') LIMIT 1", (exp_id,),
            ).fetchone()
            workspaces = cur.execute(
                "SELECT id,status FROM paper_workspaces WHERE experiment_id=?", (exp_id,),
            ).fetchall()
            if active or any(w["status"] in {"queued", "running"} for w in workspaces):
                raise ProjectError("仍有任务执行中，暂不能删除；当前对话所属实验请在任务结束后从列表删除，或切换实验后再发起删除", 409)
            paths = [r[0] for r in cur.execute(
                "SELECT stored_path FROM script_files WHERE experiment_id=? UNION "
                "SELECT f.stored_path FROM paper_workspace_files f JOIN paper_workspaces w "
                "ON w.id=f.workspace_id WHERE w.experiment_id=?", (exp_id, exp_id),
            ).fetchall()]
        root = os.path.realpath(upload_root or UPLOAD_DIR)
        directories = [os.path.join(root, str(exp["user_id"]), "paper", w["id"]) for w in workspaces]
        try:
            paths = [resolve_archive(path, root, exp["user_id"]) for path in paths]
            directories = [resolve_archive(path, root, exp["user_id"]) for path in directories]
        except ValueError as exc:
            raise ProjectError(f"{exc}，已停止删除", 409) from exc
        try:
            deleted = k8s_client.delete_pods_by_experiment(exp_id)
            # Keep metadata on cleanup failure so the same operation can be retried.
            for path in paths:
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass
            for directory in directories:
                if os.path.isdir(directory):
                    shutil.rmtree(directory)
        except Exception as exc:
            raise ProjectError(f"资源或文件清理未完成，记录已保留，可重试：{exc}", 502) from exc
        db.delete_experiment(exp_id)
        audit.log(user["id"], user["username"], "project_delete",
                  json.dumps({"experiment_id": exp_id, "kind": kind, "deleted_pods": deleted}),
                  source_ip=source_ip)
        return {"ok": True, "id": project_id, "experiment_id": exp_id, "deleted_pods": deleted}


def delete_batch(user, ids, kind="experiment", **kwargs):
    ids = validate_ids(ids, kind)
    results = []
    for project_id in ids:
        try:
            results.append(delete_project(user, project_id, kind, **kwargs))
        except ProjectError as exc:
            results.append({"id": project_id, "ok": False, "error": str(exc), "status": exc.status})
    return {"results": results, "ok": all(r["ok"] for r in results)}
