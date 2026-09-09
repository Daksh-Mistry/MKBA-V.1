import { HoldDrive, HoldServo, DriveKeys, driveSpeed, containedRectangle, validBox, controlAvailability } from './control.js';
import { PiVideo } from './video.js';

const $ = id => document.getElementById(id);
let socket, sessionId, state = {}, sequence = 0, reconnectTimer, heartbeatTimer, signedIn = false;
let videoSource, detections = null, detectionsAt = 0, videoConnected = false, toastTimer;
let lastReceived = 0, retryCount = 0, previousMode = null, pendingChat = null;
let authenticationRevision = 0;
let preferredDriveSpeed = Number($('speed').value);
let controlsActive = true;
let currentMode = 'manual';
const pending = new Map();
const pendingSpeech = new Map();
const connected = () => socket?.readyState === WebSocket.OPEN;
const ownsControl = () => true;
const controls = () => controlAvailability(state, { online: connected() });
const canDrive = () => controlsActive;

function setModeVisual(mode) {
  currentMode = mode || 'manual';
  const isAuto = currentMode === 'auto';
  const manBtn = $('manual-mode');
  const autoBtn = $('auto-mode');
  if (manBtn) {
    manBtn.setAttribute('aria-pressed', String(!isAuto));
    manBtn.classList.toggle('is-active', !isAuto);
  }
  if (autoBtn) {
    autoBtn.setAttribute('aria-pressed', String(isAuto));
    autoBtn.classList.toggle('is-active', isAuto);
  }
}

function setControlsVisual(active) {
  controlsActive = !!active;
  const enBtn = $('enable');
  const relBtn = $('release');
  if (enBtn) {
    enBtn.setAttribute('aria-pressed', String(controlsActive));
    enBtn.classList.toggle('is-active', controlsActive);
  }
  if (relBtn) {
    relBtn.setAttribute('aria-pressed', String(!controlsActive));
    relBtn.classList.toggle('is-active', !controlsActive);
  }
  const lbl = $('ownership-label');
  if (lbl) {
    lbl.textContent = controlsActive ? 'Controls Active' : 'Controls Disabled';
    lbl.classList.toggle('disabled', !controlsActive);
  }
}

function notify(message) {
  $('toast').textContent = message;
  $('toast').hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $('toast').hidden = true; }, 5000);
}

function escapeHtml(str) {
  return String(str ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function activity(entry) {
  const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const item = document.createElement('li');
  item.className = 'log-item';

  if (typeof entry === 'string') {
    item.innerHTML = `
      <div class="log-header">
        <span class="log-time">${time}</span>
        <span class="log-tag tag-info">INFO</span>
        <span class="log-text">${escapeHtml(entry)}</span>
      </div>
    `;
    $('last-event').textContent = entry;
  } else {
    const { dir = 'info', type = '', data, error } = entry;
    const badgeClass = dir === 'out' ? 'tag-out' : dir === 'in' ? 'tag-in' : dir === 'offline' ? 'tag-offline' : 'tag-info';
    const badgeText = dir === 'out' ? 'OUT ↗' : dir === 'in' ? 'IN ↙' : dir === 'offline' ? 'OFFLINE' : 'INFO';
    const payloadStr = data ? JSON.stringify(data) : '';
    item.innerHTML = `
      <div class="log-header">
        <span class="log-time">${time}</span>
        <span class="log-tag ${badgeClass}">${badgeText}</span>
        <strong class="log-type">${escapeHtml(type)}</strong>
        ${error ? `<span class="log-error">${escapeHtml(error)}</span>` : ''}
      </div>
      ${payloadStr ? `<pre class="log-json">${escapeHtml(payloadStr)}</pre>` : ''}
    `;
    $('last-event').textContent = `${badgeText} ${type}: ${payloadStr || error || ''}`;
  }

  $('activity-log').prepend(item);
  while ($('activity-log').children.length > 60) $('activity-log').lastElementChild.remove();
}

function badge(id, text, level) { $(id).textContent = text; $(id).dataset.level = level; }

function send(data, track = false) {
  if (!connected()) {
    activity({ dir: 'offline', type: data.type, data });
    console.warn('[WS OFFLINE]', data);
    return null;
  }
  const requestId = (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID() : ('req-' + Math.random().toString(36).slice(2, 11) + '-' + Date.now());
  const payload = { ...data, request_id: requestId, seq: ++sequence };
  try {
    socket.send(JSON.stringify(payload));
    console.log('%c[WS SEND]', 'color: #c4df91; font-weight: bold;', payload);
    activity({ dir: 'out', type: data.type, data: payload });
    if (track) pending.set(requestId, { type: data.type, created: Date.now() });
    return requestId;
  } catch (err) {
    console.error('[WS SEND ERROR]', err);
    activity({ dir: 'out', type: data.type, error: err.message, data: payload });
    return null;
  }
}

const drive = new HoldDrive({
  send,
  canDrive,
  speed: () => driveSpeed(preferredDriveSpeed, state.readiness?.drive),
  onChange: direction => {
    document.querySelectorAll('[data-drive]').forEach(button => {
      button.classList.toggle('is-held', button.dataset.drive === direction);
    });
  }
});

const servo = new HoldServo({
  send,
  canDrive,
  onChange: direction => {
    document.querySelectorAll('[data-servo]').forEach(button => {
      button.classList.toggle('is-held', button.dataset.servo === direction);
    });
  }
});

const keyboard = new DriveKeys({
  drive,
  servo,
  canDrive,
  onStop: () => stopRobot(),
  onBlocked: () => notify('Controls are disabled. Click Controls Enabled to drive.')
});
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
  if (previousMode && next.mode !== previousMode) keyboard.reset();
  previousMode = next.mode;
  state = next;
  if (typeof state.pump === 'boolean') setPumpVisual(state.pump);
  render();
}
function render() {
  const online = connected(), owned = ownsControl(), available = controls();
  const pi = state.pi || {}, ml = state.ml || {};
  const readiness = state.readiness || {};
  const simulated = pi.simulation === true || pi.simulated === true || state.simulation === true;
  const piFresh = pi.connected && Number(pi.age_ms ?? 99999) < 1500;
  badge('backend-badge', online ? 'Backend connected' : 'Backend offline', online ? 'good' : 'offline');
  badge('pi-badge', piFresh ? (simulated ? 'Pi simulated' : 'Pi connected') : pi.connected ? 'Pi status stale' : 'Pi offline', piFresh ? (simulated ? 'warn' : 'good') : pi.connected ? 'warn' : 'offline');
  badge('ml-badge', ml.ready ? 'ML ready' : ml.connected ? 'ML connected' : 'ML offline', ml.ready ? 'good' : ml.connected ? 'warn' : 'offline');
  $('stop').disabled = false;
  $('enable').disabled = false;
  $('release').disabled = false;
  $('manual-mode').disabled = false;
  $('auto-mode').disabled = false;
  if (state.mode) currentMode = state.mode;
  setModeVisual(currentMode);
  setControlsVisual(controlsActive);
  for (const [kind, enabled] of [['drive', available.drive && controlsActive], ['servo', available.servo && controlsActive]]) {
    document.querySelectorAll(`[data-${kind}]`).forEach(button => {
      button.disabled = !enabled; button.title = available.reasons[kind] || '';
    });
  }
  $('pump-toggle').disabled = false;
  $('pump-toggle').title = 'Click to toggle water pump ON / OFF';
  $('pump-note').textContent = 'Click to toggle water pump ON / OFF.';
  const limitedDrive = readiness.drive?.limited === true;
  $('speed').max = String(limitedDrive ? readiness.drive.max_speed ?? 0.2 : 0.6);
  $('speed').value = String(driveSpeed(preferredDriveSpeed, readiness.drive));
  $('speed-value').textContent = `${Math.round(Number($('speed').value) * 100)}%`;
  $('drive-note').textContent = 'Hold WASD to drive. Hold Arrow keys to step face servos (2/sec).';
  $('alignment-check').disabled = false;
  $('alignment-check').textContent = readiness.alignment_confirmed ? 'Operating check recorded' : 'Confirm camera / nozzle check';
  $('readiness-summary').textContent = ['drive', 'servo', 'pump', 'auto'].map(name =>
    `${name === 'servo' ? 'Face' : name[0].toUpperCase() + name.slice(1)}: ${readiness[name]?.available ? readiness[name]?.reason || 'ready' : readiness[name]?.reason || 'waiting for Pi status'}`).join('\n');
  $('vision-start').disabled = !ml.connected || !$('model-select').value;
  $('vision-stop').disabled = !ml.connected;
  $('model-select').disabled = false;
  $('chat-input').disabled = false;
  $('chat-send').disabled = !!pendingChat;
  $('shutdown').disabled = false;
  $('ownership-label').textContent = 'Controls enabled';
  let summary = 'Controls enabled. Hold a direction to move; release it to stop.';
  if (online && state.mode === 'auto') summary = 'Auto is active. Stop robot is always available.';
  $('control-summary').textContent = summary;
  $('hardware-issue').textContent = Object.entries(pi.hardware || {}).filter(([name, part]) => name !== 'sensors' && part.available === false).map(([name, part]) => `${name}: ${part.reason || part.state}`).join(' · ');
  $('hardware-issue').hidden = !$('hardware-issue').textContent;
  $('control-banner').dataset.level = simulated || !piFresh ? 'warn' : 'normal';
  $('auto-phase').textContent = `Auto ${state.auto?.phase || 'idle'}`;
  const servos = state.servos || {};
  const angle = value => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(1) : '—';
  $('servo-position').textContent = `${angle(servos.pan)}° / ${angle(servos.tilt)}°`;
  $('pump-state').textContent = state.pump === true ? 'On' : state.pump === false ? 'Off' : 'Unknown';
  $('sensor-age').textContent = piFresh ? `${Math.round(pi.age_ms || 0)} ms ago` : 'Readings unavailable';
  $('footer-status').textContent = online ? `${state.mode === 'auto' ? 'AUTO' : 'MANUAL'} · ${state.stopped ? 'STOPPED' : 'READY'}${simulated ? ' · SIMULATION' : ''}` : 'RECONNECTING TO BACKEND';
  $('system-details').textContent = [
    `Pi: ${pi.connected ? 'connected' : 'disconnected'}${simulated ? ' (simulation)' : ''} · telemetry age ${pi.age_ms == null ? 'unknown' : `${Math.round(pi.age_ms)} ms`}`,
    `Pi command watchdog: ${pi.watchdog ? 'available' : 'unavailable'}`,
    `Robot wiring profile: ${readiness.profile || 'waiting'}`,
    `Camera/nozzle operating check: ${readiness.alignment_confirmed ? 'recorded' : 'not recorded; manual operation remains available'}`,
    ...Object.entries(pi.hardware || {}).map(([name, part]) => `${name}: ${part.state || 'unknown'}${part.reason ? ` — ${part.reason}` : ''}${part.presence ? ` (${part.presence.replaceAll('_', ' ')})` : ''}`),
    `ML: ${ml.model_id || 'no model selected'}${ml.error ? ` · ${ml.error}` : ''}`,
    `Stream: ${videoSource?.stream_id || 'not configured'}`,
    'Detection overlay: approximate alignment; stale boxes hidden after 500 ms.',
    state.last_error ? `Last issue: ${state.last_error}` : '',
  ].filter(Boolean).join('\n');
  renderSensors(piFresh);
}
function renderSensors() {
  const sensors = state.sensors || {};
  const cells = [];
  const groups = [
    { name: 'IR', items: Array.isArray(sensors.ir) ? sensors.ir : [] },
    { name: 'Flame', items: Array.isArray(sensors.flame) ? sensors.flame : [] }
  ];
  for (const group of groups) {
    for (const [index, val] of group.items.entries()) {
      const cell = document.createElement('div');
      cell.className = 'sensor-cell';
      let stateName = 'unknown';
      let text = 'Disconnected';
      if (val === 0) {
        stateName = 'clear';
        text = 'Clear';
      } else if (val === 1) {
        stateName = 'blocked';
        text = group.name === 'IR' ? 'Obstacle' : 'Fire Detected';
      }
      cell.dataset.state = stateName;
      const label = document.createElement('span');
      label.className = 'sensor-name';
      label.textContent = `${group.name} ${index + 1}`;
      const status = document.createElement('span');
      status.className = 'sensor-value';
      status.textContent = text;
      cell.append(label, status);
      cells.push(cell);
    }
  }
  if (cells.length) $('sensor-grid').replaceChildren(...cells);
  else {
    const empty = document.createElement('p');
    empty.className = 'muted';
    empty.textContent = 'Waiting for Pi sensor readings.';
    $('sensor-grid').replaceChildren(empty);
  }
}
function connectSocket() {
  clearTimeout(reconnectTimer);
  keyboard.reset();
  socket?.close();
  sessionId = null;
  const next = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/v1/ws`);
  socket = next;
  next.onopen = () => {
    lastReceived = Date.now();
    activity('WebSocket connected to backend');
    render();
  };
  next.onmessage = event => {
    if (next !== socket) return;
    lastReceived = Date.now();
    let message;
    try { message = JSON.parse(event.data); } catch { return; }
    console.log('%c[WS RECV]', 'color: #64b5f6; font-weight: bold;', message);
    if (message.type === 'hello') {
      sessionId = message.session_id; sequence = 0; retryCount = 0;
      activity({ dir: 'in', type: 'hello', data: message });
      refreshSources().catch(error => activity(error.message));
      render();
    } else if (message.type === 'state') {
      updateState(message);
    } else if (message.type === 'detections') {
      detections = message; detectionsAt = performance.now();
      const boxes = message.detections || [];
      $('vision-summary').textContent = boxes.length ? `${boxes.length} detection${boxes.length === 1 ? '' : 's'}` : 'No fire or smoke detected';
      requestOverlay();
    } else if (message.type === 'chat.reply') {
      activity({ dir: 'in', type: 'chat.reply', data: message });
      if (pendingChat?.id === message.request_id) finishChat(message.text || 'No reply text received.', message.action_status, null, message.chat_mode);
    } else if (message.type === 'error') {
      const error = message.message || message.detail || 'A service reported an error.';
      activity({ dir: 'in', type: 'error', data: message, error });
      notify(error);
      if (pendingChat?.id === message.request_id) finishChat(error, 'error');
    } else {
      activity({ dir: 'in', type: message.type, data: message });
    }
  };
  next.onclose = () => {
    if (next !== socket) return;
    keyboard.reset();
    drive.stop();
    servo.stop();
    sessionId = null;
    detections = null;
    pendingChat = null;
    activity({ dir: 'info', type: 'status', data: { message: 'WebSocket disconnected. Retrying in 2s...' } });
    render();
    reconnectTimer = setTimeout(connectSocket, 2000);
  };
  next.onerror = () => {};
}

// Single Pump Toggle State & Visual
let pumpActive = false;
function setPumpVisual(active) {
  pumpActive = !!active;
  const btn = $('pump-toggle');
  if (btn) {
    btn.classList.toggle('is-active', pumpActive);
    btn.setAttribute('aria-pressed', String(pumpActive));
  }
  const label = $('pump-toggle-text');
  if (label) label.textContent = pumpActive ? 'ON' : 'OFF';
  const stateLabel = $('pump-state');
  if (stateLabel) stateLabel.textContent = pumpActive ? 'On' : 'Off';
}
$('pump-toggle').addEventListener('click', () => {
  const next = !pumpActive;
  setPumpVisual(next);
  send({ type: 'pump', on: next }, true);
});

// Switch button event listeners
$('enable').addEventListener('click', () => {
  setControlsVisual(true);
  keyboard.reset();
  send({ type: 'control', command: 'enable' }, true);
  render();
});
$('alignment-check').addEventListener('click', () => {
  if (window.confirm('Confirm you have checked that the camera and nozzle move together in the shown direction, and that a short stationary water spray is safe in the current area. This records your operating check; it does not automatically calibrate hardware.')) {
    send({ type: 'readiness', command: 'confirm_alignment' }, true);
  }
});
$('release').addEventListener('click', () => {
  setControlsVisual(false);
  keyboard.reset(); drive.stop(); servo.stop();
  send({ type: 'control', command: 'release' }, true);
  render();
});
const stopRobot = () => {
  setControlsVisual(false);
  keyboard.reset(); drive.stop(); servo.stop();
  send({ type: 'system', command: 'stop' }, true);
  render();
};
$('stop').addEventListener('click', stopRobot);
$('manual-mode').addEventListener('click', () => {
  setModeVisual('manual');
  keyboard.reset(); drive.stop(); servo.stop();
  send({ type: 'mode', value: 'manual' }, true);
});
$('auto-mode').addEventListener('click', () => {
  setModeVisual('auto');
  keyboard.reset(); drive.stop(); servo.stop();
  send({ type: 'mode', value: 'auto' }, true);
});
$('speed').addEventListener('input', () => { preferredDriveSpeed = Number($('speed').value); $('speed-value').textContent = `${Math.round(preferredDriveSpeed * 100)}%`; });

// Drive buttons (Press down to move, release to stop immediately)
for (const button of document.querySelectorAll('[data-drive]')) {
  const dir = button.dataset.drive;
  button.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    event.preventDefault();
    drive.start(dir);
  });
  button.addEventListener('pointerup', event => { event.preventDefault(); drive.stop(); });
  button.addEventListener('pointercancel', event => { event.preventDefault(); drive.stop(); });
  button.addEventListener('pointerleave', event => { event.preventDefault(); drive.stop(); });
  button.addEventListener('contextmenu', event => event.preventDefault());
}

// Servo buttons (Press down to move, release to stop immediately)
for (const button of document.querySelectorAll('[data-servo]')) {
  const dir = button.dataset.servo;
  button.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    event.preventDefault();
    servo.start(dir);
  });
  button.addEventListener('pointerup', event => { event.preventDefault(); servo.stop(); });
  button.addEventListener('pointercancel', event => { event.preventDefault(); servo.stop(); });
  button.addEventListener('pointerleave', event => { event.preventDefault(); servo.stop(); });
  button.addEventListener('contextmenu', event => event.preventDefault());
}

$('vision-start').addEventListener('click', () => { $('vision-summary').textContent = 'Starting detection…'; send({ type: 'vision', command: 'start', model_id: $('model-select').value }, true); });
$('vision-stop').addEventListener('click', () => { detections = null; $('vision-summary').textContent = 'Detection paused'; send({ type: 'vision', command: 'stop' }, true); });
$('model-select').addEventListener('change', () => { if (!state.stopped) notify('Stop Robo before changing models.'); render(); });
$('video-connect').addEventListener('click', () => videoSource ? video.connect(videoSource).catch(error => notify(error.message)) : refreshSources().catch(error => notify(error.message)));
$('refresh').addEventListener('click', () => refreshSources().catch(error => notify(error.message)));
$('shutdown').addEventListener('click', () => {
  if (window.confirm('Stop all robot actions and shut down the Pi server script? You will need to start the script on the Pi again.')) send({ type: 'system', command: 'shutdown' }, true);
});

// Global window event listeners
window.addEventListener('pointerup', () => { drive.stop(); servo.stop(); });
window.addEventListener('keydown', event => keyboard.down(event));
window.addEventListener('keyup', event => keyboard.up(event));
window.addEventListener('blur', () => { keyboard.reset(); drive.stop(); servo.stop(); });
document.addEventListener('visibilitychange', () => { if (document.hidden) { keyboard.reset(); drive.stop(); servo.stop(); } });
window.addEventListener('pagehide', () => { keyboard.reset(); drive.stop(); servo.stop(); send({ type: 'control', command: 'release' }); video.stop(false); });

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
function finishChat(text, action, speech, chatMode) {
  const requestId = pendingChat?.id;
  if (requestId) pending.delete(requestId);
  pendingChat = null;
  const article = appendChat('Robo', text);
  updateChatStatus(article, action, speech);
  if (requestId && speech === 'pending') pendingSpeech.set(requestId, { article, action });
  $('chat-status').textContent = chatMode === 'local_basic' ? 'Local chat · no API key needed.' : chatMode === 'llm' ? 'LLM connected · ready for your next message.' : 'Ready for your next message.';
  render();
}
$('chat-form').addEventListener('submit', event => {
  event.preventDefault();
  const message = $('chat-input').value.trim();
  if (pendingChat && (Date.now() - pendingChat.created > 5000)) {
    pendingChat = null;
  }
  if (!message || pendingChat) return;
  appendChat('You', message);
  $('chat-input').value = '';
  if (!connected()) {
    appendChat('Robo', 'Backend is offline. Start the backend server (port 8100) to chat with Robo.');
    return;
  }
  const id = send({ type: 'chat', message }, true);
  if (!id) return;
  pendingChat = { id, created: Date.now() };
  $('chat-status').textContent = 'Robo is thinking…';
  render();
});
$('chat-input').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); $('chat-form').requestSubmit(); } });

const context = $('overlay').getContext('2d');
let overlayRunning = false;
function drawOverlay() {
  const canvas = $('overlay'), stage = $('video-stage');
  const width = stage.clientWidth, height = stage.clientHeight, ratio = window.devicePixelRatio || 1;
  if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) { canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio); }
  context.setTransform(ratio, 0, 0, ratio, 0, 0); context.clearRect(0, 0, width, height);

  if (!videoConnected && !detections) {
    overlayRunning = false;
    return;
  }

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
  if (videoConnected || detections) {
    overlayRunning = true;
    requestAnimationFrame(drawOverlay);
  } else {
    overlayRunning = false;
  }
}
function requestOverlay() {
  if (!overlayRunning) {
    overlayRunning = true;
    requestAnimationFrame(drawOverlay);
  }
}

// Render initial UI state immediately
render();

// Start connection immediately
connectSocket();
