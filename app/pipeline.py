"""Operations as data: every endpoint and /v1/pipeline run a list of these against one document.

Transforming operations can be chained freely. The last operation may produce something
other than a PDF (split, render, text, info, images, form_fields); such operations are only
allowed at the end of a pipeline.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from .doc import Doc, File, Result, open_pdf
from .errors import PdfToolError
from .ops import document, extract, forms, pages, stamp

Layer = Literal["over", "under"]


class Op(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Select(Op):
    op: Literal["select"]
    pages: str


class Delete(Op):
    op: Literal["delete"]
    pages: str


class Rotate(Op):
    op: Literal["rotate"]
    angle: int = 90
    pages: str | None = None


class InsertBlank(Op):
    op: Literal["insert_blank"]
    after: str
    count: int = Field(1, ge=1, le=100)


class Merge(Op):
    op: Literal["merge"]
    files: list[str] = Field(description="names of uploaded assets, appended in this order")


class Watermark(Op):
    op: Literal["watermark"]
    text: str
    pages: str | None = None
    font_size: float = Field(48, gt=0, le=500)
    color: str = "#888888"
    opacity: float = 0.3
    rotation: float = 45
    position: str = "center"
    margin_mm: float = 10
    layer: Layer = "over"


class StampImage(Op):
    op: Literal["stamp_image"]
    file: str = Field(description="name of the uploaded image asset (PNG/JPEG)")
    pages: str | None = None
    position: str = "bottom-right"
    width_mm: float = Field(40, gt=0, le=2000)
    opacity: float = 1.0
    margin_mm: float = 10
    layer: Layer = "over"


class PageNumbers(Op):
    op: Literal["page_numbers"]
    format: str = "{page} / {total}"
    pages: str | None = None
    start: int = 1
    position: str = "bottom-center"
    font_size: float = Field(10, gt=0, le=200)
    color: str = "#000000"
    margin_mm: float = 10


class Overlay(Op):
    op: Literal["overlay"]
    file: str = Field(description="name of the uploaded PDF asset (e.g. letterhead)")
    pages: str | None = None
    layer: Layer = "under"


class Metadata(Op):
    op: Literal["metadata"]
    title: str | None = None
    author: str | None = None
    subject: str | None = None
    keywords: str | None = None
    creator: str | None = None
    producer: str | None = None
    clear: bool = False


class FillForm(Op):
    op: Literal["fill_form"]
    values: dict[str, Any]
    flatten: bool = False
    ignore_unknown: bool = False


class Flatten(Op):
    op: Literal["flatten"]


class Compress(Op):
    op: Literal["compress"]
    image_quality: int | None = None
    max_image_px: int | None = Field(None, ge=64)
    linearize: bool = False


class Encrypt(Op):
    op: Literal["encrypt"]
    user_password: str = ""
    owner_password: str = ""
    allow_print: bool = True
    allow_copy: bool = True
    allow_modify: bool = True
    allow_annotate: bool = True
    allow_forms: bool = True


class Decrypt(Op):
    op: Literal["decrypt"]


# terminal operations


class Split(Op):
    op: Literal["split"]
    ranges: str | None = None
    every: int | None = None
    by: Literal["bookmarks"] | None = None


class Render(Op):
    op: Literal["render"]
    pages: str | None = None
    dpi: int = 150
    format: Literal["png", "jpg", "jpeg", "webp"] = "png"
    quality: int = Field(85, ge=10, le=100)


class Text(Op):
    op: Literal["text"]
    pages: str | None = None
    layout: bool = False
    tables: bool = False


class Info(Op):
    op: Literal["info"]


class Images(Op):
    op: Literal["images"]
    pages: str | None = None
    min_size: int = 32


class FormFields(Op):
    op: Literal["form_fields"]


AnyOp = Annotated[
    Select
    | Delete
    | Rotate
    | InsertBlank
    | Merge
    | Watermark
    | StampImage
    | PageNumbers
    | Overlay
    | Metadata
    | FillForm
    | Flatten
    | Compress
    | Encrypt
    | Decrypt
    | Split
    | Render
    | Text
    | Info
    | Images
    | FormFields,
    Field(discriminator="op"),
]
TERMINAL = (Split, Render, Text, Info, Images, FormFields)
_ops_adapter = TypeAdapter(list[AnyOp])


def parse_ops(raw: Any) -> list[Op]:
    try:
        ops = _ops_adapter.validate_python(raw)
    except ValidationError as exc:
        details = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors(include_url=False))
        raise PdfToolError(f"invalid operations: {details}", "invalid_operations") from None
    if not ops:
        raise PdfToolError("'ops' must contain at least one operation", "invalid_operations")
    for op in ops[:-1]:
        if isinstance(op, TERMINAL):
            raise PdfToolError(f"'{op.op}' must be the last operation", "invalid_operations")
    return ops


def _asset(assets: dict[str, bytes], name: str) -> bytes:
    if name not in assets:
        raise PdfToolError(f"asset '{name}' was not uploaded (got {sorted(assets)})", "missing_asset")
    return assets[name]


def _apply(doc: Doc, op: Op, assets: dict[str, bytes], input_size: int) -> Result | None:
    match op:
        case Select():
            pages.select(doc, op.pages)
        case Delete():
            pages.delete(doc, op.pages)
        case Rotate():
            pages.rotate(doc, op.angle, op.pages)
        case InsertBlank():
            pages.insert_blank(doc, op.after, op.count)
        case Merge():
            pages.merge(doc, [open_pdf(_asset(assets, n)) for n in op.files])
        case Watermark():
            stamp.watermark(doc, **op.model_dump(exclude={"op"}))
        case StampImage():
            params = op.model_dump(exclude={"op", "file"})
            stamp.image(doc, _asset(assets, op.file), **params)
        case PageNumbers():
            stamp.page_numbers(doc, **op.model_dump(exclude={"op"}))
        case Overlay():
            stamp.overlay(doc, open_pdf(_asset(assets, op.file)), op.pages, op.layer)
        case Metadata():
            values = op.model_dump(exclude={"op", "clear"}, exclude_unset=True)
            document.metadata(doc, values, op.clear)
        case FillForm():
            forms.fill(doc, op.values, op.flatten, op.ignore_unknown)
        case Flatten():
            forms.flatten(doc)
        case Compress():
            document.compress(doc, op.image_quality, op.max_image_px, op.linearize)
        case Encrypt():
            document.encrypt(doc, **op.model_dump(exclude={"op"}))
        case Decrypt():
            document.decrypt(doc)
        case Split():
            return Result(files=pages.split(doc, op.ranges, op.every, op.by))
        case Render():
            return Result(files=extract.render(doc, op.pages, op.dpi, op.format, op.quality))
        case Text():
            return Result(json=extract.text(doc, op.pages, op.layout, op.tables))
        case Info():
            return Result(json=document.info(doc, input_size))
        case Images():
            return Result(files=extract.images(doc, op.pages, op.min_size))
        case FormFields():
            return Result(json={"fields": forms.list_fields(doc)})
    return None


def run(doc: Doc, ops: list[Op], assets: dict[str, bytes] | None = None, input_size: int = 0) -> Result:
    assets = assets or {}
    for op in ops:
        result = _apply(doc, op, assets, input_size)
        if result is not None:
            return result
    return Result(files=[doc.as_file()])


def single(doc: Doc, op: dict[str, Any], assets: dict[str, bytes] | None = None, input_size: int = 0) -> Result:
    return run(doc, parse_ops([op]), assets, input_size)


__all__ = ["File", "Result", "parse_ops", "run", "single"]
