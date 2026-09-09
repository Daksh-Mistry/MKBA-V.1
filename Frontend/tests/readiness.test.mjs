import test from 'node:test';
import assert from 'node:assert/strict';
import { controlAvailability, driveSpeed } from '../public/control.js';

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

test('one enable action works for unowned and stopped manual controls; auto needs prerequisites', () => {
  assert.equal(controlAvailability({ ...state, stopped: true }, { online: true }).enable, true);
  assert.equal(controlAvailability({ ...state, stopped: true }, owner).enable, true);
  assert.equal(controlAvailability(state, owner).enable, false);
  assert.equal(controlAvailability({ ...state, stopped: true, mode: 'auto' }, owner).enable, false);
  assert.equal(controlAvailability({ ...state, stopped: true, mode: 'auto', readiness: { resume: { available: true }, auto: { available: true } } }, owner).enable, true);
  assert.equal(controlAvailability({ ...state, stopped: true, readiness: { resume: { available: false } } }, owner).enable, false);
});

test('gate explanations identify connection, ownership, stopped and component reasons', () => {
  assert.match(controlAvailability(state).gateReason, /Backend offline/);
  assert.match(controlAvailability({ ...state, pi: { connected: false } }, owner).gateReason, /Pi offline/);
  assert.match(controlAvailability({ ...state, pi: { connected: true, age_ms: 1200 } }, owner).gateReason, /stale/);
  const viewer = controlAvailability({ ...state, owner_session_id: 'another' }, { online: true });
  assert.equal(viewer.enable, false);
  assert.equal(viewer.pump, false);
  assert.match(viewer.reasons.pump, /Another operator/);
  const stopped = controlAvailability({ ...state, stopped: true }, owner);
  assert.equal(stopped.pump, false);
  assert.match(stopped.reasons.pump, /Enable controls/);
  const cooling = controlAvailability({ ...state, readiness: { ...state.readiness,
    pump: { available: false, reason: 'Pump cooling down: 2 seconds', cooldown_ms: 2000 } } }, owner);
  assert.equal(cooling.pump, false);
  assert.equal(cooling.servo, true);
  assert.match(cooling.reasons.pump, /cooling down/);
});

test('limited drive remains usable and caps speed until normal readiness returns', () => {
  const limited = { available: true, limited: true, max_speed: 0.2, max_hold_ms: 2000, reason: 'IR inputs unverified: manual test only' };
  const limitedState = { ...state, readiness: { ...state.readiness, drive: limited } };
  assert.equal(controlAvailability(limitedState, owner).drive, true);
  assert.match(controlAvailability(limitedState, owner).reasons.drive, /IR inputs unverified/);
  assert.equal(driveSpeed(0.6, limited), 0.2);
  assert.equal(driveSpeed(0.1, limited), 0.1);
  assert.equal(driveSpeed(0.6, { available: true }), 0.6);
  assert.equal(controlAvailability({ ...limitedState, readiness: { ...limitedState.readiness,
    drive: { ...limited, available: false, reason: 'Release the direction before the next test' } } }, owner).drive, false);
});

test('unowned auto mode can return to stopped manual mode even when auto cannot enable', () => {
  const auto = { ...state, mode: 'auto', stopped: true, owner_session_id: null };
  const viewer = controlAvailability(auto, { online: true });
  assert.equal(viewer.enable, false);
  assert.equal(viewer.manualMode, true);
  assert.equal(viewer.drive, false);
  assert.equal(controlAvailability({ ...auto, owner_session_id: 'another' }, { online: true }).manualMode, false);
  assert.equal(controlAvailability({ ...auto, pi: { connected: false } }, { online: true }).manualMode, false);
});
