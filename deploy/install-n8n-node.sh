#!/usr/bin/env bash
# Install (or update) the PDF Tools n8n node from its GitHub release into a running n8n, then restart n8n.
#
#   deploy/install-n8n-node.sh [version] [namespace]        e.g. deploy/install-n8n-node.sh 0.1.0 n8n
#
# The package has no runtime dependencies, so it is unpacked straight into ~/.n8n/nodes/node_modules
# (on the n8n PVC) instead of running `npm install`, which would also touch the other community nodes.
# It is also added to ~/.n8n/nodes/package.json so a later `npm install` there keeps it.
set -euo pipefail
VERSION="${1:-0.1.0}"
NS="${2:-n8n}"
PKG=n8n-nodes-innfactory-pdf-tools
URL="https://github.com/innFactory-AI/n8n-pdf-tools/releases/download/node-v${VERSION}/${PKG}-${VERSION}.tgz"
EXEC="${EXEC:-kubectl -n $NS exec -i deploy/n8n -c n8n --}"   # override for testing, e.g. EXEC="docker exec -i n8n"

$EXEC sh -eu -s "$PKG" "$URL" <<'REMOTE'
PKG="$1"; URL="$2"
mkdir -p ~/.n8n/nodes/node_modules && cd ~/.n8n/nodes
[ -f package.json ] || printf '{"name":"installed-nodes","private":true,"dependencies":{}}\n' > package.json
wget -qO /tmp/$PKG.tgz "$URL"
rm -rf "node_modules/$PKG.new" && mkdir -p "node_modules/$PKG.new"
tar xzf /tmp/$PKG.tgz -C "node_modules/$PKG.new" --strip-components=1
rm -rf "node_modules/$PKG" && mv "node_modules/$PKG.new" "node_modules/$PKG" && rm -f /tmp/$PKG.tgz
node -e '
  const fs = require("fs"), [pkg, url] = process.argv.slice(1);
  const p = JSON.parse(fs.readFileSync("package.json", "utf8"));
  (p.dependencies ||= {})[pkg] = url;
  fs.writeFileSync("package.json", JSON.stringify(p, null, 2) + "\n");
' "$PKG" "$URL"
echo "installed $(node -p "require('./node_modules/$PKG/package.json').version") into $(pwd)"
REMOTE

if [ -z "${NO_RESTART:-}" ]; then
  kubectl -n "$NS" rollout restart deploy/n8n
  kubectl -n "$NS" rollout status deploy/n8n --timeout=5m
fi
