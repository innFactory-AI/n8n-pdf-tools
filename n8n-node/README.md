# n8n-nodes-innfactory-pdf-tools

n8n community node for [n8n-pdf-tools](../README.md), a stateless PDF service that runs next to
n8n. It gives you one **PDF Tools** node with these operations:

| Group | Operations |
|---|---|
| Pages | Split (ranges, every N pages, bookmarks), Merge, Select / Reorder Pages, Delete Pages, Rotate Pages, Insert Blank Pages |
| Content | Add Watermark, Add Page Numbers, Stamp Image (logo, signature), Overlay / Letterhead |
| Forms | Get Form Fields, Fill Form (optionally flatten), Flatten Form |
| Read | Get Info, Extract Text (optionally tables), Render Pages (PNG/JPEG/WebP), Extract Images |
| Document | Set Metadata, Compress, Encrypt, Decrypt, Repair, Images to PDF |
| Advanced | Run Pipeline: several operations in one call (JSON, see the service README) |

No OCR. A scan without a text layer returns `has_text: false` from Extract Text; send it to Mistral OCR.

## Behaviour

- The input is a binary field (default `data`). A PDF result replaces that field (or the field set in
  *Options → Put Output File in Field*); the item's JSON and its other binaries stay.
- JSON results (info, text, form fields) become the item's JSON; the input binary passes through.
- Split, Render and Extract Images output **one item per file** (`fileName`, `index`, `count`).
  Set *Split Into Items* off to get all files in one item as `data_0`, `data_1`, ….
- Merge and Images to PDF combine **all input items** (one output item) or several binary fields of
  each item (*Combine → Fields of Each Item*).
- Stamp Image, Overlay / Letterhead and pipeline assets read their extra file from another binary
  field of the same item. Use a Merge node (*Combine by Position*) to bring the files together first.
- Pages are 1-based: `1-3,5,7-`, `last`, `odd`, `even`, `all`; `last-1` reverses.
- Errors come with the service's message (e.g. `page 99 out of range (document has 5 pages)`).
  *On Error → Continue* puts it into `error`.

## Credentials

**PDF Tools API**
- **Base URL**: `http://n8n-pdf-tools:8080`, which is the default when the service runs in the same
  namespace as n8n. From another namespace use `http://n8n-pdf-tools.<namespace>.svc.cluster.local:8080`.
- **API Token**: only needed if the service has `API_TOKEN` set.

The credential test calls `GET /v1/ping`, so it catches both a wrong URL and a wrong token.

## Installation

Self-hosted n8n ≥ 1.x. Tested with n8n 2.44.6.

### A) From npm via the n8n UI (once published)

*Settings → Community Nodes → Install*, package name `n8n-nodes-innfactory-pdf-tools`.

Or with environment variables (n8n ≥ 2.21; note that this mode uninstalls community packages that
aren't in the list):

```
N8N_COMMUNITY_PACKAGES_MANAGED_BY_ENV=true
N8N_COMMUNITY_PACKAGES=[{"name":"n8n-nodes-innfactory-pdf-tools","version":"0.1.0"}]
# unverified packages need N8N_UNVERIFIED_PACKAGES_ENABLED=true (default) or a pinned "checksum"
```

### B) From the GitHub release tarball (no npm account or registry needed)

Every `node-v*` release attaches the package `.tgz`. Install it into the n8n data volume
(`/home/node/.n8n` is on a PVC, so it survives restarts), then restart n8n:

```sh
kubectl -n n8n exec deploy/n8n -c n8n -- sh -c '
  mkdir -p ~/.n8n/nodes && cd ~/.n8n/nodes &&
  npm i --no-audit --no-fund --legacy-peer-deps --ignore-scripts \
    https://github.com/innFactory-AI/n8n-pdf-tools/releases/download/node-v0.1.0/n8n-nodes-innfactory-pdf-tools-0.1.0.tgz'
kubectl -n n8n rollout restart deploy/n8n
```

`--legacy-peer-deps` matters: without it npm tries to install all of `n8n-workflow`. The node then
shows up in the node panel, but not under *Settings → Community Nodes*. To update, run the same
command with the new URL.

### Why not GitHub Packages / GHCR?

GHCR is a container registry, and n8n cannot install nodes from container images. GitHub's npm
registry (`npm.pkg.github.com`) needs a token even for public packages. n8n could use it via
`N8N_COMMUNITY_PACKAGES_REGISTRY` + `N8N_COMMUNITY_PACKAGES_AUTH_TOKEN`, but then *all* community
packages would come from that registry. Use npmjs (A) or the tarball (B) instead.

## Development

```sh
npm ci
npm run lint && npm run build && npm pack
npm run dev                 # n8n with the node hot-reloaded, http://localhost:5678
# end-to-end in a real n8n (docker), from the repo root:
python scripts/n8n_e2e.py --image n8n-pdf-tools:dev --tarball n8n-node/n8n-nodes-innfactory-pdf-tools-*.tgz
```

Release: bump `version` in `package.json` (and `CHANGELOG.md`), merge, then
`git tag node-v<version> && git push origin node-v<version>`. CI builds the package, runs the e2e
test, creates the GitHub release with the tarball and publishes to npm if `vars.NPM_PUBLISH` is `true`.
