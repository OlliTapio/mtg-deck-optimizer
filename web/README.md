# Deck site

Archidekt-style viewer for the decks in this repo. Three tabs:

- **Cards** — card images grouped by card type (or by Archidekt category),
  sorted by mana cost, Commander first and Land last. Tapping a card opens it
  full size with its printing, price and otags.
- **Stats** — mana symbols and mana production per colour, the Command Zone
  template check, Scryfall otag counts (removal, ramp, draw, …), card types and
  the mana curve.
- **Trades** (`#trades`) — the wants & trades list: cards to get hold of and
  cards to give away. Nothing to do with the decks, so it isn't built from
  `decks/` — it's stored server-side and edited in the browser. See below.

The decks themselves are read-only: they come from `decklist.txt` via
`build_site.py`.

- `web/public/index.html` — the whole site (vanilla JS, no build step)
- `web/public/data/*.json` — generated data bundle, **committed** (one file per
  deck + `index.json`)
- `build_site.py` — regenerates the bundle from `decks/*/decklist.txt`
- `web/worker.js` — the Worker: static assets plus the `/api/*` routes
- `web/devserver.py` — the same API locally, backed by a JSON file
- `wrangler.toml` — Worker config (`name = "mtg-decks"`)

Categories come from the `[...]` tags in `decklist.txt`; untagged cards fall back
to their Scryfall card type. Card data is baked in from `cache/cards.json` and
`cache/otags.json` at build time, because `cache/` is gitignored — the browser
only loads card images from Scryfall's CDN. Stats (pips, curve, template check)
are computed in `build_site.py` via `deck_analyzer.py`, so the site and the CLI
analysis always agree.

## Wants & trades

A single list of cards, split into **Wants** and **For trade**. Type a card
name (Scryfall autocompletes it), pick a list, a count and an optional note;
the row gets its picture, set and price from Scryfall, and a card Scryfall
doesn't recognise is still added by name. `−`/`+` change the count, `×` removes
the row, and adding a card that's already on that list bumps its count instead
of making a second row.

**Reading needs no password; every change does.** The password goes in the
header bar's "Unlock edits" field, is kept for that browser tab only
(sessionStorage) and is sent with each write. Locked, the list is a plain
read-only page to show a trade partner.

The API — `web/worker.js` in production, `web/devserver.py` locally, one
contract in two runtimes:

| route | | |
| --- | --- | --- |
| `GET /api/wants` | `{items, updated}` | public |
| `POST /api/wants` | `{item}` | password |
| `PATCH /api/wants/<id>` | `{item}` | password |
| `DELETE /api/wants/<id>` | `{ok}` | password |
| `POST /api/unlock` | `{ok}` | password, checks only |

Writes carry the password in an `X-Edit-Password` header. Only known fields are
stored, and the two URLs a row can hold are pinned to Scryfall hosts because
the browser renders them.

The whole list lives under one KV key (`wants:v1`), which is why two edits in
the same second can lose one — fine for a one-person list.

### Setup (once)

```bash
npx wrangler kv namespace create WANTS   # paste the id into wrangler.toml
```

Until that id is filled in, `wrangler deploy` fails. `EDIT_PASSWORD` is a var in
`wrangler.toml` so a deploy from a fresh clone works; to keep it out of git,
delete the `[vars]` block and run `npx wrangler secret put EDIT_PASSWORD`
instead (a secret overrides a var of the same name).

Locally the KV namespace is a JSON file: `WANTS_STORE`, default
`web/wants.local.json` (gitignored), password from `EDIT_PASSWORD`.

## Tests

`web/tests/site.spec.mjs` drives the site with Playwright on an iPhone 11
viewport (WebKit — the stacked-card interaction is built for a phone) and on a
desktop viewport: grouping and ordering, open/close in a stack, tap targets,
the details overlay, the Stats tab, the missing-data path.

`web/tests/wants.spec.mjs` covers the trades tab against the real API served by
`devserver.py`: read-only until unlocked, wrong password, add/count/remove,
the merge of a duplicate, the two lists staying apart, a card Scryfall has
never heard of, and what the API stores. Scryfall itself is stubbed, so the
suite passes offline and a row's price doesn't depend on the day.

The suite starts `devserver.py` itself on its own port (8321), so it never
picks up a `npm run preview` server from another worktree, and it points
`WANTS_STORE` at `.playwright/` so it can't touch the real local list.
Screenshots go to `.playwright/` too (gitignored).

```bash
npm install     # first time
npm test        # `pretest` installs the browsers; or: npm run test:ui
```

## Update after a decklist change

```bash
python3 build_site.py                 # all decks
python3 build_site.py wise_mothman    # just one (index.json is merged, not replaced)
npm run preview                       # http://127.0.0.1:8000
```

Then commit the changed `web/public/data/*.json` along with the decklist.

## Release

Same setup as the property-bot repo: static assets served by a Worker, data
committed to git.

```bash
npm install          # first time only (wrangler)
npx wrangler login   # first time only
npm run publish      # = build_site.py + wrangler deploy
```

`npm run deploy` deploys without rebuilding the data. The first deploy also
needs the `WANTS` KV namespace above; `npx wrangler deploy --dry-run` checks
the config without shipping anything.

Optional, also mirroring property-bot: connect this repo in the Cloudflare
dashboard (Workers → mtg-decks → Settings → Builds → Connect repo) so every
push to `main` auto-deploys and no API token is needed anywhere. Because the
data bundle is committed, the build command can stay empty — Cloudflare uploads
`web/public` and bundles `web/worker.js` from `wrangler.toml`.

The custom domain `decks.otl.fi` is already declared in `wrangler.toml`; a
deploy from another Cloudflare account would need that `[[routes]]` block
changed or removed first.
