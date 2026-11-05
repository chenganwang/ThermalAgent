import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildConfigPatchPayload,
  buildConfigRollbackPayload,
  canApplyPreview,
  mutationFingerprint,
} from './configFlow.js';


test('配置修改 payload 保留严格布尔、原因和 expected_version', () => {
  const payload = buildConfigPatchPayload({
    key: 'report_visible',
    value: false,
    expectedVersion: 7,
    reason: '  浏览器验收  ',
    dryRun: true,
  });
  assert.deepEqual(payload, {
    changes: { report_visible: false },
    expected_version: 7,
    reason: '浏览器验收',
    dry_run: true,
  });
  assert.throws(() => buildConfigPatchPayload({ key: 'report_visible', value: 'false', expectedVersion: 7, reason: 'x', dryRun: true }), /boolean/);
  assert.throws(() => buildConfigPatchPayload({ key: 'report_visible', value: false, expectedVersion: 7, reason: ' ', dryRun: true }), /required/);
});

test('Apply 只有在同一输入的 dry-run 完成后可用', () => {
  const payload = buildConfigPatchPayload({
    key: 'simulation_enabled', value: true, expectedVersion: 2, reason: 'test', dryRun: true,
  });
  const fingerprint = mutationFingerprint(payload);
  const preview = { dry_run: true, side_effects: [], fingerprint };
  assert.equal(canApplyPreview(preview, fingerprint), true);
  assert.equal(canApplyPreview(preview, mutationFingerprint({ ...payload, expected_version: 3 })), false);
  assert.equal(canApplyPreview({ ...preview, dry_run: false }, fingerprint), false);
});

test('Rollback payload 明确目标版本且创建流程仍需 dry-run', () => {
  const payload = buildConfigRollbackPayload({
    targetVersion: 3,
    expectedVersion: 8,
    reason: '恢复稳定配置',
    dryRun: true,
  });
  assert.deepEqual(payload, {
    target_version: 3,
    expected_version: 8,
    reason: '恢复稳定配置',
    dry_run: true,
  });
});
