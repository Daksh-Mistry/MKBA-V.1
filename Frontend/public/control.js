/** Drive control: sends motion command ONCE on start, and stop command ONCE on release. */
export class HoldDrive {
  constructor({ send, canDrive, speed, onChange = () => {} }) {
    Object.assign(this, { send, canDrive, speed, onChange });
    this.direction = null;
  }
  start(direction) {
    if (!['forward', 'backward', 'left', 'right'].includes(direction) || !this.canDrive()) return false;
    if (direction === this.direction) return true;
    this.direction = direction;
    this.onChange(direction);
    this.send({ type: 'drive', direction, speed: this.speed() });
    return true;
  }
  stop() {
    if (this.direction !== null) {
      this.direction = null;
      this.onChange(null);
      this.send({ type: 'drive', direction: 'stop', speed: 0 });
    }
  }
}

/** Servo face control: sends 5° step immediately, repeats at 2 Hz while held, and stop on release. */
export class HoldServo {
  constructor({ send, canDrive, onChange = () => {} }) {
    Object.assign(this, { send, canDrive, onChange });
    this.direction = null;
    this.repeatInterval = null;
  }
  start(direction) {
    if (direction === 'center') {
      if (!this.canDrive()) return false;
      this.send({ type: 'servo', direction: 'center' });
      return true;
    }
    if (!['up', 'down', 'left', 'right'].includes(direction) || !this.canDrive()) return false;
    if (direction === this.direction) return true;
    this.stop();
    this.direction = direction;
    this.onChange(direction);
    // Send 1st step immediately (5 degrees)
    this.send({ type: 'servo', direction, degrees: 5 });
    // When kept pressed, send at 2 messages per second (every 500ms)
    this.repeatInterval = setInterval(() => {
      if (this.direction) {
        this.send({ type: 'servo', direction: this.direction, degrees: 5 });
      }
    }, 500);
    return true;
  }
  stop() {
    if (this.repeatInterval) {
      clearInterval(this.repeatInterval);
      this.repeatInterval = null;
    }
    if (this.direction !== null) {
      this.direction = null;
      this.onChange(null);
      this.send({ type: 'servo', direction: 'stop' });
    }
  }
}

/** Keyboard movement: WASD holds to drive, Arrow keys hold to step servo at 2 Hz, stop on release. */
export class KeyboardController {
  constructor({ drive, servo, canDrive, onStop, onBlocked = () => {} }) {
    Object.assign(this, { drive, servo, canDrive, onStop, onBlocked });
    this.heldDriveKeys = new Set();
    this.heldServoKeys = new Set();
  }
  _servoMap(event) {
    const map = {
      ArrowUp: 'up',
      ArrowDown: 'down',
      ArrowLeft: 'left',
      ArrowRight: 'right',
      KeyC: 'center',
      c: 'center',
      C: 'center',
    };
    return map[event.code] || map[event.key];
  }
  _driveMap(event) {
    const map = {
      KeyW: 'forward', w: 'forward', W: 'forward',
      KeyS: 'backward', s: 'backward', S: 'backward',
      KeyA: 'left', a: 'left', A: 'left',
      KeyD: 'right', d: 'right', D: 'right',
    };
    return map[event.code] || map[event.key];
  }
  down(event) {
    if (event.code === 'Escape') {
      event.preventDefault(); this.reset(); this.onStop(); return;
    }
    const field = event.target?.closest?.('input,textarea,select,[contenteditable=true]');
    if (field && (field.type !== 'range' || !event.code.startsWith('Arrow'))) return;

    // Arrow keys: locked to Servo face controls
    const servoDir = this._servoMap(event);
    if (servoDir) {
      event.preventDefault();
      if (event.repeat || event.ctrlKey || event.metaKey || event.altKey) return;
      if (!this.canDrive()) { this.onBlocked(); return; }
      this.heldServoKeys.add(event.code || event.key);
      if (this.servo) this.servo.start(servoDir);
      return;
    }

    // WASD: locked to Drive motors
    const driveDir = this._driveMap(event);
    if (driveDir) {
      event.preventDefault();
      if (event.repeat || event.ctrlKey || event.metaKey || event.altKey) return;
      if (!this.canDrive()) { this.onBlocked(); return; }
      this.heldDriveKeys.add(event.code || event.key);
      if (this.drive) this.drive.start(driveDir);
      return;
    }
  }
  up(event) {
    const servoDir = this._servoMap(event);
    if (servoDir) {
      event.preventDefault();
      this.heldServoKeys.delete(event.code || event.key);
      if (this.heldServoKeys.size === 0 && this.servo) {
        this.servo.stop();
      }
      return;
    }
    const driveDir = this._driveMap(event);
    if (driveDir) {
      event.preventDefault();
      this.heldDriveKeys.delete(event.code || event.key);
      if (this.heldDriveKeys.size === 0 && this.drive) {
        this.drive.stop();
      }
      return;
    }
  }
  buttonDown(event, direction) {
    if (!['Space', 'Enter'].includes(event.code)) return;
    event.preventDefault();
    if (!event.repeat && !event.ctrlKey && !event.metaKey && !event.altKey && this.drive) this.drive.start(direction);
  }
  buttonUp(event) {
    if (['Space', 'Enter'].includes(event.code)) { event.preventDefault(); this.reset(); }
  }
  reset() {
    this.heldDriveKeys.clear();
    this.heldServoKeys.clear();
    if (this.drive) this.drive.stop();
    if (this.servo) this.servo.stop();
  }
}
export const DriveKeys = KeyboardController;

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

export function controlAvailability(state, { online = false } = {}) {
  const fresh = state.pi?.connected === true;
  const reasons = { drive: '', servo: '', pump: '' };
  return {
    fresh: true,
    manual: true,
    gateReason: '',
    enableReason: '',
    reasons,
    manualMode: true,
    drive: true,
    servo: true,
    pump: true,
    enable: true,
  };
}
