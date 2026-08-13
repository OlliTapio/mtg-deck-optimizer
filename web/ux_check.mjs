// UX pass over the deck site on an iPhone 11 viewport, plus a desktop sanity
// check. Screenshots land in .playwright/ (gitignored).
//
//   npm run preview &            # serves web/public on :8000
//   npm run ux                   # or: node web/ux_check.mjs <base-url> <out-dir>
//
// Exits non-zero if it finds an issue, so it can gate a deploy.
import { chromium, devices } from 'playwright';

const BASE = process.argv[2] || 'http://127.0.0.1:8000';
const OUT = process.argv[3] || '.playwright';
const issues = [];
const note = (s) => { issues.push(s); console.log('ISSUE: ' + s); };

const browser = await chromium.launch();
const ctx = await browser.newContext({ ...devices['iPhone 11'] });
const page = await ctx.newPage();
page.on('console', m => { if (m.type() === 'error') note(`console error: ${m.text()}`); });
page.on('pageerror', e => note(`page error: ${e.message}`));
page.on('requestfailed', r => note(`request failed: ${r.url()} ${r.failure()?.errorText}`));

await page.goto(BASE, { waitUntil: 'networkidle' });
console.log('viewport', page.viewportSize());

// Horizontal overflow check
const overflow = await page.evaluate(() =>
  ({ doc: document.documentElement.scrollWidth, win: window.innerWidth }));
if (overflow.doc > overflow.win + 1) note(`body scrolls horizontally: ${overflow.doc} > ${overflow.win}`);

// Header/tap target sizes
const small = await page.evaluate(() => {
  const out = [];
  for (const el of document.querySelectorAll('button, select, input')) {
    // a checkbox inside a label is tapped via the label, so measure that
    const target = el.closest('label') || el;
    const r = target.getBoundingClientRect();
    if (r.height < 32) out.push(`${el.id || el.tagName} ${Math.round(r.width)}x${Math.round(r.height)}`);
  }
  return out;
});
small.forEach(s => note(`tap target under 32px tall: ${s}`));

await page.screenshot({ path: `${OUT}/ux-1-cards.png`, fullPage: false });

// Column count + how much of each stacked card is visible
const layout = await page.evaluate(() => {
  const cols = document.querySelectorAll('.cat');
  // measure inside one stack that actually has several cards
  const stack = [...document.querySelectorAll('.stack.stacked')]
    .sort((x, y) => y.children.length - x.children.length)[0];
  const cards = stack ? stack.children : [];
  const a = cards[0]?.getBoundingClientRect(), b = cards[1]?.getBoundingClientRect();
  return {
    columns: cols.length,
    firstColWidth: Math.round(cols[0]?.getBoundingClientRect().width || 0),
    cardWidth: Math.round(a?.width || 0),
    cardHeight: Math.round(a?.height || 0),
    visibleSliver: a && b ? Math.round(b.top - a.top) : null,
    imagesLoaded: [...document.querySelectorAll('.card img')].filter(i => i.naturalWidth > 0).length,
    imagesTotal: document.querySelectorAll('.card img').length,
  };
});
console.log('layout', layout);
if (layout.visibleSliver !== null && layout.visibleSliver < 26)
  note(`stacked sliver only ${layout.visibleSliver}px — card name row is ~28px at this width`);

// Tap a card in the middle of a stack, check the overlay, tap again to close,
// and confirm the page did not scroll.
const mid = page.locator('.stack.stacked .card').nth(4).locator('.hit');
await mid.scrollIntoViewIfNeeded();
const scrollBefore = await page.evaluate(() => window.scrollY);
const midName = await mid.getAttribute('title');
await mid.click();
const shown = await page.locator('#preview .text b').textContent();
if (!shown.startsWith(midName)) note(`tapped ${midName} but preview showed ${shown}`);
const opened = await page.locator('#preview.open').count();
if (!opened) note('tapping a card did not open the preview');
await page.screenshot({ path: `${OUT}/ux-2-preview.png` });
await page.locator('#preview').click({ position: { x: 10, y: 10 } });
if (await page.locator('#preview.open').count()) note('tapping the overlay did not close the preview');
// Second tap on the same card should open then close again
await mid.click();
await page.locator('#preview .sheet').click({ position: { x: 5, y: 5 } });
if (await page.locator('#preview.open').count()) note('tapping the open card again did not close it');
const scrollAfter = await page.evaluate(() => window.scrollY);
if (Math.abs(scrollAfter - scrollBefore) > 2)
  note(`scroll position moved on open/close: ${scrollBefore} -> ${scrollAfter}`);

// Stats tab
await page.locator('#tab-stats').click();
await page.waitForTimeout(150);
const stats = await page.evaluate(() => ({
  sections: [...document.querySelectorAll('.stats h3')].map(h => h.textContent),
  cardsHidden: document.getElementById('board').hidden,
  boardPainted: getComputedStyle(document.getElementById('board')).display !== 'none',
  overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
}));
console.log('stats', stats);
if (!stats.cardsHidden) note('card board still visible on the Stats tab');
if (stats.boardPainted) note('card board still painted on the Stats tab (hidden attr overridden by CSS)');
if (stats.overflow) note('Stats tab scrolls horizontally');
await page.screenshot({ path: `${OUT}/ux-3-stats.png`, fullPage: true });

// Deck switching keeps the tab, and drafts toggle works
await page.locator('#tab-cards').click();
await page.selectOption('#deck', { index: 1 });
await page.waitForTimeout(250);
if (!(await page.locator('.card').count())) note('no cards rendered after switching deck');
await page.locator('#drafts').check();
await page.waitForTimeout(150);
const draftOptions = await page.locator('#deck option').count();
console.log('deck options with drafts', draftOptions);

// Grid (unstacked) mode
await page.locator('#stacked').uncheck();
await page.waitForTimeout(200);
await page.screenshot({ path: `${OUT}/ux-4-grid.png` });

// Desktop sanity check
const desk = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const dp = await desk.newPage();
await dp.goto(BASE, { waitUntil: 'networkidle' });
await dp.screenshot({ path: `${OUT}/ux-5-desktop.png` });
await dp.locator('#tab-stats').click();
await dp.waitForTimeout(200);
await dp.screenshot({ path: `${OUT}/ux-6-desktop-stats.png`, fullPage: true });

console.log(`\n${issues.length} issue(s)`);
await browser.close();
process.exit(issues.length ? 1 : 0);
