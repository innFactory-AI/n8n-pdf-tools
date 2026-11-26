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

## Connection and credentials

**Authentication** on the node:
- **None (In-Cluster)**, the default: no credential needed. The node calls the **Service URL**,
  default `http://n8n-pdf-tools:8080`, which is right when the service runs in the same namespace as
  n8n. From another namespace use `http://n8n-pdf-tools.<namespace>.svc.cluster.local:8080`.
- **PDF Tools API Credential**: for a service with `API_TOKEN` set, or to manage the URL centrally.
  The credential has **Base URL** and **API Token** (sent as `X-API-Key`). Its test calls
  `GET /v1/ping`, so it catches both a wrong URL and a wrong token.

## Installation

Self-hosted n8n. Tested with n8n 2.44.6 and 2.45.7. The package is **not on npm**; each `node-v*`
release on GitHub has the `.tgz` attached. Install it into the running n8n with:

```sh
deploy/install-n8n-node.sh 0.1.0        # version, optional namespace (default n8n)
```

The script does the following:
- downloads the release tarball inside the n8n pod and unpacks it into `~/.n8n/nodes/node_modules`
  (the n8n PVC, so it survives restarts)
- adds it to `~/.n8n/nodes/package.json`
- restarts `deploy/n8n`; with the `Recreate` strategy that means a short downtime

It does not run `npm install`, so the other community nodes stay untouched. To update, run it again
with the new version.

The node then shows up in the node panel as **PDF Tools**, but not under *Settings → Community
Nodes*, because that page only lists packages installed through the UI.

Why not GHCR or the GitHub npm registry? GHCR holds container images, and n8n can't install nodes
from those. GitHub's npm registry needs a token even for public packages, and pointing n8n at it
(`N8N_COMMUNITY_PACKAGES_REGISTRY`) would move *all* community packages to that registry.

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
test and creates the GitHub release with the tarball. npm publishing exists in CI but is off
(`vars.NPM_PUBLISH`).
