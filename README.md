# n8n-pdf-tools

A small, stateless HTTP API for PDF work that is painful in n8n: split, merge, reorder,
rotate, watermark, page numbers, letterhead, forms, text, page images, compression,
passwords. It runs next to n8n in the cluster (no ingress) and is called with the
**HTTP Request** node.

No OCR: a PDF without a text layer returns `has_text: false` from `/v1/text`. Send it to Mistral OCR.

Built on [pikepdf](https://github.com/pikepdf/pikepdf) (qpdf), [pypdf](https://github.com/py-pdf/pypdf),
[pdfplumber](https://github.com/jsvine/pdfplumber), [pypdfium2](https://github.com/pypdfium2-team/pypdfium2),
[reportlab](https://www.reportlab.com/) and [img2pdf](https://gitlab.mister-muffin.de/josch/img2pdf).
These libraries use MPL, BSD, MIT or Apache licenses. PyMuPDF (AGPL) is not used on purpose.

## Calling it from n8n

The easiest way is the **PDF Tools** community node in [`n8n-node/`](n8n-node/README.md), which has
every operation as a form and handles binaries, multiple output files and errors. The plain HTTP
Request node also works:

The service runs at `http://n8n-pdf-tools.n8n.svc.cluster.local:8080`. Interactive API docs (Swagger) are at `/docs`.

HTTP Request node settings:

| Setting | Value |
|---|---|
| Method | `POST` |
| URL | `http://n8n-pdf-tools.n8n.svc.cluster.local:8080/v1/split` |
| Body Content Type | `Form-Data` |
| Body parameter 1 | type **n8n Binary File**, name `file`, input data field `data` |
| Body parameter 2… | type **Form Data**, e.g. `ranges` = `1-2,3-` |
| Options → Response | Response Format **File** for PDFs, ZIPs and images, **JSON** for `info`/`text`/`forms/fields` |

For several files (merge, images-to-pdf), add one **n8n Binary File** parameter per file,
all named `files`.

**Multiple output files** (split, render, images) come back:
- as a **ZIP** by default. Use the n8n **Compression** node (Decompress) to turn it into one binary per file.
- as JSON with base64 when you set `output=json`: `{"count": 2, "files": [{"name", "mime_type", "size", "data"}]}`.
  Then use **Split Out** on `files` and **Convert to File** (base64 → binary) on `data`.
- `output=auto` (the default) returns a single file directly and only zips when there are several.

**Already have base64 in JSON?** Use `POST /v1/pipeline/json` with a JSON body (see below).

## Page selection

Pages are 1-based: `1-3,5,7-`, `last`, `5-last`, `odd`, `even`, `all`. A descending range
reverses the order (`last-1` reverses the document). `,` and `;` both separate tokens.

## Endpoints

All are `POST`, multipart/form-data, with the PDF in `file`. Encrypted input needs `password`.

| Endpoint | Parameters (form fields) | Returns |
|---|---|---|
| `/v1/info` | | JSON: page count, page sizes (pt/mm, orientation), metadata, bookmarks, attachments, form fields |
| `/v1/text` | `pages`, `layout`, `tables` | JSON: text per page, full text, `has_text` |
| `/v1/render` | `pages`, `dpi` (≤300), `format` png/jpg/webp, `quality`, `output` | image or ZIP |
| `/v1/images` | `pages`, `min_size` | embedded images (original encoding) as file or ZIP |
| `/v1/split` | exactly one of `ranges` (one file per token), `every` (N pages), `by=bookmarks`; `output` | PDF or ZIP |
| `/v1/merge` | `files` (repeated, in order) | PDF |
| `/v1/select` | `pages` (keep, reorder, duplicate: `3,1,2`) | PDF |
| `/v1/delete` | `pages` | PDF |
| `/v1/rotate` | `angle` (90/180/270/-90), `pages` | PDF |
| `/v1/insert-blank` | `after` (`0` = before page 1, `2,4`), `count` | PDF |
| `/v1/watermark` | `text` (newlines OK), `pages`, `font_size`, `color` (#hex), `opacity`, `rotation`, `position`, `margin_mm`, `layer` over/under | PDF |
| `/v1/stamp` | `image` (PNG/JPEG file), `pages`, `position`, `width_mm`, `opacity`, `margin_mm`, `layer` | PDF |
| `/v1/page-numbers` | `format` (`{page}`, `{total}`), `pages`, `start`, `position`, `font_size`, `color`, `margin_mm` | PDF |
| `/v1/overlay` | `overlay` (PDF file), `pages`, `layer` (under = letterhead) | PDF. Overlay page k goes on target page k; the last overlay page repeats (1 page = the same everywhere, 2 pages = first page + follow-up pages). |
| `/v1/forms/fields` | | JSON: name, type, value, states/options, required |
| `/v1/forms/fill` | `values` (JSON object), `flatten`, `ignore_unknown` | PDF. Checkboxes accept `true`/`false` or a state name. |
| `/v1/forms/flatten` | | PDF with fields and annotations burned in |
| `/v1/metadata` | `title`, `author`, `subject`, `keywords`, `creator`, `producer`, `remove` (keys to delete, e.g. `subject,keywords`), `clear` | PDF. Keys you don't send stay unchanged. |
| `/v1/compress` | `image_quality` (10–95, lossy JPEG), `max_image_px`, `linearize` | PDF. Lossless without parameters. |
| `/v1/encrypt` | `user_password`, `owner_password`, `allow_print`, `allow_copy`, `allow_modify`, `allow_annotate`, `allow_forms` | PDF (AES-256) |
| `/v1/decrypt` | `password` (leave out for owner-password-only PDFs) | PDF |
| `/v1/repair` | | PDF rewritten by qpdf (recovers many damaged files) |
| `/v1/images-to-pdf` | `files` (images, repeated), `page_size` (a4, letter, a4-landscape…), `margin_mm` | PDF |
| `/v1/pipeline` | `ops` (JSON array), `assets` (extra files, referenced by filename), `output` | depends on the last op |
| `/v1/pipeline/json` | JSON body (see below) | JSON by default |

Positions: `top-left`, `top-center`, `top-right`, `center-left`, `center`, `center-right`,
`bottom-left`, `bottom-center`, `bottom-right`. Stamps stay upright on rotated pages.

Errors are JSON with a stable `error` code, e.g.
`{"error": "invalid_pages", "message": "page 9 out of range (document has 5 pages)"}`.
Status 422 means bad input, 401 a missing or wrong token, 413 too large.

## Pipeline: several steps in one call

Operations run in order on the same document. `split`, `render`, `text`, `info`, `images`
and `form_fields` produce non-PDF output and are only allowed as the **last** step.
Operation names and parameters are the same as the endpoints (snake_case):
`select`, `delete`, `rotate`, `insert_blank`, `merge` (`files`: asset names), `watermark`,
`stamp_image` (`file`: asset name), `page_numbers`, `overlay` (`file`: asset name),
`metadata` (`null` deletes a key), `fill_form`, `flatten`, `compress`, `encrypt`, `decrypt`, plus the terminal ones above.
Merge and split keep form fields working.

Multipart (`/v1/pipeline`): `file` = the PDF, `assets` = extra files (n8n Binary File, file
name = the name used in `ops`), `ops` =

```json
[
  {"op": "delete", "pages": "1"},
  {"op": "overlay", "file": "briefpapier.pdf", "layer": "under"},
  {"op": "page_numbers", "format": "Seite {page} von {total}", "position": "bottom-right"},
  {"op": "metadata", "title": "Angebot 2026-117", "author": "innFactory"},
  {"op": "compress"}
]
```

JSON (`/v1/pipeline/json`), for example from an n8n Code node or when the PDF is already base64:

```json
{
  "file": "<base64>",
  "filename": "rechnung.pdf",
  "assets": {"logo.png": "<base64>"},
  "ops": [{"op": "stamp_image", "file": "logo.png", "position": "top-right"}, {"op": "split", "every": 1}],
  "output": "json"
}
```

`output` defaults to `json` here (base64 files); `auto`/`zip` return binary like the other endpoints.

## Configuration

| Env | Default | |
|---|---|---|
| `PORT` | `8080` | |
| `WORKERS` | `2` | uvicorn worker processes |
| `MAX_CONCURRENT_JOBS` | `4` | PDF jobs per worker in parallel; further requests wait |
| `MAX_UPLOAD_MB` | `100` | per request (also enforced for chunked uploads) |
| `MAX_PAGES` | `5000` | per input document |
| `MAX_RENDER_DPI` / `MAX_RENDER_PAGES` | `300` / `200` | |
| `MAX_RENDER_MEGAPIXELS` | `40` | per rendered page (guards against huge page sizes) |
| `API_TOKEN` | – | if set, every `/v1` call needs `Authorization: Bearer <token>` or `X-API-Key: <token>` |
| `FONT_PATH` | DejaVu Sans | font for watermarks and page numbers (Unicode); falls back to Helvetica |

Health: `GET /healthz`, `GET /readyz`, `GET /version` (open), `GET /v1/ping` (behind the token, for credential tests).

## Deploy (manual)

Into the namespace where n8n runs (`n8n`), so n8n reaches it as `http://n8n-pdf-tools:8080`:

```sh
# 1. service: Deployment + ClusterIP Service + NetworkPolicy (image pinned by tag + digest)
kubectl -n n8n apply -f deploy/k8s.yaml
kubectl -n n8n rollout status deploy/n8n-pdf-tools
kubectl -n n8n exec deploy/n8n -c n8n -- wget -qO- http://n8n-pdf-tools:8080/version

# 2. n8n node from its GitHub release (restarts n8n)
deploy/install-n8n-node.sh 0.1.0
```

In n8n, add the **PDF Tools** node. *Authentication: None (In-Cluster)* is the default and needs
no credential. For a new service version, update the image tag + digest in `deploy/k8s.yaml`
(the digest is in the release's CI summary) and apply it again.

The pod runs non-root with a read-only root filesystem. All work happens in memory and in
`/tmp` (emptyDir); nothing is stored. There is no ingress, so the service is not reachable from outside the cluster.

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.lock pytest httpx ruff
make test lint      # tests + ruff
make dev            # http://localhost:8080/docs
make smoke          # build the image and run real requests against it
make lock           # re-pin requirements.lock after changing pyproject.toml
```

Releases are created from conventional commits on `main` (semantic-release). CI pushes
`ghcr.io/innfactory-ai/n8n-pdf-tools:<version>`, and also pushes to Google Artifact Registry once the `GCP_*` repo vars are set.
