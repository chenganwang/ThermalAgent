import assert from 'node:assert/strict';
import test from 'node:test';

import { formatDurationMs } from './simulationPresentation.js';


test('duration formatter bounds floating point noise without changing raw milliseconds', () => {
  assert.equal(formatDurationMs(33), '33 ms');
  assert.equal(formatDurationMs(33.00000000004), '33 ms');
  assert.equal(formatDurationMs(33.36), '33.4 ms');
  assert.equal(formatDurationMs(1500), '1.5 s');
  assert.equal(formatDurationMs(null), null);
  assert.equal(formatDurationMs(Number.NaN), null);
  assert.equal(formatDurationMs(Number.POSITIVE_INFINITY), null);
});

