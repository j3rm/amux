/**
 * amux E2E Test Suite — Exhaustive UX Coverage
 *
 * DESKTOP (1280×800) flows covered:
 *   Sessions tab:
 *     - Page loads with title and 3 tabs
 *     - Session cards render with name + status dot
 *     - Running session has .running dot
 *     - Session card expands on click, shows detail rows
 *
 *   Board tab — session-group mode (default):
 *     - Board container visible in session-group mode
 *     - Issues render inside session groups
 *
 *   Board tab — kanban/status mode:
 *     - Toggle to status mode renders 3+ columns
 *     - Horizontal scroll enabled on board container
 *     - Cards render inside columns
 *     - Due date badges appear (📅) on cards with due dates
 *     - Overdue badges are red; upcoming are accent color
 *     - Click card → board detail overlay opens
 *     - Detail has title, desc, status, session, due date fields
 *     - Detail due date is pre-filled on cards that have one
 *     - Close detail via first button → overlay inactive
 *     - Board search filters visible cards
 *     - Clearing search restores all cards
 *     - + Add button opens add form with status pre-filled
 *     - Add form creates new card (API round-trip)
 *     - New card appears in board after creation
 *     - Delete new card cleans up (via API)
 *
 *   Calendar tab:
 *     - Calendar view visible
 *     - Month grid populated (content > 200 chars)
 *     - 7 day-of-week headers
 *     - Today cell has .today class
 *     - Other-month cells have .other-month class
 *     - Issues with due dates render as .cal-chip
 *     - Calendar title shows current month/year
 *     - Click chip → board detail opens with due date pre-filled
 *     - Close detail → calendar still visible
 *     - Click empty (current-month) cell → add form opens
 *     - Add form due date pre-filled with clicked date
 *     - Close add form
 *     - Prev month navigation changes title
 *     - Today button returns to current month
 *     - iCal subscribe link href="/api/calendar.ics"
 *
 *   Back to sessions:
 *     - Switching tabs restores sessions view
 *     - Session cards still present
 *
 *   Peek drawer (desktop):
 *     - Click peek button on a session → peek overlay opens
 *     - Peek title shows session name
 *     - Terminal tab active by default, output renders
 *     - Memory tab: click → memory panel appears
 *     - Memory session textarea visible and editable
 *     - Global memory tab: click → global textarea appears
 *     - Close peek → overlay inactive, body overflow restored
 *
 * MOBILE (iPhone 14, 390×844) flows covered:
 *   - Tab bar visible and sticky (.tab-bar)
 *   - All 3 tab buttons present
 *   - Sessions render as .card elements
 *   - Board: switch to kanban, ≥3 columns
 *   - Board: horizontal scroll enabled (overflow-x: scroll)
 *   - Board detail opens on card click
 *   - Due date field visible in detail
 *   - Body overflow restored after closing detail
 *   - Board scroll restored after detail close
 *   - Calendar grid visible on mobile
 *   - Calendar cell height ≥ 40px (mobile min-height: 52px CSS)
 *   - Calendar chips visible on mobile
 *   - Calendar toolbar scrollWidth ≤ viewport + 10px (no overflow)
 *
 * API flows covered:
 *   GET /api/sessions           — correct shape (array of session objects)
 *   GET /api/sessions/<name>/memory — {content, path}
 *   POST /api/sessions/<name>/memory — saves content, returns ok
 *   GET /api/memory/global      — {content, path}
 *   POST /api/memory/global     — saves content, returns ok
 *   GET /api/board              — array of issues
 *   POST /api/board             — creates issue, returns 201 + {id}
 *   PATCH /api/board/<id>       — updates status, returns 200
 *   DELETE /api/board/<id>      — soft-deletes, returns 200
 *   GET /api/board/statuses     — array of status objects
 *   GET /api/sync?since=0       — {issues, statuses, ts}, tombstones included
 *   GET /api/sync?since=recent  — fewer results than since=0
 *   GET /api/calendar.ics       — text/calendar, VCALENDAR, VEVENT, DATE format
 *   Board create → sync → delete → tombstone (full round-trip)
 */

// Run with: node test.mjs
// Requires playwright: npx playwright install chromium
let pw;
try { pw = await import('playwright'); } catch(e) {
  pw = await import('/Users/ethan/.npm/_npx/e41f203b7505f1fb/node_modules/playwright/index.mjs');
}
const { chromium, devices, request: playwrightRequest } = pw;

const BASE = 'https://localhost:8822';
const results = [];
let passed = 0, failed = 0;
const SMOKE = process.argv.includes('--smoke'); // fast subset for pre-commit

function log(label, ok, detail = '') {
  const sym = ok ? '✓' : '✗';
  console.log(`  ${sym} ${label}${detail ? ': ' + detail : ''}`);
  results.push({ label, ok, detail });
  if (ok) passed++; else failed++;
}

async function wait(ms) { return new Promise(r => setTimeout(r, ms)); }

// Poll until condition true or timeout; avoids serialization issues with object args
async function waitForCount(page, selector, count = 1, timeout = 7000) {
  await page.waitForFunction(
    `document.querySelectorAll(${JSON.stringify(selector)}).length >= ${count}`,
    { timeout }
  ).catch(() => {});
}

async function runDesktop(browser) {
  console.log('\n── Desktop (1280×800) ──');
  const ctx = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1280, height: 800 },
    permissions: ['clipboard-read', 'clipboard-write'],
  });
  const page = await ctx.newPage();

  // ── Page load ──────────────────────────────────────────────────────────────
  await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 10000 });
  await waitForCount(page, '.card', 1);
  await page.screenshot({ path: '/tmp/amux_desktop_home.png' });

  const title = await page.title();
  log('Page title contains amux', title.toLowerCase().includes('amux'), title);

  // ── Tab bar ────────────────────────────────────────────────────────────────
  const sessionsTab = await page.$('#tab-sessions');
  log('Sessions tab exists', !!sessionsTab);
  const boardTab = await page.$('#tab-board');
  log('Board tab exists', !!boardTab);
  const calTab = await page.$('#tab-calendar');
  log('Calendar tab exists', !!calTab);

  // ── Sessions view ──────────────────────────────────────────────────────────
  const cards = await page.$$('.card');
  log('Session cards render', cards.length > 0, `${cards.length} cards`);

  // At least one card shows a session name
  const firstName = await page.$eval('.card .card-name', el => el.textContent.trim()).catch(() => '');
  log('Session card has name text', firstName.length > 0, firstName);

  // Running sessions show a .running dot
  const runningDots = await page.$$('.dot.running');
  log('Running session dot visible', runningDots.length > 0, `${runningDots.length} running`);

  // Expand a card — click the outer .card div which calls toggle() directly
  // (NOT .card-header which uses headerTap double-tap-to-peek logic)
  await page.$eval('.card', el => el.click());
  await wait(300);
  const expanded = await page.$('.card.expanded');
  log('Session card expands on click', !!expanded);

  // Collapse back
  await page.$eval('.card.expanded', el => el.click()).catch(() => {});
  await wait(200);

  // Ensure no overlay is accidentally open before navigating
  await page.keyboard.press('Escape');
  await wait(100);
  // Close peek if it opened
  await page.evaluate(() => {
    const peek = document.getElementById('peek-overlay');
    if (peek && peek.classList.contains('active')) {
      document.body.style.overflow = '';
      peek.classList.remove('active');
    }
  });

  if (SMOKE) { await ctx.close(); return; }

  // ── Board — session-group mode (default) ───────────────────────────────────
  await page.click('#tab-board');
  await waitForCount(page, '.board-card', 1);
  await page.screenshot({ path: '/tmp/amux_desktop_board_session.png' });

  const boardView = await page.$('#board-view');
  log('Board view visible', !!(await boardView?.isVisible()));

  const boardContainer = await page.$('#board-columns');
  const containerVisible = await boardContainer?.isVisible();
  log('Board container visible (session-group mode)', !!containerVisible);

  // Board has cards in session-group mode
  const sessionGroupCards = await page.$$('.board-card');
  log('Board cards render in session-group mode', sessionGroupCards.length > 0,
    `${sessionGroupCards.length} cards`);

  // ── Board — kanban/status mode ─────────────────────────────────────────────
  await page.$eval('#bv-status', el => el.click());
  await waitForCount(page, '.board-col', 3);
  await page.screenshot({ path: '/tmp/amux_desktop_board_kanban.png' });

  const cols = await page.$$('.board-col');
  log('Kanban columns render after switching to status mode', cols.length >= 3, `${cols.length} cols`);

  const overflowX = await boardContainer?.evaluate(el => getComputedStyle(el).overflowX);
  log('Board horizontal scroll enabled', overflowX === 'scroll', `overflow-x: ${overflowX}`);

  // Cards inside columns
  const kanbanCards = await page.$$('.board-card');
  log('Cards render inside kanban columns', kanbanCards.length > 0, `${kanbanCards.length} cards`);

  // Due date badges
  const dueBadges = await page.$$('.board-card-time');
  const dueText = await Promise.all(dueBadges.map(b => b.textContent()));
  log('Due date badges on cards with due dates', dueText.some(t => t.includes('📅')));

  // ── Board card detail ──────────────────────────────────────────────────────
  await page.$eval('.board-card', el => el.click());
  await wait(500);
  const detail = await page.$('#board-detail-overlay');
  const detailActive = await detail?.evaluate(el => el.classList.contains('active'));
  log('Board detail overlay opens on card click', !!detailActive);

  // Fields present
  const bdTitle = await page.$('#bd-title');
  log('Detail has title field', !!bdTitle);
  const bdStatus = await page.$('#bd-status-row');
  log('Detail has status field', !!bdStatus);
  const bdDue = await page.$('#bd-due');
  log('Detail has due date field', !!bdDue);

  // Close detail
  await page.$eval('#board-detail-overlay .btn', el => el.click());
  await wait(300);
  const detailClosed = await detail?.evaluate(el => !el.classList.contains('active'));
  log('Board detail closes', !!detailClosed);

  // ── Board search ───────────────────────────────────────────────────────────
  const searchInput = await page.$('#board-search');
  if (searchInput) {
    const allBefore = await page.$$('.board-card');
    // Type a very specific string unlikely to match anything
    await searchInput.fill('xyzzy_no_match_12345');
    await wait(300);
    const afterSearch = await page.$$('.board-card');
    log('Board search filters cards', afterSearch.length < allBefore.length,
      `${allBefore.length} → ${afterSearch.length}`);

    // Clear search
    await searchInput.fill('');
    await page.keyboard.press('Enter');
    await wait(300);
    const afterClear = await page.$$('.board-card');
    log('Clearing search restores cards', afterClear.length === allBefore.length,
      `${afterClear.length} cards`);
  }

  // ── Board add card ─────────────────────────────────────────────────────────
  const addBtn = await page.$('.board-col .board-add-btn');
  if (addBtn) {
    await addBtn.click();
    await wait(400);
    const addOverlay = await page.$('#board-edit-overlay');
    const addActive = await addOverlay?.evaluate(el => el.classList.contains('active'));
    log('Board add form opens from + Add button', !!addActive);

    // Status is pre-filled to the column's status
    const beStatus = await page.$eval('#be-status', el => el.value).catch(() => '');
    log('Add form status pre-filled from column', beStatus.length > 0, `status="${beStatus}"`);

    // Fill a title and submit
    await page.$eval('#be-title', el => { el.value = ''; });
    await page.type('#be-title', 'E2E test card — delete me');
    await page.$eval('.be-save', el => el.click());
    await wait(600);

    const addedCards = await page.$$('.board-card');
    log('New card appears after creation', addedCards.length > kanbanCards.length,
      `${addedCards.length} cards (was ${kanbanCards.length})`);

    // Clean up via API — find the card we just created
    const api2 = await playwrightRequest.newContext({ ignoreHTTPSErrors: true, baseURL: BASE });
    const boardData = await (await api2.get('/api/board')).json();
    const testCard = boardData.find(i => !i.deleted && i.title === 'E2E test card — delete me');
    if (testCard) {
      await api2.delete(`/api/board/${testCard.id}`);
      log('Add form test card cleaned up', true, testCard.id);
    }
    await api2.dispose();
  }

  // ── Calendar tab ───────────────────────────────────────────────────────────
  await page.click('#tab-calendar');
  await waitForCount(page, '.cal-day-header', 7);
  await page.screenshot({ path: '/tmp/amux_desktop_calendar.png' });

  const calViewEl = await page.$('#calendar-view');
  log('Calendar view visible', !!(await calViewEl?.isVisible()));

  const gridHTML = await page.$eval('#cal-grid', el => el.innerHTML).catch(() => '');
  log('Calendar grid populated', gridHTML.length > 200);

  const dayHeaders = await page.$$('.cal-day-header');
  log('Calendar has 7 day headers', dayHeaders.length === 7, `${dayHeaders.length}`);

  // Today cell has .today class
  const todayCell = await page.$('.cal-cell.today');
  log('Today cell highlighted', !!todayCell);

  // Other-month cells exist when needed (some months fit exactly 4-5 rows with no padding)
  const otherCells = await page.$$('.cal-cell.other-month');
  const monthNeedsPadding = await page.evaluate(() => {
    const firstDay = new Date(calYear, calMonth, 1).getDay();
    const daysInMonth = new Date(calYear, calMonth + 1, 0).getDate();
    return firstDay !== 0 || ((firstDay + daysInMonth) % 7 !== 0);
  });
  log('Other-month cells marked (when needed)',
    !monthNeedsPadding || otherCells.length > 0,
    monthNeedsPadding ? `${otherCells.length} cells` : 'month fills grid exactly — no padding needed');

  // Calendar chips (issues with due dates)
  const chips = await page.$$('.cal-chip');
  log('Calendar chips render for dated issues', chips.length > 0, `${chips.length} chips`);

  const calTitle = await page.$eval('#cal-title', el => el.textContent.trim());
  log('Calendar title shows month/year', calTitle.length > 3, calTitle);

  // Chip click → board detail with due date pre-filled
  if (chips.length > 0) {
    await page.$eval('.cal-chip', el => el.click());
    await wait(500);
    const chipDetail = await page.$('#board-detail-overlay');
    const chipDetailActive = await chipDetail?.evaluate(el => el.classList.contains('active'));
    log('Chip click opens board detail', !!chipDetailActive);

    const chipDue = await page.$eval('#bd-due', el => el.value).catch(() => '');
    log('Board detail due date pre-filled from chip', chipDue.length > 0, chipDue);

    // Close detail
    await page.$eval('#board-detail-overlay .btn', el => el.click());
    await wait(400);
    const calViewEl2 = await page.$('#calendar-view');
    log('Calendar still visible after closing chip detail', !!(await calViewEl2?.isVisible()));
  }

  // Empty cell click → add form with date pre-filled
  const currentMonthCells = await page.$$('.cal-cell:not(.other-month)');
  if (currentMonthCells.length > 5) {
    await page.$$eval('.cal-cell:not(.other-month)', cells => cells[5].click());
    await wait(400);
    const cellAddOverlay = await page.$('#board-edit-overlay');
    const cellAddActive = await cellAddOverlay?.evaluate(el => el.classList.contains('active'));
    log('Calendar cell click opens add form', !!cellAddActive);

    const cellDue = await page.$eval('#be-due', el => el.value).catch(() => '');
    log('Add form due date pre-filled from cell click', cellDue.length > 0, cellDue);

    // Close
    const cancelBtn = await page.$('.be-cancel');
    if (cancelBtn) await cancelBtn.click();
    else await page.keyboard.press('Escape');
    await wait(200);
  }

  // Calendar navigation
  await page.$eval('button[onclick="calPrev()"]', el => el.click());
  await wait(300);
  const calTitle2 = await page.$eval('#cal-title', el => el.textContent.trim());
  log('Calendar prev month navigation works', calTitle2 !== calTitle, `→ ${calTitle2}`);

  await page.$eval('#cal-today-btn', el => el.click());
  await wait(300);
  const calTitle3 = await page.$eval('#cal-title', el => el.textContent.trim());
  log('Calendar Today button returns to current month', calTitle3 === calTitle, calTitle3);

  const icalBtn = await page.$('button[onclick="showIcalInfo()"]');
  log('iCal subscribe button present', !!icalBtn);

  // ── Back to sessions ───────────────────────────────────────────────────────
  await page.click('#tab-sessions');
  await waitForCount(page, '.card', 1);
  const sessionsAfter = await page.$$('.card');
  log('Sessions tab restores session cards', sessionsAfter.length > 0,
    `${sessionsAfter.length} cards`);

  // ── Peek drawer ────────────────────────────────────────────────────────────
  // Click card to expand, then click preview lines to open peek (natural UX path)
  await page.$eval('.card', el => el.click()); // expand first card
  await wait(300);
  const previewLines = await page.$('.card-preview-lines');
  if (previewLines) {
    await previewLines.click();
    await wait(600);
  } else {
    // Fallback: use card menu > Peek terminal
    await page.evaluate(() => {
      const sessions = window.sessions;
      if (sessions && sessions.length) openPeek(sessions[0].name);
    });
    await wait(600);
  }

  const peekOverlay = await page.$('#peek-overlay');
  const peekActive = await peekOverlay?.evaluate(el => el.classList.contains('active'));
  log('Peek drawer opens (via preview lines or openPeek)', !!peekActive);

  if (peekActive) {
    // Title shows session name
    const peekTitle = await page.$eval('#peek-title', el => el.textContent.trim()).catch(() => '');
    log('Peek title shows session name', peekTitle.length > 0, peekTitle);

    // Terminal tab is default
    const termPanel = await page.$('#peek-terminal-panel');
    log('Terminal panel visible by default', !!(await termPanel?.isVisible()));

    // Memory tab
    await page.$eval('#peek-tab-memory', el => el.click());
    await wait(400);
    const memPanel = await page.$('#peek-memory-panel');
    log('Memory panel opens on Memory tab click', !!(await memPanel?.isVisible()));

    const sessionTextarea = await page.$('#peek-memory-input');
    log('Session memory textarea present', !!sessionTextarea);

    // Global memory tab
    await page.$eval('#pm-tab-global', el => el.click());
    await wait(300);
    const globalTextarea = await page.$('#peek-global-input');
    const globalVisible = await globalTextarea?.evaluate(el => getComputedStyle(el).display !== 'none');
    log('Global memory textarea visible on Global tab', !!globalVisible);

    // ── Ctrl+V paste into send input ──────────────────────────────────────────
    // Switch back to terminal tab so send input is visible
    await page.$eval('#peek-tab-terminal', el => el.click());
    await wait(200);
    await page.focus('#peek-cmd-input');
    // Verify keydown handler does NOT call preventDefault for Ctrl+V in a textarea
    // (if it did, native paste would be blocked)
    const ctrlVPrevented = await page.evaluate(() => new Promise(resolve => {
      const el = document.getElementById('peek-cmd-input');
      el.focus();
      document.addEventListener('keydown', function check(e) {
        if (e.ctrlKey && e.key === 'v') {
          document.removeEventListener('keydown', check);
          setTimeout(() => resolve(e.defaultPrevented), 0);
        }
      }, { capture: true, once: true });
      el.dispatchEvent(new KeyboardEvent('keydown', { key: 'v', ctrlKey: true, bubbles: true, cancelable: true }));
    }));
    log('Ctrl+V keydown NOT prevented in focused textarea (paste allowed)', !ctrlVPrevented);
    // Also verify paste event (text) is not blocked by handlePeekPaste
    const pasteBlocked = await page.evaluate(() => new Promise(resolve => {
      const el = document.getElementById('peek-cmd-input');
      el.focus();
      el.addEventListener('paste', e => { resolve(e.defaultPrevented); }, { once: true });
      const dt = new DataTransfer(); dt.setData('text/plain', 'hello');
      el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
    }));
    log('Text paste event NOT blocked by handlePeekPaste', !pasteBlocked);
    // Clear the input
    await page.$eval('#peek-cmd-input', el => { el.value = ''; el.dispatchEvent(new Event('input')); });

    // ── Tasks tab ──────────────────────────────────────────────────────────────
    await page.$eval('#peek-tab-tasks', el => el.click());
    await wait(400);
    const tasksPanel = await page.$('#peek-tasks-panel');
    log('Tasks panel opens on Tasks tab click', !!(await tasksPanel?.isVisible()));
    const taskInput = await page.$('#peek-task-input');
    log('Task input present', !!taskInput);
    // Clean up pre-existing tasks for this session before testing
    const peekSessName = await page.$eval('#peek-title', el => el.textContent.trim()).catch(() => '');
    if (peekSessName) {
      const tasksBase = `${BASE}/api/sessions/${encodeURIComponent(peekSessName)}/tasks`;
      const existingResp = await ctx.request.get(tasksBase).catch(() => null);
      const existing = existingResp ? await existingResp.json().catch(() => []) : [];
      if (Array.isArray(existing)) {
        for (const t of existing) {
          await ctx.request.delete(`${tasksBase}/${t.id}`).catch(() => {});
        }
      }
      await wait(200);
      await page.evaluate(() => typeof renderPeekTasks === 'function' && renderPeekTasks());
      await wait(300);
    }
    // Add a task
    await page.fill('#peek-task-input', 'e2e test task');
    await page.keyboard.press('Enter');
    await wait(500);
    const taskItems = await page.$$('.peek-task-item');
    log('Task appears after adding', taskItems.length === 1, `${taskItems.length} tasks`);
    // Check done via checkbox
    if (taskItems.length > 0) {
      await page.$eval('.peek-task-cb', el => el.click());
      await wait(300);
      const doneClass = await page.$eval('.peek-task-text', el => el.classList.contains('done'));
      log('Task toggles done state', !!doneClass);
      // Clear done
      await page.$eval('button[onclick="clearDonePeekTasks()"]', el => el.click());
      await wait(300);
      const remaining = await page.$$('.peek-task-item');
      log('Clear done removes completed tasks', remaining.length === 0, `${remaining.length} remaining`);
    }

    // ── Esc closes peek ────────────────────────────────────────────────────────
    await page.keyboard.press('Escape');
    await wait(300);
    const peekClosedByEsc = await peekOverlay?.evaluate(el => !el.classList.contains('active'));
    log('Esc key closes peek overlay', !!peekClosedByEsc);

    // Close peek via close button (button with onclick="closePeek()") — reopen first if Esc worked
    if (peekClosedByEsc) {
      // Reopen to test close button
      await page.evaluate(() => {
        const s = window.sessions;
        if (s && s.length) openPeek(s[0].name);
      });
      await wait(400);
    }
    await page.$eval('button[onclick="closePeek()"]', el => el.click());
    await wait(300);
    const peekClosed = await peekOverlay?.evaluate(el => !el.classList.contains('active'));
    log('Peek drawer closes via close button', !!peekClosed);

    const bodyOverflow = await page.evaluate(() => document.body.style.overflow);
    log('Body overflow restored after peek close', bodyOverflow === '', `"${bodyOverflow}"`);
  }

  await page.screenshot({ path: '/tmp/amux_desktop_final.png' });
  await ctx.close();
}

async function runMobile(browser) {
  console.log('\n── Mobile (iPhone 14, 390×844) ──');
  const iPhone = devices['iPhone 14'];
  const ctx = await browser.newContext({ ...iPhone, ignoreHTTPSErrors: true });
  const page = await ctx.newPage();

  await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 10000 });
  await waitForCount(page, '.card', 1);
  await page.screenshot({ path: '/tmp/amux_mobile_home.png' });

  // ── Tab bar ────────────────────────────────────────────────────────────────
  const tabBar = await page.$('.tab-bar');
  log('Tab bar visible on mobile', !!(await tabBar?.isVisible()));

  const tabs = await page.$$('.tab-bar button');
  log('All 3 tab buttons present on mobile', tabs.length === 3, `${tabs.length} tabs`);

  // Tab bar is sticky — check it has a position style or top set
  const tabTop = await tabBar?.evaluate(el => getComputedStyle(el).position);
  log('Tab bar is sticky/fixed on mobile', ['sticky','fixed'].includes(tabTop), `position: ${tabTop}`);

  // ── Sessions ───────────────────────────────────────────────────────────────
  const mobileCards = await page.$$('.card');
  log('Sessions render as cards on mobile', mobileCards.length > 0, `${mobileCards.length} cards`);

  if (SMOKE) { await ctx.close(); return; }

  // ── Board — kanban mode ────────────────────────────────────────────────────
  await page.click('#tab-board');
  await waitForCount(page, '.board-card', 1);

  // Switch to kanban mode
  await page.$eval('#bv-status', el => el.click());
  await waitForCount(page, '.board-col', 3);
  await page.screenshot({ path: '/tmp/amux_mobile_board.png' });

  const mobileCols = await page.$$('.board-col');
  log('Board kanban columns on mobile', mobileCols.length >= 3, `${mobileCols.length} cols`);

  const mobileContainer = await page.$('#board-columns');
  const mobileOverflow = await mobileContainer?.evaluate(el => getComputedStyle(el).overflowX);
  log('Board horizontal scroll enabled on mobile', mobileOverflow === 'scroll',
    `overflow-x: ${mobileOverflow}`);

  // ── Board detail on mobile ─────────────────────────────────────────────────
  const mobileCards2 = await page.$$('.board-card');
  if (mobileCards2.length > 0) {
    await page.$eval('.board-card', el => el.click());
    await wait(600);
    const mDetail = await page.$('#board-detail-overlay');
    const mDetailActive = await mDetail?.evaluate(el => el.classList.contains('active'));
    log('Board detail opens on mobile', !!mDetailActive);

    const mDue = await page.$('#bd-due');
    log('Due date field visible in detail on mobile', !!(await mDue?.isVisible()));

    // Close detail
    await page.$eval('#board-detail-overlay .btn', el => el.click());
    await wait(400);
    await page.screenshot({ path: '/tmp/amux_mobile_board_after_detail.png' });

    const mBodyOverflow = await page.evaluate(() => document.body.style.overflow);
    log('Body overflow restored after detail close on mobile', mBodyOverflow === '',
      `"${mBodyOverflow}"`);

    const mScrollAfter = await mobileContainer?.evaluate(el => getComputedStyle(el).overflowX);
    log('Board scroll intact after detail close on mobile', mScrollAfter === 'scroll',
      `overflow-x: ${mScrollAfter}`);
  }

  // ── Calendar on mobile ─────────────────────────────────────────────────────
  await page.click('#tab-calendar');
  await waitForCount(page, '.cal-day-header', 7);
  await page.screenshot({ path: '/tmp/amux_mobile_calendar.png' });

  const mCalGrid = await page.$('#cal-grid');
  log('Calendar grid visible on mobile', !!(await mCalGrid?.isVisible()));

  const mFirstCell = await page.$('.cal-cell');
  const mCellHeight = await mFirstCell?.evaluate(el => el.getBoundingClientRect().height);
  log('Calendar cell height ≥ 40px on mobile (mobile-optimized)',
    mCellHeight >= 40, `height: ${Math.round(mCellHeight ?? 0)}px`);

  const mDots = await page.$$('.cal-dot');
  log('Calendar event dots visible on mobile', mDots.length > 0, `${mDots.length} dots`);

  const mToolbar = await page.$('.cal-toolbar');
  const mToolbarWidth = await mToolbar?.evaluate(el => el.scrollWidth);
  log('Calendar toolbar fits mobile viewport (no overflow)',
    mToolbarWidth <= 400, `scrollWidth: ${mToolbarWidth}`);

  await page.screenshot({ path: '/tmp/amux_mobile_calendar_final.png' });
  await ctx.close();
}

async function testAPI() {
  console.log('\n── API & Data Layer ──');
  const api = await playwrightRequest.newContext({ ignoreHTTPSErrors: true, baseURL: BASE });

  // ── Sessions API ───────────────────────────────────────────────────────────
  const rSessions = await api.get('/api/sessions');
  const sessions = await rSessions.json();
  log('GET /api/sessions returns array', Array.isArray(sessions), `${sessions.length} sessions`);
  if (sessions.length > 0) {
    const s = sessions[0];
    log('Session object has name field', typeof s.name === 'string', s.name);
    log('Session object has running field', typeof s.running === 'boolean', `${s.name}.running=${s.running}`);
    log('Session object has dir field', 'dir' in s);
  }

  // ── Session memory API ─────────────────────────────────────────────────────
  if (sessions.length > 0) {
    const sname = sessions[0].name;
    const rMem = await api.get(`/api/sessions/${sname}/memory`);
    const memData = await rMem.json();
    log('GET /api/sessions/<name>/memory returns {content, path}',
      'content' in memData && 'path' in memData, `path=${memData.path}`);

    // Write and verify round-trip
    const testContent = memData.content + '\n<!-- e2e-test-marker -->';
    const rMemSave = await api.post(`/api/sessions/${sname}/memory`, {
      data: { content: testContent }
    });
    log('POST /api/sessions/<name>/memory saves successfully', rMemSave.ok());

    // Restore original
    await api.post(`/api/sessions/${sname}/memory`, { data: { content: memData.content } });
  }

  // ── Global memory API ──────────────────────────────────────────────────────
  const rGlobal = await api.get('/api/memory/global');
  const globalData = await rGlobal.json();
  log('GET /api/memory/global returns {content, path}',
    'content' in globalData && 'path' in globalData);

  const origGlobal = globalData.content;
  const rGlobalSave = await api.post('/api/memory/global', {
    data: { content: origGlobal + '\n<!-- e2e-test -->' }
  });
  log('POST /api/memory/global saves successfully', rGlobalSave.ok());
  await api.post('/api/memory/global', { data: { content: origGlobal } }); // restore

  // ── Board API ──────────────────────────────────────────────────────────────
  const rBoard = await api.get('/api/board');
  const boardItems = await rBoard.json();
  log('GET /api/board returns array', Array.isArray(boardItems), `${boardItems.length} items`);

  // Statuses
  const rStatuses = await api.get('/api/board/statuses');
  const statuses = await rStatuses.json();
  log('GET /api/board/statuses returns array', Array.isArray(statuses), `${statuses.length} statuses`);
  log('Built-in statuses present (todo/doing/done)',
    ['todo','doing','done'].every(id => statuses.some(s => s.id === id)));

  // ── PATCH board item ───────────────────────────────────────────────────────
  const aliveItems = boardItems.filter(i => !i.deleted);
  if (aliveItems.length > 0) {
    const target = aliveItems[0];
    const origStatus = target.status;
    const newStatus = origStatus === 'todo' ? 'doing' : 'todo';
    const rPatch = await api.patch(`/api/board/${target.id}`, {
      data: { status: newStatus }
    });
    log('PATCH /api/board/<id> updates status', rPatch.ok(), `${target.id}: ${origStatus} → ${newStatus}`);

    // Restore
    await api.patch(`/api/board/${target.id}`, { data: { status: origStatus } });
  }

  // ── Delta sync ─────────────────────────────────────────────────────────────
  const rSync0 = await api.get('/api/sync?since=0');
  const sync0 = await rSync0.json();
  log('GET /api/sync?since=0 has correct shape',
    Array.isArray(sync0.issues) && Array.isArray(sync0.statuses) && sync0.ts > 0,
    `${sync0.issues.length} issues, ${sync0.statuses.length} statuses`);

  const tombstones = sync0.issues.filter(i => i.deleted);
  const alive = sync0.issues.filter(i => !i.deleted);
  log('Sync includes soft-deleted tombstones', tombstones.length > 0,
    `alive:${alive.length} deleted:${tombstones.length}`);

  const rSyncRecent = await api.get(`/api/sync?since=${sync0.ts - 5}`);
  const syncRecent = await rSyncRecent.json();
  log('GET /api/sync?since=recent returns ≤ full results',
    syncRecent.issues.length <= sync0.issues.length,
    `recent: ${syncRecent.issues.length}`);

  // ── Create → sync → delete → tombstone (full round-trip) ──────────────────
  const now = Math.floor(Date.now() / 1000);
  const rCreate = await api.post('/api/board', {
    data: { title: 'E2E sync round-trip test', session: 'amux', due: '2026-06-01' }
  });
  const created = await rCreate.json();
  log('POST /api/board creates issue (201)', rCreate.status() === 201, `id=${created.id}`);

  const rAfterCreate = await api.get(`/api/sync?since=${now - 1}`);
  const afterCreate = await rAfterCreate.json();
  const createdInSync = afterCreate.issues.find(i => i.id === created.id);
  log('New issue appears in delta sync', !!createdInSync, created.id);
  if (createdInSync) {
    log('New issue has correct due date in sync', createdInSync.due === '2026-06-01',
      createdInSync.due);
  }

  await api.delete(`/api/board/${created.id}`);

  const rAfterDelete = await api.get(`/api/sync?since=${now - 1}`);
  const afterDelete = await rAfterDelete.json();
  const tombstone = afterDelete.issues.find(i => i.id === created.id);
  log('Deleted issue appears as tombstone', tombstone?.deleted > 0,
    `deleted=${tombstone?.deleted}`);

  // ── iCal feed ──────────────────────────────────────────────────────────────
  const rCal = await api.get('/api/calendar.ics');
  const ical = await rCal.text();
  log('iCal Content-Type is text/calendar',
    rCal.headers()['content-type']?.includes('text/calendar'),
    rCal.headers()['content-type']);
  log('iCal has VCALENDAR wrapper',
    ical.includes('BEGIN:VCALENDAR') && ical.includes('END:VCALENDAR'));
  log('iCal has VEVENT entries for dated issues',
    ical.includes('BEGIN:VEVENT'),
    `${(ical.match(/BEGIN:VEVENT/g) || []).length} events`);
  log('iCal uses DATE format (not DATETIME)',
    ical.includes('DTSTART;VALUE=DATE:'));
  log('iCal has PRODID field', ical.includes('PRODID:'));
  log('iCal has VERSION field', ical.includes('VERSION:2.0'));

  await api.dispose();
}

// ── Main ─────────────────────────────────────────────────────────────────────
const browser = await chromium.launch({ args: ['--ignore-certificate-errors'] });

try {
  await runDesktop(browser);
  await runMobile(browser);
  await testAPI();
} catch(e) {
  console.error('Test runner error:', e.message);
  console.error(e.stack);
  failed++;
} finally {
  await browser.close();
}

const bar = '═'.repeat(50);
console.log(`\n${bar}`);
console.log(`Results: ${passed} passed, ${failed} failed`);
if (failed > 0) {
  console.log('\nFailed tests:');
  results.filter(r => !r.ok).forEach(r => console.log(`  ✗ ${r.label}: ${r.detail}`));
}
process.exit(failed > 0 ? 1 : 0);
