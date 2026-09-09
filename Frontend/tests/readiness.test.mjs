import test from 'node:test';
import assert from 'node:assert/strict';
import { controlAvailability, driveSpeed } from '../public/control.js';

test('controlAvailability returns enabled controls for direct operation in closed environment', () => {
  const available = controlAvailability({});
  assert.equal(available.manual, true);
  assert.equal(available.drive, true);
  assert.equal(available.servo, true);
  assert.equal(available.pump, true);
  assert.equal(available.enable, true);
});

test('driveSpeed caps maximum speed when limited by safety or profile', () => {
  const limited = { limited: true, max_speed: 0.2 };
  assert.equal(driveSpeed(0.6, limited), 0.2);
  assert.equal(driveSpeed(0.15, limited), 0.15);
  assert.equal(driveSpeed(0.6, { limited: false }), 0.6);
  assert.equal(driveSpeed(0.5, {}), 0.5);
  assert.equal(driveSpeed(-0.1, {}), 0);
});
