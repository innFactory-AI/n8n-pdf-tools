"""Turn a Result into an HTTP response: raw file, ZIP or JSON (base64)."""

import base64
import io
import re
import zipfile
from typing import Literal
from urllib.parse import quote

from fastapi.responses import JSONResponse, Response

from .doc import File, Result

Output = Literal["auto", "zip", "json"]


def _safe_name(name: str) -> str:
    """No paths, no control characters: names may come from PDF internals."""
    name = re.sub(r"[\x00-\x1f\x7f/\\]+", "_", name).replace("..", "_").strip(" .")
    return name or "file"


def _disposition(name: str) -> str:
    name = _safe_name(name)
    ascii_name = name.encode("ascii", "replace").decode().replace('"', "_").replace("?", "_")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


def file_response(f: File, count: int = 1) -> Response:
    return Response(
        f.data,
        media_type=f.mime,
        headers={"Content-Disposition": _disposition(f.name), "X-File-Count": str(count)},
    )


def _zip(files: list[File], name: str) -> File:
    buf = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            base = _safe_name(f.name)
            entry, k = base, 1
            while entry in used:
                k += 1
                stem, _, ext = base.rpartition(".")
                entry = f"{stem}_{k}.{ext}"
            used.add(entry)
            zf.writestr(entry, f.data)
    return File(name, "application/zip", buf.getvalue())


def to_response(result: Result, output: Output, stem: str) -> Response:
    if result.json is not None:
        return JSONResponse(result.json)
    files = result.files
    if output == "json":
        return JSONResponse(
            {
                "count": len(files),
                "files": [
                    {
                        "name": f.name,
                        "mime_type": f.mime,
                        "size": len(f.data),
                        "data": base64.b64encode(f.data).decode(),
                    }
                    for f in files
                ],
            }
        )
    if output == "zip" or len(files) != 1:
        if not files and output == "auto":
            return JSONResponse({"count": 0, "files": []})
        return file_response(_zip(files, f"{stem}.zip"), len(files))
    return file_response(files[0])
