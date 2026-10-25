/* Real-browser HUD checks, using only a disposable local server/database. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');

const project = path.resolve(__dirname, '..');
const output = process.env.IVI_HUD_OUTPUT || '/workspace/.cloud-setup/IVI-v2';
const checks = [];
const consoleErrors = [];
const pageErrors = [];
const resourceFailures = [];
const cspViolations = [];
const dimensions = [];
let server, browser, temporary;
let serverOutput = '';

const wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

async function freePort() {
  const listener = net.createServer();
  await new Promise((resolve, reject) => { listener.once('error', reject); listener.listen(0, '127.0.0.1', resolve); });
  const port = listener.address().port;
  await new Promise(resolve => listener.close(resolve));
  return port;
}

async function startIsolatedServer() {
  temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'ivi-hud-'));
  const port = await freePort();
  const python = path.join(project, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  const environment = { ...process.env, IVI_DATA_DIR: temporary, IVI_ENV_FILE: path.join(temporary, 'not-configured.env'), PYTHONUNBUFFERED: '1' };
  for (const name of ['IVI_LLM_MODEL', 'IVI_STT_MODEL', 'IVI_TTS_MODEL', 'IVI_TTS_CONFIG']) delete environment[name];
  server = spawn(python, ['-m', 'ivi', '--port', String(port)], { cwd: project, env: environment, stdio: ['ignore', 'pipe', 'pipe'] });
  server.stdout.on('data', data => { serverOutput += data.toString(); });
  server.stderr.on('data', data => { serverOutput += data.toString(); });
  const base = `http://127.0.0.1:${port}`;
  for (let attempt = 0; attempt < 100; attempt++) {
    if (server.exitCode !== null) throw new Error(`Disposable IVI server exited: ${serverOutput}`);
    try {
      const response = await fetch(base + '/api/status', { signal: AbortSignal.timeout(1000) });
      if (response.ok && (await response.json()).name === 'I.V.I.') return base;
    } catch {}
    await wait(100);
  }
  throw new Error(`Disposable IVI server did not become ready: ${serverOutput}`);
}

async function run(name, callback, page) {
  try {
    await callback();
    checks.push({ name, status: 'passed' });
    console.log('PASS ' + name);
  } catch (error) {
    checks.push({ name, status: 'failed', error: error.message });
    console.error('FAIL ' + name + ': ' + error.message);
    if (page && !page.isClosed()) {
      await page.screenshot({ path: path.join(output, `failure-${checks.length}.png`) }).catch(() => {});
      await page.evaluate(() => document.querySelectorAll('dialog[open]').forEach(dialog => dialog.close())).catch(() => {});
    }
  }
}

async function connected(page) {
  await page.waitForFunction(() => document.querySelector('#connectionPill')?.classList.contains('connected'));
  await page.locator('#bootScreen').waitFor({ state: 'hidden' });
}

async function selectView(page, view) {
  const tab = page.locator(`.view-tabs [data-view="${view}"]`);
  if (await tab.isVisible()) await tab.click();
}

async function inside(page, selector) {
  const element = page.locator(selector);
  assert.equal(await element.isVisible(), true, `${selector} should be visible`);
  const box = await element.boundingBox();
  const viewport = page.viewportSize();
  assert.ok(box && box.width > 0 && box.height > 0, `${selector} has no usable size`);
  assert.ok(box.x >= -1 && box.y >= -1 && box.x + box.width <= viewport.width + 1 && box.y + box.height <= viewport.height + 1,
    `${selector} outside ${viewport.width}x${viewport.height}: ${JSON.stringify(box)}`);
  return box;
}

async function noDocumentOverflow(page) {
  const metrics = await page.evaluate(() => ({
    width: innerWidth, height: innerHeight,
    scrollWidth: document.documentElement.scrollWidth,
    scrollHeight: document.documentElement.scrollHeight,
    bodyWidth: document.body.scrollWidth,
    bodyHeight: document.body.scrollHeight,
    scrollX, scrollY,
  }));
  assert.ok(metrics.scrollWidth <= metrics.width + 1 && metrics.bodyWidth <= metrics.width + 1, 'Horizontal overflow: ' + JSON.stringify(metrics));
  assert.ok(metrics.scrollHeight <= metrics.height + 1 && metrics.bodyHeight <= metrics.height + 1, 'Document scrolling: ' + JSON.stringify(metrics));
  assert.equal(metrics.scrollX, 0);
  assert.equal(metrics.scrollY, 0);
  return metrics;
}

async function sendText(page, text) {
  await page.locator('#chatInput').fill(text);
  await page.locator('#chatInput').press('Enter');
}

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const base = await startIsolatedServer();
  const proxy = process.env.HTTPS_PROXY || process.env.HTTP_PROXY;
  browser = await chromium.launch({
    executablePath: process.env.IVI_CHROMIUM || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'],
    ...(proxy ? { proxy: { server: proxy, bypass: 'localhost,127.0.0.1' } } : {}),
  });
  const context = await browser.newContext({ viewport: { width: 1366, height: 768 }, reducedMotion: 'reduce' });
  await context.addInitScript(() => {
    window.__micRequests = 0;
    window.__cspViolations = [];
    document.addEventListener('securitypolicyviolation', event => window.__cspViolations.push(`${event.violatedDirective}: ${event.blockedURI}`));
    const original = navigator.mediaDevices?.getUserMedia?.bind(navigator.mediaDevices);
    if (original) navigator.mediaDevices.getUserMedia = (...arguments_) => { window.__micRequests++; return original(...arguments_); };
  });
  const page = await context.newPage();
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()); });
  page.on('requestfailed', request => resourceFailures.push(`${request.url()}: ${request.failure()?.errorText}`));
  page.on('response', response => { if (response.status() >= 400) resourceFailures.push(`${response.status()} ${response.url()}`); });
  await page.goto(base, { waitUntil: 'networkidle' });
  await connected(page);

  await run('HUD connects with honest missing models and microphone initially off', async () => {
    const status = await (await context.request.get(base + '/api/status')).json();
    assert.equal(status.name, 'I.V.I.');
    assert.equal(Object.values(status.models).filter(model => model.ready).length, 0);
    assert.equal(await page.locator('#modelStrip .unavailable').count(), 3);
    assert.equal(await page.locator('#micButton').getAttribute('aria-pressed'), 'false');
    assert.equal(await page.evaluate(() => window.__micRequests), 0);
    assert.match(await page.locator('#cpuValue').textContent(), /^\d+%$/);
    assert.match(await page.locator('#ramValue').textContent(), /^\d+%$/);
    const ramDetail = (await page.locator('#ramDetail').textContent()).replaceAll(',', '.');
    assert.ok(ramDetail.includes(Number(status.system.ram_total_gb).toFixed(1)), `RAM total should match the actual local status: ${ramDetail}`);
    const threadLabel = await page.locator('#cpuThreads').textContent();
    if (status.system.cpu_threads == null) {
      assert.ok(!/\d/.test(threadLabel) && /CPU LOCAL|—/i.test(threadLabel), `Unknown thread counts must not be fabricated: ${threadLabel}`);
    } else {
      assert.equal(Number(threadLabel.match(/\d+/)?.[0]), status.system.cpu_threads);
    }
  }, page);

  await run('real browser fullscreen enters and exits through the Fullscreen API', async () => {
    assert.equal(await page.evaluate(() => document.fullscreenElement === null), true);
    await page.locator('#fullscreenButton').click();
    await page.waitForFunction(() => document.fullscreenElement !== null, null, { timeout: 5000 });
    assert.equal(await page.locator('#fullscreenButton').getAttribute('aria-pressed'), 'true');
    await page.evaluate(() => document.exitFullscreen());
    await page.waitForFunction(() => document.fullscreenElement === null);
    assert.equal(await page.locator('#fullscreenButton').getAttribute('aria-pressed'), 'false');
  }, page);

  await run('chat help uses the actual WebSocket and keeps the composer visible', async () => {
    const count = await page.locator('.message.assistant').count();
    await sendText(page, '/ajuda');
    await page.waitForFunction(expected => document.querySelectorAll('.message.assistant').length === expected + 1, count);
    assert.match(await page.locator('.message.assistant').last().textContent(), /GGUF|modelo/i);
    assert.equal(await page.locator('#chatInput').inputValue(), '');
    await inside(page, '#chatForm');
    await noDocumentOverflow(page);
  }, page);

  await run('memory creates safe text, persists after reload and removes only its own fixture', async () => {
    await selectView(page, 'system');
    await page.locator('#memoryOpen').click();
    const content = 'HUD test memory <img src=x onerror=alert(1)>';
    await page.locator('#memoryInput').fill(content);
    await page.locator('#memoryForm button[type="submit"]').click();
    await page.getByText(content, { exact: true }).waitFor();
    assert.equal(await page.locator('#memoryList img').count(), 0);
    await page.locator('[data-close="memoryDialog"]').click();
    await page.reload({ waitUntil: 'networkidle' });
    await connected(page);
    await selectView(page, 'system');
    await page.locator('#memoryOpen').click();
    const row = page.locator('.memory-item').filter({ hasText: content });
    await row.waitFor();
    await row.locator('.memory-delete').click();
    await row.waitFor({ state: 'detached' });
    await page.locator('[data-close="memoryDialog"]').click();
    assert.deepEqual((await (await context.request.get(base + '/api/memory')).json()).items, []);
  }, page);

  await run('settings change and persist wake activation and speech speed', async () => {
    await page.locator('#settingsOpen').click();
    await page.locator('#wakeWordSetting').check();
    await page.locator('#rateSetting').fill('1.2');
    await page.locator('#rateSetting').dispatchEvent('change');
    await page.waitForFunction(async () => (await (await fetch('/api/status')).json()).settings.speech_rate === 1.2);
    await page.locator('[data-close="settingsDialog"]').click();
    await page.reload({ waitUntil: 'networkidle' });
    await connected(page);
    await page.locator('#settingsOpen').click();
    assert.equal(await page.locator('#wakeWordSetting').isChecked(), true);
    assert.equal(await page.locator('#rateSetting').inputValue(), '1.2');
    await page.locator('[data-close="settingsDialog"]').click();
  }, page);

  await run('missing STT blocks capture with an explanation and no permission request', async () => {
    await page.locator('#micButton').click();
    assert.equal(await page.locator('#micButton').getAttribute('aria-pressed'), 'false');
    assert.equal(await page.evaluate(() => window.__micRequests), 0);
    assert.match(await page.locator('#toast').textContent(), /reconhecimento de fala|modelo.*escuta/i);
  }, page);

  await run('application shortcuts require confirmation and files action respects Linux guard', async () => {
    await selectView(page, 'system');
    await page.locator('.application-link[data-command="abrir spotify"]').click();
    await page.locator('#toolDialog').waitFor({ state: 'visible' });
    assert.match(await page.locator('#toolDescription').textContent(), /Spotify/i);
    await page.locator('#toolReject').click();
    await page.locator('.message.tool').filter({ hasText: /cancelada/ }).waitFor();
    await selectView(page, 'system');
    await page.locator('.application-link[data-command="abrir arquivos"]').click();
    await page.locator('#toolDialog').waitFor({ state: 'visible' });
    assert.match(await page.locator('#toolTitle').textContent(), /arquivos|explorador/i);
    await page.locator('#toolApprove').click();
    await page.locator('.message.error').filter({ hasText: /Windows/ }).waitFor();
    assert.equal(await page.locator('#toolDialog').isVisible(), false);
  }, page);

  const viewports = [
    [1366, 640], [1366, 768], [1280, 720], [1920, 1080], [1024, 600], [1093, 510],
    [390, 844], [360, 640], [844, 390],
  ];
  for (const [width, height] of viewports) {
    await run(`HUD ${width}x${height}: viewport controls and internal transcript scrolling`, async () => {
      await page.setViewportSize({ width, height });
      await page.reload({ waitUntil: 'networkidle' });
      await connected(page);
      await selectView(page, 'core');
      await inside(page, '.topbar');
      await inside(page, '#controlDock');
      await inside(page, '#chatForm');
      await inside(page, '#chatInput');
      await inside(page, '#micButton');
      await inside(page, '#settingsOpen');
      await inside(page, '#stateLabel');
      const core = await inside(page, '#coreCanvas');
      assert.ok(core.width >= 140 && core.height >= 90, `Core too small: ${JSON.stringify(core)}`);
      const pixels = await page.locator('#coreCanvas').evaluate(canvas => {
        const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
        let visible = 0;
        for (let index = 3; index < data.length; index += 4) if (data[index] > 20) visible++;
        return visible;
      });
      assert.ok(pixels > 100, 'Core canvas has no rendered content');
      const metric = await noDocumentOverflow(page);
      dimensions.push({ width, height, core, metric });
      const image = width === 1366 && height === 768 ? 'desktop.png' : width === 1093 ? 'compact.png' : width === 390 ? 'mobile.png' : null;
      if (image) await page.screenshot({ path: path.join(output, image) });

      await selectView(page, 'conversation');
      await page.evaluate(() => {
        document.querySelector('#emptyConversation')?.remove();
        const log = document.querySelector('#messages');
        for (let index = 0; index < 100; index++) {
          const message = document.createElement('article');
          message.className = 'message ' + (index % 2 ? 'assistant' : 'user');
          const body = document.createElement('div');
          body.className = 'message-body';
          body.textContent = `Synthetic layout fixture ${index}: ` + 'conteúdo longo para verificar rolagem interna e limites do HUD. '.repeat(16);
          message.append(body);
          log.append(message);
        }
        const notice = document.querySelector('#connectionNotice');
        notice.textContent = 'Aviso sintético de layout. '.repeat(12);
        notice.hidden = false;
        const transcript = document.querySelector('#transcriptPreview');
        transcript.hidden = false;
        transcript.querySelector('p').textContent = 'Transcrição sintética longa. '.repeat(20);
        log.scrollTop = log.scrollHeight;
      });
      await noDocumentOverflow(page);
      await inside(page, '#chatForm');
      await inside(page, '#micButton');
      const scrolling = await page.locator('#messages').evaluate(log => ({ height: log.clientHeight, scrollHeight: log.scrollHeight, top: log.scrollTop, overflow: getComputedStyle(log).overflowY }));
      assert.ok(scrolling.height >= 35 && scrolling.scrollHeight > scrolling.height, `Transcript has no usable internal scrolling: ${JSON.stringify(scrolling)}`);
      assert.ok(['auto', 'scroll'].includes(scrolling.overflow), `Transcript overflow should be internal: ${JSON.stringify(scrolling)}`);
      assert.ok(scrolling.top > 0, 'Transcript did not scroll internally');
      if (width <= 980) {
        await page.locator('#settingsOpen').click();
        await inside(page, '#settingsDialog');
        await inside(page, '[data-close="settingsDialog"]');
        await page.locator('[data-close="settingsDialog"]').click();
      }
      cspViolations.push(...await page.evaluate(() => window.__cspViolations));
    }, page);
  }

  await run('no browser exceptions, CSP violations, 404s or failed resources', async () => {
    assert.deepEqual(pageErrors, []);
    assert.deepEqual(consoleErrors, []);
    assert.deepEqual(resourceFailures, []);
    assert.deepEqual(cspViolations, []);
  }, page);
  await browser.close();
  browser = null;
  const summary = { passed: checks.filter(check => check.status === 'passed').length, failed: checks.filter(check => check.status === 'failed').length, checks, dimensions, pageErrors, consoleErrors, resourceFailures, cspViolations };
  fs.writeFileSync(path.join(output, 'ui-hud-results.json'), JSON.stringify(summary, null, 2));
  console.log(JSON.stringify(summary, null, 2));
  process.exitCode = summary.failed ? 1 : 0;
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close().catch(() => {});
  if (server && server.exitCode === null) {
    server.kill('SIGTERM');
    await Promise.race([new Promise(resolve => server.once('exit', resolve)), wait(4000)]);
    if (server.exitCode === null) server.kill('SIGKILL');
  }
  if (serverOutput) fs.writeFileSync(path.join(output, 'server.log'), serverOutput);
  if (temporary) fs.rmSync(temporary, { recursive: true, force: true });
});
