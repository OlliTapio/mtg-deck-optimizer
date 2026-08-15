# Deck site

Archidekt-style viewer for the decks in this repo. Three tabs:

- **Cards** — card images grouped by card type (or by Archidekt category),
  sorted by mana cost, Commander first and Land last. Tapping a card opens it
  full size with its printing, price and otags.
- **Stats** — mana symbols and mana production per colour, the Command Zone
  template check, Scryfall otag counts (removal, ramp, draw, …), card types and
  the mana curve.
- **Wants** — cards to look for and cards to give away (`#wants`). The one
  editable view, and the only one with no link to any deck: it is a shopping and
  trading list, not part of a decklist. Reading is public, editing needs the
  password. See [Wants & trades](#wants--trades) below.

The decks themselves are still read-only and still generated from
`decks/*/decklist.txt`.

- `web/public/index.html` — the whole site (vanilla JS, no build step)
- `web/public/data/*.json` — generated data bundle, **committed** (one file per
  deck + `index.json`)
- `build_site.py` — regenerates the bundle from `decks/*/decklist.txt`
- `worker/index.js` — the `/api/*` routes behind the wants list
- `wrangler.toml` — the Worker (`name = "mtg-decks"`): static assets + that script

Categories come from the `[...]` tags in `decklist.txt`; untagged cards fall back
to their Scryfall card type. Card data is baked in from `cache/cards.json` and
`cache/otags.json` at build time, because `cache/` is gitignored — the browser
only loads card images from Scryfall's CDN. Stats (pips, curve, template check)
are computed in `build_site.py` via `deck_analyzer.py`, so the site and the CLI
analysis always agree.

## Wants & trades

Two lists — **Wants** and **For trade** — of cards with a quantity and an
optional note, drawn with the same card grid as a deck. They live in a
Cloudflare KV namespace rather than in git, because they are edited from a phone
rather than from a decklist, and they are deliberately not tied to any deck.

Adding a card looks it up on Scryfall in the browser and stores the printing it
finds (art, set, collector number, price, oracle text), so the list renders like
the rest of the site. A card Scryfall doesn't know is still added by name.

Editing is behind a password. `POST /api/session` trades the password for a
token — an expiry signed with the password — which the browser keeps for a
month; the password itself is never stored, and changing it invalidates every
token that was handed out. Reads need no token, so the list can be shared.

    GET    /api/wants                          the list
    POST   /api/session      {password}        -> {token, exp}
    POST   /api/wants/items  {name, list, …}   add (a repeat adds copies)
    PATCH  /api/wants/items/:id  {count|note|list}
    DELETE /api/wants/items/:id

### Setup

Once per Cloudflare account:

```bash
npx wrangler kv namespace create WANTS   # paste the id into wrangler.toml
npx wrangler secret put EDIT_PASSWORD    # the password for the Edit button
```

Without the secret the site still shows the list and says editing isn't
configured; without the namespace `/api/wants` answers 503.

Locally, `cp .dev.vars.example .dev.vars`, set a password there, and run
`npm run dev` (`wrangler dev`, with a local KV) instead of `npm run preview` —
`preview` is a plain file server, so the Wants tab reports that the list is
unavailable.

## Tests

`web/tests/site.spec.mjs` drives the site with Playwright on an iPhone 11
viewport (WebKit — the stacked-card interaction is built for a phone) and on a
desktop viewport: grouping and ordering, open/close in a stack, tap targets,
the details overlay, the Stats tab, the missing-data path. It serves
`web/public` itself, and writes screenshots to `.playwright/` (gitignored).

`web/tests/wants.spec.mjs` covers the Wants tab the same way. The suite has no
Worker behind it, so it stubs `/api/*` in the page with the contract
`worker/index.js` implements; the API's own rules — the password, token expiry,
what is stored — are tested directly in `worker/index.test.mjs` against a fake
KV.

```bash
npm install     # first time
npm test        # worker tests, then Playwright (`pretest` installs the browsers)
npm run test:worker   # just the API tests, no browsers needed
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

`npm run deploy` deploys without rebuilding the data. The deploy also uploads
`worker/index.js`; the `WANTS` namespace id in `wrangler.toml` and the
`EDIT_PASSWORD` secret are per-account, so a first deploy needs the two commands
under [Wants & trades](#wants--trades) first.

Optional, also mirroring property-bot: connect this repo in the Cloudflare
dashboard (Workers → mtg-decks → Settings → Builds → Connect repo) so every
push to `main` auto-deploys and no API token is needed anywhere. Because the
data bundle is committed, the build command can stay empty — Cloudflare just
uploads `web/public`.

The custom domain `decks.otl.fi` is already declared in `wrangler.toml`; a
deploy from another Cloudflare account would need that `[[routes]]` block
changed or removed first.
