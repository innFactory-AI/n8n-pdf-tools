import base64
import io
import json
import zipfile

import pikepdf
import pypdf
from PIL import Image

from tests.conftest import make_form, make_letterhead, make_pdf, make_png, page_count, page_texts


def post(client, path, pdf=None, data=None, files=None, name="sample.pdf"):
    upload = list(files or [])
    if pdf is not None:
        upload.insert(0, ("file", (name, pdf, "application/pdf")))
    return client.post(path, data=data or {}, files=upload)


def unzip(resp) -> dict[str, bytes]:
    assert resp.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        return {n: zf.read(n) for n in zf.namelist()}


# ------------------------------------------------------------------ meta


def test_health_and_version(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/version").json()["name"] == "n8n-pdf-tools"


def test_info(client, pdf5):
    resp = post(client, "/v1/info", pdf5)
    assert resp.status_code == 200
    body = resp.json()
    assert body["page_count"] == 5
    assert body["metadata"]["Title"] == "Sample"
    assert body["pages"][0]["width_mm"] == 210.0
    assert body["pages"][0]["orientation"] == "portrait"
    assert body["encrypted"] is False


def test_invalid_pdf(client):
    resp = post(client, "/v1/info", b"not a pdf")
    assert resp.status_code == 422
    assert resp.json()["error"] == "invalid_pdf"


# ------------------------------------------------------------------ pages


def test_split_ranges_zip(client, pdf5):
    resp = post(client, "/v1/split", pdf5, {"ranges": "1-2,3,4-"})
    files = unzip(resp)
    assert list(files) == ["sample_p1-2.pdf", "sample_p3.pdf", "sample_p4-5.pdf"]
    assert [page_count(f) for f in files.values()] == [2, 1, 2]
    assert resp.headers["x-file-count"] == "3"


def test_split_every_json(client, pdf5):
    resp = post(client, "/v1/split", pdf5, {"every": "2", "output": "json"})
    body = resp.json()
    assert body["count"] == 3
    assert page_texts(base64.b64decode(body["files"][2]["data"])) == ["Page 5"]


def test_split_single_part_returns_pdf(client, pdf5):
    resp = post(client, "/v1/split", pdf5, {"ranges": "2-3"})
    assert resp.headers["content-type"] == "application/pdf"
    assert page_texts(resp.content) == ["Page 2", "Page 3"]


def test_split_bookmarks(client):
    resp = post(client, "/v1/split", make_pdf(5, bookmarks=True), {"by": "bookmarks"})
    files = unzip(resp)
    assert [page_count(f) for f in files.values()] == [2, 3]


def test_split_requires_one_mode(client, pdf5):
    resp = post(client, "/v1/split", pdf5, {"ranges": "1", "every": "2"})
    assert resp.status_code == 422
    assert resp.json()["error"] == "invalid_split"


def test_merge(client):
    a, b = make_pdf(2), make_pdf(3)
    resp = post(client, "/v1/merge", files=[("files", ("a.pdf", a)), ("files", ("b.pdf", b))])
    assert resp.status_code == 200
    assert page_texts(resp.content) == ["Page 1", "Page 2", "Page 1", "Page 2", "Page 3"]


def test_select_reorder(client, pdf5):
    resp = post(client, "/v1/select", pdf5, {"pages": "3,1,last"})
    assert page_texts(resp.content) == ["Page 3", "Page 1", "Page 5"]


def test_delete(client, pdf5):
    resp = post(client, "/v1/delete", pdf5, {"pages": "2-4"})
    assert page_texts(resp.content) == ["Page 1", "Page 5"]


def test_delete_all_fails(client, pdf5):
    assert post(client, "/v1/delete", pdf5, {"pages": "all"}).status_code == 422


def test_page_out_of_range(client, pdf5):
    resp = post(client, "/v1/select", pdf5, {"pages": "9"})
    assert resp.status_code == 422
    assert "out of range" in resp.json()["message"]


def test_rotate(client, pdf5):
    resp = post(client, "/v1/rotate", pdf5, {"angle": "90", "pages": "1"})
    pdf = pikepdf.open(io.BytesIO(resp.content))
    assert int(pdf.pages[0].Rotate) == 90
    assert "/Rotate" not in pdf.pages[1] or int(pdf.pages[1].Rotate) == 0


def test_insert_blank(client, pdf5):
    resp = post(client, "/v1/insert-blank", pdf5, {"after": "0,2"})
    assert resp.status_code == 200, resp.text
    assert page_texts(resp.content) == ["", "Page 1", "Page 2", "", "Page 3", "Page 4", "Page 5"]


# ------------------------------------------------------------------ content


def test_watermark(client, pdf5):
    resp = post(client, "/v1/watermark", pdf5, {"text": "VERTRAULICH äöü", "pages": "1", "rotation": "0"})
    texts = page_texts(resp.content)
    assert "VERTRAULICH" in texts[0] and "äöü" in texts[0]
    assert "VERTRAULICH" not in texts[1]


def test_watermark_on_rotated_page(client, pdf5):
    rotated = post(client, "/v1/rotate", pdf5, {"angle": "90"}).content
    resp = post(client, "/v1/watermark", rotated, {"text": "DRAFT", "rotation": "0"})
    assert resp.status_code == 200
    assert "DRAFT" in page_texts(resp.content)[0] or "TFARD" in page_texts(resp.content)[0]


def test_page_numbers(client, pdf5):
    resp = post(client, "/v1/page-numbers", pdf5, {"format": "Seite {page} von {total}", "pages": "2-"})
    texts = page_texts(resp.content)
    assert "Seite" not in texts[0]
    assert "Seite 1 von 4" in texts[1]
    assert "Seite 4 von 4" in texts[4]


def test_stamp_image(client, pdf5):
    resp = post(client, "/v1/stamp", pdf5, {"pages": "1"}, files=[("image", ("logo.png", make_png(mode="RGBA")))])
    assert resp.status_code == 200
    pdf = pikepdf.open(io.BytesIO(resp.content))
    assert len(pdf.pages[0].get_images()) == 1
    assert len(pdf.pages[1].get_images()) == 0


def test_overlay_letterhead(client, pdf5):
    letterhead = make_letterhead("First", "Follow")  # page 1 = first page, page 2 = follow-up pages
    resp = post(client, "/v1/overlay", pdf5, {"layer": "under"}, files=[("overlay", ("lh.pdf", letterhead))])
    texts = page_texts(resp.content)
    assert "Letterhead First" in texts[0] and "Page 1" in texts[0]
    assert all("Letterhead Follow" in t for t in texts[1:])


# ------------------------------------------------------------------ forms


def test_form_fields_fill_flatten(client):
    form = make_form()
    fields = post(client, "/v1/forms/fields", form).json()["fields"]
    by_name = {f["name"]: f for f in fields}
    assert by_name["Name"]["type"] == "text"
    assert by_name["Agree"]["type"] == "checkbox"

    resp = post(client, "/v1/forms/fill", form, {"values": json.dumps({"Name": "Max Müller", "Agree": True})})
    assert resp.status_code == 200, resp.text
    filled = pypdf.PdfReader(io.BytesIO(resp.content)).get_fields()
    assert filled["Name"]["/V"] == "Max Müller"
    assert filled["Agree"]["/V"] != "/Off"

    flat = post(client, "/v1/forms/flatten", resp.content)
    assert not pypdf.PdfReader(io.BytesIO(flat.content)).get_fields()
    assert "Max Müller" in page_texts(flat.content)[0]


def test_form_fill_unknown_field(client):
    resp = post(client, "/v1/forms/fill", make_form(), {"values": json.dumps({"Nope": "x"})})
    assert resp.status_code == 422
    assert resp.json()["error"] == "unknown_fields"


# ------------------------------------------------------------------ read


def test_text_pages(client, pdf5):
    body = post(client, "/v1/text", pdf5, {"pages": "2,4"}).json()
    assert [p["page"] for p in body["pages"]] == [2, 4]
    assert body["text"] == "Page 2\n\nPage 4"
    assert body["has_text"] is True


def test_render_single_png(client, pdf5):
    resp = post(client, "/v1/render", pdf5, {"pages": "1", "dpi": "72"})
    assert resp.headers["content-type"] == "image/png"
    img = Image.open(io.BytesIO(resp.content))
    assert abs(img.size[0] - 595) <= 1 and abs(img.size[1] - 842) <= 1


def test_render_multi_jpg_zip(client, pdf5):
    files = unzip(post(client, "/v1/render", pdf5, {"pages": "1-2", "format": "jpg", "dpi": "50"}))
    assert list(files) == ["sample_p1.jpg", "sample_p2.jpg"]


def test_render_dpi_limit(client, pdf5):
    assert post(client, "/v1/render", pdf5, {"dpi": "5000"}).status_code == 422


def test_extract_images(client):
    pdf = make_pdf(2, image=make_png(120, 80))
    resp = post(client, "/v1/images", pdf)
    assert resp.headers["content-type"].startswith("image/")
    assert Image.open(io.BytesIO(resp.content)).size == (120, 80)


# ------------------------------------------------------------------ document


def test_metadata(client, pdf5):
    resp = post(client, "/v1/metadata", pdf5, {"title": "Rechnung 42", "author": "innFactory", "remove": "subject"})
    info = post(client, "/v1/info", resp.content).json()["metadata"]
    assert info["Title"] == "Rechnung 42"
    assert info["Author"] == "innFactory"
    assert "Subject" not in info
    assert info["Creator"]  # untouched keys survive


def test_metadata_unknown_remove_key(client, pdf5):
    resp = post(client, "/v1/metadata", pdf5, {"remove": "colour"})
    assert resp.status_code == 422


def test_encrypt_decrypt(client, pdf5):
    enc = post(client, "/v1/encrypt", pdf5, {"user_password": "geheim", "allow_copy": "false"})
    assert pikepdf.open(io.BytesIO(enc.content), password="geheim").is_encrypted
    locked = post(client, "/v1/info", enc.content)
    assert locked.status_code == 422 and locked.json()["error"] == "encrypted"
    assert post(client, "/v1/info", enc.content, {"password": "falsch"}).json()["error"] == "wrong_password"
    dec = post(client, "/v1/decrypt", enc.content, {"password": "geheim"})
    assert not pikepdf.open(io.BytesIO(dec.content)).is_encrypted


def test_compress_images(client):
    noisy = Image.effect_noise((1500, 1500), 60).convert("RGB")
    buf = io.BytesIO()
    noisy.save(buf, "PNG")
    pdf = make_pdf(1, image=buf.getvalue())
    resp = post(client, "/v1/compress", pdf, {"image_quality": "40", "max_image_px": "500"})
    assert resp.status_code == 200
    assert len(resp.content) < len(pdf) / 2


def test_images_to_pdf(client):
    files = [("files", ("a.png", make_png())), ("files", ("b.png", make_png(300, 400, "RGBA")))]
    resp = client.post("/v1/images-to-pdf", data={"page_size": "a4"}, files=files)
    assert resp.status_code == 200, resp.text
    assert page_count(resp.content) == 2
    assert resp.headers["content-disposition"].startswith('attachment; filename="a.pdf"')


# ------------------------------------------------------------------ pipeline


def test_pipeline_multipart(client, pdf5):
    ops = [
        {"op": "delete", "pages": "1"},
        {"op": "page_numbers", "format": "{page}"},
        {"op": "merge", "files": ["extra.pdf"]},
        {"op": "split", "every": 3},
    ]
    resp = post(client, "/v1/pipeline", pdf5, {"ops": json.dumps(ops)}, files=[("assets", ("extra.pdf", make_pdf(2)))])
    files = unzip(resp)
    assert [page_count(f) for f in files.values()] == [3, 3]


def test_pipeline_json(client, pdf5):
    body = {
        "file": base64.b64encode(pdf5).decode(),
        "filename": "rechnung.pdf",
        "ops": [{"op": "select", "pages": "1"}, {"op": "text"}],
    }
    resp = client.post("/v1/pipeline/json", json=body)
    assert resp.json()["text"] == "Page 1"


def test_pipeline_json_files(client, pdf5):
    body = {"file": base64.b64encode(pdf5).decode(), "ops": [{"op": "select", "pages": "2"}]}
    out = client.post("/v1/pipeline/json", json=body).json()
    assert out["files"][0]["name"] == "document.pdf"
    assert page_texts(base64.b64decode(out["files"][0]["data"])) == ["Page 2"]


def test_pipeline_terminal_must_be_last(client, pdf5):
    ops = [{"op": "text"}, {"op": "delete", "pages": "1"}]
    resp = post(client, "/v1/pipeline", pdf5, {"ops": json.dumps(ops)})
    assert resp.status_code == 422
    assert resp.json()["error"] == "invalid_operations"


def test_pipeline_unknown_op(client, pdf5):
    resp = post(client, "/v1/pipeline", pdf5, {"ops": json.dumps([{"op": "explode"}])})
    assert resp.status_code == 422


def test_missing_file(client):
    resp = client.post("/v1/info", data={})
    assert resp.status_code == 422
    assert resp.json()["error"] == "invalid_request"
