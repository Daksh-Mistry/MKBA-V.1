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
  const manual = online && owned && fresh && !state.stopped && state.mode === 'manual' && !hidden;
  const ready = state.readiness || {};
  return {
    fresh, manual,
    drive: manual && ready.drive?.available === true,
    servo: manual && ready.servo?.available === true,
    pump: manual && ready.pump?.available === true,
    resume: online && owned && fresh && state.stopped === true && ready.resume?.available === true && (state.mode !== 'auto' || ready.auto?.available === true),
  };
}
