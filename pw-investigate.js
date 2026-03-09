const { chromium } = require('playwright');
const { homedir } = require('os');
(async () => {
  const ctx = await chromium.launchPersistentContext(
    `${homedir()}/.amux/playwright-auth/profile`,
    { headless: true, viewport: { width: 1440, height: 900 }, ignoreHTTPSErrors: true }
  );
  const page = await ctx.newPage();
  await page.goto('https://localhost:8822', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);
  await page.click('#tab-files');
  await page.waitForTimeout(1500);
  await page.screenshot({ path: '/tmp/pw-files.png' });
  await ctx.close();
})().catch(console.error);
