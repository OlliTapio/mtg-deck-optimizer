// Worker behind decks.otl.fi. The deck site itself is still static assets —
// Cloudflare serves web/public and only calls this script for paths that aren't
// a file, which in practice means /api/*. Everything here belongs to the wants
// & trades list: the one part of the site that is editable, and therefore the
// one part that needs storage (KV) and a password.
//
// Reads are public, writes need a token from POST /api/session. The token is an
// expiry signed with EDIT_PASSWORD, so nothing has to be stored server-side and
// changing the password invalidates every token that was handed out.
//
//   POST   /api/session          {password}          -> {token, exp}
//   GET    /api/session                              -> {editing, configured}
//   GET    /api/wants                                -> {items, updated}
//   POST   /api/wants/items      {name, list, ...}   -> {item, merged}
//   PATCH  /api/wants/items/:id  {count|note|list}   -> {item}
//   DELETE /api/wants/items/:id                      -> {removed}

const KEY = 'wants-trades';
const MAX_ITEMS = 500;
const MAX_COUNT = 99;
const TOKEN_TTL_MS = 30 * 24 * 60 * 60 * 1000;
const LISTS = ['want', 'trade'];
// Card art is copied from Scryfall's CDN by the browser that adds the card, so
// only Scryfall URLs are ever stored — the list must not become a way to point
// the site's <img> tags at somebody else's host.
const IMAGE_HOSTS = ['cards.scryfall.io', 'svgs.scryfall.io'];

// --- helpers ---

const json = (status, body) => new Response(JSON.stringify(body), {
  status,
  headers: {'content-type': 'application/json; charset=utf-8',
            'cache-control': 'no-store'},
});

const enc = s => new TextEncoder().encode(s);

const b64url = buf => btoa(String.fromCharCode(...new Uint8Array(buf)))
  .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

// Compares in time that doesn't depend on where the first difference is, so a
// wrong password or token can't be found one character at a time.
function equals(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string') return false;
  let diff = a.length ^ b.length;
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    diff |= a.charCodeAt(i % a.length || 0) ^ b.charCodeAt(i % b.length || 0);
  }
  return diff === 0;
}

async function sign(secret, message) {
  const key = await crypto.subtle.importKey(
    'raw', enc(secret), {name: 'HMAC', hash: 'SHA-256'}, false, ['sign']);
  return b64url(await crypto.subtle.sign('HMAC', key, enc(message)));
}

async function issueToken(secret, now) {
  const exp = now + TOKEN_TTL_MS;
  return {token: `${exp}.${await sign(secret, String(exp))}`, exp};
}

async function verify(env, request, now) {
  const secret = env.EDIT_PASSWORD;
  if (!secret) return false;
  const header = request.headers.get('authorization') || '';
  const token = header.replace(/^Bearer\s+/i, '').trim();
  const [exp, sig] = token.split('.');
  if (!exp || !sig || !/^\d+$/.test(exp) || Number(exp) <= now) return false;
  return equals(sig, await sign(secret, exp));
}

// --- storage ---

// The whole list lives in one KV value: it is a few hundred cards at most, and
// one value means a card can't half-exist. Writes are read-modify-write, which
// is fine for a list one person edits from one phone.
async function readList(env) {
  const stored = await env.WANTS.get(KEY, 'json');
  if (!stored || !Array.isArray(stored.items)) return {version: 1, items: [], updated: null};
  return stored;
}

async function writeList(env, items, now) {
  const data = {version: 1, updated: new Date(now).toISOString(), items};
  await env.WANTS.put(KEY, JSON.stringify(data));
  return data;
}

// --- validation ---

const text = (value, max) => typeof value === 'string' ? value.trim().slice(0, max) : '';

function count(value, fallback = 1) {
  const n = Math.trunc(Number(value));
  if (!Number.isFinite(n) || n < 1) return fallback;
  return Math.min(n, MAX_COUNT);
}

function image(value) {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    if (url.protocol === 'https:' && IMAGE_HOSTS.includes(url.hostname)) return url.href;
  } catch { /* not a URL */ }
  return null;
}

function price(value) {
  const s = String(value ?? '');
  return /^\d{1,6}(\.\d{1,2})?$/.test(s) ? s : null;
}

// The card snapshot the browser sends comes straight from Scryfall, but it is
// still client input: keep the fields the site renders, drop everything else.
function cleanItem(body) {
  const name = text(body?.name, 200);
  if (!name) return {error: 'name is required'};
  const list = LISTS.includes(body?.list) ? body.list : 'want';
  const cmc = Number(body?.cmc);
  return {
    item: {
      name,
      list,
      count: count(body?.count),
      note: text(body?.note, 200),
      foil: body?.foil === true,
      set: text(body?.set, 10).toLowerCase(),
      number: text(body?.number, 12),
      mana_cost: text(body?.mana_cost, 60),
      type_line: text(body?.type_line, 200),
      oracle_text: text(body?.oracle_text, 2000),
      image: image(body?.image),
      price_eur: price(body?.price_eur),
      cmc: Number.isFinite(cmc) && cmc >= 0 && cmc <= 30 ? cmc : null,
      scryfall_uri: /^https:\/\/scryfall\.com\//.test(body?.scryfall_uri || '')
        ? body.scryfall_uri : null,
    },
  };
}

// --- routes ---

async function session(request, env, now) {
  if (request.method === 'GET') {
    return json(200, {configured: Boolean(env.EDIT_PASSWORD),
                      editing: await verify(env, request, now)});
  }
  if (request.method !== 'POST') return json(405, {error: 'method not allowed'});
  if (!env.EDIT_PASSWORD) {
    return json(503, {error: 'editing is not configured: set the EDIT_PASSWORD secret'});
  }
  const body = await request.json().catch(() => ({}));
  if (!equals(String(body?.password ?? ''), env.EDIT_PASSWORD)) {
    return json(401, {error: 'wrong password'});
  }
  return json(200, await issueToken(env.EDIT_PASSWORD, now));
}

async function addItem(request, env, now) {
  const {item, error} = cleanItem(await request.json().catch(() => ({})));
  if (error) return json(400, {error});

  const {items} = await readList(env);
  // Adding a card you already want bumps the count rather than making a second
  // row: two rows for the same card is never what the list is meant to say.
  const same = items.find(i => i.list === item.list
    && i.name.toLowerCase() === item.name.toLowerCase() && i.foil === item.foil);
  if (same) {
    same.count = Math.min(MAX_COUNT, same.count + item.count);
    if (item.note) same.note = item.note;
    const data = await writeList(env, items, now);
    return json(200, {item: same, merged: true, updated: data.updated});
  }
  if (items.length >= MAX_ITEMS) return json(409, {error: `the list is full (${MAX_ITEMS})`});

  const stored = {id: crypto.randomUUID(), added: new Date(now).toISOString(), ...item};
  items.push(stored);
  const data = await writeList(env, items, now);
  return json(201, {item: stored, merged: false, updated: data.updated});
}

async function patchItem(request, env, id, now) {
  const body = await request.json().catch(() => ({}));
  const {items} = await readList(env);
  const item = items.find(i => i.id === id);
  if (!item) return json(404, {error: 'no such card on the list'});

  if (body.count !== undefined) item.count = count(body.count, item.count);
  if (body.note !== undefined) item.note = text(body.note, 200);
  if (LISTS.includes(body.list)) item.list = body.list;
  const data = await writeList(env, items, now);
  return json(200, {item, updated: data.updated});
}

async function deleteItem(env, id, now) {
  const {items} = await readList(env);
  const kept = items.filter(i => i.id !== id);
  if (kept.length === items.length) return json(404, {error: 'no such card on the list'});
  const data = await writeList(env, kept, now);
  return json(200, {removed: id, updated: data.updated});
}

async function api(request, env, url, now) {
  const path = url.pathname.replace(/\/+$/, '');

  if (path === '/api/session') return session(request, env, now);

  if (!env.WANTS) return json(503, {error: 'storage is not configured: bind the WANTS KV namespace'});

  if (path === '/api/wants') {
    if (request.method !== 'GET') return json(405, {error: 'method not allowed'});
    const {items, updated} = await readList(env);
    return json(200, {items, updated});
  }

  const write = path === '/api/wants/items' || path.startsWith('/api/wants/items/');
  if (!write) return json(404, {error: 'no such endpoint'});
  if (!await verify(env, request, now)) return json(401, {error: 'unlock the list first'});

  if (path === '/api/wants/items') {
    if (request.method !== 'POST') return json(405, {error: 'method not allowed'});
    return addItem(request, env, now);
  }
  const id = decodeURIComponent(path.slice('/api/wants/items/'.length));
  if (request.method === 'DELETE') return deleteItem(env, id, now);
  if (request.method === 'PATCH') return patchItem(request, env, id, now);
  return json(405, {error: 'method not allowed'});
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    // Static assets are matched before the Worker runs, so anything arriving
    // here is either the API or a path with no file behind it.
    if (!url.pathname.startsWith('/api/')) {
      return env.ASSETS ? env.ASSETS.fetch(request) : new Response('Not found', {status: 404});
    }
    try {
      return await api(request, env, url, Date.now());
    } catch (err) {
      return json(500, {error: String(err?.message || err)});
    }
  },
};
