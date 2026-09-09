import test from 'node:test';
import assert from 'node:assert/strict';
import { controlAvailability } from '../public/control.js';

const state = { pi: { connected: true, age_ms: 50 }, mode: 'manual', stopped: false,
  readiness: { resume: { available: true }, drive: { available: false }, servo: { available: true }, pump: { available: true }, auto: { available: false } } };
const owner = { online: true, owned: true };

test('missing motor/sensor readiness does not disable healthy face or pump', () => {
  const available = controlAvailability(state, owner);
  assert.equal(available.drive, false);
  assert.equal(available.servo, true);
  assert.equal(available.pump, true);
});

test('missing readiness, stale state, viewers and hidden pages cannot actuate', () => {
  for (const available of [controlAvailability({ ...state, readiness: {} }, owner),
    controlAvailability({ ...state, pi: { connected: true, age_ms: 1100 } }, owner),
    controlAvailability(state, { online: true, owned: false }),
    controlAvailability(state, { ...owner, hidden: true })]) {
    assert.equal(available.drive, false);
    assert.equal(available.servo, false);
    assert.equal(available.pump, false);
  }
});

test('manual resume works independently while auto resume requires all prerequisites', () => {
  assert.equal(controlAvailability({ ...state, stopped: true }, owner).resume, true);
  assert.equal(controlAvailability({ ...state, stopped: true, mode: 'auto' }, owner).resume, false);
  assert.equal(controlAvailability({ ...state, stopped: true, mode: 'auto', readiness: { resume: { available: true }, auto: { available: true } } }, owner).resume, true);
  assert.equal(controlAvailability({ ...state, stopped: true, readiness: { resume: { available: false } } }, owner).resume, false);
});
