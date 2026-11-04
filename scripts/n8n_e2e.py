#!/usr/bin/env python3
"""End-to-end test of the n8n node against a real n8n and the service image.

Starts n8n-pdf-tools and n8n in docker, installs the packed node the same way as a manual
install (~/.n8n/nodes), runs a workflow with the n8n CLI and checks every node's output.

    scripts/n8n_e2e.py --image n8n-pdf-tools:dev --tarball n8n-node/n8n-nodes-*.tgz [--n8n n8nio/n8n:2.44.6]
"""

import argparse
import io
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

NODE = "n8n-nodes-innfactory-pdf-tools.pdfTools"
NET = "pdf-e2e-net"


def sh(*args: str, check: bool = True, capture: bool = False) -> str:
    result = subprocess.run(args, check=check, text=True, capture_output=capture)
    return result.stdout if capture else ""


def sample_pdfs(target: Path) -> None:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for i in range(1, 6):
        c.drawString(72, 750, f"Page {i}")
        c.showPage()
    c.save()
    (target / "sample.pdf").write_bytes(buf.getvalue())
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 760, "Form")
    c.acroForm.textfield(name="Name", x=72, y=700, width=200, height=20)
    c.acroForm.checkbox(name="Agree", x=72, y=650, size=20)
    c.showPage()
    c.save()
    (target / "form.pdf").write_bytes(buf.getvalue())
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(300, 800, "Letterhead")
    c.showPage()
    c.save()
    (target / "letterhead.pdf").write_bytes(buf.getvalue())
    from PIL import Image

    Image.new("RGB", (120, 60), (200, 30, 30)).save(target / "logo.png")


def workflow() -> dict:
    cred = {"pdfToolsApi": {"id": "pdfcred1", "name": "PDF Tools"}}
    nodes: list[dict] = []
    conns: dict = {}

    def node(name, typ, params, extra=None):
        n = {"id": name, "name": name, "type": typ, "typeVersion": 1, "position": [0, 0], "parameters": params}
        if typ == NODE:
            n["credentials"] = cred
        n.update(extra or {})
        nodes.append(n)
        return name

    def link(a, b, index=0):
        conns.setdefault(a, {"main": [[]]})["main"][0].append({"node": b, "type": "main", "index": index})

    def pdf(name, params, src, extra=None):
        node(name, NODE, params, extra)
        link(src, name)
        return name

    start = node("Start", "n8n-nodes-base.manualTrigger", {})
    read = {"operation": "read", "options": {}}
    rs = node("Read Sample", "n8n-nodes-base.readWriteFile", {**read, "fileSelector": "/e2e/data/sample.pdf"})
    rf = node("Read Form", "n8n-nodes-base.readWriteFile", {**read, "fileSelector": "/e2e/data/form.pdf"})
    link(start, rs)
    link(start, rf)
    pdf("Info", {"operation": "info"}, rs)
    split = pdf("Split", {"operation": "split", "splitMode": "every", "every": 2}, rs)
    merge = pdf("Merge", {"operation": "merge", "combineMode": "items"}, split)
    pdf("Merged Info", {"operation": "info"}, merge)
    wm = pdf(
        "Watermark", {"operation": "watermark", "text": "GEHEIM äöü", "options": {"rotation": 0, "pages": "1"}}, rs
    )
    pdf("Watermark Text", {"operation": "text"}, wm)
    pdf("Render", {"operation": "render", "options": {"pages": "1-2", "dpi": 50, "imageFormat": "jpg"}}, rs)
    pdf("Bad Select", {"operation": "select", "pages": "99"}, rs, {"onError": "continueRegularOutput"})
    pn = pdf("Page Numbers", {"operation": "pageNumbers", "format": "Seite {page} von {total}"}, rs)
    pdf("PN Text", {"operation": "text", "options": {"pages": "5"}}, pn)
    ops = [{"op": "delete", "pages": "1"}, {"op": "text", "pages": "1"}]
    pdf("Pipeline", {"operation": "pipeline", "ops": json.dumps(ops)}, rs)
    fields = {"field": [{"name": "Name", "value": "Jörg Groß"}, {"name": "Agree", "value": "true"}]}
    fill = pdf("Fill", {"operation": "fillForm", "formInput": "fields", "formFields": fields, "flatten": True}, rf)
    pdf("Fill Text", {"operation": "text"}, fill)
    enc = pdf("Encrypt", {"operation": "encrypt", "userPassword": "pw"}, rs)
    pdf("Enc Info", {"operation": "info", "options": {"password": "pw"}}, enc)
    dec = pdf("Decrypt", {"operation": "decrypt", "options": {"password": "pw"}}, enc)
    pdf("Dec Info", {"operation": "info"}, dec)
    rot = pdf("Rotate", {"operation": "rotate", "angle": 90, "pages": "1"}, rs)
    pdf("Rot Info", {"operation": "info"}, rot)
    blank = pdf("Insert Blank", {"operation": "insertBlank", "after": "0", "count": 1}, rs)
    meta = pdf(
        "Metadata", {"operation": "metadata", "metadata": {"title": "Angebot 42"}, "removeKeys": ["author"]}, blank
    )
    pdf("Meta Info", {"operation": "info"}, meta)
    pdf("Compress", {"operation": "compress", "options": {"linearize": True}}, rs)
    pdf("Form Fields", {"operation": "formFields"}, rf)
    pdf("Extract Images", {"operation": "images"}, rs)
    pdf(
        "Split One Item",
        {"operation": "split", "splitMode": "ranges", "ranges": "1,2-3", "options": {"splitIntoItems": False}},
        rs,
    )

    # several binaries in one item: sample (data) + logo (image) + letterhead (letterhead)
    def read_into(name, path, field):
        params = {"operation": "read", "fileSelector": path, "options": {"dataPropertyName": field}}
        return node(name, "n8n-nodes-base.readWriteFile", params)

    rl = read_into("Read Logo", "/e2e/data/logo.png", "image")
    rh = read_into("Read Letterhead", "/e2e/data/letterhead.pdf", "letterhead")
    link(start, rl)
    link(start, rh)
    combo = node("Combine", "n8n-nodes-base.merge",
                 {"mode": "combine", "combineBy": "combineByPosition", "numberInputs": 3, "options": {}},
                 {"typeVersion": 3.2})  # fmt: skip
    link(rs, combo, 0)
    link(rl, combo, 1)
    link(rh, combo, 2)
    st = pdf("Stamp", {"operation": "stampImage", "imageBinaryPropertyName": "image", "options": {"pages": "1"}}, combo)
    pdf("Stamp Images", {"operation": "images"}, st)
    ov = pdf("Overlay", {"operation": "overlay", "overlayBinaryPropertyName": "letterhead"}, combo)
    pdf("Overlay Text", {"operation": "text", "options": {"pages": "2"}}, ov)
    mf = pdf(
        "Merge Fields",
        {"operation": "merge", "combineMode": "fields", "combineBinaryPropertyNames": "data, letterhead"},
        combo,
    )
    pdf("Merge Fields Info", {"operation": "info"}, mf)
    images = {"operation": "imagesToPdf", "combineMode": "fields", "combineBinaryPropertyNames": "image"}
    ip = pdf("Images To PDF", {**images, "options": {"pageSize": "a4"}}, combo)
    pdf("Images PDF Info", {"operation": "info"}, ip)
    assets = {"asset": [{"name": "lh.pdf", "binaryPropertyName": "letterhead"}]}
    ops = [{"op": "overlay", "file": "lh.pdf"}, {"op": "text", "pages": "3"}]
    pdf("Pipeline Assets", {"operation": "pipeline", "ops": json.dumps(ops), "assets": assets}, combo)
    settings = {"executionOrder": "v1"}
    return {
        "id": "e2eWf1",
        "name": "pdf e2e",
        "active": False,
        "nodes": nodes,
        "connections": conns,
        "settings": settings,
    }


EXPECT = {
    "Info": lambda items: items[0]["json"]["page_count"] == 5,
    "Split": lambda items: (
        [i["json"]["fileName"] for i in items] == ["sample_p1-2.pdf", "sample_p3-4.pdf", "sample_p5.pdf"]
    ),
    "Merge": lambda items: len(items) == 1 and items[0]["binary"]["data"]["mimeType"] == "application/pdf",
    "Merged Info": lambda items: items[0]["json"]["page_count"] == 5,
    "Watermark Text": lambda items: (
        "GEHEIM äöü" in items[0]["json"]["pages"][0]["text"] and "GEHEIM" not in items[0]["json"]["pages"][1]["text"]
    ),
    "Render": lambda items: [i["binary"]["data"]["mimeType"] for i in items] == ["image/jpeg"] * 2,
    "Bad Select": lambda items: "out of range" in items[0]["json"]["error"],
    "PN Text": lambda items: "Seite 5 von 5" in items[0]["json"]["text"],
    "Pipeline": lambda items: items[0]["json"]["text"] == "Page 2",
    "Fill Text": lambda items: "Jörg Groß" in items[0]["json"]["text"],
    "Enc Info": lambda items: items[0]["json"]["encrypted"] is True,
    "Dec Info": lambda items: items[0]["json"]["encrypted"] is False,
    "Rot Info": lambda items: [p["rotation"] for p in items[0]["json"]["pages"][:2]] == [90, 0],
    "Meta Info": lambda items: (
        items[0]["json"]["page_count"] == 6
        and items[0]["json"]["metadata"]["Title"] == "Angebot 42"
        and "Author" not in items[0]["json"]["metadata"]
    ),
    "Compress": lambda items: items[0]["binary"]["data"]["mimeType"] == "application/pdf",
    "Form Fields": lambda items: {f["name"] for f in items[0]["json"]["fields"]} == {"Name", "Agree"},
    "Extract Images": lambda items: items[0]["json"]["count"] == 0,
    "Split One Item": lambda items: len(items) == 1 and set(items[0]["binary"]) == {"data_0", "data_1"},
    "Stamp Images": lambda items: len(items) == 1 and items[0]["binary"]["data"]["mimeType"].startswith("image/"),
    "Overlay Text": lambda items: "Letterhead" in items[0]["json"]["text"] and "Page 2" in items[0]["json"]["text"],
    "Merge Fields Info": lambda items: items[0]["json"]["page_count"] == 6,
    "Images PDF Info": lambda items: (
        items[0]["json"]["page_count"] == 1 and items[0]["json"]["pages"][0]["width_mm"] == 210
    ),
    "Pipeline Assets": lambda items: "Letterhead" in items[0]["json"]["text"],
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--tarball", required=True)
    ap.add_argument("--n8n", default="n8nio/n8n:2.44.6")
    args = ap.parse_args()

    work = Path(tempfile.mkdtemp(prefix="pdf-e2e-"))
    (work / "data").mkdir()
    sample_pdfs(work / "data")
    shutil.copy(args.tarball, work / "node.tgz")
    creds = [{"id": "pdfcred1", "name": "PDF Tools", "type": "pdfToolsApi",
              "data": {"baseUrl": "http://n8n-pdf-tools:8080", "apiToken": ""}}]  # fmt: skip
    (work / "creds.json").write_text(json.dumps(creds))
    (work / "wf.json").write_text(json.dumps([workflow()]))
    sh("chmod", "-R", "a+rwX", str(work))

    containers = ["n8n-pdf-tools", "n8n-e2e"]
    sh("docker", "rm", "-f", *containers, check=False, capture=True)
    sh("docker", "network", "create", NET, check=False, capture=True)
    try:
        sh("docker", "run", "-d", "--name", "n8n-pdf-tools", "--network", NET, "--read-only", "--tmpfs", "/tmp",
           args.image, capture=True)  # fmt: skip
        sh("docker", "run", "-d", "--name", "n8n-e2e", "--network", NET, "-v", f"{work}:/e2e",
           "-e", "N8N_ENCRYPTION_KEY=e2e", "-e", "N8N_RESTRICT_FILE_ACCESS_TO=/e2e",
           "--entrypoint", "sh", args.n8n, "-c", "sleep infinity", capture=True)  # fmt: skip
        script = (
            "set -e; mkdir -p ~/.n8n/nodes && cd ~/.n8n/nodes"
            " && npm i --no-audit --no-fund --legacy-peer-deps --ignore-scripts /e2e/node.tgz >/dev/null"
            " && n8n import:credentials --input=/e2e/creds.json >>/e2e/n8n.log 2>&1"
            " && n8n import:workflow --input=/e2e/wf.json >>/e2e/n8n.log 2>&1"
            " && n8n execute --id e2eWf1 --rawOutput > /e2e/out.json 2>>/e2e/n8n.log"
        )
        for _ in range(30):
            ok = subprocess.run(["docker", "run", "--rm", "--network", NET, "curlimages/curl", "-fsS",
                                 "http://n8n-pdf-tools:8080/healthz"], capture_output=True)  # fmt: skip
            if ok.returncode == 0:
                break
            time.sleep(1)
        if subprocess.run(["docker", "exec", "n8n-e2e", "sh", "-c", script]).returncode != 0:
            log = work / "n8n.log"
            print(log.read_text()[-4000:] if log.exists() else "no n8n log")
            return 1
        raw = (work / "out.json").read_text()
        run = json.loads(raw[raw.index("{") :])
        result = run.get("data", run)["resultData"]
        failed = []
        for name, check in EXPECT.items():
            runs = result["runData"].get(name)
            try:
                items = runs[0]["data"]["main"][0]
                ok = check(items)
            except Exception as exc:  # noqa: BLE001
                ok, items = False, f"{type(exc).__name__}: {exc} / {runs and runs[0].get('error')}"
            print(f"{'ok  ' if ok else 'FAIL'} {name}")
            if not ok:
                failed.append(name)
                print(f"     {str(items)[:400]}")
        return 1 if failed else 0
    finally:
        sh("docker", "rm", "-f", *containers, check=False, capture=True)
        sh("docker", "network", "rm", NET, check=False, capture=True)


if __name__ == "__main__":
    sys.exit(main())
