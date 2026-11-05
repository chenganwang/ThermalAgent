import assert from 'node:assert/strict';
import test from 'node:test';
import {
  comparePemResults, createPemStudy, downloadPemImportSource, exportPemCandidates, exportPemReport,
  generatePemDoe, getPemCandidates, getPemResults, getPemStudies, getPemStudy, importPemResults,
} from '../api/client.js';
import { decodeUtf8Import, demoResultRows, demoStudyDefinition, observedChartOption, parseFieldMap, prepareImportPayload, prepareStudyDefinition, provenanceLabel, qualityLabel } from './pemContracts.js';

async function network(action, response = {}) {
  const requests = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => { requests.push({ url, options }); return new Response(JSON.stringify(response), { status: 200 }); };
  try { await action(); return requests; } finally { globalThis.fetch = originalFetch; }
}

test('research definition records electrode, physics, boundary quantities and parameter range sources', () => {
  const original = demoStudyDefinition();
  const { definition, errors } = prepareStudyDefinition(original);
  assert.deepEqual(errors, []);
  assert.equal(definition.parameter_space.length, 8);
  assert.equal(definition.parameter_space.find(item => item.name === 'topology').unit, '1');
  assert.equal(definition.side, 'anode');
  assert.equal(definition.physics_model, 'single_phase');
  assert.ok(definition.parameter_space.every(item => /非制造边界/.test(item.source)));
  assert.notEqual(definition, original);
});

test('parameter input blocks missing sources, missing fields, reversed ranges and fractional integer limits', () => {
  const draft = demoStudyDefinition();
  draft.parameter_space[0].source = '';
  draft.parameter_space[1].lower = 9;
  draft.parameter_space[3].lower = 1.5;
  draft.parameter_space.pop();
  const { errors } = prepareStudyDefinition(draft);
  assert.ok(errors.some(item => item.includes('来源')));
  assert.ok(errors.some(item => item.includes('下界不能')));
  assert.ok(errors.some(item => item.includes('整数')));
  assert.ok(errors.some(item => item.includes('拓扑')));
});

test('finite range validation and category normalization do not mutate the editable draft', () => {
  const draft = demoStudyDefinition();
  draft.parameter_space[0].lower = Infinity;
  draft.parameter_space[7].choices = 'parallel, serpentine, ';
  const { definition, errors } = prepareStudyDefinition(draft);
  assert.ok(errors.some(item => item.includes('有限数值')));
  assert.deepEqual(definition.parameter_space[7].choices, ['parallel', 'serpentine']);
  assert.equal(draft.parameter_space[7].choices, 'parallel, serpentine, ');
});

test('canonical to input field mapping accepts string columns and rejects malformed mapping', () => {
  assert.deepEqual(parseFieldMap('{"pressure_drop":"压降"}'), { pressure_drop: '压降' });
  for (const content of ['[]', 'null', '{"pressure_drop":1}', '{bad']) assert.throws(() => parseFieldMap(content));
});

test('UTF-8 source import retains BOM, CRLF and Unicode exact bytes and rejects invalid encodings', () => {
  const original = '\ufeffpressure_drop,备注\r\n120,阳极\r\n';
  const bytes = new TextEncoder().encode(original);
  assert.equal(decodeUtf8Import(bytes), original);
  assert.deepEqual(new TextEncoder().encode(decodeUtf8Import(bytes)), bytes);
  assert.throws(() => decodeUtf8Import(new Uint8Array([0xff, 0x80])), /UTF-8/);
});

test('import cannot silently relabel explicit synthetic fixtures as Fluent observations', () => {
  const input = { format: 'json', filename: 'example.json', content: '[{"solver_version":"synthetic-fixture-no-Fluent-solver"}]', provenance: 'fluent_export', fieldMap: '{}' };
  assert.throws(() => prepareImportPayload(input), /synthetic_demo/);
  input.provenance = 'synthetic_demo';
  assert.equal(prepareImportPayload(input).provenance, 'synthetic_demo');
  assert.throws(() => prepareImportPayload({ ...input, filename: '' }), /文件来源/);
  assert.throws(() => prepareImportPayload({ ...input, provenance: 'unknown' }), /明确的数据来源/);
});

test('demo observations carry actual candidate versions, fixed observation values and intentional failed quality example', () => {
  const definition = demoStudyDefinition();
  const candidates = [0, 1, 2].map(index => ({ candidate_id: `candidate-${index}`, geometry_version: `geometry-${index}`, parameters: { channel_count: 8 + index } }));
  const before = structuredClone(candidates);
  const rows = demoResultRows({ definition }, candidates);
  assert.deepEqual(rows.map(row => row.pressure_drop), [125, 140, 118]);
  assert.deepEqual(rows.map(row => row.geometry_version), ['geometry-0', 'geometry-1', 'geometry-2']);
  assert.equal(rows[2].convergence_status, 'unconverged');
  assert.equal(rows[0].mass_balance_scope, 'whole_domain_all_boundaries');
  assert.equal(rows[0].flow_distribution_basis, 'total_mass_flow');
  for (const row of rows) assert.ok(Math.abs(row.channel_mass_flows.reduce((sum, value) => sum + value, 0) - 0.001) < 1e-12);
  assert.deepEqual(candidates, before);
  assert.equal(demoResultRows({ definition }, []).length, 0);
});

test('demo never invents observational performance from geometric DOE parameters', () => {
  const study = { definition: demoStudyDefinition() };
  const first = [{ candidate_id: 'first', geometry_version: 'a', parameters: { channel_count: 10, channel_width: 0.8 } }];
  const second = [{ candidate_id: 'second', geometry_version: 'b', parameters: { channel_count: 10, channel_width: 800 } }];
  assert.equal(demoResultRows(study, first)[0].pressure_drop, demoResultRows(study, second)[0].pressure_drop);
  study.definition.physics_model = 'electrochemical';
  assert.throws(() => demoResultRows(study, first), /固定演示观测/);
});

test('synthetic demo records explicit pressure measurement context for comparability', () => {
  const [row] = demoResultRows({ definition: demoStudyDefinition() }, [{ candidate_id: 'demo', geometry_version: 'geom', parameters: { channel_count: 10 } }]);
  assert.deepEqual(row.pressure_drop_definition, {
    pressure_kind: 'static', inlet_surface: 'inlet', outlet_surface: 'outlet',
    averaging: 'area_weighted_mean', sign_convention: 'inlet_minus_outlet',
  });
  assert.match(row.solver_version, /synthetic/);
});

test('charts display only supplied observed metrics and never fill missing metrics from parameters', () => {
  const option = observedChartOption([{ candidate_id: 'observed', pressure_drop_pa: 50, flow_cv: 0.1 }, { candidate_id: 'missing', parameters: { channel_width: 1 } }]);
  assert.deepEqual(option.series[0].data, [50, null]);
  assert.deepEqual(option.series[1].data, [0.1, null]);
  assert.equal(qualityLabel('screened'), '软件初筛通过');
  assert.match(provenanceLabel('synthetic_demo'), /非仿真/);
});

test('no-selection comparison sends an empty request, selected comparison sends exact observed IDs', async () => {
  const requests = await network(async () => { await comparePemResults('study id'); await comparePemResults('study id', ['result-1']); });
  assert.equal(requests[0].url, '/api/pem/studies/study%20id/compare');
  assert.deepEqual(JSON.parse(requests[0].options.body), {});
  assert.deepEqual(JSON.parse(requests[1].options.body), { result_ids: ['result-1'] });
});

test('study editing creates a child version and DOE transports seed without changing research settings', async () => {
  const payload = { ...demoStudyDefinition(), parent_study_id: 'prior-study' };
  const requests = await network(async () => { await createPemStudy(payload); await generatePemDoe('new-study', { samples: 7, seed: 42 }); });
  assert.equal(requests[0].options.method, 'POST');
  assert.equal(JSON.parse(requests[0].options.body).parent_study_id, 'prior-study');
  assert.deepEqual(JSON.parse(requests[1].options.body), { samples: 7, seed: 42 });
  assert.ok(requests.every(request => !['PATCH', 'DELETE', 'PUT'].includes(request.options.method)));
});

test('JSON imports preserve exact file text, source provenance and explicit field mapping', async () => {
  const payload = { content: '[{"delta_p": 120}]\n', format: 'json', filename: 'local-export.json', provenance: 'manual_import', field_map: { pressure_drop: 'delta_p' } };
  const [request] = await network(async () => importPemResults('study', payload));
  assert.deepEqual(JSON.parse(request.options.body), payload);
  assert.equal(request.url, '/api/pem/studies/study/imports');
});

test('PEM read and download endpoints use bounded shared client and URL-encoded identity', async () => {
  const requests = await network(async () => {
    await getPemStudies(); await getPemStudy('a/b'); await getPemCandidates('a/b'); await getPemResults('a/b');
    assert.ok(await exportPemCandidates('a/b', 'csv') instanceof Blob);
    assert.ok(await exportPemCandidates('a/b', 'json') instanceof Blob);
    assert.ok(await exportPemReport('a/b') instanceof Blob);
    assert.ok(await downloadPemImportSource('a/b', 'i/j') instanceof Blob);
  });
  assert.deepEqual(requests.map(request => request.url), [
    '/api/pem/studies', '/api/pem/studies/a%2Fb', '/api/pem/studies/a%2Fb/candidates', '/api/pem/studies/a%2Fb/results',
    '/api/pem/studies/a%2Fb/candidates?format=csv', '/api/pem/studies/a%2Fb/candidates?format=json',
    '/api/pem/studies/a%2Fb/report?format=markdown', '/api/pem/studies/a%2Fb/imports/i%2Fj/source',
  ]);
  assert.throws(() => exportPemCandidates('study', 'xlsx'), /CSV 或 JSON/);
});

test('PEM API failures preserve structured server validation, do not invent success or retry import', async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => { calls++; return new Response(JSON.stringify({ detail: { message: 'Unit rejected', errors: ['channel_width unit'] } }), { status: 422 }); };
  try {
    await assert.rejects(importPemResults('study', { content: 'bad' }), error => error.statusCode === 422 && error.detail.errors[0] === 'channel_width unit');
    assert.equal(calls, 1);
  } finally { globalThis.fetch = originalFetch; }
});
