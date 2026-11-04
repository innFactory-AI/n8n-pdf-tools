"""Page structure: select/reorder, delete, rotate, merge, split, blank pages."""

import io
from itertools import pairwise

import pikepdf
import pypdf

from .. import pagespec
from ..doc import PDF_MIME, Doc, File, save_pdf
from ..errors import PdfToolError


def _rebuild(pdf: pikepdf.Pdf, indices: list[int]) -> None:
    keep = [pdf.pages[i] for i in indices]
    del pdf.pages[:]
    pdf.pages.extend(keep)


def select(doc: Doc, pages: str) -> None:
    """Keep only the given pages, in the given order (duplicates allowed)."""
    _rebuild(doc.pdf, pagespec.parse(pages, len(doc.pdf.pages)))


def delete(doc: Doc, pages: str) -> None:
    n = len(doc.pdf.pages)
    drop = pagespec.parse_set(pages, n, default="")
    if len(drop) >= n:
        raise PdfToolError("cannot delete every page", "invalid_pages")
    _rebuild(doc.pdf, [i for i in range(n) if i not in drop])


def rotate(doc: Doc, angle: int, pages: str | None = None) -> None:
    if angle % 90 != 0:
        raise PdfToolError("angle must be a multiple of 90", "invalid_angle")
    for i in pagespec.parse_set(pages, len(doc.pdf.pages)):
        doc.pdf.pages[i].rotate(angle, relative=True)


def merge(doc: Doc, others: list[pikepdf.Pdf]) -> None:
    for other in others:
        doc.pdf.add_pages_from(other)  # unlike pages.extend, keeps form fields working


def insert_blank(doc: Doc, after: str, count: int = 1) -> None:
    """Insert blank pages (same size as the preceding page) after each given page; 0 = before page 1."""
    n = len(doc.pdf.pages)
    positions: set[int] = set()
    for token in pagespec.tokens(after):
        if token.strip() == "0":
            positions.add(0)
        else:
            positions.update(i + 1 for i in pagespec.parse_token(token, n))
    for pos in sorted(positions, reverse=True):
        ref = doc.pdf.pages[max(pos - 1, 0)]
        box = [float(v) for v in ref.mediabox]
        for _ in range(count):
            doc.pdf.pages.insert(pos, _blank_page(doc.pdf, box))


def _blank_page(pdf: pikepdf.Pdf, mediabox: list[float]) -> pikepdf.Page:
    page = pikepdf.Dictionary(
        Type=pikepdf.Name.Page,
        MediaBox=mediabox,
        Resources=pikepdf.Dictionary(),
        Contents=pdf.make_stream(b""),
    )
    return pikepdf.Page(pdf.make_indirect(page))


def _part(doc: Doc, indices: list[int]) -> bytes:
    part = pikepdf.new()
    part.add_pages_from(doc.pdf, indices)
    if doc.pdf.docinfo:
        part.docinfo = part.copy_foreign(doc.pdf.docinfo)
    return save_pdf(part, **doc.save_options)


def _name(doc: Doc, indices: list[int]) -> str:
    first, last = indices[0] + 1, indices[-1] + 1
    label = f"p{first}" if first == last else f"p{first}-{last}"
    return f"{doc.stem}_{label}.pdf"


def _bookmark_groups(doc: Doc) -> list[list[int]]:
    reader = pypdf.PdfReader(io.BytesIO(doc.snapshot()))
    starts: set[int] = set()
    for item in reader.outline:
        if isinstance(item, list):  # children of the previous top-level item
            continue
        try:
            page = reader.get_destination_page_number(item)
        except Exception:
            continue
        if page is not None and page >= 0:
            starts.add(page)
    if not starts:
        raise PdfToolError("the PDF has no usable bookmarks", "no_bookmarks")
    starts.add(0)
    bounds = sorted(starts) + [len(reader.pages)]
    return [list(range(a, b)) for a, b in pairwise(bounds) if b > a]


def split(
    doc: Doc,
    ranges: str | None = None,
    every: int | None = None,
    by: str | None = None,
) -> list[File]:
    """Split into several PDFs.

    - ``ranges="1-3,4-6,7-"``: one file per comma-separated token
    - ``every=N``: chunks of N pages
    - ``by="bookmarks"``: one file per top-level bookmark
    """
    n = len(doc.pdf.pages)
    modes = sum(x is not None and x != "" for x in (ranges, every, by))
    if modes != 1:
        raise PdfToolError("set exactly one of 'ranges', 'every' or 'by'", "invalid_split")
    if ranges:
        groups = [pagespec.parse_token(t, n) for t in pagespec.tokens(ranges)]
    elif every is not None:
        if every < 1:
            raise PdfToolError("'every' must be >= 1", "invalid_split")
        groups = [list(range(i, min(i + every, n))) for i in range(0, n, every)]
    elif by == "bookmarks":
        groups = _bookmark_groups(doc)
    else:
        raise PdfToolError("'by' supports only 'bookmarks'", "invalid_split")
    return [File(_name(doc, g), PDF_MIME, _part(doc, g)) for g in groups]
