// Functional tests for the deck site, run on an iPhone 11 viewport (the size the
// stacked-card interaction is designed for) plus a desktop one.
//
//   npm test            # starts the preview server itself, see playwright.config.mjs
import { test, expect, devices } from '@playwright/test';

const cards = page => page.locator('.stack.stacked .card');
// Position within the document, not the viewport: clicking may scroll the
// element into view, and what matters is that the layout doesn't shift.
const topOf = loc => loc.evaluate(el => el.getBoundingClientRect().top + window.scrollY);
// How much of a card the reader can see: the gap to the next card, or, for the
// last one in a stack, its own height.
const visibleHeight = loc => loc.evaluate(el => {
  const next = el.nextElementSibling;
  const rect = el.getBoundingClientRect();
  return Math.round(next ? next.getBoundingClientRect().top - rect.top : rect.height);
});
const fullHeight = loc => loc.evaluate(el => Math.round(el.getBoundingClientRect().height));

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('.card').first()).toBeVisible();
});

test.describe('deck view', () => {
  test('renders the selected deck grouped with Commander first and Land last', async ({ page }) => {
    const headings = await page.locator('.cat h2').allInnerTexts();
    expect(headings[0]).toContain('Commander');
    expect(headings[headings.length - 1]).toContain('Land');

    // The counts in the headings add up to the deck size in the header.
    const total = (await page.locator('.cat h2 span').allInnerTexts())
      .reduce((sum, t) => sum + Number(t.replace(/\D/g, '')), 0);
    await expect(page.locator('#count')).toHaveText(`${total} cards`);
  });

  test('cards in a group are ordered by mana cost', async ({ page }) => {
    const group = page.locator('.cat', { hasText: 'Creature' }).first();
    const names = await group.locator('.hit').evaluateAll(els => els.map(e => e.title));
    const deck = await page.evaluate(() => window.location.hash.slice(1));
    const data = await (await fetch(`http://127.0.0.1:8000/data/${deck}.json`)).json();
    const cmcOf = name => (data.cards.find(c => c.name === name) || {}).cmc ?? 0;
    const cmcs = names.map(cmcOf);
    expect(cmcs).toEqual([...cmcs].sort((a, b) => a - b));
  });

  test('group-by-category uses the decklist tags', async ({ page }) => {
    await page.selectOption('#group', 'category');
    const headings = await page.locator('.cat h2').allInnerTexts();
    expect(headings.join(' ')).toMatch(/Ramp|Removal|Draw|Counters/);
  });

  test('switching deck loads the other deck', async ({ page }) => {
    const first = await page.locator('#count').innerText();
    await page.selectOption('#deck', { index: 1 });
    await expect(page.locator('.card').first()).toBeVisible();
    expect(page.url()).toContain('#');
    expect(await page.locator('.cat').count()).toBeGreaterThan(0);
    expect(await page.locator('#count').innerText()).toBeTruthy();
    expect(first).toBeTruthy();
  });

  test('drafts are hidden until asked for', async ({ page }) => {
    const built = await page.locator('#deck option').count();
    await page.locator('#drafts').check();
    const withDrafts = await page.locator('#deck option').count();
    expect(withDrafts).toBeGreaterThan(built);
    expect((await page.locator('#deck option').allInnerTexts()).some(t => t.includes('draft')))
      .toBe(true);
  });

  test('a deck whose data is missing reports itself instead of showing the previous one', async ({ page }) => {
    const other = await page.locator('#deck option').nth(1).getAttribute('value');
    await page.route(`**/data/${other}.json`, route => route.fulfill({ status: 404 }));

    await page.selectOption('#deck', other);

    await expect(page.locator('#empty')).toContainText(`No data for ${other}`);
    await expect(page.locator('.card')).toHaveCount(0);
    // A layout toggle must not bring the previous deck back.
    await page.locator('#stacked').uncheck();
    await expect(page.locator('.card')).toHaveCount(0);
  });
});

test.describe('stacked cards', () => {
  test('opening a card reveals it fully and pushes the following cards down', async ({ page }) => {
    const card = cards(page).nth(4);
    const next = cards(page).nth(5);
    await card.locator('.hit').scrollIntoViewIfNeeded();

    const cardTop = await topOf(card);
    const nextTop = await topOf(next);
    const sliver = await visibleHeight(card);
    expect(sliver).toBeLessThan(await fullHeight(card));

    await card.locator('.hit').click();

    await expect(card).toHaveClass(/open/);
    expect(await visibleHeight(card)).toBeGreaterThanOrEqual(await fullHeight(card) - 2);
    expect(await topOf(next)).toBeGreaterThan(nextTop);   // pushed down
    expect(await topOf(card)).toBeCloseTo(cardTop, 0);    // itself stayed put
  });

  test('tapping the open card closes the stack back up', async ({ page }) => {
    const card = cards(page).nth(4);
    await card.locator('.hit').scrollIntoViewIfNeeded();
    const cardTop = await topOf(card);
    const sliver = await visibleHeight(card);

    await card.locator('.hit').click();
    await card.locator('.hit').click();

    await expect(card).not.toHaveClass(/open/);
    expect(await visibleHeight(card)).toBe(sliver);
    expect(await topOf(card)).toBeCloseTo(cardTop, 0);
  });

  test('opening a card keeps the position of the cards above it', async ({ page }) => {
    const above = cards(page).nth(2);
    const below = cards(page).nth(6);
    await below.locator('.hit').scrollIntoViewIfNeeded();

    await above.locator('.hit').click();          // one card already open above
    const aboveTop = await topOf(above);
    const belowTop = await topOf(below);

    await below.locator('.hit').click();

    expect(await topOf(above)).toBeCloseTo(aboveTop, 0);
    expect(await topOf(below)).toBeCloseTo(belowTop, 0);
    await expect(above).toHaveClass(/open/);      // toggling is per card
  });

  test('a tap hits the card whose strip you touched, not the one on top of it', async ({ page }) => {
    const card = cards(page).nth(3);
    const name = await card.locator('.hit').getAttribute('title');
    await card.locator('.hit').scrollIntoViewIfNeeded();

    // Tap the visible strip; the next card covers this card's centre.
    await card.locator('.hit').click();

    await expect(card).toHaveClass(/open/);
    await card.locator('.info').click();
    await expect(page.locator('#preview .text b')).toContainText(name);
  });

  test('card details open from the info button and close on tap or Escape', async ({ page }) => {
    const card = cards(page).nth(4);
    await card.locator('.hit').scrollIntoViewIfNeeded();
    await card.locator('.hit').click();

    await card.locator('.info').click();
    await expect(page.locator('#preview')).toHaveClass(/open/);
    await expect(page.locator('#preview .sheet').locator('img, .missing').first())
      .toBeVisible();

    await page.locator('#preview').click({ position: { x: 8, y: 8 } });
    await expect(page.locator('#preview')).not.toHaveClass(/open/);

    await card.locator('.info').click();
    await page.keyboard.press('Escape');
    await expect(page.locator('#preview')).not.toHaveClass(/open/);
  });

  test('unstacking lays the cards out as a grid', async ({ page }) => {
    await page.locator('#stacked').uncheck();
    const card = page.locator('.stack .card').first();
    expect(await visibleHeight(card)).toBeGreaterThanOrEqual(await fullHeight(card));
  });
});

test.describe('stats tab', () => {
  test('shows mana, template, otag, type and curve sections', async ({ page }) => {
    await page.locator('#tab-stats').click();

    const titles = (await page.locator('.stats h3').allInnerTexts()).join(' ').toLowerCase();
    expect(titles).toContain('mana symbols');
    expect(titles).toContain('mana production');
    expect(titles).toContain('template check');
    expect(titles).toContain('otags');
    expect(titles).toContain('card types');
    expect(titles).toContain('mana curve');
    await expect(page.locator('.stats')).toContainText('removal');
  });

  test('hides the card board', async ({ page }) => {
    await page.locator('#tab-stats').click();
    await expect(page.locator('#board')).toBeHidden();
    await page.locator('#tab-cards').click();
    await expect(page.locator('#board')).toBeVisible();
    await expect(page.locator('#stats')).toBeHidden();
  });

  test('template check matches the deck data', async ({ page }) => {
    const slug = await page.evaluate(() => location.hash.slice(1));
    const data = await (await fetch(`http://127.0.0.1:8000/data/${slug}.json`)).json();
    await page.locator('#tab-stats').click();

    const section = page.locator('.stats section', { hasText: 'Template check' });
    for (const row of data.stats.template) {
      await expect(section).toContainText(`${row.count}/${row.target}`);
    }
  });

  test('land count in the template check equals the Land column', async ({ page }) => {
    const landHeading = await page.locator('.cat h2', { hasText: 'Land' }).last().innerText();
    const lands = Number(landHeading.replace(/\D/g, ''));
    await page.locator('#tab-stats').click();
    await expect(page.locator('.stats section', { hasText: 'Template check' }))
      .toContainText(`${lands}/38`);
  });
});

test.describe('layout', () => {
  test('never scrolls horizontally', async ({ page }) => {
    for (const tab of ['#tab-cards', '#tab-stats']) {
      await page.locator(tab).click();
      const overflow = await page.evaluate(() =>
        document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow).toBeLessThanOrEqual(1);
    }
  });

  test('controls are comfortable tap targets', async ({ page }) => {
    const small = await page.evaluate(() => {
      const out = [];
      for (const el of document.querySelectorAll('header button, header select, header input')) {
        const target = el.closest('label') || el;
        const r = target.getBoundingClientRect();
        if (r.width && r.height && r.height < 32) out.push(`${el.id || el.tagName}:${r.height}`);
      }
      return out;
    });
    expect(small).toEqual([]);
  });

  test('every card image loads', async ({ page }) => {
    const broken = await page.evaluate(() =>
      [...document.querySelectorAll('.card img')]
        .filter(i => i.complete && i.naturalWidth === 0).map(i => i.alt));
    expect(broken).toEqual([]);
    expect(await page.locator('.missing').count()).toBe(0);
  });
});

// Screenshots for eyeballing the layout after a change; they also fail the run
// if a page throws or a request dies while they're being taken.
test.describe('screenshots', () => {
  test('capture cards, an open card, details and stats', async ({ page }, testInfo) => {
    const dir = `.playwright/${testInfo.project.name}`;
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    page.on('requestfailed', r => errors.push(`${r.url()} ${r.failure()?.errorText}`));

    // Lazy images decode after load; without this the shots come out blank.
    await page.evaluate(() => Promise.all(
      [...document.querySelectorAll('.card img')].slice(0, 12).map(i => i.decode())));
    await page.screenshot({ path: `${dir}/cards.png` });

    const card = cards(page).nth(4);
    await card.locator('.hit').scrollIntoViewIfNeeded();
    await card.locator('.hit').click();
    await page.screenshot({ path: `${dir}/card-open.png` });

    await card.locator('.info').click();
    await page.screenshot({ path: `${dir}/card-details.png` });
    await page.locator('#preview').click({ position: { x: 8, y: 8 } });

    await page.locator('#tab-stats').click();
    await page.screenshot({ path: `${dir}/stats.png`, fullPage: true });

    expect(errors).toEqual([]);
  });
});
