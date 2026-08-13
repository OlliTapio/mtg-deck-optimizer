# Deck site

Read-only Archidekt-style viewer for the decks in this repo. Two tabs:

- **Cards** — card images grouped by card type (or by Archidekt category),
  sorted by mana cost, Commander first and Land last. Tapping a card opens it
  full size with its printing, price and otags.
- **Stats** — mana symbols and mana production per colour, the Command Zone
  template check, Scryfall otag counts (removal, ramp, draw, …), card types and
  the mana curve.

No editing, no API.

- `web/public/index.html` — the whole site (vanilla JS, no build step)
- `web/public/data/*.json` — generated data bundle, **committed** (one file per
  deck + `index.json`)
- `build_site.py` — regenerates the bundle from `decks/*/decklist.txt`
- `wrangler.toml` — static-assets-only Worker (`name = "mtg-decks"`)

Categories come from the `[...]` tags in `decklist.txt`; untagged cards fall back
to their Scryfall card type. Card data is baked in from `cache/cards.json` and
`cache/otags.json` at build time, because `cache/` is gitignored — the browser
only loads card images from Scryfall's CDN. Stats (pips, curve, template check)
are computed in `build_site.py` via `deck_analyzer.py`, so the site and the CLI
analysis always agree.

## Tests

`web/tests/site.spec.mjs` drives the site with Playwright on an iPhone 11
viewport (WebKit — the stacked-card interaction is built for a phone) and on a
desktop viewport: grouping and ordering, open/close in a stack, tap targets,
the details overlay, the Stats tab, the missing-data path. It serves
`web/public` itself, and writes screenshots to `.playwright/` (gitignored).

```bash
npm install     # first time
npm test        # `pretest` installs the browsers; or: npm run test:ui
```

The suite serves the bundle on its own port (8321), so it never picks up a
`npm run preview` server from another worktree.

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

`npm run deploy` deploys without rebuilding the data.

Optional, also mirroring property-bot: connect this repo in the Cloudflare
dashboard (Workers → mtg-decks → Settings → Builds → Connect repo) so every
push to `main` auto-deploys and no API token is needed anywhere. Because the
data bundle is committed, the build command can stay empty — Cloudflare just
uploads `web/public`.

The custom domain `decks.otl.fi` is already declared in `wrangler.toml`; a
deploy from another Cloudflare account would need that `[[routes]]` block
changed or removed first.
