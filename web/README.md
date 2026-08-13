# Deck site

Read-only Archidekt-style viewer for the decks in this repo: a deck picker plus
card images grouped into their Archidekt categories. Nothing else — no editing,
no stats, no API.

- `web/public/index.html` — the whole site (vanilla JS, no build step)
- `web/public/data/*.json` — generated data bundle, **committed** (one file per
  deck + `index.json`)
- `build_site.py` — regenerates the bundle from `decks/*/decklist.txt`
- `wrangler.toml` — static-assets-only Worker (`name = "mtg-decks"`)

Categories come from the `[...]` tags in `decklist.txt` (Archidekt writes the
primary category first); untagged cards fall back to their Scryfall card type.
Card images/prices/oracle text are baked in from `cache/cards.json` at build
time, because `cache/` is gitignored — the browser never calls Scryfall.

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
