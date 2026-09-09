/** Holding a direction refreshes a short backend lease; releasing always sends zero. */
export class HoldDrive {
  constructor({ send, canDrive, speed, onChange = () => {}, interval = setInterval, cancel = clearInterval }) {
    Object.assign(this, { send, canDrive, speed, onChange, interval, cancel });
    this.direction = null;
    this.timer = null;
  }
  start(direction) {
    if (!['forward', 'backward', 'left', 'right'].includes(direction) || !this.canDrive()) return false;
    if (direction === this.direction) return true;
    this.stop();
    this.direction = direction;
    this.onChange(direction);
    this.send({ type: 'drive', direction, speed: this.speed() });
    this.timer = this.interval(() => {
      if (!this.canDrive()) return this.stop();
      this.send({ type: 'drive', direction: this.direction, speed: this.speed() });
    }, 100);
    return true;
  }
  stop() {
    if (this.timer !== null) this.cancel(this.timer);
    this.timer = null;
    const wasMoving = this.direction !== null;
    this.direction = null;
    this.onChange(null);
    if (wasMoving) this.send({ type: 'drive', direction: 'stop', speed: 0 });
  }
}

/** Keyboard movement always needs a fresh press; cancelled holds never replay. */
export class DriveKeys {
  constructor({ drive, canDrive, onStop, onBlocked = () => {} }) {
    Object.assign(this, { drive, canDrive, onStop, onBlocked });
    this.heldKey = null;
  }
  down(event) {
    if (event.code === 'Escape') {
      event.preventDefault(); this.reset(); this.onStop(); return;
    }
    const direction = { KeyW: 'forward', ArrowUp: 'forward', KeyS: 'backward', ArrowDown: 'backward',
      KeyA: 'left', ArrowLeft: 'left', KeyD: 'right', ArrowRight: 'right' }[event.code];
    if (!direction || event.repeat || event.ctrlKey || event.metaKey || event.altKey) return;
    const field = event.target?.closest?.('input,textarea,select,[contenteditable=true]');
    // WASD still works after adjusting speed; arrows retain the slider's normal behavior.
    if (field && (field.type !== 'range' || event.code.startsWith('Arrow'))) return;
    event.preventDefault();
    if (!this.canDrive()) { this.onBlocked(); return; }
    if (this.drive.start(direction)) this.heldKey = event.code;
  }
  up(event) {
    if (event.code === this.heldKey) { event.preventDefault(); this.reset(); }
  }
  buttonDown(event, direction) {
    if (!['Space', 'Enter'].includes(event.code)) return;
    event.preventDefault();
    if (!event.repeat && !event.ctrlKey && !event.metaKey && !event.altKey) this.drive.start(direction);
  }
  buttonUp(event) {
    if (['Space', 'Enter'].includes(event.code)) { event.preventDefault(); this.reset(); }
  }
  reset() { this.heldKey = null; this.drive.stop(); }
}

export function driveSpeed(value, readiness = {}) {
  const requested = Number(value);
  const maximum = readiness.limited && Number.isFinite(readiness.max_speed) ? readiness.max_speed : 0.6;
  return Math.max(0, Math.min(Number.isFinite(requested) ? requested : 0, maximum));
}

export function containedRectangle(containerWidth, containerHeight, sourceWidth, sourceHeight) {
  if (![containerWidth, containerHeight, sourceWidth, sourceHeight].every(n => Number.isFinite(n) && n > 0)) return null;
  const scale = Math.min(containerWidth / sourceWidth, containerHeight / sourceHeight);
  const width = sourceWidth * scale, height = sourceHeight * scale;
  return { x: (containerWidth - width) / 2, y: (containerHeight - height) / 2, width, height };
}

export function validBox(box) {
  return Array.isArray(box) && box.length === 4 && box.every(v => Number.isFinite(v) && v >= 0 && v <= 1) && box[2] > box[0] && box[3] > box[1];
}

/** Each output follows its own reported readiness; missing parts do not disable healthy ones. */
export function controlAvailability(state, { online = false, owned = false, hidden = false } = {}) {
  const fresh = state.pi?.connected === true && Number(state.pi.age_ms ?? Infinity) < 1000;
  const ready = state.readiness || {};
  const anotherOwner = !!state.owner_session_id && !owned;
  const connectionReason = !online ? 'Backend offline. Wait for it to reconnect.'
    : !state.pi?.connected ? 'Pi offline. Start the Pi API and wait for it to connect.'
    : !fresh ? 'Pi status is stale. Wait for fresh readings.'
    : hidden ? 'Return to this tab to use the controls.'
    : anotherOwner ? 'Another operator has control. They must disable their controls first.' : '';
  const gateReason = connectionReason || (!owned || state.stopped !== false ? 'Click Enable controls first.'
    : state.mode !== 'manual' ? 'Auto mode is selected. Select Manual, then Enable controls to use these buttons.' : '');
  const manual = !gateReason;
  const enableReason = connectionReason || (ready.resume?.available !== true ? ready.resume?.reason || 'Waiting for Pi readiness.'
    : state.mode === 'auto' && ready.auto?.available !== true ? ready.auto?.reason || 'Auto is not ready.'
    : owned && state.stopped === false ? 'Controls are already enabled.' : '');
  const reasons = Object.fromEntries(['drive', 'servo', 'pump'].map(name => [name,
    gateReason || (ready[name]?.available === true ? ready[name]?.reason || '' : ready[name]?.reason || 'Waiting for component readiness.')]));
  return {
    fresh, manual, gateReason, enableReason, reasons,
    manualMode: !connectionReason,
    drive: manual && ready.drive?.available === true,
    servo: manual && ready.servo?.available === true,
    pump: manual && ready.pump?.available === true,
    enable: !enableReason,
  };
}
