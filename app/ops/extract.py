"""Read-only output: text/tables (pdfplumber), page images (pdfium), embedded images (pikepdf)."""

import io
import re
import threading
from typing import Any

import pdfplumber
import pikepdf
import pypdfium2 as pdfium

from .. import pagespec
from ..config import settings
from ..doc import Doc, File
from ..errors import PdfToolError

# pdfium is not thread-safe; all pdfium calls in this process go through this lock.
_pdfium_lock = threading.Lock()

IMAGE_FORMATS = {
    "png": ("image/png", "PNG"),
    "jpg": ("image/jpeg", "JPEG"),
    "jpeg": ("image/jpeg", "JPEG"),
    "webp": ("image/webp", "WEBP"),
}


def text(doc: Doc, pages: str | None = None, layout: bool = False, tables: bool = False) -> dict[str, Any]:
    data = doc.snapshot()
    result_pages = []
    with pdfplumber.open(io.BytesIO(data)) as plumber:
        for i in pagespec.parse(pages, len(plumber.pages)):
            page = plumber.pages[i]
            entry: dict[str, Any] = {"page": i + 1, "text": page.extract_text(layout=layout) or ""}
            if tables:
                entry["tables"] = page.extract_tables()
            result_pages.append(entry)
    full = "\n\n".join(p["text"] for p in result_pages)
    return {
        "page_count": len(doc.pdf.pages),
        "pages": result_pages,
        "text": full,
        # no text layer at all usually means a scan: OCR it elsewhere (e.g. Mistral OCR)
        "has_text": bool(full.strip()),
    }


def render(
    doc: Doc,
    pages: str | None = None,
    dpi: int = 150,
    format: str = "png",
    quality: int = 85,
) -> list[File]:
    fmt = IMAGE_FORMATS.get(format.lower())
    if not fmt:
        raise PdfToolError("format must be png, jpg or webp", "invalid_format")
    if not 10 <= dpi <= settings.max_render_dpi:
        raise PdfToolError(f"dpi must be between 10 and {settings.max_render_dpi}", "invalid_dpi")
    mime, pil_format = fmt
    ext = "jpg" if pil_format == "JPEG" else format.lower()
    data = doc.snapshot()
    files = []
    with _pdfium_lock:
        pdf = pdfium.PdfDocument(data)
        try:
            indices = pagespec.parse(pages, len(pdf))
            if len(indices) > settings.max_render_pages:
                raise PdfToolError(
                    f"rendering is limited to {settings.max_render_pages} pages per request", "too_many_pages", 413
                )
            scale = dpi / 72
            for i in indices:
                w, h = pdf[i].get_size()
                megapixels = w * h * scale * scale / 1e6
                if megapixels > settings.max_render_megapixels:
                    raise PdfToolError(
                        f"page {i + 1} would be {megapixels:.0f} MP at {dpi} dpi, "
                        f"limit is {settings.max_render_megapixels} MP; lower the dpi",
                        "too_large",
                        413,
                    )
            for i in indices:
                bitmap = pdf[i].render(scale=scale, may_draw_forms=True)
                img = bitmap.to_pil()
                if pil_format == "JPEG":
                    img = img.convert("RGB")
                out = io.BytesIO()
                img.save(out, pil_format, **({"quality": quality} if pil_format != "PNG" else {"optimize": True}))
                files.append(File(f"{doc.stem}_p{i + 1}.{ext}", mime, out.getvalue()))
        finally:
            pdf.close()
    return files


def images(doc: Doc, pages: str | None = None, min_size: int = 32) -> list[File]:
    """Extract embedded raster images in their original encoding where possible."""
    seen: set[tuple[int, int]] = set()
    files = []
    for i in sorted(pagespec.parse_set(pages, len(doc.pdf.pages))):
        for name, raw in doc.pdf.pages[i].get_images().items():
            if raw.objgen in seen:
                continue
            seen.add(raw.objgen)
            try:
                img = pikepdf.PdfImage(raw)
                if img.width < min_size or img.height < min_size:
                    continue
                out = io.BytesIO()
                ext = img.extract_to(stream=out).lstrip(".")
            except Exception:
                continue  # exotic encodings (JBIG2 without decoder etc.) are skipped
            mime = {"jpg": "image/jpeg", "png": "image/png", "tif": "image/tiff", "jp2": "image/jp2"}.get(
                ext, "application/octet-stream"
            )
            label = re.sub(r"[^\w\-]+", "_", str(name).lstrip("/"))[:40] or "img"
            files.append(File(f"{doc.stem}_p{i + 1}_{label}.{ext}", mime, out.getvalue()))
    return files
