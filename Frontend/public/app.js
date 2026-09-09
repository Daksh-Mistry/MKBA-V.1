import { HoldDrive, DriveKeys, driveSpeed, containedRectangle, validBox, controlAvailability } from './control.js';
import { PiVideo } from './video.js';

const $ = id => document.getElementById(id);
let socket, sessionId, state = {}, sequence = 0, reconnectTimer, heartbeatTimer, signedIn = false;
let videoSource, detections = null, detectionsAt = 0, videoConnected = false, toastTimer;
let lastReceived = 0, retryCount = 0, previousMode = null, pendingChat = null;
let authenticationRevision = 0;
let preferredDriveSpeed = Number($('speed').value);
const pending = new Map();
const pendingSpeech = new Map();
const connected = () => socket?.readyState === WebSocket.OPEN && !!sessionId;
const ownsControl = () => connected() && state.owner_session_id === sessionId;
const controls = () => controlAvailability(state, { online: connected(), owned: ownsControl(), hidden: document.hidden });
const canDrive = () => controls().drive;

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
const drive = new HoldDrive({ send, canDrive, speed: () => driveSpeed(preferredDriveSpeed, state.readiness?.drive), onChange: direction => {
  document.querySelectorAll('[data-drive]').forEach(button => button.classList.toggle('is-held', button.dataset.drive === direction));
}});
const keyboard = new DriveKeys({ drive, canDrive, onStop: () => stopRobot(), onBlocked: () => notify(controls().reasons.drive) });
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
  if (!canDrive()) keyboard.reset();
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
  $('stop').disabled = !online;
  $('enable').disabled = !available.enable;
  $('enable').title = available.enableReason;
  $('enable').textContent = owned && !state.stopped ? 'Controls enabled' : 'Enable controls';
  $('release').disabled = !owned;
  $('release').title = owned ? 'Stop the robot and let another browser enable controls.' : 'This browser does not control the robot.';
  $('manual-mode').disabled = !available.manualMode;
  $('manual-mode').title = available.manualMode ? 'Select manual operation. Click Enable controls afterwards.' : available.enableReason;
  $('auto-mode').disabled = !owned || !piFresh;
  $('manual-mode').setAttribute('aria-pressed', state.mode !== 'auto');
  $('auto-mode').setAttribute('aria-pressed', state.mode === 'auto');
  for (const [kind, enabled] of [['drive', available.drive], ['servo', available.servo]]) {
    document.querySelectorAll(`[data-${kind}]`).forEach(button => {
      button.disabled = !enabled; button.title = available.reasons[kind];
    });
  }
  $('pump-on').disabled = !available.pump;
  $('pump-on').title = available.reasons.pump;
  $('pump-off').disabled = !owned || !available.fresh || !pi.hardware?.pump?.available;
  const limitedDrive = readiness.drive?.limited === true;
  $('speed').max = String(limitedDrive ? readiness.drive.max_speed ?? 0.2 : 0.6);
  $('speed').value = String(driveSpeed(preferredDriveSpeed, readiness.drive));
  $('speed-value').textContent = `${Math.round(Number($('speed').value) * 100)}%`;
  $('drive-note').textContent = limitedDrive ? readiness.drive.reason || 'IR inputs unverified: manual driving is limited to short, slow tests.' : available.drive ? 'Hold WASD, arrow keys or a direction button to move.' : available.reasons.drive;
  $('pump-note').textContent = available.pump ? 'One short burst per click.' : available.reasons.pump;
  $('alignment-check').disabled = !owned || !state.stopped || !readiness.servo?.available || !readiness.pump?.available || readiness.alignment_confirmed === true;
  $('alignment-check').textContent = readiness.alignment_confirmed ? 'Operating check recorded' : 'Confirm camera / nozzle check';
  $('readiness-summary').textContent = ['drive', 'servo', 'pump', 'auto'].map(name =>
    `${name === 'servo' ? 'Face' : name[0].toUpperCase() + name.slice(1)}: ${readiness[name]?.available ? readiness[name]?.reason || 'ready' : readiness[name]?.reason || 'waiting for Pi status'}`).join('\n');
  $('vision-start').disabled = !owned || !ml.connected || !$('model-select').value;
  $('vision-stop').disabled = !owned || !ml.connected;
  $('model-select').disabled = !owned || !state.stopped;
  $('chat-input').disabled = !online;
  $('chat-send').disabled = !online || !!pendingChat;
  $('speech-stop').disabled = !online;
  $('shutdown').disabled = !owned;
  $('ownership-label').textContent = owned ? state.stopped ? 'Stopped' : 'Controls enabled' : state.owner_session_id ? 'Another operator' : 'Viewing';
  let summary = available.gateReason || 'Controls enabled. Hold a direction to move; release it to stop.';
  if (online && available.fresh && owned && !state.stopped && state.mode === 'auto') summary = 'Auto is active. Stop robot is always available.';
  else if (!available.gateReason) {
    const issues = ['drive', 'servo', 'pump'].filter(name => !available[name]).map(name => `${name === 'servo' ? 'Face' : name[0].toUpperCase() + name.slice(1)}: ${available.reasons[name]}`);
    if (issues.length) summary += ` ${issues.join(' ')}`;
    if (limitedDrive) summary += ` ${$('drive-note').textContent}`;
  } else if ((state.stopped || !owned) && online && available.fresh && !available.enable && (!state.owner_session_id || owned)) summary = available.enableReason;
  if (simulated) summary = `SIMULATION · No physical robot. ${summary}`;
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
function renderSensors(fresh) {
  const sensors = state.sensors || {};
  const cells = [];
  for (const [group, items] of [['IR', sensors.ir], ['Flame', sensors.flame]]) {
    const entries = Array.isArray(items) ? items : items && typeof items === 'object' ? Object.entries(items).map(([position, value]) => ({ position, ...(typeof value === 'object' ? value : { detected: value }) })) : [];
    for (const [index, item] of entries.entries()) {
      const valid = fresh && item.valid === true;
      const detected = group === 'IR' ? item.blocked : item.detected ?? item.active;
      const inputUnverified = group === 'IR' && sensors.signal_evidence_required && !item.signal_observed;
      const value = valid && !inputUnverified && typeof detected === 'boolean' ? detected ? 'blocked' : 'clear' : 'unknown';
      const cell = document.createElement('div'); cell.className = 'sensor-cell'; cell.dataset.state = value;
      const label = document.createElement('span'); label.className = 'sensor-name'; label.textContent = `${group} · ${String(item.position ?? item.name ?? index + 1).replaceAll('_', ' ')}`;
      const status = document.createElement('span'); status.className = 'sensor-value'; status.textContent = inputUnverified && valid ? 'Input unverified' : value === 'unknown' ? 'Unknown' : detected ? group === 'IR' ? 'Blocked' : 'Signal active' : group === 'IR' ? 'Clear' : 'Signal inactive';
      cell.title = inputUnverified ? 'GPIO is readable but has not changed. Trigger and release this IR sensor to check its signal.' : group === 'Flame' ? 'Digital signal only; this does not prove a sensor is connected or identify a fire.' : 'Clear requires two consecutive clear readings; signal changes do not prove physical attachment.';
      cell.append(label, status); cells.push(cell);
    }
  }
  if (cells.length) $('sensor-grid').replaceChildren(...cells);
  else { const empty = document.createElement('p'); empty.className = 'muted'; empty.textContent = 'Waiting for Pi sensor readings.'; $('sensor-grid').replaceChildren(empty); }
}
function connectSocket() {
  if (!signedIn) return;
  clearTimeout(reconnectTimer);
  keyboard.reset();
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
      activity('Backend connected. Click Enable controls when ready.');
      clearInterval(heartbeatTimer);
      heartbeatTimer = setInterval(() => {
        if (Date.now() - lastReceived > 6000) { keyboard.reset(); next.close(); return; }
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
      if (pendingChat?.id === message.request_id) finishChat(message.text || 'No reply text received.', message.action_status, message.speech_status, message.chat_mode);
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
    keyboard.reset(); sessionId = null; clearInterval(heartbeatTimer); detections = null;
    if (pendingChat) finishChat('Connection interrupted. Your message will not be replayed.', 'interrupted');
    for (const reply of pendingSpeech.values()) updateChatStatus(reply.article, reply.action, 'connection_lost');
    pendingSpeech.clear();
    pending.clear(); state = { ...state, pi: { ...state.pi, connected: false } }; render();
    if (signedIn) reconnectTimer = setTimeout(async () => {
      try { if (!await openLocalSession()) await signOut(false); }
      catch (error) { if (signedIn) { activity(error.message); connectSocket(); } }
    }, Math.min(5000, 1000 * ++retryCount));
  };
  next.onerror = () => {};
}
async function signIn() {
  authenticationRevision += 1;
  signedIn = true;
  $('login-screen').hidden = true; $('console-screen').hidden = false;
  connectSocket();
}
async function signOut(request = true) {
  authenticationRevision += 1;
  keyboard.reset(); send({ type: 'control', command: 'release' });
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
$('enable').addEventListener('click', () => { keyboard.reset(); send({ type: 'control', command: 'enable' }, true); });
$('alignment-check').addEventListener('click', () => {
  if (window.confirm('Confirm you have checked that the camera and nozzle move together in the shown direction, and that a short stationary water spray is safe in the current area. This records your operating check; it does not automatically calibrate hardware.')) {
    send({ type: 'readiness', command: 'confirm_alignment' }, true);
  }
});
$('release').addEventListener('click', () => { keyboard.reset(); send({ type: 'control', command: 'release' }, true); });
const stopRobot = () => { keyboard.reset(); send({ type: 'system', command: 'stop' }, true); };
$('stop').addEventListener('click', stopRobot);
for (const mode of ['manual', 'auto']) $(`${mode}-mode`).addEventListener('click', () => { keyboard.reset(); send({ type: 'mode', value: mode }, true); });
$('speed').addEventListener('input', () => { preferredDriveSpeed = Number($('speed').value); $('speed-value').textContent = `${Math.round(preferredDriveSpeed * 100)}%`; });
for (const button of document.querySelectorAll('[data-drive]')) {
  button.addEventListener('pointerdown', event => { if (event.button !== 0) return; event.preventDefault(); if (drive.start(button.dataset.drive)) button.setPointerCapture(event.pointerId); });
  for (const kind of ['pointerup', 'pointercancel', 'lostpointercapture']) button.addEventListener(kind, () => keyboard.reset());
  button.addEventListener('contextmenu', event => event.preventDefault());
  button.addEventListener('keydown', event => keyboard.buttonDown(event, button.dataset.drive));
  button.addEventListener('keyup', event => keyboard.buttonUp(event));
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
window.addEventListener('keydown', event => keyboard.down(event));
window.addEventListener('keyup', event => keyboard.up(event));
window.addEventListener('blur', () => keyboard.reset());
document.addEventListener('visibilitychange', () => { if (document.hidden) keyboard.reset(); });
window.addEventListener('pagehide', () => { keyboard.reset(); send({ type: 'control', command: 'release' }); video.stop(false); });

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
async function openLocalSession() {
  const revision = authenticationRevision;
  const session = await fetch('/session', { credentials: 'same-origin' });
  // A later sign-out or sign-in wins over a delayed automatic renewal.
  if (revision !== authenticationRevision) return true;
  if (session.ok) { await signIn(); return true; }
  if (session.status !== 401) throw new Error('The frontend session service is unavailable.');
  // The server grants this only to the local computer with local access enabled.
  // LAN deployments retain the ordinary token login form.
  const local = await fetch('/login/local', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}', credentials: 'same-origin' });
  if (revision !== authenticationRevision) return true;
  if (local.ok) { await signIn(); return true; }
  return false;
}
$('local-connect').hidden = !['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
$('local-connect').addEventListener('click', async () => {
  $('login-error').textContent = ''; $('local-connect').disabled = true;
  try { if (!await openLocalSession()) $('login-error').textContent = 'Automatic local access is unavailable for this server. Use its protected login below.'; }
  catch { $('login-error').textContent = 'The frontend server is unavailable.'; }
  finally { $('local-connect').disabled = false; }
});
openLocalSession().catch(() => { $('login-error').textContent = 'The frontend server is unavailable.'; });
