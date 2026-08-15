// Playwright config for the deck site tests (web/tests). It serves the built
// bundle in web/public itself, so `npm test` needs no other terminal.
import { defineConfig, devices } from '@playwright/test';

// Distinct from the plain `npm run preview` port so a stale server in another
// git worktree can't serve a different bundle to the suite.
const PORT = 8321;

export default defineConfig({
  testDir: './web/tests',
  fullyParallel: true,
  reporter: process.env.CI ? 'line' : [['list']],
  use: { baseURL: `http://127.0.0.1:${PORT}` },
  projects: [
    // The stacked-card interaction is designed for a phone; check a desktop
    // viewport too so the grid/columns don't regress.
    { name: 'iphone-11', use: { ...devices['iPhone 11'] } },
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
  ],
  webServer: {
    // devserver.py, not a plain file server: the wants & trades tab needs the
    // /api/* routes, and the suite should exercise the ones the site talks to.
    command: `python3 web/devserver.py ${PORT}`,
    url: `http://127.0.0.1:${PORT}/data/index.json`,
    reuseExistingServer: !process.env.CI,
    env: {
      // Never the real web/wants.local.json: the wants tests add and remove rows.
      WANTS_STORE: '.playwright/wants.test.json',
      EDIT_PASSWORD: 'test-password',
    },
  },
});
