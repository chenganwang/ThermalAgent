import test from 'node:test';
import assert from 'node:assert/strict';

import { adminErrorMessage, booleanState, healthMeta } from './api/contracts.js';

test('健康状态不会把 unknown 或 disabled 显示为绿色健康', () => {
  assert.equal(healthMeta('healthy').color, 'success');
  assert.equal(healthMeta('unknown').color, 'warning');
  assert.equal(healthMeta('disabled').label, '未启用');
  assert.notEqual(healthMeta('disabled').label, '健康');
});

test('四态布尔字段明确区分未检查', () => {
  assert.equal(booleanState(true), '是');
  assert.equal(booleanState(false), '否');
  assert.equal(booleanState(null), '未检查');
});

test('Admin 错误状态映射为安全用户提示', () => {
  assert.match(adminErrorMessage({ statusCode: 401 }), /重新输入/);
  assert.match(adminErrorMessage({ statusCode: 503 }), /暂不可用/);
  assert.match(adminErrorMessage({ statusCode: 412, code: 'ADMIN_CONFIG_VERSION_CONFLICT' }), /重新 dry-run/);
  assert.match(adminErrorMessage({ statusCode: 401, code: 'ADMIN_CONFIG_WRITE_AUTH_INVALID' }), /写凭据/);
});
