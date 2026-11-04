.PHONY: dev test lint fmt lock image smoke

dev:
	.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload

test:
	.venv/bin/pytest -q

lint:
	.venv/bin/ruff check . && .venv/bin/ruff format --check .

fmt:
	.venv/bin/ruff check --fix . && .venv/bin/ruff format .

# pin runtime deps as resolved inside the image's base
lock:
	docker run --rm -v $$PWD:/src:ro python:3.14-slim sh -c 'python -c "import tomllib;print(\"\n\".join(tomllib.load(open(\"/src/pyproject.toml\",\"rb\"))[\"project\"][\"dependencies\"]))" > /tmp/r.txt && pip -q install --root-user-action=ignore -r /tmp/r.txt >/dev/null && pip freeze' > requirements.lock.tmp
	(echo '# Pinned runtime dependencies for the image. Regenerate with `make lock` after changing pyproject.toml.'; cat requirements.lock.tmp) > requirements.lock && rm requirements.lock.tmp

image:
	docker build --build-arg VERSION=dev -t n8n-pdf-tools:dev .

smoke: image
	./scripts/smoke.sh n8n-pdf-tools:dev
