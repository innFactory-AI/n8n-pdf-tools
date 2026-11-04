"""Regression tests for issues found in code review."""

import io
import json

import pikepdf
import pypdf
from reportlab.pdfgen import canvas

from tests.conftest import make_form, make_letterhead, make_pdf, page_texts
from tests.test_api import post, unzip


def test_metadata_keeps_existing_docinfo(client, pdf5):
    resp = post(client, "/v1/metadata", pdf5, {"author": "X"})
    meta = post(client, "/v1/info", resp.content).json()["metadata"]
    assert meta["Title"] == "Sample" and meta["Author"] == "X" and "Producer" in meta


def test_merge_and_split_keep_form_fields(client):
    merged = post(client, "/v1/merge", files=[("files", ("a.pdf", make_pdf(1))), ("files", ("f.pdf", make_form()))])
    assert {f["name"] for f in post(client, "/v1/forms/fields", merged.content).json()["fields"]} == {"Name", "Agree"}
    part = post(client, "/v1/split", merged.content, {"ranges": "2"})
    assert post(client, "/v1/forms/fields", part.content).json()["fields"]


def test_flatten_regenerates_when_need_appearances(client):
    # simulate another tool: value set, NeedAppearances=true, appearance left empty
    pdf = pikepdf.open(io.BytesIO(make_form()))
    for annot in pdf.pages[0].Annots:
        if annot.get("/T") == "Name":
            annot.V = pikepdf.String("Erika Müller")
    pdf.Root.AcroForm.NeedAppearances = True
    out = io.BytesIO()
    pdf.save(out)
    flat = post(client, "/v1/forms/flatten", out.getvalue())
    assert "Erika Müller" in page_texts(flat.content)[0]
    assert not pypdf.PdfReader(io.BytesIO(flat.content)).get_fields()


def test_fill_and_flatten_in_one_call(client):
    resp = post(client, "/v1/forms/fill", make_form(), {"values": json.dumps({"Name": "Jörg"}), "flatten": "true"})
    assert "Jörg" in page_texts(resp.content)[0]


def test_overlay_is_shared_not_copied(client):
    letterhead = make_letterhead("A")
    one = post(client, "/v1/overlay", make_pdf(1), files=[("overlay", ("lh.pdf", letterhead))]).content
    many = post(client, "/v1/overlay", make_pdf(50), files=[("overlay", ("lh.pdf", letterhead))]).content
    plain = make_pdf(50)
    assert len(many) - len(plain) < 5 * (len(one) - len(make_pdf(1)) + 2000)


def test_page_spec_cap(client, pdf5):
    resp = post(client, "/v1/select", pdf5, {"pages": "all," * 3000})
    assert resp.status_code == 422
    assert resp.json()["error"] == "invalid_pages"


def test_page_number_format_rejects_specs(client, pdf5):
    resp = post(client, "/v1/page-numbers", pdf5, {"format": "{page:>999999999}"})
    assert resp.status_code == 422
    assert resp.json()["error"] == "invalid_format"
    ok = post(client, "/v1/page-numbers", pdf5, {"format": "S. {page} {x}"})
    assert ok.status_code == 422


def test_render_megapixel_cap(client):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(14400, 14400))
    c.showPage()
    c.save()
    resp = post(client, "/v1/render", buf.getvalue(), {"dpi": "72"})
    assert resp.status_code == 413
    assert resp.json()["error"] == "too_large"


def test_extracted_image_names_are_safe(client):
    from tests.conftest import make_png

    pdf = pikepdf.open(io.BytesIO(make_pdf(1, image=make_png(100, 100))))
    xobjects = pdf.pages[0].Resources.XObject
    key = next(iter(xobjects.keys()))
    xobjects[pikepdf.Name("/x/../../etc/evil")] = xobjects[key]
    del xobjects[key]
    content = pdf.pages[0].Contents.read_bytes().replace(key.encode(), b"/x/../../etc/evil")
    pdf.pages[0].Contents = pdf.make_stream(content)
    out = io.BytesIO()
    pdf.save(out)
    files = unzip(post(client, "/v1/images", out.getvalue(), {"output": "zip"}))
    assert all("/" not in n and ".." not in n for n in files)


def test_decrypt_owner_only_without_password(client, pdf5):
    enc = post(client, "/v1/encrypt", pdf5, {"owner_password": "owner", "allow_modify": "false"}).content
    resp = post(client, "/v1/decrypt", enc)
    assert resp.status_code == 200
    assert not pikepdf.open(io.BytesIO(resp.content)).is_encrypted
