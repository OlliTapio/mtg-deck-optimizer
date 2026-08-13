// Functional tests for the deck site, run on an iPhone 11 viewport (the size the
// stacked-card interaction is designed for) plus a desktop one.
//
//   npm test            # starts the preview server itself, see playwright.config.mjs
import { test, expect, devices } from '@playwright/test';

// Scope to one stack: card indices across the whole board would silently span
// two columns if a deck's first group were short, making position tests vacuous.
const cards = page => page.locator('.stack.stacked').nth(1).locator('.card');
const deckData = async (page) => {
  const slug = await page.evaluate(() => location.hash.slice(1));
  return (await page.request.get(`/data/${slug}.json`)).json();
};
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

// Collected from before navigation, so load-time failures are caught too.
let pageErrors;

test.beforeEach(async ({ page }) => {
  pageErrors = [];
  page.on('pageerror', e => pageErrors.push(String(e)));
  await page.goto('/');
  await expect(page.locator('.card').first()).toBeVisible();
});

test.afterEach(() => {
  expect(pageErrors).toEqual([]);
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
    const names = await group.locator('.hit').evaluateAll(
      els => els.map(e => e.title.split(' — ')[0]));
    const data = await deckData(page);
    const cmcOf = name => (data.cards.find(c => c.name === name) || {}).cmc ?? 0;
    const cmcs = names.map(cmcOf);
    expect(cmcs).toEqual([...cmcs].sort((a, b) => a - b));
  });

  test('group-by-category uses the categories in the deck data', async ({ page }) => {
    const data = await deckData(page);
    const expected = new Set(data.cards.map(c => c.category).concat('Commander'));

    await page.selectOption('#group', 'category');

    const headings = (await page.locator('.cat h2').allInnerTexts())
      .map(t => t.replace(/\s*\(\d+\)\s*$/, '').trim());
    expect(headings.length).toBe(expected.size);
    for (const h of headings) expect(expected.has(h)).toBe(true);
  });

  test('switching deck loads that deck', async ({ page }) => {
    const other = await page.locator('#deck option').nth(1).getAttribute('value');

    await page.selectOption('#deck', other);
    await expect(page.locator('.card').first()).toBeVisible();

    expect(new URL(page.url()).hash).toBe(`#${other}`);
    const data = await deckData(page);
    expect(data.slug).toBe(other);
    await expect(page.locator('#count')).toHaveText(`${data.total} cards`);
    await expect(page.locator('.cat').first()).toContainText('Commander');
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

  // Cards are drawn in document order and nothing may lift one out of it: a
  // tap leaves :hover behind on a touch screen, so a rule raising the card
  // being tapped outlives the tap, and the closed card goes on covering the
  // slivers of the cards after it — which reads as "closing did nothing".
  // Opening makes room for the whole card, so no card ever needs raising.
  test('no card is painted out of stack order, open or closed', async ({ page }) => {
    const zIndexes = () => cards(page).evaluateAll(
      els => els.map(el => getComputedStyle(el).zIndex));
    const card = cards(page).nth(4);
    await card.locator('.hit').scrollIntoViewIfNeeded();

    await card.locator('.hit').click();
    await expect(card).toHaveClass(/open/);
    expect(new Set(await zIndexes())).toEqual(new Set(['auto']));

    await card.locator('.hit').click();
    await expect(card).not.toHaveClass(/open/);
    expect(new Set(await zIndexes())).toEqual(new Set(['auto']));

    // And the card it covered before opening is back to its own sliver.
    expect(await visibleHeight(cards(page).nth(5)))
      .toBe(await visibleHeight(cards(page).nth(6)));
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

  test('a tap on a covered area belongs to the card drawn on top', async ({ page }) => {
    const card = cards(page).nth(3);
    const next = cards(page).nth(4);
    await card.locator('.hit').scrollIntoViewIfNeeded();

    // 60% down card 3 is covered by the cards stacked over it.
    const box = await card.boundingBox();
    await page.mouse.click(box.x + box.width / 2, box.y + box.height * 0.6);

    await expect(card).not.toHaveClass(/open/);
    const openCount = await cards(page).locator('.open').count()
      + await page.locator('.card.open').count();
    expect(openCount).toBeGreaterThan(0);   // some later card took the tap
    expect(await next.evaluate(el => el.classList.contains('open'))
      || await cards(page).nth(5).evaluate(el => el.classList.contains('open'))
      || await cards(page).nth(6).evaluate(el => el.classList.contains('open'))).toBe(true);
  });

  test('the tappable strip is exactly the part of the card you can see', async ({ page }) => {
    const card = cards(page).nth(2);
    await card.locator('.hit').scrollIntoViewIfNeeded();

    const hitHeight = await card.locator('.hit')
      .evaluate(el => Math.round(el.getBoundingClientRect().height));
    expect(Math.abs(hitHeight - await visibleHeight(card))).toBeLessThanOrEqual(2);

    // The last card in a stack is fully visible, so all of it is tappable.
    const last = cards(page).last();
    await last.locator('.hit').scrollIntoViewIfNeeded();
    const lastHit = await last.locator('.hit')
      .evaluate(el => Math.round(el.getBoundingClientRect().height));
    expect(lastHit).toBeGreaterThanOrEqual(await fullHeight(last) - 2);
  });

  test('cards are reachable and openable by keyboard', async ({ page }) => {
    const card = cards(page).nth(1);
    await card.locator('.hit').focus();
    await expect(card.locator('.hit')).toHaveAttribute('aria-expanded', 'false');

    await page.keyboard.press('Enter');

    await expect(card).toHaveClass(/open/);
    await expect(card.locator('.hit')).toHaveAttribute('aria-expanded', 'true');

    // Tab moves to the details button of the open card, which opens the dialog
    // and returns focus when closed.
    await page.keyboard.press('Tab');
    await expect(card.locator('.info')).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.locator('#preview')).toHaveClass(/open/);
    await page.keyboard.press('Escape');
    await expect(page.locator('#preview')).not.toHaveClass(/open/);
    await expect(card.locator('.info')).toBeFocused();
  });

  test('switching tabs keeps the open cards and the board as it was', async ({ page }) => {
    const card = cards(page).nth(3);
    await card.locator('.hit').scrollIntoViewIfNeeded();
    await card.locator('.hit').click();
    const cardTop = await topOf(card);

    await page.locator('#tab-stats').click();
    await page.locator('#tab-cards').click();

    await expect(card).toHaveClass(/open/);
    expect(await topOf(card)).toBeCloseTo(cardTop, 0);
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
    expect(titles).toContain('mana');
    const mana = (await page.locator('.mana-line .head b').allInnerTexts()).join(' ').toLowerCase();
    expect(mana).toContain('mana symbols');
    expect(mana).toContain('mana production');
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

  test('mana is one stacked bar per question, split by colour', async ({ page }) => {
    const data = await deckData(page);
    await page.locator('#tab-stats').click();

    const lines = page.locator('.mana-line');
    await expect(lines).toHaveCount(2);
    for (const [i, counts] of [data.mana_symbols, data.mana_production].entries()) {
      const colours = Object.entries(counts).filter(([, n]) => n);
      const total = colours.reduce((n, [, v]) => n + v, 0);
      const line = lines.nth(i);
      // One bar with one segment per colour in the deck, widths summing to 100%.
      await expect(line.locator('.mana-bar')).toHaveCount(1);
      const widths = await line.locator('.mana-bar > span')
        .evaluateAll(els => els.map(e => parseFloat(e.style.width)));
      expect(widths.length).toBe(colours.length);
      expect(widths.reduce((a, b) => a + b, 0)).toBeCloseTo(100, 2);
      await expect(line.locator('.head')).toContainText(String(total));
      for (const [c, n] of colours) {
        await expect(line.locator('.legend > span', { hasText: String(n) }).first())
          .toBeVisible();
        await expect(line.locator(`.mana-bar > span.${c}`)).toHaveCount(1);
      }
    }
  });

  test('template check matches the deck data', async ({ page }) => {
    // Via the page's own origin: a hard-coded port picks up whatever server
    // happens to be running there, which is a different bundle or no JSON at all.
    const data = await deckData(page);
    await page.locator('#tab-stats').click();

    const section = page.locator('.stats section', { hasText: 'Template check' });
    for (const row of data.stats.template) {
      await expect(section).toContainText(`${row.count}/${row.target}`);
    }
  });

  test('the land row counts modal cards with a land back, unlike the Land column', async ({ page }) => {
    const data = await deckData(page);
    const landColumn = data.cards.filter(c => c.type === 'Land')
      .reduce((n, c) => n + c.count, 0);
    const landDrops = data.cards.filter(c => c.is_land)
      .reduce((n, c) => n + c.count, 0);
    expect(landDrops).toBeGreaterThanOrEqual(landColumn);

    const heading = await page.locator('.cat h2', { hasText: 'Land' }).last().innerText();
    expect(Number(heading.replace(/\D/g, ''))).toBe(landColumn);

    await page.locator('#tab-stats').click();
    await expect(page.locator('.stats section', { hasText: 'Template check' }))
      .toContainText(`${landDrops}/38`);
  });

  test('otag, type and curve numbers match the deck data', async ({ page }) => {
    const data = await deckData(page);
    await page.locator('#tab-stats').click();

    const otags = page.locator('.stats section', { hasText: 'otags' });
    for (const [tag, n] of Object.entries(data.stats.otags).slice(0, 5)) {
      await expect(otags.locator('.stat-row', { hasText: tag }).first()).toContainText(String(n));
    }
    const types = page.locator('.stats section', { hasText: 'Card types' });
    for (const [type, n] of Object.entries(data.stats.types)) {
      await expect(types.locator('.stat-row', { hasText: type }).first()).toContainText(String(n));
    }
    await expect(page.locator('.stats section', { hasText: 'Mana curve' }))
      .toContainText(`avg ${data.stats.avg_cmc}`);
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

  test('card images actually decode', async ({ page }) => {
    // Lazy images are never "complete" on first paint, so force a sample and
    // wait for it — otherwise the assertion is empty by construction.
    const result = await page.evaluate(async () => {
      const imgs = [...document.querySelectorAll('.card img')].slice(0, 8);
      const broken = [];
      await Promise.all(imgs.map(i => i.decode().catch(() => broken.push(i.alt))));
      return {tried: imgs.length, broken};
    });
    expect(result.tried).toBeGreaterThan(0);
    expect(result.broken).toEqual([]);
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
