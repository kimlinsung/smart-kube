"""Bounded gzip variants for public frontend code, never API or upload responses."""
from functools import lru_cache
import gzip
import hashlib
from io import BytesIO
from pathlib import Path

from flask import request, send_file, send_from_directory
from werkzeug.security import safe_join


@lru_cache(maxsize=48)
def _compressed(path, modified_ns, size):
    content = gzip.compress(Path(path).read_bytes(), compresslevel=6, mtime=0)
    return content, hashlib.sha256(content).hexdigest()


def serve_frontend(root, filename):
    response = send_from_directory(root, filename)
    compressible = filename.endswith((".js", ".mjs", ".css")) and filename.startswith(("js/", "css/", "vendor/"))
    if not compressible:
        return response
    response.vary.add("Accept-Encoding")
    if request.accept_encodings["gzip"] <= 0:
        return response
    path = safe_join(str(root), filename)
    stat = Path(path).stat()
    if not 1024 <= stat.st_size <= 3 * 1024 * 1024:
        return response
    content, etag = _compressed(path, stat.st_mtime_ns, stat.st_size)
    mime = response.mimetype
    response.close()
    response = send_file(BytesIO(content), mimetype=mime, conditional=False,
                         etag=etag, last_modified=stat.st_mtime, max_age=0)
    response.headers["Content-Encoding"] = "gzip"
    response.vary.add("Accept-Encoding")
    response.make_conditional(request)
    return response
