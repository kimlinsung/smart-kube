"""Resolve the one documented pre-migration upload root without widening access."""
import os

from .config import UPLOAD_DIR

LEGACY_ROOT = "/home/ubuntu/smart-kube/uploads"


def resolve_archive(path, root=None, owner=None):
    root = os.path.realpath(root or UPLOAD_DIR)
    path = os.fspath(path)
    if path.startswith(LEGACY_ROOT + "/"):
        relative = path[len(LEGACY_ROOT) + 1:]
        parts = relative.split("/")
        if ".." in parts or not parts[0].isdigit() or (owner is not None and parts[0] != str(owner)):
            raise ValueError("旧归档路径与文件所有者不匹配")
        path = os.path.join(root, *parts)
    resolved = os.path.realpath(path)
    if resolved == root or os.path.commonpath((root, resolved)) != root:
        raise ValueError("归档路径超出上传目录")
    return resolved


def migrated_file(row):
    if row is None:
        return None
    item = dict(row)
    if item.get("stored_path", "").startswith(LEGACY_ROOT + "/"):
        item["stored_path"] = resolve_archive(item["stored_path"], owner=item.get("user_id"))
    return item
