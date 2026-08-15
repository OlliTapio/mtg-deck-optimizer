// Unit tests for the wants & trades API — the auth and validation rules that
// the Playwright suite can't see, because there the API is stubbed in the page.
//
//   node --test worker/        (or: npm run test:worker)
import test from 'node:test';
import assert from 'node:assert/strict';

import worker from './index.js';

const PASSWORD = 'test-password';

// KV, near enough: get(key, 'json') and put(key, string).
function fakeKV(initial) {
  const store = new Map(initial ? [['wants-trades', JSON.stringify(initial)]] : []);
  return {
    store,
    get: async (key, type) => {
      const value = store.get(key);
      if (value === undefined) return null;
      return type === 'json' ? JSON.parse(value) : value;
    },
    put: async (key, value) => void store.set(key, value),
  };
}

const env = (over = {}) => ({EDIT_PASSWORD: PASSWORD, WANTS: fakeKV(), ...over});

const call = (env, path, {method = 'GET', body, token} = {}) => worker.fetch(
  new Request(`https://decks.otl.fi${path}`, {
    method,
    headers: {
      ...(body ? {'content-type': 'application/json'} : {}),
      ...(token ? {authorization: `Bearer ${token}`} : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  }), env);

async function unlocked(e = env()) {
  const res = await call(e, '/api/session', {method: 'POST', body: {password: PASSWORD}});
  assert.equal(res.status, 200);
  return {env: e, token: (await res.json()).token};
}

const add = (e, token, item) =>
  call(e, '/api/wants/items', {method: 'POST', token, body: item});

const items = async e => (await (await call(e, '/api/wants')).json()).items;

test('the list is readable without a password', async () => {
  const e = env();
  const res = await call(e, '/api/wants');
  assert.equal(res.status, 200);
  assert.deepEqual((await res.json()).items, []);
});

test('the wrong password is refused and the right one issues a token', async () => {
  const e = env();
  const bad = await call(e, '/api/session', {method: 'POST', body: {password: 'guess'}});
  assert.equal(bad.status, 401);

  const {token} = await unlocked(e);
  assert.match(token, /^\d+\.[\w-]+$/);

  const check = await call(e, '/api/session', {token});
  assert.deepEqual(await check.json(), {configured: true, editing: true});
});

test('writes without a valid token are refused', async () => {
  const {env: e, token} = await unlocked();
  const [exp, sig] = token.split('.');

  for (const bad of [undefined, 'nonsense', `${exp}.${'A'.repeat(sig.length)}`,
                     `${Date.now() - 1000}.${sig}`]) {
    const res = await add(e, bad, {name: 'Sol Ring'});
    assert.equal(res.status, 401, `token ${bad} should not be accepted`);
  }
  assert.deepEqual(await items(e), []);
});

test('a token stops working when the password changes', async () => {
  const {env: e, token} = await unlocked();
  e.EDIT_PASSWORD = 'a new password';
  assert.equal((await add(e, token, {name: 'Sol Ring'})).status, 401);
});

test('adding a card stores only the fields the site renders', async () => {
  const {env: e, token} = await unlocked();
  const res = await add(e, token, {
    name: '  Arcane Signet  ',
    list: 'trade',
    count: '2',
    note: 'have two spares',
    set: 'ELD',
    number: '331',
    foil: 'yes',
    image: 'https://cards.scryfall.io/normal/front/a/b/arcane-signet.jpg',
    price_eur: '1.24',
    cmc: 2,
    scryfall_uri: 'https://scryfall.com/card/eld/331',
    admin: true,
  });

  assert.equal(res.status, 201);
  const {item, merged} = await res.json();
  assert.equal(merged, false);
  assert.equal(item.name, 'Arcane Signet');
  assert.equal(item.list, 'trade');
  assert.equal(item.count, 2);
  assert.equal(item.set, 'eld');
  assert.equal(item.foil, false, 'only a real boolean means foil');
  assert.equal(item.admin, undefined, 'unknown fields are dropped');
  assert.ok(item.id && item.added);
  assert.deepEqual(await items(e), [item]);
});

test('junk in the card snapshot is dropped rather than stored', async () => {
  const {env: e, token} = await unlocked();
  const res = await add(e, token, {
    name: 'Command Tower',
    image: 'https://evil.example/pixel.png',
    price_eur: 'free',
    cmc: 999,
    scryfall_uri: 'javascript:alert(1)',
    count: 1000,
    note: 'x'.repeat(500),
  });

  const {item} = await res.json();
  assert.equal(item.image, null);
  assert.equal(item.price_eur, null);
  assert.equal(item.cmc, null);
  assert.equal(item.scryfall_uri, null);
  assert.equal(item.count, 99, 'counts are capped');
  assert.equal(item.note.length, 200, 'notes are truncated');
});

test('a card with no name is refused', async () => {
  const {env: e, token} = await unlocked();
  const res = await add(e, token, {name: '   '});
  assert.equal(res.status, 400);
});

test('adding the same card again bumps the count instead of duplicating it', async () => {
  const {env: e, token} = await unlocked();
  await add(e, token, {name: 'Sol Ring', count: 1});
  const res = await add(e, token, {name: 'sol ring', count: 2, note: 'for the mothman deck'});

  assert.equal(res.status, 200);
  const {item, merged} = await res.json();
  assert.equal(merged, true);
  assert.equal(item.count, 3);
  assert.equal(item.note, 'for the mothman deck');
  assert.equal((await items(e)).length, 1);
});

test('the same card on the other list is its own row', async () => {
  const {env: e, token} = await unlocked();
  await add(e, token, {name: 'Sol Ring', list: 'want'});
  await add(e, token, {name: 'Sol Ring', list: 'trade'});
  assert.deepEqual((await items(e)).map(i => i.list), ['want', 'trade']);
});

test('a card can be edited and removed', async () => {
  const {env: e, token} = await unlocked();
  const {item} = await (await add(e, token, {name: 'Sol Ring'})).json();

  const patched = await call(e, `/api/wants/items/${item.id}`,
    {method: 'PATCH', token, body: {count: 4, list: 'trade', note: 'boxed'}});
  assert.equal(patched.status, 200);
  assert.deepEqual((await items(e))[0], {...item, count: 4, list: 'trade', note: 'boxed'});

  const removed = await call(e, `/api/wants/items/${item.id}`, {method: 'DELETE', token});
  assert.equal(removed.status, 200);
  assert.deepEqual(await items(e), []);

  const again = await call(e, `/api/wants/items/${item.id}`, {method: 'DELETE', token});
  assert.equal(again.status, 404);
});

test('a list that was never written reads as empty', async () => {
  const e = env({WANTS: fakeKV({version: 1})});
  assert.deepEqual(await items(e), []);
});

test('an unconfigured deployment says so instead of letting anyone edit', async () => {
  const noPassword = env({EDIT_PASSWORD: undefined});
  const res = await call(noPassword, '/api/session', {method: 'POST', body: {password: ''}});
  assert.equal(res.status, 503);
  assert.equal((await (await call(noPassword, '/api/session')).json()).configured, false);
  assert.equal((await add(noPassword, 'anything', {name: 'Sol Ring'})).status, 401);

  const noStore = env({WANTS: undefined});
  assert.equal((await call(noStore, '/api/wants')).status, 503);
});

test('unknown endpoints and methods are refused', async () => {
  const {env: e, token} = await unlocked();
  assert.equal((await call(e, '/api/nope')).status, 404);
  assert.equal((await call(e, '/api/wants', {method: 'POST', token, body: {}})).status, 405);
  assert.equal((await call(e, '/api/wants/items', {method: 'GET', token})).status, 405);
});

test('anything that is not the API falls through to the static site', async () => {
  const e = env({ASSETS: {fetch: async () => new Response('the deck site')}});
  const res = await worker.fetch(new Request('https://decks.otl.fi/index.html'), e);
  assert.equal(await res.text(), 'the deck site');
});
