# n8n-pdf-tools: agent notes

Stateless FastAPI service for PDF manipulation, called by n8n over HTTP inside the cluster.
The user docs (API, n8n usage, configuration, deploy) are in `README.md`; keep them in sync with any API change.

## Layout

- `app/main.py`: HTTP layer only. Each endpoint maps form fields to **one pipeline op** and calls `_run`.
- `app/pipeline.py`: op models (pydantic, `extra="forbid"`) and dispatch. Every feature is an op, so
  it works both as its own endpoint and in `/v1/pipeline`. Ops that don't return a PDF go in `TERMINAL`.
- `app/ops/*`: the PDF work, as functions on `Doc` (`app/doc.py`). Mutate `doc.pdf` (pikepdf) in place.
  Write-time options (encryption, compression) go into `doc.save_options`.
- `app/pagespec.py`: the single page-selection syntax (1-based in, 0-based out).
- `app/responses.py`: `output=auto|zip|json`.

## Rules

- New feature = op model in `pipeline.py` + function in `app/ops/` + endpoint in `main.py` + test + README row.
- Raise `PdfToolError(message, code, status)` for caller errors; `code` values are API, don't rename them.
- pdfium (`pypdfium2`) is not thread-safe: always use `extract._pdfium_lock`.
- No AGPL dependencies (no PyMuPDF). No OCR (that goes to Mistral).
- Requests run in a thread pool limited by `MAX_CONCURRENT_JOBS`; keep endpoints async and do the PDF work in `work()`.
- Pin runtime deps in `requirements.lock` (`make lock`); `pyproject.toml` holds ranges and tool config.
- Conventional commits; `feat`/`fix` on `main` creates a release and image (`.github/workflows/ci.yaml`).

## Verify

`make test lint smoke`
