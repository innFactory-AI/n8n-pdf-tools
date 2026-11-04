"""The working document of a request and the result types an operation can produce."""

import io
import re
from dataclasses import dataclass, field
from typing import Any

import pikepdf

from .config import settings
from .errors import PdfToolError

PDF_MIME = "application/pdf"


@dataclass
class File:
    name: str
    mime: str
    data: bytes


@dataclass
class Result:
    """Either files (one or more) or a JSON document."""

    files: list[File] = field(default_factory=list)
    json: dict[str, Any] | None = None


def stem_of(filename: str | None) -> str:
    base = (filename or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if base.lower().endswith(".pdf"):
        base = base[:-4]
    base = re.sub(r"[^\w.\- ]+", "_", base).strip(" ._")
    return base or "document"


def open_pdf(data: bytes, password: str | None = None) -> pikepdf.Pdf:
    if not data:
        raise PdfToolError("empty file", "invalid_pdf")
    try:
        pdf = pikepdf.open(io.BytesIO(data), password=password or "")
    except pikepdf.PasswordError:
        if password:
            raise PdfToolError("wrong password", "wrong_password") from None
        raise PdfToolError("the PDF is encrypted, send its password in 'password'", "encrypted") from None
    except pikepdf.PdfError as exc:
        raise PdfToolError(f"not a readable PDF: {exc}", "invalid_pdf") from None
    if len(pdf.pages) > settings.max_pages:
        raise PdfToolError(
            f"document has {len(pdf.pages)} pages, limit is {settings.max_pages}",
            "too_many_pages",
            413,
        )
    return pdf


def save_pdf(pdf: pikepdf.Pdf, **options: Any) -> bytes:
    out = io.BytesIO()
    pdf.save(out, **options)
    return out.getvalue()


class Doc:
    """A PDF being transformed by a chain of operations.

    Operations mutate ``pdf`` in place. Options that only take effect when writing
    (compression, encryption, linearization) are collected in ``save_options``.
    """

    def __init__(self, pdf: pikepdf.Pdf, stem: str, was_encrypted: bool = False):
        self.pdf = pdf
        self.stem = stem
        self.was_encrypted = was_encrypted
        self.save_options: dict[str, Any] = {}

    @classmethod
    def load(cls, data: bytes, filename: str | None, password: str | None = None) -> "Doc":
        pdf = open_pdf(data, password)
        return cls(pdf, stem_of(filename), was_encrypted=pdf.is_encrypted)

    def to_bytes(self) -> bytes:
        return save_pdf(self.pdf, **self.save_options)

    def snapshot(self) -> bytes:
        """Current content as plain (unencrypted) bytes for libraries other than pikepdf."""
        return save_pdf(self.pdf)

    def replace(self, data: bytes) -> None:
        self.pdf = open_pdf(data)

    def as_file(self, suffix: str = "") -> File:
        return File(f"{self.stem}{suffix}.pdf", PDF_MIME, self.to_bytes())
