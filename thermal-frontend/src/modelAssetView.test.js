import assert from 'node:assert/strict';
import test from 'node:test';

import {
  formatFileSize,
  modelAssetCanSubmitReview,
  normalizeModelAssetList,
  publicModelAssetView,
  validateModelAssetFile,
} from './modelAssetView.js';

test('列表响应以后端返回的格式和大小限制为准', () => {
  const normalized = normalizeModelAssetList({
    assets: [{ asset_id: 'asset-1' }],
    upload_enabled: false,
    max_file_size_mb: 80,
    allowed_extensions: ['.SLX', '.STEP'],
  });
  assert.equal(normalized.assets.length, 1);
  assert.equal(normalized.upload_enabled, false);
  assert.equal(normalized.max_file_size_mb, 80);
  assert.deepEqual(normalized.allowed_extensions, ['.slx', '.step']);
});

test('后端未返回限制时只使用 100 MB 安全大小 fallback', () => {
  const normalized = normalizeModelAssetList({});
  assert.equal(normalized.max_file_size_mb, 100);
  assert.equal(normalized.upload_enabled, false);
  assert.deepEqual(normalized.allowed_extensions, []);
});

test('文件大小和扩展名在上传前预检', () => {
  const limits = { max_file_size_mb: 100, allowed_extensions: ['.slx', '.step'] };
  assert.equal(validateModelAssetFile({ name: 'model.slx', size: 1024 }, limits), '');
  assert.match(validateModelAssetFile({ name: 'script.m', size: 1024 }, limits), /仅允许上传/);
  assert.match(validateModelAssetFile({ name: 'large.slx', size: 101 * 1024 ** 2 }, limits), /100 MB/);
});

test('公开详情映射不携带 stored_filename、本机路径或 operator 身份', () => {
  const view = publicModelAssetView({
    asset_id: 'asset-1',
    original_filename: 'network.slx',
    sha256: 'abc123',
    status: 'user_uploaded_unvalidated',
    execution_allowed: false,
    operator_notes: '待复核',
    stored_filename: 'internal-name',
    evidence_path: 'C:\\private\\asset',
    operator_identity: 'secret-operator',
  });
  assert.equal(view.asset_id, 'asset-1');
  assert.equal(view.execution_allowed, false);
  assert.equal(view.operator_notes, '待复核');
  assert.equal(Object.hasOwn(view, 'stored_filename'), false);
  assert.equal(Object.hasOwn(view, 'evidence_path'), false);
  assert.equal(Object.hasOwn(view, 'operator_identity'), false);
  assert.doesNotMatch(JSON.stringify(view), /C:\\\\private|secret-operator|internal-name/);
});

test('只有未提交复核的非验证状态可提交', () => {
  assert.equal(modelAssetCanSubmitReview({ status: 'quarantined' }), true);
  assert.equal(modelAssetCanSubmitReview({ status: 'user_uploaded_unvalidated' }), true);
  assert.equal(modelAssetCanSubmitReview({ status: 'pending_operator_review' }), false);
  assert.equal(modelAssetCanSubmitReview({ status: 'approved' }), false);
  assert.equal(modelAssetCanSubmitReview({ status: 'rejected' }), false);
});

test('operator 复核结果可由公开 status 安全派生', () => {
  assert.equal(publicModelAssetView({ status: 'pending_review' }).operator_result, '待 operator 复核');
  assert.equal(publicModelAssetView({ status: 'approved' }).operator_result, '已批准');
  assert.equal(publicModelAssetView({ status: 'rejected' }).operator_result, '已驳回');
});

test('文件大小格式化', () => {
  assert.equal(formatFileSize(1024), '1 KB');
  assert.equal(formatFileSize(2 * 1024 ** 2), '2 MB');
});
