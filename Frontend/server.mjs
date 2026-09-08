/** Local UI and authenticated JSON/WebSocket proxy. No camera or API keys in the browser. */
import http from 'node:http';
import https from 'node:https';
import { randomBytes, timingSafeEqual } from 'node:crypto';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const directory = path.dirname(fileURLToPath(import.meta.url));
const staticFiles = new Map([
  ['/', ['index.html', 'text/html; charset=utf-8']],
  ['/app.js', ['app.js', 'text/javascript; charset=utf-8']],
  ['/control.js', ['control.js', 'text/javascript; charset=utf-8']],
  ['/video.js', ['video.js', 'text/javascript; charset=utf-8']],
  ['/style.css', ['style.css', 'text/css; charset=utf-8']],
]);
const apiPaths = new Set(['/api/v1/health', '/api/v1/robot', '/api/v1/video/sources', '/api/v1/ml/models', '/api/v1/auto/config']);
const cookieName = 'robo_session';

export function loadEnvironment(env = process.env) {
  const filename = path.join(directory, '.env');
  if (!existsSync(filename)) return;
  for (const raw of readFileSync(filename, 'utf8').split(/\r?\n/)) {
    const match = raw.match(/^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (!match || Object.hasOwn(env, match[1])) continue;
    let value = match[2];
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1);
    else value = value.replace(/\s+#.*$/, '');
    env[match[1]] = value;
  }
}

export function settingsFromEnvironment(env = process.env) {
  const port = Number(env.FRONTEND_PORT || 3000);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('FRONTEND_PORT must be a TCP port.');
  const backend = new URL(env.ROBO_BACKEND_URL || env.BACKEND_URL || 'http://127.0.0.1:8100');
  if (!['http:', 'https:'].includes(backend.protocol) || backend.username || backend.password || backend.pathname !== '/' || backend.search || backend.hash) throw new Error('BACKEND_URL must be an HTTP server origin.');
  for (const key of ['ROBO_UI_TOKEN', 'ROBO_SERVICE_TOKEN']) if (!env[key] || env[key].length < 24) throw new Error(`${key} must contain at least 24 characters. See Frontend/.env.example.`);
  if (env.ROBO_UI_TOKEN === env.ROBO_SERVICE_TOKEN) throw new Error('Use different UI and service tokens.');
  const origins = new Set([`http://localhost:${port}`, `http://127.0.0.1:${port}`]);
  for (const origin of (env.FRONTEND_ORIGINS || '').split(',').map(s => s.trim()).filter(Boolean)) {
    const url = new URL(origin);
    if (!['http:', 'https:'].includes(url.protocol) || url.origin !== origin) throw new Error('FRONTEND_ORIGINS must contain exact HTTP origins.');
    origins.add(origin);
  }
  return { host: env.FRONTEND_HOST || '127.0.0.1', port, backend, uiToken: env.ROBO_UI_TOKEN,
    serviceToken: env.ROBO_SERVICE_TOKEN, origins, sessionTtlMs: 8 * 3600 * 1000 };
}

export function createFrontend(settings) {
  const sessions = new Map();
  const attempts = new Map();
  const proxySockets = new Set();
  const transport = settings.backend.protocol === 'https:' ? https : http;
  const secureHeaders = {
    'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self' http: https: ws: wss:; media-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
    'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=()', 'Cache-Control': 'no-store',
  };
  function reply(res, status, body) {
    if (res.destroyed || res.writableEnded) return;
    res.writeHead(status, { ...secureHeaders, 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify(body));
  }
  function originFor(req) {
    const host = req.headers.host;
    if (!host || /[\s,\/\\]/.test(host)) return null;
    return [...settings.origins].find(origin => new URL(origin).host === host) || null;
  }
  function allowed(req, requireOrigin = false) {
    const origin = originFor(req);
    if (!origin) return false;
    return req.headers.origin ? req.headers.origin === origin : !requireOrigin;
  }
  function sessionFor(req) {
    const match = (req.headers.cookie || '').match(/(?:^|;\s*)robo_session=([a-f0-9]{64})(?:;|$)/);
    const id = match?.[1];
    const session = sessions.get(id);
    if (!session || session.expires <= Date.now()) {
      if (session) endSession(id);
      return null;
    }
    return { id, ...session };
  }
  function endSession(id) {
    const session = sessions.get(id);
    if (session) for (const socket of session.sockets) socket.destroy();
    sessions.delete(id);
  }
  function cookie(value, req, age) {
    return `${cookieName}=${value}; HttpOnly; SameSite=Strict; Path=/; Max-Age=${age}${originFor(req)?.startsWith('https:') ? '; Secure' : ''}`;
  }
  async function body(req, maximum) {
    if (Number(req.headers['content-length']) > maximum) throw Object.assign(new Error('Request is too large.'), { status: 413 });
    let length = 0;
    const parts = [];
    for await (const part of req) {
      length += part.length;
      if (length > maximum) throw Object.assign(new Error('Request is too large.'), { status: 413 });
      parts.push(part);
    }
    return Buffer.concat(parts);
  }
  function safeEqual(value, expected) {
    if (typeof value !== 'string') return false;
    const a = Buffer.from(value), b = Buffer.from(expected);
    return a.length === b.length && timingSafeEqual(a, b);
  }
  const server = http.createServer(async (req, res) => {
    try {
      if (!allowed(req)) return reply(res, 403, { error: 'Origin is not allowed.' });
      const pathname = new URL(req.url, 'http://local').pathname;
      if (req.url.includes('?')) return reply(res, 400, { error: 'Query parameters are not supported.' });
      if (pathname === '/login' && req.method === 'POST') {
        if (!allowed(req, true)) return reply(res, 403, { error: 'Same-origin login required.' });
        const address = req.socket.remoteAddress;
        const now = Date.now();
        let record = attempts.get(address);
        if (!record || now - record.started > 60_000) record = { started: now, count: 0 };
        record.count++;
        attempts.set(address, record);
        if (record.count > 10) return reply(res, 429, { error: 'Too many attempts. Wait a minute.' });
        if (!req.headers['content-type']?.startsWith('application/json')) return reply(res, 415, { error: 'JSON body required.' });
        let data;
        try { data = JSON.parse((await body(req, 2048)).toString('utf8')); }
        catch (error) { return reply(res, error.status || 400, { error: error.status ? error.message : 'Invalid JSON.' }); }
        if (!safeEqual(data?.token, settings.uiToken)) return reply(res, 401, { error: 'Token was not accepted.' });
        const previous = sessionFor(req);
        if (previous) endSession(previous.id);
        if (sessions.size >= 128) return reply(res, 503, { error: 'Too many active sessions.' });
        const id = randomBytes(32).toString('hex');
        sessions.set(id, { expires: now + settings.sessionTtlMs, sockets: new Set() });
        res.setHeader('Set-Cookie', cookie(id, req, Math.floor(settings.sessionTtlMs / 1000)));
        return reply(res, 200, { authenticated: true });
      }
      if (pathname === '/session' && req.method === 'GET') return reply(res, sessionFor(req) ? 200 : 401, { authenticated: !!sessionFor(req) });
      if (pathname === '/logout' && req.method === 'POST') {
        if (!allowed(req, true)) return reply(res, 403, { error: 'Same-origin logout required.' });
        const session = sessionFor(req);
        if (session) endSession(session.id);
        res.setHeader('Set-Cookie', cookie('', req, 0));
        return reply(res, 200, { authenticated: false });
      }
      if (staticFiles.has(pathname) && ['GET', 'HEAD'].includes(req.method)) {
        const [filename, mime] = staticFiles.get(pathname);
        const bytes = readFileSync(path.join(directory, 'public', filename));
        res.writeHead(200, { ...secureHeaders, 'Content-Type': mime, 'Content-Length': bytes.length });
        return res.end(req.method === 'HEAD' ? undefined : bytes);
      }
      if (!apiPaths.has(pathname)) return reply(res, 404, { error: 'Not found.' });
      if (!sessionFor(req)) return reply(res, 401, { error: 'Sign in again.' });
      if (req.method !== 'GET' && !(pathname === '/api/v1/auto/config' && req.method === 'PUT')) return reply(res, 405, { error: 'Method is not allowed.' });
      if (req.method !== 'GET' && !allowed(req, true)) return reply(res, 403, { error: 'Same-origin request required.' });
      const bytes = await body(req, 65536);
      const upstream = transport.request(new URL(pathname, settings.backend), {
        method: req.method, headers: { Authorization: `Bearer ${settings.serviceToken}`, 'Content-Type': 'application/json', 'Content-Length': bytes.length, Accept: 'application/json' },
      }, incoming => {
        res.writeHead(incoming.statusCode, { ...secureHeaders, 'Content-Type': 'application/json; charset=utf-8' });
        incoming.on('error', () => res.destroy());
        incoming.pipe(res);
      });
      upstream.setTimeout(15_000, () => upstream.destroy(new Error('Backend timeout.')));
      upstream.on('error', () => { if (!res.headersSent) reply(res, 502, { error: 'Backend is unavailable.' }); else res.destroy(); });
      res.on('close', () => upstream.destroy());
      upstream.end(bytes);
    } catch (error) { reply(res, error.status || 400, { error: error.status ? error.message : 'Request could not be read.' }); }
  });
  server.requestTimeout = 10_000;
  server.headersTimeout = 10_000;
  server.on('upgrade', (req, socket, head) => {
    const reject = (status, message) => socket.end(`HTTP/1.1 ${status} ${message}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`);
    if (req.url !== '/api/v1/ws' || req.method !== 'GET') return reject(404, 'Not Found');
    if (!allowed(req, true)) return reject(403, 'Forbidden');
    const session = sessionFor(req);
    if (!session) return reject(401, 'Unauthorized');
    if (req.headers.upgrade?.toLowerCase() !== 'websocket' || req.headers['sec-websocket-version'] !== '13' || !/^[A-Za-z0-9+/]{22}==$/.test(req.headers['sec-websocket-key'] || '')) return reject(400, 'Bad Request');
    if (session.sockets.size >= 4) return reject(429, 'Too Many Requests');
    session.sockets.add(socket);
    proxySockets.add(socket);
    const expiry = setTimeout(() => socket.destroy(), Math.max(1, session.expires - Date.now()));
    expiry.unref();
    const upstream = transport.request(new URL('/api/v1/ws', settings.backend), { headers: {
      Authorization: `Bearer ${settings.serviceToken}`, Connection: 'Upgrade', Upgrade: 'websocket',
      'Sec-WebSocket-Version': '13', 'Sec-WebSocket-Key': req.headers['sec-websocket-key'],
    }});
    upstream.setTimeout(5000, () => upstream.destroy());
    upstream.on('upgrade', (response, peer, peerHead) => {
      upstream.setTimeout(0);
      const headers = [`HTTP/1.1 101 Switching Protocols`, 'Upgrade: websocket', 'Connection: Upgrade', `Sec-WebSocket-Accept: ${response.headers['sec-websocket-accept']}`];
      socket.write(`${headers.join('\r\n')}\r\n\r\n`);
      if (head.length) peer.write(head);
      if (peerHead.length) socket.write(peerHead);
      socket.pipe(peer).pipe(socket);
      socket.on('close', () => peer.destroy());
      peer.on('close', () => socket.destroy());
      peer.on('error', () => socket.destroy());
    });
    upstream.on('response', response => { response.resume(); reject(502, 'Bad Gateway'); });
    upstream.on('error', () => socket.destroy());
    socket.on('error', () => upstream.destroy());
    socket.on('close', () => {
      clearTimeout(expiry); session.sockets.delete(socket); proxySockets.delete(socket); upstream.destroy();
    });
    upstream.end();
  });
  const cleanup = setInterval(() => {
    const now = Date.now();
    for (const [id, session] of sessions) if (session.expires <= now) endSession(id);
    for (const [address, record] of attempts) if (now - record.started > 60_000) attempts.delete(address);
  }, 30_000);
  cleanup.unref();
  server.on('close', () => { clearInterval(cleanup); for (const socket of proxySockets) socket.destroy(); });
  server.closeConnections = () => { for (const id of [...sessions.keys()]) endSession(id); server.closeAllConnections(); };
  return server;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    loadEnvironment();
    const settings = settingsFromEnvironment();
    const server = createFrontend(settings);
    server.on('error', error => { console.error(`Frontend could not start: ${error.message}`); process.exitCode = 1; });
    server.listen(settings.port, settings.host, () => console.log(`Robo console: http://${settings.host}:${settings.port}`));
    for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => { server.closeConnections(); server.close(); });
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
