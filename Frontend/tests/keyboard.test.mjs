import test from 'node:test';
import assert from 'node:assert/strict';
import { DriveKeys, HoldDrive } from '../public/control.js';

function fixture() {
  const sent = []; let allowed = true, stops = 0, blocked = 0, tick;
  const drive = new HoldDrive({ send: message => sent.push(message), canDrive: () => allowed,
    speed: () => 0.2, interval: callback => { tick = callback; return 1; }, cancel: () => {} });
  const keys = new DriveKeys({ drive, canDrive: () => allowed, onStop: () => stops++, onBlocked: () => blocked++ });
  const event = (code, extra = {}) => ({ code, preventDefault() { this.prevented = true; }, target: { closest: () => null }, ...extra });
  return { sent, drive, keys, event, tick: () => tick(), allow: value => { allowed = value; }, stops: () => stops, blocked: () => blocked };
}

test('WASD and arrow keys start on a fresh press and stop on release', () => {
  for (const [code, direction] of Object.entries({ KeyW: 'forward', ArrowUp: 'forward', KeyS: 'backward', ArrowDown: 'backward', KeyA: 'left', ArrowLeft: 'left', KeyD: 'right', ArrowRight: 'right' })) {
    const f = fixture();
    f.keys.down(f.event(code));
    assert.equal(f.sent.at(-1).direction, direction);
    f.keys.up(f.event(code));
    assert.equal(f.sent.at(-1).direction, 'stop');
    assert.equal(f.keys.heldKey, null);
  }
});

test('Stop, focus loss and authority loss cancel held keys without replay', () => {
  for (const cancel of [f => f.keys.down(f.event('Escape')), f => f.keys.reset(), f => { f.allow(false); f.tick(); f.keys.reset(); }]) {
    const f = fixture(); f.keys.down(f.event('KeyW')); cancel(f);
    assert.equal(f.sent.at(-1).direction, 'stop');
    assert.equal(f.keys.heldKey, null);
    const before = f.sent.length;
    f.allow(true); f.keys.down(f.event('KeyW', { repeat: true }));
    assert.equal(f.sent.length, before);
    f.keys.down(f.event('KeyW'));
    assert.equal(f.sent.at(-1).direction, 'forward');
  }
});

test('typing and keyboard shortcuts never drive; WASD works after moving the speed slider', () => {
  const f = fixture();
  for (const extra of [{ ctrlKey: true }, { metaKey: true }, { altKey: true },
    { target: { closest: () => ({ type: 'textarea' }) } }, { target: { closest: () => ({ type: 'text' }) } }]) f.keys.down(f.event('KeyW', extra));
  const slider = { target: { closest: () => ({ type: 'range' }) } };
  f.keys.down(f.event('ArrowUp', slider));
  assert.equal(f.sent.length, 0);
  f.keys.down(f.event('KeyW', slider));
  assert.equal(f.sent.at(-1).direction, 'forward');
});

test('blocked controls explain the reason and do not remember the pressed key', () => {
  const f = fixture(); f.allow(false); f.keys.down(f.event('ArrowUp'));
  assert.equal(f.sent.length, 0); assert.equal(f.keys.heldKey, null); assert.equal(f.blocked(), 1);
  f.allow(true); f.keys.down(f.event('ArrowUp', { repeat: true }));
  assert.equal(f.sent.length, 0);
});

test('held Space or Enter cannot restart a stopped direction button', () => {
  for (const code of ['Space', 'Enter']) {
    const f = fixture();
    f.keys.buttonDown(f.event(code), 'left');
    assert.equal(f.sent.at(-1).direction, 'left');
    f.keys.reset(); const before = f.sent.length;
    f.keys.buttonDown(f.event(code, { repeat: true }), 'left');
    assert.equal(f.sent.length, before);
    f.keys.buttonUp(f.event(code));
    assert.equal(f.keys.heldKey, null);
  }
});
