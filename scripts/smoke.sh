#!/usr/bin/env bash
# Start the image read-only (as in Kubernetes) and run a few real requests against it.
set -euo pipefail
IMAGE="${1:?usage: smoke.sh <image>}"
NAME="pdf-tools-smoke-$$"
docker run -d --rm --name "$NAME" --read-only --tmpfs /tmp -p 18080:8080 "$IMAGE" >/dev/null
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT

for _ in $(seq 1 30); do
  curl -fsS http://localhost:18080/healthz >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS http://localhost:18080/version; echo

WORK="$(mktemp -d)"
# two one-page PDFs from images, merged, then split back; text and render on the way
python3 - "$WORK" <<'PY'
import struct, sys, zlib
def png(path, rgb):
    raw = b"".join(b"\x00" + bytes(rgb) * 64 for _ in range(64))
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 64, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
png(f"{sys.argv[1]}/a.png", (255, 0, 0)); png(f"{sys.argv[1]}/b.png", (0, 0, 255))
PY
curl -fsS -F files=@"$WORK/a.png" -F files=@"$WORK/b.png" -F page_size=a4 \
  http://localhost:18080/v1/images-to-pdf -o "$WORK/doc.pdf"
curl -fsS -F file=@"$WORK/doc.pdf" -F text="SMOKE TEST" -F rotation=0 http://localhost:18080/v1/watermark -o "$WORK/wm.pdf"
curl -fsS -F file=@"$WORK/wm.pdf" -F pages=1 http://localhost:18080/v1/text | grep -q "SMOKE TEST"
curl -fsS -F file=@"$WORK/wm.pdf" -F every=1 http://localhost:18080/v1/split -o "$WORK/parts.zip"
python3 -c "import sys,zipfile; n=len(zipfile.ZipFile(sys.argv[1]).namelist()); assert n == 2, n" "$WORK/parts.zip"
curl -fsS -F file=@"$WORK/wm.pdf" -F pages=1 -F dpi=72 http://localhost:18080/v1/render -o "$WORK/p1.png"
python3 -c "import sys; assert open(sys.argv[1],'rb').read(4) == b'\x89PNG'" "$WORK/p1.png"
echo "smoke ok"
