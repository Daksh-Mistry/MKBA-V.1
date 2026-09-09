import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { once } from 'node:events';
import { createFrontend, settingsFromEnvironment } from '../server.mjs';
import { HoldDrive, containedRectangle, validBox } from '../public/control.js';

test('settingsFromEnvironment provides default host, port and backend URL', () => {
  const settings = settingsFromEnvironment({});
  assert.equal(settings.port, 3001);
  assert.equal(settings.host, '0.0.0.0');
  assert.equal(settings.backend.href, 'http://127.0.0.1:8100/');
});

test('static UI serves index.html without errors', async t => {
  const backend = http.createServer((req, res) => {
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({ ok: true }));
  });
  backend.listen(0, '127.0.0.1');
  await once(backend, 'listening');

  const origins = new Set(['http://127.0.0.1:0', 'http://localhost:0']);
  const frontend = createFrontend({
    backend: new URL(`http://127.0.0.1:${backend.address().port}`),
    origins
  });
  frontend.listen(0, '127.0.0.1');
  await once(frontend, 'listening');

  const origin = `http://127.0.0.1:${frontend.address().port}`;
  origins.add(origin);

  t.after(() => {
    frontend.closeConnections();
    frontend.close();
    backend.close();
  });

  const page = await fetch(origin + '/');
  assert.equal(page.status, 200);
  const html = await page.text();
  assert.ok(html.includes('Stop robot'));
  assert.ok(html.includes('Controls Enabled'));
});

test('overlay respects letterboxing and rejects malformed boxes', () => {
  assert.deepEqual(containedRectangle(400, 300, 1920, 1080), { x: 0, y: 37.5, width: 400, height: 225 });
  assert.equal(containedRectangle(0, 300, 1920, 1080), null);
  assert.equal(validBox([0.1, 0.2, 0.8, 0.9]), true);
  assert.equal(validBox([0.8, 0.2, 0.1, 0.9]), false);
  assert.equal(validBox([0, NaN, 1, 1]), false);
  assert.equal(validBox([-0.1, 0, 1, 1]), false);
});
