import io

import pikepdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.main import app


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


def make_pdf(pages: int = 5, bookmarks: bool = False, image: bytes | None = None) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle("Sample")
    for i in range(1, pages + 1):
        c.drawString(72, 750, f"Page {i}")
        if bookmarks and i in (1, 3):
            c.bookmarkPage(f"ch{i}")
            c.addOutlineEntry(f"Chapter {i}", f"ch{i}", level=0)
        if image and i == 1:
            from reportlab.lib.utils import ImageReader

            c.drawImage(ImageReader(io.BytesIO(image)), 72, 400, 200, 200)
        c.showPage()
    c.save()
    return buf.getvalue()


def make_letterhead(*labels: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for label in labels:
        c.drawString(300, 800, f"Letterhead {label}")
        c.showPage()
    c.save()
    return buf.getvalue()


def make_form() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(72, 760, "Form")
    c.acroForm.textfield(name="Name", x=72, y=700, width=200, height=20)
    c.acroForm.checkbox(name="Agree", x=72, y=650, size=20)
    c.showPage()
    c.save()
    return buf.getvalue()


def make_png(w: int = 400, h: int = 300, mode: str = "RGB") -> bytes:
    img = Image.new(mode, (w, h), (200, 30, 30, 128) if mode == "RGBA" else (200, 30, 30))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def page_texts(data: bytes) -> list[str]:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return [(p.extract_text() or "") for p in pdf.pages]


def page_count(data: bytes, password: str = "") -> int:
    return len(pikepdf.open(io.BytesIO(data), password=password).pages)


@pytest.fixture
def pdf5() -> bytes:
    return make_pdf(5)
