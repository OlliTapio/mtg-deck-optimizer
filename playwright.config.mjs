// Playwright config for the deck site tests (web/tests). It serves the built
// bundle in web/public itself, so `npm test` needs no other terminal.
import { defineConfig, devices } from '@playwright/test';

const PORT = 8000;

export default defineConfig({
  testDir: './web/tests',
  fullyParallel: true,
  reporter: process.env.CI ? 'line' : [['list']],
  use: { baseURL: `http://127.0.0.1:${PORT}` },
  projects: [
    // The stacked-card interaction is designed for a phone; check a desktop
    // viewport too so the grid/columns don't regress.
    { name: 'iphone-11', use: { ...devices['iPhone 11'] } },
    { name: 'desktop', use: { viewport: { width: 1440, height: 900 } } },
  ],
  webServer: {
    command: `python3 -m http.server --directory web/public ${PORT}`,
    url: `http://127.0.0.1:${PORT}/data/index.json`,
    reuseExistingServer: true,
  },
});
