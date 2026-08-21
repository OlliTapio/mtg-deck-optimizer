# Deck site (epic #6)

React + Vite SPA that visualizes every deck in this repo. Reads a static data
bundle generated from the per-deck files — the repo stays the source of truth.

## Local development

```bash
# 1. Build the data bundle from the decks (repo root)
python3 sync_decks.py          # ensure deck.json is fresh (issue #7)
python3 build_site_data.py     # -> web/public/data/*.json

# 2. Run the SPA
cd web
npm install
npm run dev                     # http://localhost:5173
```

The bundle (`web/public/data/`) **is committed** — it's the generated data the
deployed site serves (like property-bot's `listings.json`). It's regenerated and
committed by `.github/workflows/build-data.yml`; don't hand-edit it.

## Deploy (Cloudflare Workers Builds)

Same model as the property-bot repo: a **git-connected Cloudflare Workers Build**
auto-deploys on every push to `main` — no API tokens in GitHub.

One-time setup in the Cloudflare dashboard (Workers → Builds → Connect repo):

- **Root directory:** repo root
- **Build command:** `cd web && npm ci && npm run build`
- **Deploy command:** `npx wrangler deploy`

`wrangler.toml` serves the built `web/dist` via `[assets]`. Pushing a
`decklist.txt` change triggers `build-data.yml` (regenerates + commits the
bundle); that commit triggers the Workers Build, which runs the Vite build and
deploys.

## What's next (later milestones)

- **M3 draft workflow (#10):** add a Worker script (`main` in `wrangler.toml`)
  with `/api/*` routes over a **D1** event-sourced write-bridge. Writes are gated
  by a shared passphrase stored as a Cloudflare secret (`EDIT_PASSWORD`) — the
  same pattern as property-bot's `FAV_PASSPHRASE`. Create the store and secret:
  ```bash
  npx wrangler d1 create mtg-deck-changes   # paste id into wrangler.toml
  npx wrangler secret put EDIT_PASSWORD
  ```
- **M2 (#9) / M4 (#11):** buy list / cuts / swaps display and buy-list management.
