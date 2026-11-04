"""Document-level operations: info, metadata, security, compression, images to PDF."""

import io
import warnings
from typing import Any

import img2pdf
import pikepdf
from PIL import Image

from ..doc import Doc
from ..errors import PdfToolError
from . import forms

MM = 25.4 / 72
DOCINFO_KEYS = {
    "title": "/Title",
    "author": "/Author",
    "subject": "/Subject",
    "keywords": "/Keywords",
    "creator": "/Creator",
    "producer": "/Producer",
}
XMP_KEYS = {
    "title": "dc:title",
    "author": "dc:creator",
    "subject": "dc:description",
    "keywords": "pdf:Keywords",
    "creator": "xmp:CreatorTool",
    "producer": "pdf:Producer",
}


def _docinfo(pdf: pikepdf.Pdf) -> dict[str, str]:
    result = {}
    for key, value in (pdf.docinfo or {}).items():
        try:
            result[str(key).lstrip("/")] = str(value)
        except Exception:
            continue
    return result


def _bookmarks(pdf: pikepdf.Pdf) -> list[dict[str, Any]]:
    result = []
    try:
        with pdf.open_outline() as outline:
            for item in outline.root:
                page = None
                try:
                    dest = item.destination
                    if dest is None and item.action is not None and "/D" in item.action:
                        dest = item.action.D
                    if isinstance(dest, pikepdf.Array) and len(dest) > 0:
                        page = pikepdf.Page(dest[0]).index + 1
                except Exception:
                    pass
                result.append({"title": item.title, "page": page})
    except Exception:
        pass
    return result


def info(doc: Doc, size: int | None = None) -> dict[str, Any]:
    pdf = doc.pdf
    pages = []
    for i, page in enumerate(pdf.pages):
        box = page.cropbox
        w, h = float(box[2] - box[0]), float(box[3] - box[1])
        rot = int(page.obj.get("/Rotate", 0)) % 360
        if rot in (90, 270):
            w, h = h, w
        pages.append(
            {
                "page": i + 1,
                "width_pt": round(w, 2),
                "height_pt": round(h, 2),
                "width_mm": round(w * MM, 1),
                "height_mm": round(h * MM, 1),
                "rotation": rot,
                "orientation": "landscape" if w > h else "portrait",
            }
        )
    fields = forms.list_fields(doc) if "/AcroForm" in pdf.Root else []
    return {
        "page_count": len(pdf.pages),
        "pdf_version": pdf.pdf_version,
        "encrypted": doc.was_encrypted,
        "file_size": size,
        "metadata": _docinfo(pdf),
        "pages": pages,
        "bookmarks": _bookmarks(pdf),
        "attachments": list(pdf.attachments.keys()),
        "form_fields": fields,
    }


def metadata(doc: Doc, values: dict[str, str | None], clear: bool = False) -> None:
    """Set document metadata (docinfo and XMP). ``None``/empty removes a key; ``clear`` removes all first."""
    pdf = doc.pdf
    unknown = sorted(set(values) - set(DOCINFO_KEYS))
    if unknown:
        raise PdfToolError(f"unknown metadata keys {unknown}, allowed: {sorted(DOCINFO_KEYS)}", "invalid_metadata")
    if clear:
        if "/Metadata" in pdf.Root:
            del pdf.Root["/Metadata"]
        pdf.trailer.Info = pdf.make_indirect(pikepdf.Dictionary())
    had_xmp = "/Metadata" in pdf.Root
    with pdf.open_metadata(set_pikepdf_as_editor=False) as xmp:
        if not had_xmp:
            # closing the block syncs XMP → docinfo; seed XMP so existing docinfo survives
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # e.g. /Trapped has no XMP equivalent; docinfo keeps it
                xmp.load_from_docinfo(pdf.docinfo)
        for key, value in values.items():
            xmp_key = XMP_KEYS[key]
            if value:
                xmp[xmp_key] = [value] if key == "author" else value
            elif xmp_key in xmp:
                del xmp[xmp_key]
    for key, value in values.items():
        if value:
            pdf.docinfo[DOCINFO_KEYS[key]] = value
        elif DOCINFO_KEYS[key] in pdf.docinfo:
            del pdf.docinfo[DOCINFO_KEYS[key]]


def encrypt(
    doc: Doc,
    user_password: str = "",
    owner_password: str = "",
    allow_print: bool = True,
    allow_copy: bool = True,
    allow_modify: bool = True,
    allow_annotate: bool = True,
    allow_forms: bool = True,
) -> None:
    """AES-256 encryption, applied when the document is written."""
    if not user_password and not owner_password:
        raise PdfToolError("set 'user_password' (to open) and/or 'owner_password'", "missing_password")
    permissions = pikepdf.Permissions(
        print_lowres=allow_print,
        print_highres=allow_print,
        extract=allow_copy,
        accessibility=True,
        modify_other=allow_modify,
        modify_assembly=allow_modify,
        modify_annotation=allow_annotate,
        modify_form=allow_forms,
    )
    doc.save_options["encryption"] = pikepdf.Encryption(
        owner=owner_password or user_password, user=user_password, R=6, allow=permissions
    )


def decrypt(doc: Doc) -> None:
    """Written without encryption. The password itself is passed when opening the input."""
    doc.save_options.pop("encryption", None)


def _recompress_images(pdf: pikepdf.Pdf, quality: int, max_px: int | None) -> None:
    seen: set[tuple[int, int]] = set()
    for page in pdf.pages:
        for raw in page.get_images().values():
            if raw.objgen in seen:
                continue
            seen.add(raw.objgen)
            try:
                if raw.get("/ImageMask") or "/Decode" in raw or "/SMask" in raw and raw.SMask.get("/Matte"):
                    continue
                img = pikepdf.PdfImage(raw)
                if img.mode not in ("RGB", "L") or img.bits_per_component != 8:
                    continue
                pil = img.as_pil_image()
                if max_px and max(pil.size) > max_px:
                    pil.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
                out = io.BytesIO()
                pil.save(out, "JPEG", quality=quality, optimize=True)
                data = out.getvalue()
                if len(data) >= len(raw.read_raw_bytes()):
                    continue
                raw.write(data, filter=pikepdf.Name.DCTDecode)
                raw.Width, raw.Height = pil.size
                raw.BitsPerComponent = 8
                if "/DecodeParms" in raw:
                    del raw["/DecodeParms"]
            except Exception:
                continue


def compress(
    doc: Doc,
    image_quality: int | None = None,
    max_image_px: int | None = None,
    linearize: bool = False,
) -> None:
    """Lossless stream/object compression; optionally recompress large images as JPEG (lossy)."""
    if image_quality is not None:
        if not 10 <= image_quality <= 95:
            raise PdfToolError("image_quality must be between 10 and 95", "invalid_quality")
        _recompress_images(doc.pdf, image_quality, max_image_px)
    elif max_image_px:
        _recompress_images(doc.pdf, 85, max_image_px)
    doc.pdf.remove_unreferenced_resources()
    doc.save_options.update(
        compress_streams=True,
        recompress_flate=True,
        object_stream_mode=pikepdf.ObjectStreamMode.generate,
        linearize=linearize,
    )


def images_to_pdf(images: list[bytes], page_size: str | None = None, margin_mm: float = 0) -> bytes:
    """One page per image. Without ``page_size`` each page has the image's own size."""
    if not images:
        raise PdfToolError("send at least one image in 'files'", "missing_file")
    sizes = {
        "a4": (img2pdf.mm_to_pt(210), img2pdf.mm_to_pt(297)),
        "letter": (img2pdf.in_to_pt(8.5), img2pdf.in_to_pt(11)),
    }
    layout = None
    if page_size:
        key = page_size.lower().removesuffix("-landscape")
        if key not in sizes:
            raise PdfToolError("page_size must be a4, letter, a4-landscape or letter-landscape", "invalid_page_size")
        w, h = sizes[key]
        if page_size.lower().endswith("-landscape"):
            w, h = h, w
        border = img2pdf.mm_to_pt(margin_mm)
        layout = img2pdf.get_layout_fun((w, h), border=(border, border), fit=img2pdf.FitMode.into)
    prepared = []
    for data in images:
        try:
            with Image.open(io.BytesIO(data)) as img:
                # img2pdf refuses alpha channels; flatten those onto white
                if img.mode in ("RGBA", "LA", "P") and ("A" in img.mode or "transparency" in img.info):
                    rgba = img.convert("RGBA")
                    bg = Image.new("RGB", rgba.size, "white")
                    bg.paste(rgba, mask=rgba.split()[-1])
                    out = io.BytesIO()
                    bg.save(out, "PNG")
                    data = out.getvalue()
        except Exception:
            raise PdfToolError("one of the files is not a readable image", "invalid_image") from None
        prepared.append(data)
    try:
        return img2pdf.convert(prepared, layout_fun=layout) if layout else img2pdf.convert(prepared)
    except Exception as exc:
        raise PdfToolError(f"could not convert images: {exc}", "invalid_image") from None
