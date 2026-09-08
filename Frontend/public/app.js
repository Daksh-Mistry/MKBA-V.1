import { HoldDrive, containedRectangle, validBox } from './control.js';
import { PiVideo } from './video.js';

const $ = id => document.getElementById(id);
let socket, sessionId, state = {}, sequence = 0, reconnectTimer, heartbeatTimer, signedIn = false;
let videoSource, detections = null, detectionsAt = 0, videoConnected = false, toastTimer;
let lastReceived = 0, retryCount = 0, previousMode = null, pendingChat = null;
const pending = new Map();
const pendingSpeech = new Map();
const connected = () => socket?.readyState === WebSocket.OPEN && !!sessionId;
const ownsControl = () => connected() && state.owner_session_id === sessionId;
const canDrive = () => ownsControl() && state.pi?.connected && Number(state.pi.age_ms ?? 99999) < 1000 && !state.stopped && state.mode === 'manual' && !document.hidden;

function notify(message) {
  $('toast').textContent = message;
  $('toast').hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $('toast').hidden = true; }, 5000);
}
function activity(message) {
  const item = document.createElement('li');
  item.textContent = `${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })} · ${message}`;
  $('activity-log').prepend(item);
  while ($('activity-log').children.length > 30) $('activity-log').lastElementChild.remove();
  $('last-event').textContent = message;
}
function badge(id, text, level) { $(id).textContent = text; $(id).dataset.level = level; }
function send(data, track = false) {
  if (!connected()) return null;
  const requestId = crypto.randomUUID();
  try {
    socket.send(JSON.stringify({ ...data, request_id: requestId, seq: ++sequence }));
    if (track) pending.set(requestId, { type: data.type, created: Date.now() });
    return requestId;
  } catch { return null; }
}
const drive = new HoldDrive({ send, canDrive, speed: () => Number($('speed').value), onChange: direction => {
  document.querySelectorAll('[data-drive]').forEach(button => button.classList.toggle('is-held', button.dataset.drive === direction));
}});
const video = new PiVideo($('camera'), (status, message) => {
  videoConnected = status === 'connected';
  badge('video-badge', videoConnected ? 'Video live' : status === 'connecting' ? 'Connecting' : 'Video offline', videoConnected ? 'good' : status === 'error' ? 'error' : 'offline');
  $('video-placeholder').hidden = videoConnected;
  $('video-message').textContent = message;
  if (!videoConnected) detections = null;
});

async function api(path) {
  const response = await fetch(path, { credentials: 'same-origin' });
  if (response.status === 401) { await signOut(false); throw new Error('Your session expired. Sign in again.'); }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || data.detail || `Service returned ${response.status}.`);
  return data;
}
async function refreshSources() {
  const results = await Promise.allSettled([api('/api/v1/video/sources'), api('/api/v1/ml/models'), api('/api/v1/robot')]);
  const [source, models, robot] = results;
  if (source.status === 'fulfilled') {
    const next = source.value;
    if (next.whep_url) {
      const changed = !videoSource || next.whep_url !== videoSource.whep_url || next.stream_revision !== videoSource.stream_revision;
      videoSource = next;
      const viewer = next.viewer_url ? new URL(next.viewer_url) : null;
      if (viewer && ['http:', 'https:'].includes(viewer.protocol) && !viewer.username && !viewer.password) { $('raw-viewer').href = viewer.href; $('raw-viewer').hidden = false; }
      if (changed && signedIn) video.connect(next).catch(error => activity(error.message));
    }
  } else activity(`Video settings: ${source.reason.message}`);
  if (models.status === 'fulfilled') renderModels(models.value.models || []);
  else { $('model-select').replaceChildren(new Option('ML unavailable', '')); activity(`Model list: ${models.reason.message}`); }
  if (robot.status === 'fulfilled') updateState(robot.value);
  render();
}
function renderModels(models) {
  const selected = $('model-select').value || state.ml?.model_id;
  $('model-select').replaceChildren();
  for (const model of models) {
    const option = new Option(`${model.name || model.id}${model.artifact_available === false ? ' · weights missing' : ''}`, model.id);
    option.disabled = model.artifact_available === false;
    $('model-select').append(option);
  }
  if (![...$('model-select').options].length) $('model-select').append(new Option('No models registered', ''));
  if ([...$('model-select').options].some(o => o.value === selected)) $('model-select').value = selected;
}
function updateState(next) {
  if (previousMode && next.mode !== previousMode) drive.stop();
  previousMode = next.mode;
  state = next;
  if (!canDrive()) drive.stop();
  render();
}
function render() {
  const online = connected(), owned = ownsControl(), manual = canDrive();
  const pi = state.pi || {}, ml = state.ml || {}, calibration = state.calibration || {};
  const simulated = pi.simulation === true || pi.simulated === true || state.simulation === true;
  const piFresh = pi.connected && Number(pi.age_ms ?? 99999) < 1500;
  badge('backend-badge', online ? 'Backend connected' : 'Backend offline', online ? 'good' : 'offline');
  badge('pi-badge', piFresh ? (simulated ? 'Pi simulated' : 'Pi connected') : pi.connected ? 'Pi status stale' : 'Pi offline', piFresh ? (simulated ? 'warn' : 'good') : pi.connected ? 'warn' : 'offline');
  badge('ml-badge', ml.ready ? 'ML ready' : ml.connected ? 'ML connected' : 'ML offline', ml.ready ? 'good' : ml.connected ? 'warn' : 'offline');
  $('stop').disabled = !online;
  $('claim').disabled = !online || owned || !!state.owner_session_id;
  $('resume').disabled = !owned || !piFresh || !state.stopped;
  $('release').disabled = !owned;
  $('manual-mode').disabled = !owned;
  $('auto-mode').disabled = !owned || !piFresh;
  $('manual-mode').setAttribute('aria-pressed', state.mode !== 'auto');
  $('auto-mode').setAttribute('aria-pressed', state.mode === 'auto');
  document.querySelectorAll('[data-drive],[data-servo]').forEach(button => { button.disabled = !manual; });
  $('pump-on').disabled = !manual;
  $('pump-off').disabled = !online;
  $('vision-start').disabled = !owned || !ml.connected || !$('model-select').value;
  $('vision-stop').disabled = !owned || !ml.connected;
  $('model-select').disabled = !owned || !state.stopped;
  $('chat-input').disabled = !online;
  $('chat-send').disabled = !online || !!pendingChat;
  $('speech-stop').disabled = !online;
  $('shutdown').disabled = !owned;
  $('ownership-label').textContent = owned ? 'Your controls' : state.owner_session_id ? 'Another operator' : 'Viewing';
  let summary = !online ? 'Backend offline. Controls are unavailable.' : !pi.connected ? 'Pi offline. Chat and video can connect independently.' : owned ? state.stopped ? 'You have control. Robo is stopped — press Resume when ready.' : state.mode === 'auto' ? 'Auto is active. Stop robot is always available.' : 'You have control. Hold a direction to move.' : state.owner_session_id ? 'Another operator has control. You can watch, chat or stop the robot.' : 'Viewing only. Take control to operate Robo.';
  if (simulated) summary = `SIMULATION · No physical robot. ${summary}`;
  $('control-summary').textContent = summary;
  $('control-banner').dataset.level = simulated || !piFresh ? 'warn' : 'normal';
  $('auto-phase').textContent = `Auto ${state.auto?.phase || 'idle'}`;
  const servos = state.servos || {};
  $('servo-position').textContent = `${servos.pan ?? '—'}° / ${servos.tilt ?? '—'}°`;
  $('pump-state').textContent = state.pump === true ? 'On' : state.pump === false ? 'Off' : 'Unknown';
  $('sensor-age').textContent = piFresh ? `${Math.round(pi.age_ms || 0)} ms ago` : 'Readings unavailable';
  $('footer-status').textContent = online ? `${state.mode === 'auto' ? 'AUTO' : 'MANUAL'} · ${state.stopped ? 'STOPPED' : 'READY'}${simulated ? ' · SIMULATION' : ''}` : 'RECONNECTING TO BACKEND';
  $('system-details').textContent = [
    `Pi: ${pi.connected ? 'connected' : 'disconnected'}${simulated ? ' (simulation)' : ''} · telemetry age ${pi.age_ms == null ? 'unknown' : `${Math.round(pi.age_ms)} ms`}`,
    `Pi command watchdog: ${pi.watchdog ? 'available' : 'unavailable'}`,
    `Motion calibration: ${calibration.motion_calibrated ? 'configured' : 'not configured'}`,
    `Auto calibration: ${calibration.auto_calibrated ? 'configured' : 'not configured'}`,
    `ML: ${ml.model_id || 'no model selected'}${ml.error ? ` · ${ml.error}` : ''}`,
    `Stream: ${videoSource?.stream_id || 'not configured'}`,
    'Detection overlay: approximate alignment; stale boxes hidden after 500 ms.',
    state.last_error ? `Last issue: ${state.last_error}` : '',
  ].filter(Boolean).join('\n');
  renderSensors(piFresh);
}
function renderSensors(fresh) {
  const sensors = state.sensors || {};
  const cells = [];
  for (const [group, items] of [['IR', sensors.ir], ['Flame', sensors.flame]]) {
    const entries = Array.isArray(items) ? items : items && typeof items === 'object' ? Object.entries(items).map(([position, value]) => ({ position, ...(typeof value === 'object' ? value : { detected: value }) })) : [];
    for (const [index, item] of entries.entries()) {
      const valid = fresh && item.valid === true;
      const detected = group === 'IR' ? item.blocked : item.detected ?? item.active;
      const value = valid && typeof detected === 'boolean' ? detected ? 'blocked' : 'clear' : 'unknown';
      const cell = document.createElement('div'); cell.className = 'sensor-cell'; cell.dataset.state = value;
      const label = document.createElement('span'); label.className = 'sensor-name'; label.textContent = `${group} · ${String(item.position ?? item.name ?? index + 1).replaceAll('_', ' ')}`;
      const status = document.createElement('span'); status.className = 'sensor-value'; status.textContent = value === 'unknown' ? 'Unknown' : detected ? group === 'IR' ? 'Blocked' : 'Detected' : 'Clear';
      cell.append(label, status); cells.push(cell);
    }
  }
  if (cells.length) $('sensor-grid').replaceChildren(...cells);
  else { const empty = document.createElement('p'); empty.className = 'muted'; empty.textContent = 'Waiting for Pi sensor readings.'; $('sensor-grid').replaceChildren(empty); }
}
function connectSocket() {
  if (!signedIn) return;
  clearTimeout(reconnectTimer);
  socket?.close();
  sessionId = null;
  const next = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/v1/ws`);
  socket = next;
  next.onopen = () => { lastReceived = Date.now(); };
  next.onmessage = event => {
    if (next !== socket) return;
    lastReceived = Date.now();
    let message;
    try { message = JSON.parse(event.data); } catch { return; }
    if (message.type === 'hello') {
      sessionId = message.session_id; sequence = 0; retryCount = 0;
      activity('Backend connected. Control is not resumed automatically.');
      clearInterval(heartbeatTimer);
      heartbeatTimer = setInterval(() => {
        if (Date.now() - lastReceived > 6000) { drive.stop(); next.close(); return; }
        send({ type: 'heartbeat' });
        for (const [id, item] of pending) if (Date.now() - item.created > 60_000) pending.delete(id);
        if (pendingChat && Date.now() - pendingChat.created > 60_000) finishChat('Robo did not respond in time. You can try again.', 'timeout');
      }, 1000);
      refreshSources().catch(error => activity(error.message));
      render();
    } else if (message.type === 'state') updateState(message);
    else if (message.type === 'detections') {
      if (videoSource && message.stream_id && message.stream_id !== videoSource.stream_id) return;
      if (videoSource && message.stream_revision != null && message.stream_revision !== videoSource.stream_revision) return;
      detections = message; detectionsAt = performance.now();
      const boxes = message.detections || [];
      $('vision-summary').textContent = boxes.length ? `${boxes.length} detection${boxes.length === 1 ? '' : 's'}` : 'No fire or smoke detected';
    } else if (message.type === 'command_result') {
      const request = pending.get(message.request_id); pending.delete(message.request_id);
      if (['blocked', 'error', 'rejected'].includes(message.status)) {
        notify(message.message || `${request?.type || 'Command'} was blocked.`);
        activity(message.message || `${request?.type || 'Command'}: ${message.status}`);
        if (pendingChat?.id === message.request_id) finishChat(message.message || 'That request could not be completed.', message.status);
      } else if (request && request.type !== 'chat') activity(message.message || `${request.type}: ${message.status}`);
    } else if (message.type === 'chat.reply') {
      if (pendingChat?.id === message.request_id) finishChat(message.text || 'No reply text received.', message.action_status, message.speech_status);
    } else if (message.type === 'error') {
      const error = message.message || message.detail || 'A service reported an error.';
      activity(error); notify(error);
      if (pendingChat?.id === message.request_id) finishChat(error, 'error');
    } else if (message.type === 'event') {
      if (message.code === 'speech_status') {
        const reply = pendingSpeech.get(message.request_id);
        if (reply) {
          updateChatStatus(reply.article, reply.action, message.status);
          pendingSpeech.delete(message.request_id);
        }
        activity(`Pi voice: ${String(message.status || 'unknown').replaceAll('_', ' ')}`);
      } else activity(message.message || message.event || 'Robot state updated.');
    }
  };
  next.onclose = () => {
    if (next !== socket) return;
    drive.stop(); sessionId = null; clearInterval(heartbeatTimer); detections = null;
    if (pendingChat) finishChat('Connection interrupted. Your message will not be replayed.', 'interrupted');
    for (const reply of pendingSpeech.values()) updateChatStatus(reply.article, reply.action, 'connection_lost');
    pendingSpeech.clear();
    pending.clear(); state = { ...state, pi: { ...state.pi, connected: false } }; render();
    if (signedIn) reconnectTimer = setTimeout(async () => {
      try { await api('/session'); connectSocket(); }
      catch (error) { if (signedIn) { activity(error.message); connectSocket(); } }
    }, Math.min(5000, 1000 * ++retryCount));
  };
  next.onerror = () => {};
}
async function signIn() {
  signedIn = true;
  $('login-screen').hidden = true; $('console-screen').hidden = false;
  connectSocket();
}
async function signOut(request = true) {
  drive.stop(); send({ type: 'control', command: 'release' });
  signedIn = false; clearTimeout(reconnectTimer); clearInterval(heartbeatTimer);
  socket?.close(); sessionId = null; video.stop(); videoSource = null; state = {}; pending.clear();
  pendingChat = null; pendingSpeech.clear(); $('chat-input').value = ''; $('chat-history').replaceChildren();
  appendChat('Robo', 'Ready to chat when you sign in.');
  if (request) await fetch('/logout', { method: 'POST', credentials: 'same-origin' }).catch(() => {});
  $('console-screen').hidden = true; $('login-screen').hidden = false; $('access-token').value = '';
  $('access-token').focus();
}
$('login-form').addEventListener('submit', async event => {
  event.preventDefault(); $('login-error').textContent = ''; $('login-button').disabled = true;
  try {
    const response = await fetch('/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: $('access-token').value }), credentials: 'same-origin' });
    const result = await response.json();
    $('access-token').value = '';
    if (!response.ok) throw new Error(result.error || 'Sign-in failed.');
    await signIn();
  } catch (error) { $('login-error').textContent = error.message; }
  finally { $('login-button').disabled = false; }
});
$('logout').addEventListener('click', () => signOut());
$('claim').addEventListener('click', () => send({ type: 'control', command: 'claim' }, true));
$('resume').addEventListener('click', () => send({ type: 'control', command: 'resume' }, true));
$('release').addEventListener('click', () => { drive.stop(); send({ type: 'control', command: 'release' }, true); });
const stopRobot = () => { drive.stop(); send({ type: 'system', command: 'stop' }, true); };
$('stop').addEventListener('click', stopRobot);
for (const mode of ['manual', 'auto']) $(`${mode}-mode`).addEventListener('click', () => { drive.stop(); send({ type: 'mode', value: mode }, true); });
$('speed').addEventListener('input', () => { $('speed-value').textContent = `${Math.round(Number($('speed').value) * 100)}%`; });
for (const button of document.querySelectorAll('[data-drive]')) {
  button.addEventListener('pointerdown', event => { if (event.button !== 0) return; event.preventDefault(); if (drive.start(button.dataset.drive)) button.setPointerCapture(event.pointerId); });
  for (const kind of ['pointerup', 'pointercancel', 'lostpointercapture']) button.addEventListener(kind, () => drive.stop());
  button.addEventListener('contextmenu', event => event.preventDefault());
  button.addEventListener('keydown', event => { if (event.code === 'Space' || event.code === 'Enter') { event.preventDefault(); drive.start(button.dataset.drive); } });
  button.addEventListener('keyup', event => { if (event.code === 'Space' || event.code === 'Enter') { event.preventDefault(); drive.stop(); } });
}
for (const button of document.querySelectorAll('[data-servo]')) button.addEventListener('click', () => send({ type: 'servo', direction: button.dataset.servo, degrees: 5 }, true));
$('pump-on').addEventListener('click', () => send({ type: 'pump', on: true, duration_ms: 800 }, true));
$('pump-off').addEventListener('click', () => send({ type: 'pump', on: false }, true));
$('vision-start').addEventListener('click', () => { $('vision-summary').textContent = 'Starting detection…'; send({ type: 'vision', command: 'start', model_id: $('model-select').value }, true); });
$('vision-stop').addEventListener('click', () => { detections = null; $('vision-summary').textContent = 'Detection paused'; send({ type: 'vision', command: 'stop' }, true); });
$('model-select').addEventListener('change', () => { if (!state.stopped) notify('Stop Robo before changing models.'); render(); });
$('video-connect').addEventListener('click', () => videoSource ? video.connect(videoSource).catch(error => notify(error.message)) : refreshSources().catch(error => notify(error.message)));
$('refresh').addEventListener('click', () => refreshSources().catch(error => notify(error.message)));
$('speech-stop').addEventListener('click', () => send({ type: 'speech', command: 'stop' }, true));
$('shutdown').addEventListener('click', () => {
  if (window.confirm('Stop all robot actions and shut down the Pi server script? You will need to start the script on the Pi again.')) send({ type: 'system', command: 'shutdown' }, true);
});
const keys = { KeyW: 'forward', KeyS: 'backward', KeyA: 'left', KeyD: 'right' };
let heldKey = null;
window.addEventListener('keydown', event => {
  if (event.code === 'Escape') { event.preventDefault(); heldKey = null; stopRobot(); return; }
  if (event.ctrlKey || event.metaKey || event.altKey || event.repeat || event.target.closest('input,textarea,select,[contenteditable=true]')) return;
  if (keys[event.code] && canDrive()) { event.preventDefault(); heldKey = event.code; drive.start(keys[event.code]); }
});
window.addEventListener('keyup', event => { if (event.code === heldKey) { event.preventDefault(); heldKey = null; drive.stop(); } });
window.addEventListener('blur', () => { heldKey = null; drive.stop(); });
document.addEventListener('visibilitychange', () => { if (document.hidden) { heldKey = null; drive.stop(); } });
window.addEventListener('pagehide', () => { drive.stop(); send({ type: 'control', command: 'release' }); video.stop(false); });

function appendChat(author, text, status) {
  const article = document.createElement('article'); article.className = `chat-message ${author === 'You' ? 'user' : 'robot'}`;
  const label = document.createElement('span'); label.className = 'message-author'; label.textContent = author.toUpperCase();
  const paragraph = document.createElement('p'); paragraph.textContent = text;
  article.append(label, paragraph);
  if (status) { const note = document.createElement('span'); note.className = 'message-status'; note.textContent = status; article.append(note); }
  $('chat-history').append(article);
  while ($('chat-history').children.length > 100) $('chat-history').firstElementChild.remove();
  $('chat-history').scrollTop = $('chat-history').scrollHeight;
  return article;
}
function updateChatStatus(article, action, speech) {
  const notes = [];
  if (action === 'sent_to_pi') notes.push('Gesture sent to Pi');
  else if (action && action !== 'none') notes.push(`Gesture: ${action}`);
  if (speech && speech !== 'not_requested') notes.push(`Voice: ${speech === 'accepted' ? 'accepted by Pi' : String(speech).replaceAll('_', ' ')}`);
  let note = article.querySelector('.message-status');
  if (!notes.length) { note?.remove(); return; }
  if (!note) { note = document.createElement('span'); note.className = 'message-status'; article.append(note); }
  note.textContent = notes.join(' · ');
}
function finishChat(text, action, speech) {
  const requestId = pendingChat?.id;
  if (requestId) pending.delete(requestId);
  pendingChat = null;
  const article = appendChat('Robo', text);
  updateChatStatus(article, action, speech);
  if (requestId && speech === 'pending') pendingSpeech.set(requestId, { article, action });
  $('chat-status').textContent = 'Ready for your next message.';
  render();
}
$('chat-form').addEventListener('submit', event => {
  event.preventDefault();
  const message = $('chat-input').value.trim();
  if (!message || pendingChat || !connected()) return;
  const id = send({ type: 'chat', message, speak: $('speak').checked }, true);
  if (!id) return;
  appendChat('You', message); $('chat-input').value = '';
  pendingChat = { id, created: Date.now() };
  $('chat-status').textContent = 'Robo is thinking…'; render();
});
$('chat-input').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); $('chat-form').requestSubmit(); } });

const context = $('overlay').getContext('2d');
function drawOverlay() {
  const canvas = $('overlay'), stage = $('video-stage');
  const width = stage.clientWidth, height = stage.clientHeight, ratio = window.devicePixelRatio || 1;
  if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) { canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio); }
  context.setTransform(ratio, 0, 0, ratio, 0, 0); context.clearRect(0, 0, width, height);
  const elapsed = performance.now() - detectionsAt;
  const age = elapsed + Math.max(0, Number(detections?.frame_age_at_send_ms || 0));
  const fresh = detections && age < 500 && videoConnected;
  $('overlay-age').textContent = fresh ? `Overlay ≈ ${Math.round(age)} ms` : 'Direct camera view';
  if (detections && age >= 500) $('vision-summary').textContent = 'Waiting for fresh detections';
  if (fresh && $('show-boxes').checked && width > 0) {
    const image = detections.image || {};
    const sourceWidth = image.width || $('camera').videoWidth, sourceHeight = image.height || $('camera').videoHeight;
    const area = containedRectangle(width, height, sourceWidth, sourceHeight);
    if (area) for (const item of detections.detections || []) {
      const box = item.bbox;
      if (!validBox(box)) continue;
      const [x1, y1, x2, y2] = box;
      const x = area.x + x1 * area.width, y = area.y + y1 * area.height;
      const color = item.class === 'fire' ? '#ffb174' : '#c9e6ac';
      context.strokeStyle = color; context.lineWidth = 2;
      context.strokeRect(x, y, (x2 - x1) * area.width, (y2 - y1) * area.height);
      context.font = '11px Segoe UI, sans-serif';
      const score = Number.isFinite(item.score) ? ` ${Math.round(item.score * 100)}%` : '';
      const label = `${String(item.class || 'Detection').slice(0, 30)}${score}`;
      const labelWidth = context.measureText(label).width + 12;
      const labelY = Math.max(0, y - 22);
      context.fillStyle = color; context.fillRect(Math.min(x, width - labelWidth), labelY, labelWidth, 21);
      context.fillStyle = '#142017'; context.fillText(label, Math.min(x, width - labelWidth) + 6, labelY + 14);
    }
  }
  requestAnimationFrame(drawOverlay);
}
requestAnimationFrame(drawOverlay);
fetch('/session', { credentials: 'same-origin' }).then(response => { if (response.ok) return signIn(); }).catch(() => { $('login-error').textContent = 'The frontend server is unavailable.'; });
