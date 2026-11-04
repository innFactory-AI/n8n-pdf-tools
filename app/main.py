"""HTTP API. Every endpoint takes multipart/form-data (`file` + parameters as form fields)
and returns the resulting PDF, a ZIP/JSON for multiple files, or JSON for read-only operations."""

import base64
import binascii
import hmac
import json
import logging
import time
from typing import Annotated, Any

import anyio
from fastapi import FastAPI, Form, Request, UploadFile
from fastapi import File as FormFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from . import pipeline
from .config import settings
from .doc import PDF_MIME, Doc, File, Result, stem_of
from .errors import PdfToolError
from .ops import document
from .responses import Output, file_response, to_response

log = logging.getLogger("pdftools")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(
    title="n8n-pdf-tools",
    version=settings.version,
    description=(
        "Stateless PDF toolbox for n8n (cluster-internal). Send the PDF as multipart field `file`; "
        "pages are 1-based (`1-3,5,7-`, `last`, `odd`, `even`, `all`). "
        "`output=auto` returns one file directly and several as ZIP; `zip`/`json` force a format."
    ),
)

OPEN_PATHS = {"/healthz", "/readyz", "/version", "/docs", "/openapi.json", "/redoc"}
_limiter = anyio.CapacityLimiter(settings.max_concurrent_jobs)


# ---------------------------------------------------------------- middleware / errors


class Guard:
    """Token check, request size limit (also for chunked uploads without Content-Length) and access log."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] in OPEN_PATHS:
            return await self.app(scope, receive, send)
        started = time.perf_counter()
        headers = {k.decode().lower(): v.decode("latin-1") for k, v in scope["headers"]}
        limit = settings.max_upload_bytes
        status = {"code": 0}

        async def reply(response: Response) -> None:
            status["code"] = response.status_code
            await response(scope, receive, send)

        if settings.api_token:
            auth = headers.get("authorization", "")
            given = auth[7:] if auth.lower().startswith("bearer ") else headers.get("x-api-key", "")
            if not hmac.compare_digest(given.encode(), settings.api_token.encode()):
                return await reply(_error(401, "unauthorized", "missing or wrong API token"))
        length = headers.get("content-length", "")
        if length.isdigit() and int(length) > limit:
            return await reply(_error(413, "too_large", f"request exceeds {settings.max_upload_mb} MB"))

        state = {"received": 0, "exceeded": False, "replaced": False}

        async def limited_receive():
            message = await receive()
            if message["type"] == "http.request":
                state["received"] += len(message.get("body", b""))
                if state["received"] > limit:
                    state["exceeded"] = True
                    raise PdfToolError(f"request exceeds {settings.max_upload_mb} MB", "too_large", 413)
            return message

        async def guarded_send(message):
            # body parsing errors get wrapped by FastAPI (400); answer with the real reason instead
            if state["exceeded"]:
                if not state["replaced"] and message["type"] == "http.response.start":
                    state["replaced"] = True
                    await reply(_error(413, "too_large", f"request exceeds {settings.max_upload_mb} MB"))
                return
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except PdfToolError:
            if not state["replaced"]:
                await reply(_error(413, "too_large", f"request exceeds {settings.max_upload_mb} MB"))
        log.info(
            "%s %s %s %.0fms", scope["method"], scope["path"], status["code"], (time.perf_counter() - started) * 1000
        )


app.add_middleware(Guard)


def _error(status: int, code: str, message: str, details: Any = None) -> JSONResponse:
    body: dict[str, Any] = {"error": code, "message": message}
    if details is not None:
        body["details"] = details
    return JSONResponse(body, status_code=status)


@app.exception_handler(PdfToolError)
async def _tool_error(_request: Request, exc: PdfToolError) -> JSONResponse:
    return _error(exc.status, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
    msg = "; ".join(f"{d['field']}: {d['message']}" for d in details)
    return _error(422, "invalid_request", msg, details)


@app.exception_handler(Exception)
async def _unexpected(_request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error")
    return _error(500, "internal_error", f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------- helpers


async def _read(upload: UploadFile) -> bytes:
    data = await upload.read()
    if len(data) > settings.max_upload_bytes:
        raise PdfToolError(f"file exceeds {settings.max_upload_mb} MB", "too_large", 413)
    return data


async def _run(
    file: UploadFile,
    op: dict[str, Any],
    password: str | None = None,
    output: Output = "auto",
    assets: dict[str, bytes] | None = None,
) -> Response:
    data = await _read(file)

    def work() -> Result:
        doc = Doc.load(data, file.filename, password)
        return pipeline.single(doc, op, assets, len(data))

    result = await anyio.to_thread.run_sync(work, limiter=_limiter)
    return to_response(result, output, stem_of(file.filename))


def _clean(params: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in params.items() if v is not None}


PdfFile = Annotated[UploadFile, FormFile(description="the PDF")]
Password = Annotated[str | None, Form(description="password of an encrypted input PDF")]
OutputForm = Annotated[Output, Form(description="auto | zip | json (base64)")]
Pages = Annotated[str | None, Form(description="page selection, default all")]


# ---------------------------------------------------------------- meta


@app.get("/healthz", include_in_schema=False)
@app.get("/readyz", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/version")
async def version() -> dict[str, str]:
    return {"name": "n8n-pdf-tools", "version": settings.version}


@app.get("/v1/ping", summary="Authenticated no-op, e.g. for the n8n credential test")
async def ping() -> dict[str, str]:
    return {"status": "ok", "version": settings.version}


# ---------------------------------------------------------------- read


@app.post("/v1/info", tags=["read"], summary="Page count, sizes, metadata, bookmarks, form fields")
async def info(file: PdfFile, password: Password = None) -> Response:
    return await _run(file, {"op": "info"}, password)


@app.post("/v1/text", tags=["read"], summary="Text (and optionally tables) per page as JSON")
async def text(
    file: PdfFile,
    pages: Pages = None,
    layout: Annotated[bool, Form(description="keep the visual layout (spaces)")] = False,
    tables: Annotated[bool, Form(description="also extract tables as row arrays")] = False,
    password: Password = None,
) -> Response:
    return await _run(file, {"op": "text", "pages": pages, "layout": layout, "tables": tables}, password)


@app.post("/v1/render", tags=["read"], summary="Render pages to PNG/JPEG/WebP")
async def render(
    file: PdfFile,
    pages: Pages = None,
    dpi: Annotated[int, Form()] = 150,
    format: Annotated[str, Form(description="png | jpg | webp")] = "png",
    quality: Annotated[int, Form(description="JPEG/WebP quality")] = 85,
    password: Password = None,
    output: OutputForm = "auto",
) -> Response:
    op = {"op": "render", "pages": pages, "dpi": dpi, "format": format, "quality": quality}
    return await _run(file, op, password, output)


@app.post("/v1/images", tags=["read"], summary="Extract embedded images")
async def images(
    file: PdfFile,
    pages: Pages = None,
    min_size: Annotated[int, Form(description="skip images smaller than this (px)")] = 32,
    password: Password = None,
    output: OutputForm = "auto",
) -> Response:
    return await _run(file, {"op": "images", "pages": pages, "min_size": min_size}, password, output)


@app.post("/v1/forms/fields", tags=["forms"], summary="List form fields with type, value and options")
async def form_fields(file: PdfFile, password: Password = None) -> Response:
    return await _run(file, {"op": "form_fields"}, password)


# ---------------------------------------------------------------- pages


@app.post("/v1/split", tags=["pages"], summary="Split by ranges, every N pages or bookmarks")
async def split(
    file: PdfFile,
    ranges: Annotated[str | None, Form(description="one output per token, e.g. 1-3,4-6,7-")] = None,
    every: Annotated[int | None, Form(description="chunks of N pages")] = None,
    by: Annotated[str | None, Form(description="bookmarks")] = None,
    password: Password = None,
    output: OutputForm = "auto",
) -> Response:
    return await _run(file, _clean({"op": "split", "ranges": ranges, "every": every, "by": by}), password, output)


@app.post("/v1/merge", tags=["pages"], summary="Merge several PDFs in upload order")
async def merge(
    files: Annotated[list[UploadFile], FormFile(description="PDFs in order (repeat the field)")],
    output: OutputForm = "auto",
) -> Response:
    if len(files) < 2:
        raise PdfToolError("send at least two PDFs in 'files'", "missing_file")
    names = [f"#{i}" for i in range(1, len(files))]
    assets = {name: await _read(f) for name, f in zip(names, files[1:], strict=True)}
    return await _run(files[0], {"op": "merge", "files": names}, None, output, assets)


@app.post("/v1/select", tags=["pages"], summary="Keep/reorder/duplicate pages (e.g. 3,1,2 or last-1)")
async def select(file: PdfFile, pages: Annotated[str, Form()], password: Password = None) -> Response:
    return await _run(file, {"op": "select", "pages": pages}, password)


@app.post("/v1/delete", tags=["pages"], summary="Delete pages")
async def delete(file: PdfFile, pages: Annotated[str, Form()], password: Password = None) -> Response:
    return await _run(file, {"op": "delete", "pages": pages}, password)


@app.post("/v1/rotate", tags=["pages"], summary="Rotate pages clockwise by a multiple of 90°")
async def rotate(
    file: PdfFile, angle: Annotated[int, Form()] = 90, pages: Pages = None, password: Password = None
) -> Response:
    return await _run(file, {"op": "rotate", "angle": angle, "pages": pages}, password)


@app.post("/v1/insert-blank", tags=["pages"], summary="Insert blank pages after the given pages (0 = at start)")
async def insert_blank(
    file: PdfFile,
    after: Annotated[str, Form()],
    count: Annotated[int, Form()] = 1,
    password: Password = None,
) -> Response:
    return await _run(file, {"op": "insert_blank", "after": after, "count": count}, password)


# ---------------------------------------------------------------- content


@app.post("/v1/watermark", tags=["content"], summary="Text watermark or stamp")
async def watermark(
    file: PdfFile,
    text: Annotated[str, Form(description="newlines allowed")],
    pages: Pages = None,
    font_size: Annotated[float, Form()] = 48,
    color: Annotated[str, Form()] = "#888888",
    opacity: Annotated[float, Form()] = 0.3,
    rotation: Annotated[float, Form()] = 45,
    position: Annotated[str, Form(description="center, top-left, …, bottom-right")] = "center",
    margin_mm: Annotated[float, Form()] = 10,
    layer: Annotated[str, Form(description="over | under")] = "over",
    password: Password = None,
) -> Response:
    op = {
        "op": "watermark", "text": text, "pages": pages, "font_size": font_size, "color": color,
        "opacity": opacity, "rotation": rotation, "position": position, "margin_mm": margin_mm, "layer": layer,
    }  # fmt: skip
    return await _run(file, op, password)


@app.post("/v1/stamp", tags=["content"], summary="Image stamp (logo, signature) on pages")
async def stamp_image(
    file: PdfFile,
    image: Annotated[UploadFile, FormFile(description="PNG or JPEG")],
    pages: Pages = None,
    position: Annotated[str, Form()] = "bottom-right",
    width_mm: Annotated[float, Form()] = 40,
    opacity: Annotated[float, Form()] = 1.0,
    margin_mm: Annotated[float, Form()] = 10,
    layer: Annotated[str, Form()] = "over",
    password: Password = None,
) -> Response:
    op = {
        "op": "stamp_image", "file": "image", "pages": pages, "position": position, "width_mm": width_mm,
        "opacity": opacity, "margin_mm": margin_mm, "layer": layer,
    }  # fmt: skip
    return await _run(file, op, password, assets={"image": await _read(image)})


@app.post("/v1/page-numbers", tags=["content"], summary="Add page numbers")
async def page_numbers(
    file: PdfFile,
    format: Annotated[str, Form(description="placeholders {page} and {total}")] = "{page} / {total}",
    pages: Pages = None,
    start: Annotated[int, Form()] = 1,
    position: Annotated[str, Form()] = "bottom-center",
    font_size: Annotated[float, Form()] = 10,
    color: Annotated[str, Form()] = "#000000",
    margin_mm: Annotated[float, Form()] = 10,
    password: Password = None,
) -> Response:
    op = {
        "op": "page_numbers", "format": format, "pages": pages, "start": start, "position": position,
        "font_size": font_size, "color": color, "margin_mm": margin_mm,
    }  # fmt: skip
    return await _run(file, op, password)


@app.post("/v1/overlay", tags=["content"], summary="Letterhead/background from another PDF")
async def overlay(
    file: PdfFile,
    overlay: Annotated[UploadFile, FormFile(description="PDF; last page repeats for remaining pages")],
    pages: Pages = None,
    layer: Annotated[str, Form(description="under | over")] = "under",
    password: Password = None,
) -> Response:
    op = {"op": "overlay", "file": "overlay", "pages": pages, "layer": layer}
    return await _run(file, op, password, assets={"overlay": await _read(overlay)})


# ---------------------------------------------------------------- forms


@app.post("/v1/forms/fill", tags=["forms"], summary="Fill form fields (JSON object name → value)")
async def form_fill(
    file: PdfFile,
    values: Annotated[str, Form(description='JSON, e.g. {"Name": "Max", "Agree": true}')],
    flatten: Annotated[bool, Form()] = False,
    ignore_unknown: Annotated[bool, Form()] = False,
    password: Password = None,
) -> Response:
    try:
        parsed = json.loads(values)
    except json.JSONDecodeError as exc:
        raise PdfToolError(f"'values' is not valid JSON: {exc}", "invalid_json") from None
    if not isinstance(parsed, dict):
        raise PdfToolError("'values' must be a JSON object", "invalid_json")
    op = {"op": "fill_form", "values": parsed, "flatten": flatten, "ignore_unknown": ignore_unknown}
    return await _run(file, op, password)


@app.post("/v1/forms/flatten", tags=["forms"], summary="Burn form fields and annotations into the pages")
async def form_flatten(file: PdfFile, password: Password = None) -> Response:
    return await _run(file, {"op": "flatten"}, password)


# ---------------------------------------------------------------- document


@app.post("/v1/metadata", tags=["document"], summary="Set title/author/…; `remove` deletes keys")
async def metadata(
    file: PdfFile,
    title: Annotated[str | None, Form()] = None,
    author: Annotated[str | None, Form()] = None,
    subject: Annotated[str | None, Form()] = None,
    keywords: Annotated[str | None, Form()] = None,
    creator: Annotated[str | None, Form()] = None,
    producer: Annotated[str | None, Form()] = None,
    remove: Annotated[str | None, Form(description="comma-separated keys to delete, e.g. subject,keywords")] = None,
    clear: Annotated[bool, Form(description="remove all existing metadata first")] = False,
    password: Password = None,
) -> Response:
    values = {"title": title, "author": author, "subject": subject, "keywords": keywords,
              "creator": creator, "producer": producer}  # fmt: skip
    op: dict[str, Any] = {"op": "metadata", "clear": clear, **_clean(values)}
    for key in (remove or "").split(","):
        if key.strip():
            op[key.strip().lower()] = None  # explicit None = delete; unknown keys are rejected by the op
    return await _run(file, op, password)


@app.post("/v1/compress", tags=["document"], summary="Compress (lossless; lossy with image_quality)")
async def compress(
    file: PdfFile,
    image_quality: Annotated[int | None, Form(description="10-95: recompress images as JPEG")] = None,
    max_image_px: Annotated[int | None, Form(description="downscale images to this long side")] = None,
    linearize: Annotated[bool, Form(description="optimize for web view")] = False,
    password: Password = None,
) -> Response:
    op = _clean(
        {"op": "compress", "image_quality": image_quality, "max_image_px": max_image_px, "linearize": linearize}
    )
    return await _run(file, op, password)


@app.post("/v1/encrypt", tags=["document"], summary="Password-protect (AES-256)")
async def encrypt(
    file: PdfFile,
    user_password: Annotated[str, Form(description="needed to open; empty = opens without")] = "",
    owner_password: Annotated[str, Form(description="needed to change permissions")] = "",
    allow_print: Annotated[bool, Form()] = True,
    allow_copy: Annotated[bool, Form()] = True,
    allow_modify: Annotated[bool, Form()] = True,
    allow_annotate: Annotated[bool, Form()] = True,
    allow_forms: Annotated[bool, Form()] = True,
    password: Password = None,
) -> Response:
    op = {
        "op": "encrypt", "user_password": user_password, "owner_password": owner_password,
        "allow_print": allow_print, "allow_copy": allow_copy, "allow_modify": allow_modify,
        "allow_annotate": allow_annotate, "allow_forms": allow_forms,
    }  # fmt: skip
    return await _run(file, op, password)


@app.post("/v1/decrypt", tags=["document"], summary="Remove the password")
async def decrypt(
    file: PdfFile, password: Annotated[str, Form(description="empty for owner-password-only PDFs")] = ""
) -> Response:
    return await _run(file, {"op": "decrypt"}, password)


@app.post("/v1/repair", tags=["document"], summary="Rewrite a damaged PDF (qpdf recovery); output is unencrypted")
async def repair(file: PdfFile, password: Password = None) -> Response:
    return await _run(file, {"op": "decrypt"}, password)


@app.post("/v1/images-to-pdf", tags=["document"], summary="Images (PNG/JPEG/…) to one PDF, one page each")
async def images_to_pdf(
    files: Annotated[list[UploadFile], FormFile(description="images in order (repeat the field)")],
    page_size: Annotated[str | None, Form(description="a4, letter, a4-landscape; default = image size")] = None,
    margin_mm: Annotated[float, Form()] = 0,
) -> Response:
    datas = [await _read(f) for f in files]
    pdf = await anyio.to_thread.run_sync(lambda: document.images_to_pdf(datas, page_size, margin_mm), limiter=_limiter)
    return file_response(File(f"{stem_of(files[0].filename).rsplit('.', 1)[0]}.pdf", PDF_MIME, pdf))


# ---------------------------------------------------------------- pipeline


@app.post("/v1/pipeline", tags=["pipeline"], summary="Run several operations in one request (multipart)")
async def run_pipeline(
    file: PdfFile,
    ops: Annotated[str, Form(description='JSON array, e.g. [{"op":"delete","pages":"1"},{"op":"compress"}]')],
    assets: Annotated[
        list[UploadFile] | None, FormFile(description="extra files, referenced in ops by their filename")
    ] = None,
    password: Password = None,
    output: OutputForm = "auto",
) -> Response:
    try:
        raw_ops = json.loads(ops)
    except json.JSONDecodeError as exc:
        raise PdfToolError(f"'ops' is not valid JSON: {exc}", "invalid_json") from None
    parsed = pipeline.parse_ops(raw_ops)
    asset_data = {(a.filename or f"asset{i}"): await _read(a) for i, a in enumerate(assets or [])}
    data = await _read(file)

    def work() -> Result:
        doc = Doc.load(data, file.filename, password)
        return pipeline.run(doc, parsed, asset_data, len(data))

    result = await anyio.to_thread.run_sync(work, limiter=_limiter)
    return to_response(result, output, stem_of(file.filename))


class JsonPipeline(BaseModel):
    file: str = Field(description="the PDF, base64")
    filename: str = "document.pdf"
    ops: list[dict[str, Any]]
    assets: dict[str, str] = Field(default_factory=dict, description="name → base64")
    password: str | None = None
    output: Output = "json"


def _b64(value: str, what: str) -> bytes:
    if "," in value[:100] and value.startswith("data:"):
        value = value.split(",", 1)[1]
    try:
        data = base64.b64decode(value, validate=False)
    except (binascii.Error, ValueError):
        raise PdfToolError(f"'{what}' is not valid base64", "invalid_base64") from None
    if len(data) > settings.max_upload_bytes:
        raise PdfToolError(f"'{what}' exceeds {settings.max_upload_mb} MB", "too_large", 413)
    return data


@app.post("/v1/pipeline/json", tags=["pipeline"], summary="Pipeline with base64 JSON in and (default) out")
async def run_pipeline_json(body: JsonPipeline) -> Response:
    parsed = pipeline.parse_ops(body.ops)
    data = _b64(body.file, "file")
    assets = {name: _b64(value, f"assets.{name}") for name, value in body.assets.items()}

    def work() -> Result:
        doc = Doc.load(data, body.filename, body.password)
        return pipeline.run(doc, parsed, assets, len(data))

    result = await anyio.to_thread.run_sync(work, limiter=_limiter)
    return to_response(result, body.output, stem_of(body.filename))
