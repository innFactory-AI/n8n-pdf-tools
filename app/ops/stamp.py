"""Content on top of (or below) existing pages: text watermarks, images, page numbers, letterheads.

Overlays are drawn with reportlab into one helper PDF (one page per target page) and
placed onto the target pages with pikepdf, which compensates /Rotate, so stamps stay
upright on rotated pages.
"""

import io
import os
import re
from collections.abc import Callable
from functools import lru_cache

import pikepdf
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas

from .. import pagespec
from ..config import settings
from ..doc import Doc
from ..errors import PdfToolError

MM = 72 / 25.4
POSITIONS = {
    "top-left", "top-center", "top-right",
    "center-left", "center", "center-right",
    "bottom-left", "bottom-center", "bottom-right",
}  # fmt: skip


@lru_cache(maxsize=1)
def font_name() -> str:
    """DejaVu Sans if available (full Unicode), otherwise Helvetica (Latin-1 only)."""
    if settings.font_path and os.path.exists(settings.font_path):
        pdfmetrics.registerFont(TTFont("Stamp", settings.font_path))
        return "Stamp"
    return "Helvetica"


def _color(value: str) -> HexColor:
    value = value.strip()
    try:
        return HexColor(value if value.startswith("#") else f"#{value}")
    except Exception:
        raise PdfToolError(f"invalid color '{value}', use hex like #ff0000", "invalid_color") from None


def _check(position: str, opacity: float) -> None:
    if position not in POSITIONS:
        raise PdfToolError(f"position must be one of {sorted(POSITIONS)}", "invalid_position")
    if not 0 <= opacity <= 1:
        raise PdfToolError("opacity must be between 0 and 1", "invalid_opacity")


def _anchor(position: str, w: float, h: float, bw: float, bh: float, margin: float) -> tuple[float, float]:
    """Lower-left corner for a box of size bw x bh on a w x h page."""
    vertical, _, horizontal = position.partition("-") if position != "center" else ("center", "", "center")
    if not horizontal:
        horizontal = "center"
    x = {"left": margin, "center": (w - bw) / 2, "right": w - margin - bw}[horizontal]
    y = {"bottom": margin, "center": (h - bh) / 2, "top": h - margin - bh}[vertical]
    return x, y


Draw = Callable[[rl_canvas.Canvas, float, float, int, int], None]


def _apply(doc: Doc, pages: str | None, draw: Draw, layer: str = "over") -> None:
    """Run ``draw(canvas, visual_w, visual_h, page_index, page_count)`` for every target page."""
    pdf = doc.pdf
    n = len(pdf.pages)
    targets = sorted(pagespec.parse_set(pages, n))
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pageCompression=1)
    for i in targets:
        page = pdf.pages[i]
        box = page.cropbox
        w, h = float(box[2] - box[0]), float(box[3] - box[1])
        rot = int(page.obj.get("/Rotate", 0)) % 360
        # pikepdf places overlays upright on rotated pages, so draw in visual orientation
        vw, vh = (h, w) if rot in (90, 270) else (w, h)
        c.setPageSize((vw, vh))
        draw(c, vw, vh, i, n)
        c.showPage()
    c.save()
    overlay = pikepdf.open(io.BytesIO(buf.getvalue()))
    for k, i in enumerate(targets):
        page = pdf.pages[i]
        rect = pikepdf.Rectangle(page.cropbox)
        src = pdf.copy_foreign(overlay.pages[k].obj)
        if layer == "under":
            page.add_underlay(src, rect)
        else:
            page.add_overlay(src, rect)


def watermark(
    doc: Doc,
    text: str,
    pages: str | None = None,
    font_size: float = 48,
    color: str = "#888888",
    opacity: float = 0.3,
    rotation: float = 45,
    position: str = "center",
    margin_mm: float = 10,
    layer: str = "over",
) -> None:
    if not text:
        raise PdfToolError("'text' is required", "missing_text")
    _check(position, opacity)
    rgb, font = _color(color), font_name()
    lines = text.splitlines() or [text]

    def draw(c: rl_canvas.Canvas, w: float, h: float, _i: int, _n: int) -> None:
        c.setFillColor(rgb)
        c.setFillAlpha(opacity)
        c.setFont(font, font_size)
        bw = max(c.stringWidth(line, font, font_size) for line in lines)
        bh = font_size * 1.2 * len(lines)
        x, y = _anchor(position, w, h, bw, bh, margin_mm * MM)
        c.translate(x + bw / 2, y + bh / 2)
        c.rotate(rotation)
        for k, line in enumerate(lines):
            offset = (len(lines) / 2 - k - 0.8) * font_size * 1.2
            c.drawCentredString(0, offset, line)

    _apply(doc, pages, draw, layer)


def image(
    doc: Doc,
    data: bytes,
    pages: str | None = None,
    position: str = "bottom-right",
    width_mm: float = 40,
    opacity: float = 1.0,
    margin_mm: float = 10,
    layer: str = "over",
) -> None:
    _check(position, opacity)
    try:
        img = ImageReader(io.BytesIO(data))
        iw, ih = img.getSize()
    except Exception:
        raise PdfToolError("the stamp image is not a readable PNG/JPEG", "invalid_image") from None
    bw = width_mm * MM
    bh = bw * ih / iw

    def draw(c: rl_canvas.Canvas, w: float, h: float, _i: int, _n: int) -> None:
        x, y = _anchor(position, w, h, bw, bh, margin_mm * MM)
        c.setFillAlpha(opacity)
        c.drawImage(img, x, y, bw, bh, mask="auto")

    _apply(doc, pages, draw, layer)


def page_numbers(
    doc: Doc,
    format: str = "{page} / {total}",
    pages: str | None = None,
    start: int = 1,
    position: str = "bottom-center",
    font_size: float = 10,
    color: str = "#000000",
    margin_mm: float = 10,
) -> None:
    """Number pages. ``{page}`` counts only the selected pages, starting at ``start``;
    ``{total}`` is the number of selected pages (plus ``start - 1``)."""
    _check(position, 1)
    rgb, font = _color(color), font_name()
    n = len(doc.pdf.pages)
    targets = sorted(pagespec.parse_set(pages, n))
    number = {idx: start + k for k, idx in enumerate(targets)}
    total = start - 1 + len(targets)

    if len(format) > 200 or re.search(r"\{(?!page\}|total\})", format):
        raise PdfToolError("format may only use the placeholders {page} and {total}", "invalid_format")

    def draw(c: rl_canvas.Canvas, w: float, h: float, i: int, _n: int) -> None:
        label = format.replace("{page}", str(number[i])).replace("{total}", str(total))
        c.setFillColor(rgb)
        c.setFont(font, font_size)
        bw = c.stringWidth(label, font, font_size)
        x, y = _anchor(position, w, h, bw, font_size, margin_mm * MM)
        c.drawString(x, y + font_size * 0.2, label)

    _apply(doc, pages, draw)


def overlay(doc: Doc, other: pikepdf.Pdf, pages: str | None = None, layer: str = "under") -> None:
    """Place pages of another PDF (e.g. letterhead) under or over the target pages.

    Target page k gets overlay page k; once the overlay runs out, its last page repeats
    (one page = same background everywhere, two pages = first page + follow-up pages).
    """
    if layer not in ("under", "over"):
        raise PdfToolError("layer must be 'under' or 'over'", "invalid_layer")
    pdf = doc.pdf
    targets = sorted(pagespec.parse_set(pages, len(pdf.pages)))
    # one shared Form XObject per overlay page, not a copy per target page
    sources = [pdf.make_indirect(pdf.copy_foreign(p.as_form_xobject())) for p in other.pages]
    for k, i in enumerate(targets):
        page = pdf.pages[i]
        src = sources[min(k, len(sources) - 1)]
        rect = pikepdf.Rectangle(page.cropbox)
        if layer == "under":
            page.add_underlay(src, rect)
        else:
            page.add_overlay(src, rect)
