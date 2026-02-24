#!/usr/bin/env node
/**
 * Playwright UI test suite for amux dashboard.
 * Usage: node tests/browser-comparison.js
 *
 * Requires: npm install (installs playwright from local package.json)
 * Auth profile: ~/.amux/playwright-auth/profile (run `amux playwright-auth capture`)
 */

const { chromium } = require('playwright');
const { writeFileSync } = require('fs');
const { homedir } = require('os');

const BASE = 'https://localhost:8822';
const PROFILE = `${homedir()}/.amux/playwright-auth/profile`;
const RESULTS_FILE = '/tmp/pw-test-results.json';

const results = [];

function record(name, pass, ms, detail = '') {
  results.push({ name, pass, ms, detail });
  const icon = pass ? '✓' : '✗';
  console.log(`  ${icon} ${name} (${ms}ms)${detail ? ' — ' + detail : ''}`);
}

async function run() {
  const t0 = Date.now();
  console.log('\n══ amux Playwright UI Tests ══\n');

  const ctx = await chromium.launchPersistentContext(PROFILE, {
    headless: true,
    viewport: { width: 1440, height: 900 },
    ignoreHTTPSErrors: true,
  });
  const page = await ctx.newPage();

  // ── 1: Navigate ──
  {
    const t = Date.now();
    try {
      await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 10000 });
      await page.waitForTimeout(2000);
      const title = await page.title();
      record('Navigate to dashboard', title.includes('amux'), Date.now() - t, `title="${title}"`);
    } catch (e) { record('Navigate to dashboard', false, Date.now() - t, e.message); }
  }

  // ── 2: Screenshot ──
  {
    const t = Date.now();
    try {
      await page.screenshot({ path: '/tmp/pw-test-screenshot.png' });
      record('Take screenshot', true, Date.now() - t);
    } catch (e) { record('Take screenshot', false, Date.now() - t, e.message); }
  }

  // ── 3: Session cards ──
  {
    const t = Date.now();
    try {
      const count = await page.$$eval('.card', cards => cards.length);
      record('Count session cards', count > 0, Date.now() - t, `${count} cards`);
    } catch (e) { record('Count session cards', false, Date.now() - t, e.message); }
  }

  // ── 4: Read names ──
  {
    const t = Date.now();
    try {
      const names = await page.$$eval('.card-name', els => els.map(e => e.textContent.trim()).slice(0, 5));
      record('Read session names', names.length > 0, Date.now() - t, names.join(', '));
    } catch (e) { record('Read session names', false, Date.now() - t, e.message); }
  }

  // ── 5: Board tab ──
  {
    const t = Date.now();
    try {
      await page.click('button#tab-board');
      await page.waitForTimeout(800);
      const active = await page.$eval('#tab-board', el => el.classList.contains('active'));
      record('Click Board tab', active, Date.now() - t);
    } catch (e) { record('Click Board tab', false, Date.now() - t, e.message); }
  }

  // ── 6: Board columns (wait for render) ──
  {
    const t = Date.now();
    try {
      // Switch to status (column) view, fetch data, then render
      await page.evaluate(async () => {
        boardViewMode = 'status';
        await fetchBoard();
        renderBoard();
      });
      await page.waitForSelector('.board-col-header', { timeout: 5000 });
      const cols = await page.$$eval('.board-col-header', els => els.map(e => e.textContent.trim()));
      record('Read board columns', cols.length > 0, Date.now() - t, cols.join(', '));
    } catch (e) { record('Read board columns', false, Date.now() - t, e.message); }
  }

  // ── 7: Calendar tab ──
  {
    const t = Date.now();
    try {
      await page.click('button#tab-calendar');
      await page.waitForTimeout(500);
      const active = await page.$eval('#tab-calendar', el => el.classList.contains('active'));
      record('Switch to Calendar tab', active, Date.now() - t);
    } catch (e) { record('Switch to Calendar tab', false, Date.now() - t, e.message); }
  }

  // ── 8: Toggle light mode ──
  {
    const t = Date.now();
    try {
      await page.evaluate(() => { localStorage.setItem('amux_theme', 'light'); document.body.classList.add('light'); });
      const isLight = await page.evaluate(() => document.body.classList.contains('light'));
      record('Toggle light mode', isLight, Date.now() - t);
    } catch (e) { record('Toggle light mode', false, Date.now() - t, e.message); }
  }

  // ── 9: Light mode screenshot ──
  {
    const t = Date.now();
    try {
      await page.screenshot({ path: '/tmp/pw-test-light.png' });
      record('Light mode screenshot', true, Date.now() - t);
    } catch (e) { record('Light mode screenshot', false, Date.now() - t, e.message); }
  }

  // ── 10: Open peek ──
  {
    const t = Date.now();
    try {
      await page.click('button#tab-sessions');
      await page.waitForTimeout(300);
      // Use first available session from API
      const name = await page.evaluate(async () => {
        const r = await fetch('/api/sessions');
        const s = await r.json();
        return s[0]?.name;
      });
      await page.evaluate((n) => openPeek(n), name);
      await page.waitForTimeout(1000);
      const active = await page.$eval('#peek-overlay', el => el.classList.contains('active'));
      record('Open peek overlay', active, Date.now() - t, `session=${name}`);
    } catch (e) { record('Open peek overlay', false, Date.now() - t, e.message); }
  }

  // ── 11: Read peek content ──
  {
    const t = Date.now();
    try {
      const text = await page.$eval('#peek-body', el => el.textContent.trim().slice(0, 100));
      record('Read peek terminal content', text.length > 0, Date.now() - t, `${text.length} chars`);
    } catch (e) { record('Read peek terminal content', false, Date.now() - t, e.message); }
  }

  // ── 12: Find send input ──
  {
    const t = Date.now();
    try {
      const visible = await page.$eval('#peek-cmd-input', el => el.offsetParent !== null);
      record('Find send input in peek', visible, Date.now() - t);
    } catch (e) { record('Find send input in peek', false, Date.now() - t, e.message); }
  }

  // ── 13: Type into input ──
  {
    const t = Date.now();
    try {
      await page.fill('#peek-cmd-input', '/status');
      const val = await page.$eval('#peek-cmd-input', el => el.value);
      record('Type into send input', val === '/status', Date.now() - t, `value="${val}"`);
    } catch (e) { record('Type into send input', false, Date.now() - t, e.message); }
  }

  // ── 14: Close peek ──
  {
    const t = Date.now();
    try {
      await page.evaluate(() => closePeek());
      await page.waitForTimeout(300);
      const active = await page.$eval('#peek-overlay', el => el.classList.contains('active'));
      record('Close peek overlay', !active, Date.now() - t);
    } catch (e) { record('Close peek overlay', false, Date.now() - t, e.message); }
  }

  // ── 15: Workspace tab ──
  {
    const t = Date.now();
    try {
      await page.click('button#tab-grid');
      await page.waitForTimeout(500);
      const active = await page.$eval('#grid-view', el => el.classList.contains('active'));
      record('Open Workspace tab', active, Date.now() - t);
    } catch (e) { record('Open Workspace tab', false, Date.now() - t, e.message); }
  }

  // ── 16: Workspace light bg ──
  {
    const t = Date.now();
    try {
      const bg = await page.$eval('#grid-view', el => getComputedStyle(el).backgroundColor);
      const isDark = bg.includes('10, 13, 18') || bg.includes('0a0d12');
      record('Workspace light bg (not dark)', !isDark, Date.now() - t, `bg=${bg}`);
    } catch (e) { record('Workspace light bg (not dark)', false, Date.now() - t, e.message); }
  }

  // ── 17: Mobile viewport ──
  {
    const t = Date.now();
    try {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.evaluate(() => exitGridMode());
      await page.waitForTimeout(300);
      await page.screenshot({ path: '/tmp/pw-test-mobile.png' });
      const tabsVisible = await page.$eval('#tab-sessions', el => el.offsetParent !== null);
      record('Mobile viewport + tabs visible', tabsVisible, Date.now() - t);
    } catch (e) { record('Mobile viewport + tabs visible', false, Date.now() - t, e.message); }
  }

  // ── 18: Execute JS ──
  {
    const t = Date.now();
    try {
      const ver = await page.evaluate(() => navigator.userAgent);
      record('Execute JS (userAgent)', ver.includes('Headless'), Date.now() - t, ver.slice(0, 60));
    } catch (e) { record('Execute JS (userAgent)', false, Date.now() - t, e.message); }
  }

  // ── 19: API fetch from page ──
  {
    const t = Date.now();
    try {
      const count = await page.evaluate(async () => {
        const r = await fetch('/api/sessions');
        return (await r.json()).length;
      });
      record('Fetch API from page context', count > 0, Date.now() - t, `${count} sessions`);
    } catch (e) { record('Fetch API from page context', false, Date.now() - t, e.message); }
  }

  // ── 20: Aria snapshot (modern Playwright API) ──
  {
    const t = Date.now();
    try {
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.waitForTimeout(200);
      const snap = await page.locator('body').ariaSnapshot();
      record('Aria snapshot', snap.length > 50, Date.now() - t, `${snap.length} chars`);
    } catch (e) { record('Aria snapshot', false, Date.now() - t, e.message); }
  }

  // ── 21: Peek zoom — cmd bar stays visible ──
  {
    const t = Date.now();
    try {
      await page.evaluate(async () => {
        const r = await fetch('/api/sessions');
        const s = await r.json();
        openPeek(s[0]?.name);
      });
      await page.waitForTimeout(1000);
      // Simulate zoom: shrink viewport
      await page.setViewportSize({ width: 1440, height: 400 });
      await page.waitForTimeout(200);
      const cmdBarRect = await page.$eval('.peek-cmd-bar', el => {
        const r = el.getBoundingClientRect();
        return { bottom: r.bottom, viewH: window.innerHeight };
      });
      const visible = cmdBarRect.bottom <= cmdBarRect.viewH;
      record('Peek zoom — cmd bar visible', visible, Date.now() - t, `bottom=${cmdBarRect.bottom} viewH=${cmdBarRect.viewH}`);
      await page.evaluate(() => closePeek());
    } catch (e) { record('Peek zoom — cmd bar visible', false, Date.now() - t, e.message); }
  }

  // ── 22: Dark mode session card preview bg ──
  {
    const t = Date.now();
    try {
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.evaluate(() => { localStorage.setItem('amux_theme', 'dark'); document.body.classList.remove('light'); });
      await page.waitForTimeout(200);
      await page.screenshot({ path: '/tmp/pw-test-dark.png' });
      const bodyBg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
      record('Dark mode body bg', bodyBg.includes('13, 17, 23') || bodyBg.includes('0d1117'), Date.now() - t, `bg=${bodyBg}`);
    } catch (e) { record('Dark mode body bg', false, Date.now() - t, e.message); }
  }

  await ctx.close();

  const totalMs = Date.now() - t0;
  const passed = results.filter(r => r.pass).length;
  const total = results.length;

  console.log(`\n══ Results: ${passed}/${total} passed (${totalMs}ms) ══\n`);
  if (results.filter(r => !r.pass).length) {
    console.log('Failures:');
    results.filter(r => !r.pass).forEach(r => console.log(`  ✗ ${r.name}: ${r.detail}`));
    console.log('');
  }

  writeFileSync(RESULTS_FILE, JSON.stringify({ results, totalMs, passed, failed: total - passed }, null, 2));
  process.exit(total - passed > 0 ? 1 : 0);
}

run().catch(e => {
  console.error('Fatal:', e.message);
  process.exit(1);
});
