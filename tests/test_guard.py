import dataclasses

import pytest

import app.main as main


@pytest.fixture
def with_settings(monkeypatch):
    def apply(**changes):
        monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, **changes))

    return apply


def test_token_required(client, pdf5, with_settings):
    with_settings(api_token="s3cret")
    files = {"file": ("a.pdf", pdf5)}
    assert client.post("/v1/info", files=files).status_code == 401
    assert client.post("/v1/info", files=files, headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.post("/v1/info", files=files, headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert client.post("/v1/info", files=files, headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.get("/healthz").status_code == 200


def test_upload_limit(client, with_settings):
    with_settings(max_upload_mb=1)
    resp = client.post("/v1/info", files={"file": ("big.pdf", b"0" * (2 * 1024 * 1024))})
    assert resp.status_code == 413
    assert resp.json()["error"] == "too_large"


def test_upload_limit_chunked(client, with_settings):
    with_settings(max_upload_mb=1)

    def chunks():
        boundary = b"--b\r\n"
        yield boundary + b'Content-Disposition: form-data; name="file"; filename="a.pdf"\r\n\r\n'
        for _ in range(3):
            yield b"0" * (1024 * 1024)
        yield b"\r\n--b--\r\n"

    resp = client.post("/v1/info", content=chunks(), headers={"Content-Type": "multipart/form-data; boundary=b"})
    assert resp.status_code == 413
    assert resp.json()["error"] == "too_large"
