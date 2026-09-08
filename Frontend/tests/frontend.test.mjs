import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { createHash } from 'node:crypto';
import { once } from 'node:events';
import { createFrontend, settingsFromEnvironment } from '../server.mjs';
import { HoldDrive, containedRectangle, validBox } from '../public/control.js';

const uiToken = 'ui-test-only-token-with-more-than-24-characters';
const serviceToken = 'service-test-only-token-with-more-than-24-characters';

async function fixture(t, ttl = 60_000) {
  const received = [];
  const backend = http.createServer((req, res) => {
    received.push(req.headers);
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({ ok: true }));
  });
  backend.on('upgrade', (req, socket) => {
    received.push(req.headers);
    const accept = createHash('sha1').update(req.headers['sec-websocket-key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
    socket.write(`HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`);
    socket.on('data', bytes => socket.write(bytes));
    socket.on('error', () => {});
  });
  backend.listen(0, '127.0.0.1'); await once(backend, 'listening');
  const origins = new Set();
  const frontend = createFrontend({ backend: new URL(`http://127.0.0.1:${backend.address().port}`), uiToken, serviceToken, origins, sessionTtlMs: ttl });
  frontend.listen(0, '127.0.0.1'); await once(frontend, 'listening');
  const origin = `http://127.0.0.1:${frontend.address().port}`;
  origins.add(origin);
  t.after(async () => {
    frontend.closeConnections();
    frontend.close(); backend.closeAllConnections(); backend.close();
  });
  async function request(path, options = {}) {
    return fetch(origin + path, { ...options, headers: { Origin: origin, ...options.headers } });
  }
  async function login() {
    const response = await request('/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: uiToken }) });
    assert.equal(response.status, 200);
    return response.headers.get('set-cookie').split(';')[0];
  }
  function upgrade(headers = {}) {
    return new Promise((resolve, reject) => {
      const req = http.request(origin + '/api/v1/ws', { headers: { Host: new URL(origin).host, Origin: origin, Connection: 'Upgrade', Upgrade: 'websocket', 'Sec-WebSocket-Version': '13', 'Sec-WebSocket-Key': 'MDEyMzQ1Njc4OTAxMjM0NQ==', ...headers } });
      req.on('upgrade', (response, socket) => resolve({ response, socket }));
      req.on('response', response => { response.resume(); resolve({ response }); });
      req.on('error', reject); req.end();
    });
  }
  return { origin, request, login, upgrade, received };
}

test('configuration rejects weak or shared secrets', () => {
  assert.throws(() => settingsFromEnvironment({}), /ROBO_UI_TOKEN/);
  assert.throws(() => settingsFromEnvironment({ ROBO_UI_TOKEN: uiToken, ROBO_SERVICE_TOKEN: uiToken }), /different/);
  assert.throws(() => settingsFromEnvironment({ ROBO_UI_TOKEN: uiToken, ROBO_SERVICE_TOKEN: serviceToken, ROBO_BACKEND_URL: 'file:///tmp' }), /HTTP/);
});
test('static UI contains neither secrets nor unsafe inline scripts; unknown assets rejected', async t => {
  const f = await fixture(t);
  const page = await f.request('/');
  assert.equal(page.status, 200);
  const html = await page.text();
  assert.ok(html.includes('Stop robot'));
  assert.ok(!html.includes(uiToken) && !html.includes(serviceToken));
  assert.match(page.headers.get('content-security-policy'), /frame-ancestors 'none'/);
  assert.equal((await f.request('/.env')).status, 404);
});
test('login requires same origin, correct token, JSON and bounded body', async t => {
  const f = await fixture(t);
  assert.equal((await f.request('/login', { method: 'POST', headers: { Origin: 'http://evil.invalid', 'Content-Type': 'application/json' }, body: JSON.stringify({ token: uiToken }) })).status, 403);
  assert.equal((await fetch(f.origin + '/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: uiToken }) })).status, 403);
  assert.equal((await f.request('/login', { method: 'POST', body: 'hello' })).status, 415);
  assert.equal((await f.request('/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"token":"wrong"}' })).status, 401);
  assert.equal((await f.request('/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: 'a'.repeat(3000) })).status, 413);
});
test('HTTP proxy is authenticated and sends only server-side credentials', async t => {
  const f = await fixture(t);
  assert.equal((await f.request('/api/v1/robot')).status, 401);
  const cookie = await f.login();
  const response = await f.request('/api/v1/robot', { headers: { Cookie: cookie, Authorization: 'Bearer browser-secret' } });
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true });
  assert.equal(f.received[0].authorization, `Bearer ${serviceToken}`);
  assert.equal(f.received[0].origin, undefined);
  assert.equal(f.received[0].cookie, undefined);
  assert.equal((await f.request('/api/v1/robot?token=bad', { headers: { Cookie: cookie } })).status, 400);
  assert.equal((await f.request('/api/v1/robot', { method: 'POST', headers: { Cookie: cookie } })).status, 405);
});
test('login session uses HttpOnly SameSite cookie and logout revokes it', async t => {
  const f = await fixture(t);
  const response = await f.request('/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: uiToken }) });
  const cookieHeader = response.headers.get('set-cookie');
  assert.match(cookieHeader, /HttpOnly; SameSite=Strict/);
  const cookie = cookieHeader.split(';')[0];
  assert.equal((await f.request('/session', { headers: { Cookie: cookie } })).status, 200);
  assert.equal((await f.request('/logout', { method: 'POST', headers: { Cookie: cookie } })).status, 200);
  assert.equal((await f.request('/session', { headers: { Cookie: cookie } })).status, 401);
});
test('login attempts are rate limited', async t => {
  const f = await fixture(t);
  let response;
  for (let i = 0; i < 11; i++) response = await f.request('/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"token":"bad"}' });
  assert.equal(response.status, 429);
});
test('WebSocket upgrade rejects missing authentication and foreign origins', async t => {
  const f = await fixture(t);
  assert.equal((await f.upgrade()).response.statusCode, 401);
  const cookie = await f.login();
  assert.equal((await f.upgrade({ Cookie: cookie, Origin: 'http://evil.invalid' })).response.statusCode, 403);
});
test('WebSocket proxy forwards bidirectionally and logout closes connection', async t => {
  const f = await fixture(t);
  const cookie = await f.login();
  const { response, socket } = await f.upgrade({ Cookie: cookie });
  t.after(() => socket.destroy());
  assert.equal(response.statusCode, 101);
  assert.equal(f.received[0].authorization, `Bearer ${serviceToken}`);
  assert.equal(f.received[0].origin, undefined);
  assert.equal(f.received[0].cookie, undefined);
  const echoed = once(socket, 'data'); socket.write(Buffer.from([0x81, 0]));
  assert.deepEqual((await echoed)[0], Buffer.from([0x81, 0]));
  const closed = once(socket, 'close');
  await f.request('/logout', { method: 'POST', headers: { Cookie: cookie } });
  await closed;
});
test('expired sessions cannot access API', async t => {
  const f = await fixture(t, 5);
  const cookie = await f.login();
  await new Promise(resolve => setTimeout(resolve, 12));
  assert.equal((await f.request('/api/v1/robot', { headers: { Cookie: cookie } })).status, 401);
});
test('held drive refreshes at 10 Hz, release sends stop, loss of authority stops', () => {
  const sent = []; let allowed = true, tick, cancelled = 0;
  const drive = new HoldDrive({ send: message => sent.push(message), canDrive: () => allowed, speed: () => 0.2, interval: (callback, delay) => { assert.equal(delay, 100); tick = callback; return 1; }, cancel: () => cancelled++ });
  assert.equal(drive.start('forward'), true); tick();
  assert.equal(sent.length, 2);
  drive.stop(); assert.equal(sent.at(-1).direction, 'stop');
  assert.equal(cancelled, 1);
  drive.stop(); assert.equal(sent.length, 3);
  drive.start('right'); allowed = false; tick();
  assert.equal(sent.at(-1).direction, 'stop');
  assert.equal(drive.start('forward'), false);
});
test('overlay respects letterboxing and rejects malformed normalized boxes', () => {
  assert.deepEqual(containedRectangle(400, 300, 1920, 1080), { x: 0, y: 37.5, width: 400, height: 225 });
  assert.equal(containedRectangle(0, 300, 1920, 1080), null);
  assert.equal(validBox([0.1, 0.2, 0.8, 0.9]), true);
  assert.equal(validBox([0.8, 0.2, 0.1, 0.9]), false);
  assert.equal(validBox([0, NaN, 1, 1]), false);
  assert.equal(validBox([-0.1, 0, 1, 1]), false);
});
