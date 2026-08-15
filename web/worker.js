/**
 * Worker for the deck site.
 *
 * Static assets (web/public) are served by the assets layer; this script only
 * answers the wants & trades API, which no asset can:
 *
 *   GET    /api/wants       -> {items, updated}   public
 *   POST   /api/wants       -> {item}             password
 *   PATCH  /api/wants/<id>  -> {item}             password
 *   DELETE /api/wants/<id>  -> {ok: true}         password
 *   POST   /api/unlock      -> {ok: true}         password, checks only
 *
 * Writes carry the password in an X-Edit-Password header (EDIT_PASSWORD, see
 * wrangler.toml). Reads are public — the list is meant to be shown to trade
 * partners.
 *
 * The whole list lives under one KV key: it is one person's want list, a few
 * hundred rows at most, so a single value keeps the "updated" stamp and the
 * ordering trivial. That does mean two edits landing in the same second can
 * lose one of them, which is the right trade for a one-person list.
 *
 * web/devserver.py serves this same API locally from a JSON file. The two are
 * one contract in two runtimes: change a route or a field here, change it there.
 */

const KEY = 'wants:v1';
const MAX_ITEMS = 500;
const LISTS = new Set(['want', 'trade']);

const json = (data, status = 200) => new Response(JSON.stringify(data), {
  status,
  headers: {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  },
});

const text = (value, max) =>
  typeof value === 'string' ? value.trim().slice(0, max) : '';

// Both stored URLs are rendered by the browser (an <img src> and an <a href>),
// so they are pinned to Scryfall rather than taken on trust from the request.
function scryfallUrl(value, host) {
  const raw = text(value, 500);
  if (!raw) return '';
  try {
    const url = new URL(raw);
    const sameHost = url.hostname === host || url.hostname.endsWith('.' + host);
    return url.protocol === 'https:' && sameHost ? url.href : '';
  } catch {
    return '';
  }
}

function quantity(value, fallback) {
  const n = Math.round(Number(value));
  return Number.isFinite(n) ? Math.min(99, Math.max(1, n)) : fallback;
}

// Only these fields are ever stored, whatever else the body carries. Absent
// fields keep the value they already had, so PATCH can send just {count: 3}.
function sanitize(body, base = {}) {
  const name = text(body.name, 150) || base.name || '';
  if (!name) return null;
  const keep = (field, clean, fallback = '') =>
    field in body ? clean(body[field]) : (base[field] ?? fallback);
  return {
    id: base.id,
    added: base.added,
    name,
    list: LISTS.has(body.list) ? body.list : (base.list || 'want'),
    count: 'count' in body ? quantity(body.count, base.count ?? 1) : (base.count ?? 1),
    note: keep('note', v => text(v, 200)),
    image: keep('image', v => scryfallUrl(v, 'scryfall.io')),
    set: keep('set', v => text(v, 10)),
    number: keep('number', v => text(v, 10)),
    mana_cost: keep('mana_cost', v => text(v, 60)),
    type_line: keep('type_line', v => text(v, 150)),
    price_eur: keep('price_eur', v => text(v, 12)),
    scryfall_uri: keep('scryfall_uri', v => scryfallUrl(v, 'scryfall.com')),
  };
}

// Length-independent compare, so a wrong password can't be narrowed down by
// timing it. (Rate limiting is Cloudflare's job, not this script's.)
function authorized(request, env) {
  const expected = env.EDIT_PASSWORD || '';
  if (!expected) return false;
  const encoder = new TextEncoder();
  const given = encoder.encode(request.headers.get('x-edit-password') || '');
  const want = encoder.encode(expected);
  let diff = given.length ^ want.length;
  for (let i = 0; i < given.length; i++) diff |= given[i] ^ want[i % want.length];
  return diff === 0;
}

async function readStore(env) {
  const raw = await env.WANTS.get(KEY, 'json');
  const items = Array.isArray(raw?.items) ? raw.items : [];
  return { items, updated: typeof raw?.updated === 'string' ? raw.updated : null };
}

async function writeStore(env, items) {
  const store = { items, updated: new Date().toISOString() };
  await env.WANTS.put(KEY, JSON.stringify(store));
  return store;
}

async function body(request) {
  try {
    const parsed = await request.json();
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

async function handleApi(request, env, url) {
  const path = url.pathname;
  const method = request.method.toUpperCase();

  if (method === 'OPTIONS') {
    return new Response(null, {
      status: 204,
      headers: { allow: 'GET, POST, PATCH, DELETE, OPTIONS' },
    });
  }

  const needsPassword = !(path === '/api/wants' && method === 'GET');
  if (needsPassword && !authorized(request, env)) {
    return json({ error: 'wrong password' }, 401);
  }
  if (path === '/api/unlock') {
    return method === 'POST' ? json({ ok: true }) : json({ error: 'not found' }, 404);
  }
  if (!env.WANTS) {
    return json({ error: 'no WANTS KV namespace bound — see web/README.md' }, 503);
  }

  if (path === '/api/wants') {
    if (method === 'GET') return json(await readStore(env));
    if (method === 'POST') {
      const store = await readStore(env);
      if (store.items.length >= MAX_ITEMS) {
        return json({ error: `list is full (${MAX_ITEMS} entries)` }, 409);
      }
      const item = sanitize(await body(request));
      if (!item) return json({ error: 'a card name is required' }, 400);
      item.id = crypto.randomUUID();
      item.added = new Date().toISOString();
      // Same card on the same list is one row with a bigger count, which is how
      // a want list is read ("3× Sol Ring"), not three identical rows.
      const same = store.items.find(
        i => i.list === item.list && i.name.toLowerCase() === item.name.toLowerCase());
      if (same) {
        same.count = quantity(same.count + item.count, same.count);
        await writeStore(env, store.items);
        return json({ item: same });
      }
      store.items.push(item);
      await writeStore(env, store.items);
      return json({ item }, 201);
    }
    return json({ error: 'method not allowed' }, 405);
  }

  const id = decodeURIComponent(path.slice('/api/wants/'.length));
  const store = await readStore(env);
  const at = store.items.findIndex(i => i.id === id);
  if (at < 0) return json({ error: 'no such entry' }, 404);

  if (method === 'PATCH') {
    const item = sanitize(await body(request), store.items[at]);
    if (!item) return json({ error: 'a card name is required' }, 400);
    store.items[at] = item;
    await writeStore(env, store.items);
    return json({ item });
  }
  if (method === 'DELETE') {
    store.items.splice(at, 1);
    await writeStore(env, store.items);
    return json({ ok: true });
  }
  return json({ error: 'method not allowed' }, 405);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === '/api/unlock' || url.pathname === '/api/wants' ||
        url.pathname.startsWith('/api/wants/')) {
      return handleApi(request, env, url);
    }
    // Everything else is the site itself. Reached only for paths the assets
    // layer had no file for, but the binding serves those correctly too.
    return env.ASSETS.fetch(request);
  },
};
