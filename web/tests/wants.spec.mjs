// Functional tests for the wants & trades tab.
//
// The suite serves web/public as plain files, so there is no Worker behind it:
// the API is stubbed in the page with the same contract worker/index.js
// implements (and worker/index.test.mjs pins). What's tested here is the view —
// read-only until the password is given, and what add/remove do to the list.
import { test, expect } from '@playwright/test';

const PASSWORD = 'sininenkollari0726';
const TOKEN = 'test-token';

// A 1×1 PNG, so a card added in a test paints without reaching Scryfall's CDN.
const PIXEL = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64');

const CARDS = {
  'Sol Ring': {
    name: 'Sol Ring', set: 'c21', collector_number: '263', cmc: 1,
    mana_cost: '{1}', type_line: 'Artifact', oracle_text: '{T}: Add {C}{C}.',
    image_uris: {normal: 'https://cards.scryfall.io/normal/front/sol-ring.jpg'},
    prices: {eur: '1.50'}, scryfall_uri: 'https://scryfall.com/card/c21/263',
  },
  'Cyclonic Rift': {
    name: 'Cyclonic Rift', set: 'ima', collector_number: '58', cmc: 2,
    mana_cost: '{1}{U}', type_line: 'Instant', oracle_text: 'Return target permanent…',
    image_uris: {normal: 'https://cards.scryfall.io/normal/front/cyclonic-rift.jpg'},
    prices: {eur: '20.00'}, scryfall_uri: 'https://scryfall.com/card/ima/58',
  },
};

// The list as the Worker would keep it, held in the test process instead of KV.
function stubApi(page, {items = [], down = false} = {}) {
  const state = {items: items.map((i, n) => ({id: `id${n}`, count: 1, note: '', ...i}))};
  const json = (route, status, body) => route.fulfill({
    status, contentType: 'application/json', body: JSON.stringify(body)});

  return page.route('**/api/**', async route => {
    const request = route.request();
    if (down) return json(route, 404, {error: 'the list is unavailable (404)'});

    const url = new URL(request.url());
    const method = request.method();
    const body = ['POST', 'PATCH'].includes(method) ? request.postDataJSON() : {};
    const authed = request.headers().authorization === `Bearer ${TOKEN}`;

    if (url.pathname === '/api/session') {
      if (method === 'GET') return json(route, 200, {configured: true, editing: authed});
      return body.password === PASSWORD
        ? json(route, 200, {token: TOKEN, exp: Date.now() + 1e9})
        : json(route, 401, {error: 'wrong password'});
    }
    if (url.pathname === '/api/wants') return json(route, 200, {items: state.items});
    if (!authed) return json(route, 401, {error: 'unlock the list first'});

    if (url.pathname === '/api/wants/items') {
      const same = state.items.find(i => i.list === body.list
        && i.name.toLowerCase() === body.name.toLowerCase());
      if (same) {
        same.count += body.count;
        return json(route, 200, {item: same, merged: true});
      }
      const item = {id: `id${state.items.length}`, note: '', ...body};
      state.items.push(item);
      return json(route, 201, {item, merged: false});
    }
    const id = url.pathname.split('/').pop();
    const item = state.items.find(i => i.id === id);
    if (!item) return json(route, 404, {error: 'no such card on the list'});
    if (method === 'DELETE') {
      state.items = state.items.filter(i => i !== item);
      return json(route, 200, {removed: id});
    }
    Object.assign(item, {count: body.count ?? item.count});
    return json(route, 200, {item});
  });
}

async function stubScryfall(page) {
  await page.route('**://api.scryfall.com/**', route => {
    const url = new URL(route.request().url());
    const query = url.searchParams.get('q') || url.searchParams.get('fuzzy') || '';
    const match = Object.keys(CARDS).find(
      name => name.toLowerCase().startsWith(query.toLowerCase()));
    const body = url.pathname.endsWith('/autocomplete')
      ? {data: match ? [match] : []}
      : (CARDS[match] || {status: 404});
    return route.fulfill({
      status: match ? 200 : 404, contentType: 'application/json', body: JSON.stringify(body)});
  });
  await page.route('**://cards.scryfall.io/**', route =>
    route.fulfill({contentType: 'image/png', body: PIXEL}));
}

const wanted = ['Wants', 'For trade'];
const column = (page, title) => page.locator('#wants-board .cat', {hasText: title});
const openWants = async page => {
  await page.goto('/');
  await page.locator('#tab-wants').click();
  await expect(page.locator('#wants')).toBeVisible();
};

let pageErrors;

test.beforeEach(async ({ page }) => {
  pageErrors = [];
  page.on('pageerror', e => pageErrors.push(String(e)));
  await stubScryfall(page);
});

test.afterEach(() => {
  expect(pageErrors).toEqual([]);
});

test.describe('wants & trades', () => {
  test('shows both lists read-only until the password is given', async ({ page }) => {
    await stubApi(page, {items: [
      {name: 'Sol Ring', list: 'want', count: 2},
      {name: 'Cyclonic Rift', list: 'trade', count: 1},
    ]});
    await openWants(page);

    for (const title of wanted) await expect(column(page, title)).toBeVisible();
    await expect(column(page, 'Wants')).toContainText('(2)');
    await expect(page.locator('#count')).toHaveText('2 wanted · 1 for trade');

    // Read-only: no add form, and no way to take a card off the list.
    await expect(page.locator('#wants-add')).toBeHidden();
    await expect(page.locator('#wants-board .del')).toHaveCount(0);
    await expect(page.locator('#wants-edit')).toHaveText('Edit');
    // And the deck controls are out of the way — this view has no deck.
    await expect(page.locator('#deck')).toBeHidden();
    await expect(page.locator('#group')).toBeHidden();
  });

  test('the wrong password does not unlock editing', async ({ page }) => {
    await stubApi(page);
    await openWants(page);

    await page.locator('#wants-edit').click();
    await page.locator('#unlock-password').fill('hunter2');
    await page.locator('#unlock-form button[type=submit]').click();

    await expect(page.locator('#unlock-error')).toHaveText('wrong password');
    await expect(page.locator('#unlock')).toHaveClass(/open/);
    await expect(page.locator('#wants-add')).toBeHidden();
  });

  test('the password unlocks adding, and a card keeps its Scryfall printing', async ({ page }) => {
    await stubApi(page);
    await openWants(page);
    await unlock(page);

    await page.locator('#want-name').fill('Sol Ring');
    await page.locator('#want-note').fill('for the mothman deck');
    await page.locator('#want-add').click();

    const card = column(page, 'Wants').locator('.card');
    await expect(card).toHaveCount(1);
    await expect(page.locator('#wants-status')).toHaveText('added Sol Ring');
    await expect(card.locator('img')).toHaveAttribute(
      'src', 'https://cards.scryfall.io/normal/front/sol-ring.jpg');

    // The printing, price and note came along, and show in the details sheet.
    await card.locator('.hit').click();
    await card.locator('.info').click();
    await expect(page.locator('#preview .text')).toContainText('C21 263');
    await expect(page.locator('#preview .text')).toContainText('€1.50');
    await expect(page.locator('#preview .text')).toContainText('for the mothman deck');
  });

  test('a card can be added to the trades list and lands in that column', async ({ page }) => {
    await stubApi(page);
    await openWants(page);
    await unlock(page);

    await page.locator('#want-name').fill('Cyclonic Rift');
    await page.selectOption('#want-list', 'trade');
    await page.locator('#want-add').click();

    await expect(column(page, 'For trade').locator('.card')).toHaveCount(1);
    await expect(column(page, 'Wants').locator('.card')).toHaveCount(0);
    await expect(page.locator('#count')).toHaveText('0 wanted · 1 for trade');
  });

  test('adding a card twice counts copies instead of repeating the card', async ({ page }) => {
    await stubApi(page, {items: [{name: 'Sol Ring', list: 'want', count: 1}]});
    await openWants(page);
    await unlock(page);

    await page.locator('#want-name').fill('Sol Ring');
    await page.locator('#want-count').fill('2');
    await page.locator('#want-add').click();

    await expect(column(page, 'Wants').locator('.card')).toHaveCount(1);
    await expect(column(page, 'Wants').locator('.qty')).toHaveText('3×');
    await expect(page.locator('#count')).toHaveText('3 wanted · 0 for trade');
  });

  test('an unknown card is still added, by name', async ({ page }) => {
    await stubApi(page);
    await openWants(page);
    await unlock(page);

    await page.locator('#want-name').fill('Not A Real Card');
    await page.locator('#want-add').click();

    const card = column(page, 'Wants').locator('.card');
    await expect(card).toHaveCount(1);
    await expect(card.locator('.missing')).toHaveText('Not A Real Card');
  });

  test('removing takes the card off the list, and one copy at a time', async ({ page }) => {
    await stubApi(page, {items: [
      {name: 'Sol Ring', list: 'want', count: 3},
      {name: 'Cyclonic Rift', list: 'trade', count: 1},
    ]});
    await openWants(page);
    await unlock(page);

    // The quantity badge drops a single copy…
    await column(page, 'Wants').locator('.qty').click();
    await expect(column(page, 'Wants').locator('.qty')).toHaveText('2×');

    // …and the × removes the card, after asking.
    page.on('dialog', d => d.accept());
    await column(page, 'Wants').locator('.del').click();
    await expect(column(page, 'Wants').locator('.card')).toHaveCount(0);
    await expect(column(page, 'Wants')).toContainText('nothing on the wants list yet');
    await expect(column(page, 'For trade').locator('.card')).toHaveCount(1);

    // The list survives a reload, and so does being unlocked.
    await page.reload();
    await page.locator('#tab-wants').click();
    await expect(column(page, 'Wants').locator('.card')).toHaveCount(0);
    await expect(page.locator('#wants-add')).toBeVisible();
  });

  test('locking hides editing again and forgets the password', async ({ page }) => {
    await stubApi(page, {items: [{name: 'Sol Ring', list: 'want', count: 1}]});
    await openWants(page);
    await unlock(page);

    await page.locator('#wants-edit').click();

    await expect(page.locator('#wants-edit')).toHaveText('Edit');
    await expect(page.locator('#wants-add')).toBeHidden();
    await expect(page.locator('#wants-board .del')).toHaveCount(0);
    expect(await page.evaluate(() => localStorage.getItem('wants-token'))).toBe(null);

    await page.reload();
    await page.locator('#tab-wants').click();
    await expect(page.locator('#wants-add')).toBeHidden();
  });

  test('a stale token is dropped rather than showing controls that would fail', async ({ page }) => {
    await stubApi(page);
    await page.addInitScript(() => localStorage.setItem('wants-token', 'expired'));
    await openWants(page);

    await expect(page.locator('#wants-add')).toBeHidden();
    expect(await page.evaluate(() => localStorage.getItem('wants-token'))).toBe(null);
  });

  test('no API behind the site says so instead of showing an empty list', async ({ page }) => {
    await stubApi(page, {down: true});
    await openWants(page);

    await expect(page.locator('#wants-status')).toContainText('unavailable');
    await expect(page.locator('#wants-status')).toHaveClass(/err/);
  });

  test('the list has its own URL and does not need a built deck', async ({ page }) => {
    await stubApi(page, {items: [{name: 'Sol Ring', list: 'want', count: 1}]});
    await page.route('**/data/*.json', route =>
      route.request().url().endsWith('index.json') ? route.continue() : route.fulfill({status: 404}));

    await page.goto('/#wants');

    await expect(page.locator('#wants')).toBeVisible();
    await expect(column(page, 'Wants').locator('.card')).toHaveCount(1);
    await expect(page.locator('#tab-wants')).toHaveAttribute('aria-selected', 'true');

    // And back to the decks, which loaded in the background.
    await page.locator('#tab-cards').click();
    await expect(page.locator('#wants')).toBeHidden();
    await expect(page.locator('#empty')).toContainText('No data for');
  });

  test('never scrolls horizontally', async ({ page }) => {
    await stubApi(page, {items: [
      {name: 'Sol Ring', list: 'want', count: 1},
      {name: 'Cyclonic Rift', list: 'trade', count: 1},
    ]});
    await openWants(page);

    const overflow = await page.evaluate(() =>
      document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  });
});

async function unlock(page) {
  await page.locator('#wants-edit').click();
  await page.locator('#unlock-password').fill(PASSWORD);
  await page.locator('#unlock-form button[type=submit]').click();
  await expect(page.locator('#wants-add')).toBeVisible();
}
