import test from 'node:test';
import assert from 'node:assert/strict';
import { KeyboardController, HoldDrive, HoldServo } from '../public/control.js';

function fixture() {
  const sent = []; let allowed = true, stops = 0, blocked = 0;
  const drive = new HoldDrive({
    send: message => sent.push(message),
    canDrive: () => allowed,
    speed: () => 0.2
  });
  const servo = new HoldServo({
    send: message => sent.push(message),
    canDrive: () => allowed
  });
  const keys = new KeyboardController({
    drive, servo,
    canDrive: () => allowed,
    onStop: () => stops++,
    onBlocked: () => blocked++
  });
  const event = (code, extra = {}) => ({
    code,
    preventDefault() { this.prevented = true; },
    target: { closest: () => null },
    ...extra
  });
  return { sent, drive, servo, keys, event, allow: value => { allowed = value; }, stops: () => stops, blocked: () => blocked };
}

test('WASD drives forward, backward, left, right and stops on release', () => {
  for (const [code, direction] of Object.entries({ KeyW: 'forward', KeyS: 'backward', KeyA: 'left', KeyD: 'right' })) {
    const f = fixture();
    f.keys.down(f.event(code));
    assert.equal(f.sent.at(-1).type, 'drive');
    assert.equal(f.sent.at(-1).direction, direction);
    f.keys.up(f.event(code));
    assert.equal(f.sent.at(-1).type, 'drive');
    assert.equal(f.sent.at(-1).direction, 'stop');
  }
});

test('Arrow keys move servos up, down, left, right and stop on release', () => {
  for (const [code, direction] of Object.entries({ ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right' })) {
    const f = fixture();
    const ev = f.event(code);
    f.keys.down(ev);
    assert.equal(ev.prevented, true); // Arrow keys call preventDefault so page does not scroll
    assert.equal(f.sent.at(-1).type, 'servo');
    assert.equal(f.sent.at(-1).direction, direction);
    assert.equal(f.sent.at(-1).degrees, 5);
    f.keys.up(f.event(code));
    assert.equal(f.sent.at(-1).type, 'servo');
    assert.equal(f.sent.at(-1).direction, 'stop');
    f.servo.stop(); // Clean up timers
  }
});

test('Holding servo repeats at 2 messages per second (every 500ms)', async () => {
  const f = fixture();
  f.keys.down(f.event('ArrowUp'));
  assert.equal(f.sent.length, 1);
  assert.equal(f.sent[0].type, 'servo');
  assert.equal(f.sent[0].direction, 'up');

  // Wait 550ms: should receive 2nd message
  await new Promise(r => setTimeout(r, 550));
  assert.ok(f.sent.length >= 2, `Expected at least 2 messages, got ${f.sent.length}`);
  assert.equal(f.sent[1].direction, 'up');

  // Releasing stops repeat
  f.keys.up(f.event('ArrowUp'));
  assert.equal(f.sent.at(-1).direction, 'stop');
  const countAfterStop = f.sent.length;

  await new Promise(r => setTimeout(r, 550));
  assert.equal(f.sent.length, countAfterStop);
});

test('Stop, focus loss and Escape cancel held keys', () => {
  const f = fixture();
  f.keys.down(f.event('KeyW'));
  f.keys.down(f.event('Escape'));
  assert.equal(f.sent.at(-1).direction, 'stop');
  assert.equal(f.stops(), 1);
});

test('Typing in input fields is ignored', () => {
  const f = fixture();
  const textareaEvent = f.event('KeyW', { target: { closest: () => ({ type: 'textarea' }) } });
  f.keys.down(textareaEvent);
  assert.equal(f.sent.length, 0);
});
