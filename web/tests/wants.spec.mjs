// Functional tests for the wants & trades tab, against the real API served by
// web/devserver.py (see playwright.config.mjs for the store and the password).
//
//   npm test
import { test, expect } from '@playwright/test';

const PASSWORD = 'test-password';

// Both projects run against one server and one store, so every test works on
// rows only it could have created and takes them away again afterwards. Names
// that aren't real cards also keep the Scryfall stub honest.
const uniq = (info, label) =>
  `ZZ ${label} ${info.project.name} ${info.title.replace(/\W+/g, '-')}`.slice(0, 90);

const api = (page, path, method = 'GET', data) => page.request.fetch(path, {
  method,
  headers: { 'x-edit-password': PASSWORD, 'content-type': 'application/json' },
  data,
});

const row = (page, name) => page.locator('.want-row').filter({ hasText: name });

// Scryfall is stubbed: the suite must pass offline, and a live lookup would
// make what a row says depend on the day's prices.
async function stubScryfall(page) {
  await page.route('https://api.scryfall.com/cards/named*', route => route.fulfill({
    json: {
      name: new URL(route.request().url()).searchParams.get('fuzzy'),
      image_uris: { normal: 'https://cards.scryfall.io/normal/stub.jpg' },
      set: 'tst', collector_number: '7', mana_cost: '{1}{U}',
      type_line: 'Artifact', prices: { eur: '2.50' },
      scryfall_uri: 'https://scryfall.com/card/tst/7/stub',
    },
  }));
  await page.route('https://api.scryfall.com/cards/autocomplete*', route =>
    route.fulfill({ json: { data: ['Stubbed Card'] } }));
}

let pageErrors;
let added;

test.beforeEach(async ({ page }) => {
  pageErrors = [];
  added = [];
  page.on('pageerror', e => pageErrors.push(String(e)));
  await stubScryfall(page);
  await page.goto('/#trades');
  await expect(page.locator('#wants')).toBeVisible();
});

test.afterEach(async ({ page }) => {
  const { items } = await (await api(page, '/api/wants')).json();
  for (const item of items.filter(i => added.includes(i.name))) {
    await api(page, `/api/wants/${item.id}`, 'DELETE');
  }
  expect(pageErrors).toEqual([]);
});

// Adds a row through the UI and remembers it for the cleanup above.
async function add(page, name, { list = 'want', count = 1, note = '' } = {}) {
  added.push(name);
  await page.fill('#want-name', name);
  await page.selectOption('#want-list', list);
  await page.fill('#want-count', String(count));
  if (note) await page.fill('#want-note', note);
  await page.click('#want-add');
  await expect(row(page, name)).toBeVisible();
}

const unlock = async page => {
  await page.fill('#pw', PASSWORD);
  await page.click('#unlock-form button');
  await expect(page.locator('#want-form')).toBeVisible();
};

test.describe('wants & trades', () => {
  test('the tab is reachable by hash and by the tab button', async ({ page }) => {
    await expect(page.locator('#tab-wants')).toHaveAttribute('aria-selected', 'true');
    await expect(page.locator('.want-list')).toHaveCount(2);
    await expect(page.locator('.want-list').first()).toContainText('Wants');
    await expect(page.locator('.want-list').nth(1)).toContainText('For trade');
    // The deck controls belong to the deck view, not to this one.
    await expect(page.locator('#deck')).toBeHidden();
    await expect(page.locator('#deck-controls')).toBeHidden();
    await expect(page.locator('#board')).toBeHidden();

    await page.click('#tab-cards');
    await expect(page.locator('#wants')).toBeHidden();
    await expect(page.locator('#deck')).toBeVisible();
    await expect(page.locator('.card').first()).toBeVisible();
    expect(new URL(page.url()).hash).not.toBe('#trades');

    await page.click('#tab-wants');
    await expect(page.locator('#wants')).toBeVisible();
    expect(new URL(page.url()).hash).toBe('#trades');
  });

  test('the list is readable without the password and not editable', async ({ page }) => {
    const name = uniq(test.info(), 'readonly');
    await api(page, '/api/wants', 'POST', { name, list: 'want', count: 2 });
    await page.reload();

    await expect(row(page, name)).toBeVisible();
    added.push(name);
    await expect(page.locator('#want-form')).toBeHidden();
    await expect(page.locator('#unlock-form')).toBeVisible();
    await expect(row(page, name).locator('.want-controls')).toBeHidden();
  });

  test('a wrong password does not unlock and says so', async ({ page }) => {
    await page.fill('#pw', 'not-the-password');
    await page.click('#unlock-form button');

    await expect(page.locator('#wants-msg')).toHaveText(/wrong password/i);
    await expect(page.locator('#want-form')).toBeHidden();
  });

  test('unlocking lets a card be added, counted up and removed again', async ({ page }) => {
    const name = uniq(test.info(), 'crud');
    await unlock(page);
    await add(page, name, { note: 'from a friend' });

    // Scryfall filled the row in, and the card landed on the wants list.
    const entry = row(page, name);
    await expect(entry).toContainText('TST');
    await expect(entry).toContainText('€2.50');
    await expect(entry).toContainText('from a friend');
    await expect(entry.locator('img')).toHaveAttribute('src', /cards\.scryfall\.io/);
    await expect(page.locator('.want-list[data-list=want]')).toContainText(name);
    await expect(page.locator('.want-list[data-list=trade]')).not.toContainText(name);

    // Counts round-trip through the API, so a reload shows the same number.
    await expect(entry.locator('.want-num')).toHaveText('1×');
    await expect(entry.locator('.less')).toBeDisabled();  // nothing below one
    await entry.locator('.more').click();
    await expect(entry.locator('.want-num')).toHaveText('2×');
    await entry.locator('.less').click();
    await expect(entry.locator('.want-num')).toHaveText('1×');
    await entry.locator('.more').click();
    await page.reload();
    await expect(row(page, name).locator('.want-num')).toHaveText('2×');
    // The heading totals the copies and their price.
    await expect(page.locator('.want-list[data-list=want] h2')).toContainText('€');

    await expect(page.locator('#want-form')).toBeVisible();  // still unlocked
    await row(page, name).locator('.remove').click();
    await expect(row(page, name)).toHaveCount(0);
    const { items } = await (await api(page, '/api/wants')).json();
    expect(items.some(i => i.name === name)).toBe(false);
  });

  test('the same card twice is one row with a bigger count', async ({ page }) => {
    const name = uniq(test.info(), 'dupe');
    await unlock(page);
    await add(page, name, { count: 2 });
    await add(page, name, { count: 3 });

    await expect(row(page, name)).toHaveCount(1);
    await expect(row(page, name).locator('.want-num')).toHaveText('5×');
  });

  test('the two lists are kept apart', async ({ page }) => {
    const name = uniq(test.info(), 'trade');
    await unlock(page);
    await add(page, name, { list: 'trade' });

    await expect(page.locator('.want-list[data-list=trade]')).toContainText(name);
    await expect(page.locator('.want-list[data-list=want]')).not.toContainText(name);
  });

  test('a row opens the card in the same overlay the deck view uses', async ({ page }) => {
    const name = uniq(test.info(), 'preview');
    await unlock(page);
    await add(page, name);

    await row(page, name).locator('.thumb').click();

    await expect(page.locator('#preview')).toHaveClass(/open/);
    await expect(page.locator('#preview .text')).toContainText(name);
    await expect(page.locator('#preview .text')).toContainText('€2.50');
    await page.locator('#preview').click();
    await expect(page.locator('#preview')).not.toHaveClass(/open/);
  });

  test('a card Scryfall has never heard of is still added by name', async ({ page }) => {
    const name = uniq(test.info(), 'unknown');
    await page.route('https://api.scryfall.com/cards/named*', route =>
      route.fulfill({ status: 404, json: { object: 'error' } }));
    await unlock(page);
    await add(page, name);

    await expect(row(page, name)).toBeVisible();
    await expect(row(page, name).locator('.missing')).toHaveText(name);
  });

  test('locking again hides the controls without touching the list', async ({ page }) => {
    const name = uniq(test.info(), 'lock');
    await unlock(page);
    await add(page, name);

    await page.click('#lock');

    await expect(page.locator('#want-form')).toBeHidden();
    await expect(row(page, name)).toBeVisible();
    await expect(row(page, name).locator('.want-controls')).toBeHidden();
    // And the password isn't remembered for the next visit.
    await page.reload();
    await expect(page.locator('#unlock-form')).toBeVisible();
    await expect(page.locator('#want-form')).toBeHidden();
  });

  test('an unlocked tab stays unlocked across a reload', async ({ page }) => {
    await unlock(page);
    await page.reload();

    await expect(page.locator('#want-form')).toBeVisible();
    await expect(page.locator('#unlock-form')).toBeHidden();
  });
});

test.describe('wants API', () => {
  test('writes need the password, reads do not', async ({ page }) => {
    const anonymous = (path, method = 'GET', data) =>
      page.request.fetch(path, { method, data, headers: { 'content-type': 'application/json' } });

    expect((await anonymous('/api/wants')).status()).toBe(200);
    expect((await anonymous('/api/wants', 'POST', { name: 'ZZ Nope' })).status()).toBe(401);
    expect((await anonymous('/api/unlock', 'POST', {})).status()).toBe(401);
    expect((await page.request.fetch('/api/wants', {
      method: 'POST', data: { name: 'ZZ Nope' },
      headers: { 'x-edit-password': PASSWORD + 'x', 'content-type': 'application/json' },
    })).status()).toBe(401);

    const { items } = await (await anonymous('/api/wants')).json();
    expect(items.some(i => i.name === 'ZZ Nope')).toBe(false);
  });

  test('an entry keeps only known fields, and only Scryfall URLs', async ({ page }) => {
    const name = uniq(test.info(), 'sanitize');
    added.push(name);
    const res = await api(page, '/api/wants', 'POST', {
      name, list: 'nonsense', count: 500, id: 'chosen-by-me', evil: 'x',
      image: 'https://example.com/tracker.gif',
      scryfall_uri: 'javascript:alert(1)',
    });
    const { item } = await res.json();

    expect(item.list).toBe('want');       // unknown list falls back
    expect(item.count).toBe(99);          // clamped
    expect(item.id).not.toBe('chosen-by-me');
    expect(item.image).toBe('');          // not a Scryfall host
    expect(item.scryfall_uri).toBe('');
    expect(item.evil).toBeUndefined();
  });

  test('a nameless entry is rejected and a missing one is a 404', async ({ page }) => {
    expect((await api(page, '/api/wants', 'POST', { name: '   ' })).status()).toBe(400);
    expect((await api(page, '/api/wants/nope', 'PATCH', { count: 2 })).status()).toBe(404);
    expect((await api(page, '/api/wants/nope', 'DELETE')).status()).toBe(404);
  });
});
