import { useEffect, useState } from 'react';
import { Alert, Button, Card, Form, Input, InputNumber, Select, Space, Table, Tabs, Tag, Typography } from 'antd';
import ReactECharts from 'echarts-for-react';
import {
  comparePemResults, createPemStudy, downloadPemImportSource, exportPemCandidates, exportPemReport, generatePemDoe,
  getPemCandidates, getPemResults, getPemStudies, getPemStudy, importPemResults, requestFailureMessage,
} from '../api/client.js';
import { decodeUtf8Import, demoResultRows, demoStudyDefinition, formatNumber, observedChartOption, PARAMETER_LABELS, prepareImportPayload, prepareStudyDefinition, PROVENANCE, provenanceLabel, qualityLabel } from './pemContracts.js';
import './pemWorkspace.css';

function download(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename; anchor.click();
  globalThis.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function errorText(error) {
  const detail = error?.detail;
  if (typeof detail === 'object' && detail) return `${requestFailureMessage(error)}\n${JSON.stringify(detail, null, 2)}`;
  return requestFailureMessage(error);
}

const emptyDefinition = () => {
  const definition = demoStudyDefinition();
  return { ...definition, title: '', objective: '', model_version: '', parameter_space: definition.parameter_space.map(parameter => ({ ...parameter, source: '' })) };
};

export default function PemWorkspace() {
  const [studies, setStudies] = useState([]);
  const [study, setStudy] = useState(null);
  const [draft, setDraft] = useState(emptyDefinition);
  const [parentStudyId, setParentStudyId] = useState(null);
  const [researchConditions, setResearchConditions] = useState('{}');
  const [boundaryAdditional, setBoundaryAdditional] = useState('{}');
  const [knowledgeSources, setKnowledgeSources] = useState('');
  const [massTolerance, setMassTolerance] = useState(0.01);
  const [candidates, setCandidates] = useState([]);
  const [results, setResults] = useState([]);
  const [imports, setImports] = useState([]);
  const [doe, setDoe] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [busy, setBusy] = useState('loading');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [activeTab, setActiveTab] = useState('research');
  const [sampleCount, setSampleCount] = useState(3);
  const [seed, setSeed] = useState(42);
  const [format, setFormat] = useState('json');
  const [content, setContent] = useState('');
  const [filename, setFilename] = useState('fluent-results.json');
  const [provenance, setProvenance] = useState('manual_import');
  const [fieldMap, setFieldMap] = useState('{}');
  const [importReceipt, setImportReceipt] = useState(null);
  const [resultSelection, setResultSelection] = useState([]);
  const disabled = Boolean(busy);

  useEffect(() => {
    const controller = new AbortController();
    getPemStudies({ signal: controller.signal }).then(payload => setStudies(payload.studies || []))
      .catch(failure => { if (!controller.signal.aborted) setError(errorText(failure)); })
      .finally(() => { if (!controller.signal.aborted) setBusy(''); });
    return () => controller.abort();
  }, []);

  const operate = async (label, action) => {
    if (busy) return;
    setBusy(label); setError(''); setNotice('');
    try { await action(); } catch (failure) { setError(errorText(failure)); }
    finally { setBusy(''); }
  };
  const update = (name, value) => setDraft(previous => ({ ...previous, [name]: value }));
  const updateBoundary = (name, key, value) => setDraft(previous => ({ ...previous, boundary_conditions: { ...previous.boundary_conditions, [name]: { ...previous.boundary_conditions[name], [key]: value } } }));
  const updateParameter = (index, name, value) => setDraft(previous => ({ ...previous, parameter_space: previous.parameter_space.map((parameter, position) => position === index ? { ...parameter, [name]: value } : parameter) }));

  const loadStudy = async studyId => {
    const [record, candidateData, resultData] = await Promise.all([getPemStudy(studyId), getPemCandidates(studyId), getPemResults(studyId)]);
    setStudy(record); setCandidates(candidateData.candidates || []); setResults(resultData.results || []); setImports(resultData.imports || []);
    setComparison(null); setDoe(null); setImportReceipt(null); setResultSelection([]);
  };
  const refresh = () => operate('refresh', async () => {
    const payload = await getPemStudies(); setStudies(payload.studies || []);
    if (study) await loadStudy(study.study_id);
  });
  const editVersion = () => {
    setDraft(structuredClone(study.definition)); setParentStudyId(study.study_id);
    setResearchConditions(JSON.stringify(study.definition.research_conditions || {}, null, 2));
    setBoundaryAdditional(JSON.stringify(study.definition.boundary_conditions.additional || {}, null, 2));
    setKnowledgeSources((study.definition.knowledge_sources || []).join('\n'));
    setMassTolerance(study.definition.quality_policy?.mass_balance_relative_tolerance ?? 0.01);
    setActiveTab('research'); setNotice('编辑后将创建新研究版本，原候选和观测记录仍属于原版本。');
  };
  const saveStudy = () => operate('create', async () => {
    const { definition, errors } = prepareStudyDefinition(draft);
    if (errors.length) throw new Error(errors.join('\n'));
    const conditions = JSON.parse(researchConditions);
    if (!conditions || Array.isArray(conditions) || typeof conditions !== 'object') throw new Error('研究条件必须是 JSON 对象。');
    const additional = JSON.parse(boundaryAdditional);
    if (!additional || Array.isArray(additional) || typeof additional !== 'object') throw new Error('附加边界条件必须是 JSON 对象。');
    definition.boundary_conditions.additional = additional;
    const created = await createPemStudy({ ...definition, research_conditions: conditions, knowledge_sources: knowledgeSources.split('\n').map(item => item.trim()).filter(Boolean), quality_policy: { mass_balance_relative_tolerance: massTolerance }, parent_study_id: parentStudyId });
    const list = await getPemStudies(); setStudies(list.studies || []); await loadStudy(created.study_id);
    setParentStudyId(null); setNotice(`研究 ${created.study_id} 已保存；所有 DOE 均为待仿真候选。`); setActiveTab('doe');
  });
  const generate = () => operate('doe', async () => {
    const generated = await generatePemDoe(study.study_id, { samples: sampleCount, seed });
    setDoe(generated); setCandidates((await getPemCandidates(study.study_id)).candidates || []);
    setNotice(`接受 ${generated.accepted_samples} / ${generated.requested_samples} 个候选；未计算性能。`);
  });
  const exportCandidates = exportFormat => operate('export', async () => download(await exportPemCandidates(study.study_id, exportFormat), `${study.study_id}-candidates.${exportFormat}`));
  const fillDemo = () => {
    try {
      const rows = demoResultRows(study, candidates);
      if (!rows.length) throw new Error('先生成候选，再填入合成演示观测。');
      setContent(JSON.stringify(rows, null, 2)); setFormat('json'); setFilename('synthetic-demo-observations.json'); setProvenance('synthetic_demo'); setFieldMap('{}');
      setNotice('已填入固定合成观测夹具；未运行 Fluent，最后一条故意未收敛。');
    } catch (failure) { setError(failure.message); }
  };
  const readFile = async event => {
    const file = event.target.files?.[0]; if (!file) return;
    try { setContent(decodeUtf8Import(await file.arrayBuffer())); setFilename(file.name); setFormat(file.name.toLowerCase().endsWith('.csv') ? 'csv' : 'json'); setNotice(`已读取本地 UTF-8 文件 ${file.name}，尚未提交导入。`); }
    catch (failure) { setError(failure.message); }
    event.target.value = '';
  };
  const importResults = () => operate('import', async () => {
    const receipt = await importPemResults(study.study_id, prepareImportPayload({ format, content, filename, provenance, fieldMap }));
    setImportReceipt(receipt);
    const data = await getPemResults(study.study_id); setResults(data.results || []); setImports(data.imports || []); setComparison(null);
    setNotice(`已保存 ${receipt.counts?.total ?? receipt.records?.length ?? 0} 条观测，初筛通过 ${receipt.counts?.screened ?? 0} 条；失败观测仍保留。`);
  });
  const compare = () => operate('compare', async () => { setComparison(await comparePemResults(study.study_id, resultSelection)); setActiveTab('compare'); });

  const research = <Card title={parentStudyId ? '修订研究 · 保存为新版本' : '建立研究'} size="small">
    <Form layout="vertical" onFinish={saveStudy}>
      <div className="pem-form-grid">
        <Form.Item label="研究名称"><Input aria-label="研究名称" value={draft.title} onChange={event => update('title', event.target.value)} disabled={disabled} /></Form.Item>
        <Form.Item label="研究目标与验证范围"><Input aria-label="研究目标与验证范围" value={draft.objective} onChange={event => update('objective', event.target.value)} disabled={disabled} /></Form.Item>
        <Form.Item label="研究电极"><Select aria-label="研究电极" value={draft.side} onChange={value => update('side', value)} disabled={disabled} options={[{ value: 'anode', label: '阳极' }, { value: 'cathode', label: '阴极' }]} /></Form.Item>
        <Form.Item label="物理模型"><Select aria-label="物理模型" value={draft.physics_model} onChange={value => update('physics_model', value)} disabled={disabled} options={[{ value: 'single_phase', label: '单相流' }, { value: 'two_phase', label: '两相流' }, { value: 'electrochemical', label: '电化学耦合' }]} /></Form.Item>
        <Form.Item label="物理模型版本"><Input aria-label="物理模型版本" value={draft.model_version} onChange={event => update('model_version', event.target.value)} disabled={disabled} /></Form.Item>
        <Form.Item label="介质标识"><Input aria-label="介质标识" value={draft.fluid} onChange={event => update('fluid', event.target.value)} disabled={disabled} /></Form.Item>
      </div>
      <p className="pem-muted">输入范围由研究者提供。演示数值只用于软件测试；几何检查按平行通道横向排布与板厚关系初筛，实际拓扑需专业几何验证。</p>
      <div className="pem-boundary-grid">{[['mass_flow_rate', '质量流量', ['kg/s', 'g/s', 'kg/h']], ['temperature', '入口温度', ['K', 'degC']], ['outlet_pressure', '出口压力', ['Pa', 'kPa', 'MPa']]].map(([key, label, units]) => <Form.Item key={key} label={label}><Space.Compact className="pem-quantity"><InputNumber aria-label={label} value={draft.boundary_conditions[key]?.value} onChange={value => updateBoundary(key, 'value', value)} disabled={disabled} /><Select aria-label={`${label}单位`} value={draft.boundary_conditions[key]?.unit} onChange={value => updateBoundary(key, 'unit', value)} options={units.map(value => ({ value, label: value }))} disabled={disabled} /></Space.Compact></Form.Item>)}</div>
      <Table className="pem-parameters" size="small" rowKey="name" dataSource={draft.parameter_space} pagination={false} scroll={{ x: 1020 }} columns={[
        { title: '参数', width: 145, render: (_, parameter) => <span>{PARAMETER_LABELS[parameter.name] || parameter.name}<small className="pem-code">{parameter.name}</small></span> },
        { title: '变量类型', width: 125, render: (_, parameter, index) => <Select aria-label={`${parameter.name}变量类型`} value={parameter.kind} onChange={value => updateParameter(index, 'kind', value)} disabled={disabled} options={['continuous', 'integer', 'categorical'].map(value => ({ value, label: { continuous: '连续', integer: '整数', categorical: '类别' }[value] }))} /> },
        { title: '单位', width: 100, render: (_, parameter, index) => <Input aria-label={`${parameter.name}单位`} value={parameter.unit || '1'} onChange={event => updateParameter(index, 'unit', event.target.value)} disabled={disabled || parameter.kind === 'categorical'} /> },
        { title: '下界 / 类别（逗号分隔）', width: 170, render: (_, parameter, index) => parameter.kind === 'categorical' ? <Input aria-label={`${parameter.name}类别`} value={Array.isArray(parameter.choices) ? parameter.choices.join(',') : parameter.choices || ''} onChange={event => updateParameter(index, 'choices', event.target.value)} disabled={disabled} /> : <InputNumber aria-label={`${parameter.name}下界`} value={parameter.lower} onChange={value => updateParameter(index, 'lower', value)} disabled={disabled} /> },
        { title: '上界（相等为固定）', width: 160, render: (_, parameter, index) => parameter.kind !== 'categorical' && <InputNumber aria-label={`${parameter.name}上界`} value={parameter.upper} onChange={value => updateParameter(index, 'upper', value)} disabled={disabled} /> },
        { title: '范围 / 参数来源', width: 300, render: (_, parameter, index) => <Input aria-label={`${parameter.name}来源`} value={parameter.source} onChange={event => updateParameter(index, 'source', event.target.value)} disabled={disabled} /> },
      ]} />
      <div className="pem-form-grid pem-extra-settings">
        <Form.Item label="附加边界条件（JSON；进出口/相/电化学约束）"><Input.TextArea aria-label="附加边界条件" rows={3} value={boundaryAdditional} onChange={event => setBoundaryAdditional(event.target.value)} disabled={disabled} /></Form.Item>
        <Form.Item label="研究条件（JSON；含专业假设/边界补充说明）"><Input.TextArea aria-label="研究条件" rows={3} value={researchConditions} onChange={event => setResearchConditions(event.target.value)} disabled={disabled} /></Form.Item>
        <Form.Item label="知识来源 / 资料引用（每行一条）"><Input.TextArea aria-label="知识来源" rows={3} value={knowledgeSources} onChange={event => setKnowledgeSources(event.target.value)} disabled={disabled} /></Form.Item>
        <Form.Item label="质量守恒相对容差（研究者判据）"><InputNumber aria-label="质量守恒相对容差" value={massTolerance} onChange={setMassTolerance} min={0} max={1} step={0.001} disabled={disabled} /></Form.Item>
      </div>
      <Space wrap><Button type="primary" htmlType="submit" data-testid="pem-create-study" loading={busy === 'create'} disabled={disabled}>{parentStudyId ? '保存为新版本' : '创建研究'}</Button><Button data-testid="pem-fill-demo-study" disabled={disabled} onClick={() => { setDraft(demoStudyDefinition()); setParentStudyId(null); setResearchConditions('{"purpose":"synthetic_demo","limits":"软件演示，未经专业模型验证"}'); setBoundaryAdditional('{}'); setKnowledgeSources('MVP 固定演示夹具，非真实科研资料'); setNotice('已填入合成演示设定；可编辑后创建研究。'); }}>填入演示设定</Button><Button disabled={disabled} onClick={() => { setDraft(emptyDefinition()); setParentStudyId(null); setResearchConditions('{}'); setBoundaryAdditional('{}'); setKnowledgeSources(''); }}>新建空白研究</Button></Space>
    </Form>
  </Card>;

  const doePanel = <Space orientation="vertical" className="pem-full-width" size="middle">
    <Card size="small" title="拉丁超立方 DOE · 待仿真候选">
      <Space wrap align="end"><Form.Item label="候选数量"><InputNumber aria-label="候选数量" min={1} max={1000} precision={0} value={sampleCount} onChange={setSampleCount} disabled={disabled} /></Form.Item><Form.Item label="随机种子"><InputNumber aria-label="随机种子" min={0} max={4294967295} precision={0} value={seed} onChange={setSeed} disabled={disabled} /></Form.Item><Form.Item><Button type="primary" data-testid="pem-generate-doe" disabled={disabled || !study} loading={busy === 'doe'} onClick={generate}>生成候选</Button></Form.Item></Space>
      {doe && <><p data-testid="pem-doe-receipt">接受 {doe.accepted_samples} / {doe.requested_samples} · seed {doe.metadata?.seed} · {doe.metadata?.sampler} · Run {doe.run_id || '未返回'}</p>{(doe.warnings || []).map((warning, index) => <Alert key={index} type="warning" title={String(warning)} />)}<details><summary>被拒绝方案与生成依据（{doe.rejected?.length || 0} 条）</summary><pre>{JSON.stringify({ rejected: doe.rejected, metadata: doe.metadata }, null, 2)}</pre></details></>}
    </Card>
    <Card size="small" title={`候选记录（${candidates.length}）`} extra={<Space><Button disabled={disabled || !study} onClick={() => exportCandidates('csv')} data-testid="pem-export-csv">导出 CSV</Button><Button disabled={disabled || !study} onClick={() => exportCandidates('json')} data-testid="pem-export-json">导出 JSON</Button></Space>}>
      <Table rowKey="candidate_id" size="small" dataSource={candidates} scroll={{ x: 680 }} pagination={{ pageSize: 8, showSizeChanger: false }} columns={[{ title: '候选编号', dataIndex: 'candidate_id' }, { title: '几何版本', dataIndex: 'geometry_version' }, { title: '状态', render: () => <Tag>待仿真 · 性能未知</Tag> }]} expandable={{ expandedRowRender: candidate => <pre>{JSON.stringify(candidate, null, 2)}</pre> }} />
    </Card>
  </Space>;

  const resultsPanel = <Space orientation="vertical" className="pem-full-width" size="middle">
    <Card size="small" title="导入 Fluent 观测 · CSV / JSON">
      <Alert showIcon type="info" title="仅支持 UTF-8 CSV/JSON；必须显式提供工况、模型与网格/收敛信息，以及压降的静压/总压、入口/出口取面、平均方式与符号定义。Fluent 来源由用户声明，系统不认证求解真实性。提交文本、SHA-256 与失败观测保留。" />
      <p className="pem-muted">pressure_drop_definition 必须记录 pressure_kind（static/total）、inlet_surface、outlet_surface、averaging 和 sign_convention（inlet_minus_outlet）。取面与平均方式由实际模型填写，软件不自动设定专业测量依据。</p>
      <Form layout="vertical" className="pem-extra-settings" onFinish={importResults}>
        <div className="pem-form-grid"><Form.Item label="输入格式"><Select aria-label="输入格式" value={format} onChange={setFormat} options={['json', 'csv'].map(value => ({ value, label: value.toUpperCase() }))} disabled={disabled} /></Form.Item><Form.Item label="数据来源"><Select aria-label="数据来源" value={provenance} onChange={setProvenance} options={Object.entries(PROVENANCE).map(([value, item]) => ({ value, label: item.label }))} disabled={disabled} /></Form.Item><Form.Item label="文件来源名称"><Input aria-label="文件来源名称" value={filename} onChange={event => setFilename(event.target.value)} disabled={disabled} /></Form.Item><Form.Item label="选择本地文件"><input aria-label="选择仿真结果文件" type="file" accept=".csv,.json,text/csv,application/json" onChange={readFile} disabled={disabled || !study} /></Form.Item></div>
        {provenance === 'synthetic_demo' && <Alert data-testid="pem-synthetic-warning" showIcon type="warning" title="合成演示数据：未运行 Fluent，不能作为科研性能证据。" />}
        <Form.Item label="CSV / JSON 内容"><Input.TextArea aria-label="CSV / JSON 内容" data-testid="pem-import-content" rows={7} value={content} onChange={event => setContent(event.target.value)} disabled={disabled} placeholder="JSON 对象数组；CSV 数组/对象字段填写 JSON 单元格。" /></Form.Item>
        <Form.Item label="字段映射 JSON（标准字段名 → 文件字段名）"><Input.TextArea aria-label="字段映射" rows={2} value={fieldMap} onChange={event => setFieldMap(event.target.value)} disabled={disabled} placeholder={'{"pressure_drop":"压降"}'} /></Form.Item>
        <Space wrap><Button htmlType="submit" type="primary" data-testid="pem-import-results" disabled={disabled || !study} loading={busy === 'import'}>导入并检查</Button><Button data-testid="pem-fill-demo-results" disabled={disabled || !study || candidates.length === 0} onClick={fillDemo}>填入合成演示结果</Button></Space>
      </Form>
      {importReceipt && <div data-testid="pem-import-receipt"><p>导入 {importReceipt.import_id} · Run {importReceipt.run_id || '未返回'}</p><pre>{JSON.stringify({ source: importReceipt.source, counts: importReceipt.counts, warnings: importReceipt.warnings }, null, 2)}</pre></div>}
    </Card>
    <Card size="small" title={`质量检查与观测记录（${results.length}）`} extra={<Button data-testid="pem-compare" type="primary" disabled={disabled || !study || results.length === 0} onClick={compare}>比较已观测结果</Button>}>
      <p className="pem-muted">初筛通过只表示软件检查与导入方判据满足；仍需专业模型、网格独立性和实验验证。选择部分行可进行子集比较；未选行时按全部观测分组。</p>
      <Table rowKey="result_id" size="small" data-testid="pem-results-table" dataSource={results} rowSelection={{ selectedRowKeys: resultSelection, onChange: setResultSelection }} scroll={{ x: 1040 }} pagination={{ pageSize: 8, showSizeChanger: false }} columns={[
        { title: '观测 / 候选', render: (_, result) => <><small className="pem-code">{result.result_id}</small>{result.candidate_id}</> },
        { title: '来源', render: (_, result) => <Tag color={PROVENANCE[result.provenance]?.color}>{provenanceLabel(result.provenance)}</Tag> },
        { title: '质量', render: (_, result) => <Tag color={result.quality?.eligible_for_comparison ? 'green' : 'red'}>{qualityLabel(result.quality?.status)}</Tag> },
        { title: '求解状态', render: (_, result) => result.observation?.convergence_status || '缺失' },
        { title: '压降 / Pa', render: (_, result) => formatNumber(result.quality?.metrics?.pressure_drop_pa) },
        { title: '流量 CV', render: (_, result) => formatNumber(result.quality?.metrics?.flow_cv) },
        { title: '文件 SHA-256', width: 210, render: (_, result) => <code className="pem-hash">{result.source?.sha256 || '缺失'}</code> },
      ]} expandable={{ expandedRowRender: result => <div><Space orientation="vertical" className="pem-full-width">{(result.quality?.checks || []).map((check, index) => <Alert key={index} type={check.level === 'error' ? 'error' : check.level === 'warning' ? 'warning' : 'info'} title={`${check.code}：${check.message}`} />)}</Space><details><summary>观测、参数快照与来源</summary><pre>{JSON.stringify(result, null, 2)}</pre></details></div> }} />
      <details><summary>已保存导入来源（{imports.length}）</summary>{imports.map(record => <div key={record.import_id}><Button size="small" disabled={disabled} onClick={() => operate('source', async () => download(await downloadPemImportSource(study.study_id, record.import_id), record.filename || record.source?.filename || `${record.import_id}.txt`))}>下载原件 · {record.filename || record.source?.filename || record.import_id}</Button></div>)}<pre>{JSON.stringify(imports, null, 2)}</pre></details>
    </Card>
  </Space>;

  const comparePanel = <Space orientation="vertical" size="middle" className="pem-full-width">
    <Alert showIcon type="info" title="只比较有观测指标且质量可用的同工况结果。不同模型、工况和数据来源分别分组。非支配方案是已有观测之间的筛选，不能称为全局最优。单相结果不能推断电解效率。" />
    <Space wrap><Button data-testid="pem-compare-refresh" type="primary" onClick={compare} disabled={disabled || !study || results.length === 0}>刷新比较</Button><Button data-testid="pem-export-report" onClick={() => operate('report', async () => download(await exportPemReport(study.study_id), `${study.study_id}-research-report.md`))} disabled={disabled || !study}>导出研究报告</Button></Space>
    {!comparison && <Card size="small">导入观测后点击“比较已观测结果”，软件将按可比工况分组。</Card>}
    {comparison && <><p data-testid="pem-comparison-receipt">可比组 {comparison.groups?.length || 0} · 排除 {comparison.excluded?.length || 0} 条 · 只使用已观测数据</p>{(comparison.groups || []).map(group => <Card size="small" key={group.group_id} title={`可比组 ${group.group_id}`} extra={<Tag>{provenanceLabel(group.context?.provenance || group.results?.[0]?.provenance)}</Tag>}>
      <details><summary>比较工况与模型</summary><pre>{JSON.stringify(group.context, null, 2)}</pre></details>
      <ReactECharts option={observedChartOption(group.results || [])} style={{ height: 330 }} />
      <Table rowKey="result_id" size="small" pagination={false} dataSource={group.results || []} scroll={{ x: 660 }} columns={[{ title: '候选', dataIndex: 'candidate_id' }, { title: '压降 / Pa', dataIndex: 'pressure_drop_pa', render: formatNumber }, { title: '流量 CV（越低越均匀）', dataIndex: 'flow_cv', render: formatNumber }, { title: '观测筛选', render: (_, row) => <Tag color={(group.pareto_result_ids || []).includes(row.result_id) ? 'blue' : 'default'}>{(group.pareto_result_ids || []).includes(row.result_id) ? '非支配观测' : '受支配观测'}</Tag> }]} />
    </Card>)}<Card size="small" title="验证限制与被排除结果"><pre>{JSON.stringify({ excluded: comparison.excluded, limitations: comparison.limitations, selection_basis: comparison.selection_basis }, null, 2)}</pre></Card></>}
  </Space>;

  return <section className="pem-workspace" aria-label="PEM 流道初筛工作区" data-testid="pem-workspace">
    <div className="pem-intro"><div><span className="ta-eyebrow">PEM FLOWFIELD · PRE-SCREENING MVP 0.1</span><Typography.Title level={3}>双极板流道研究工作区</Typography.Title><Typography.Paragraph type="secondary">研究设定 → 参数空间 → DOE 候选 → 导入与质量检查 → 同工况比较 → 下一轮研究建议</Typography.Paragraph></div><Button onClick={refresh} loading={busy === 'refresh'} disabled={disabled}>刷新研究记录</Button></div>
    <Alert showIcon type="warning" title="DOE 不产生性能预测。本模块用于仿真初筛，实际制造边界、两相/电化学模型与 Fluent 自动求解仍需专业资料及验证。" />
    {error && <Alert type="error" showIcon title="操作未完成" description={<pre data-testid="pem-error">{error}</pre>} closable onClose={() => setError('')} />}
    {notice && <Alert type="info" showIcon title={notice} data-testid="pem-notice" />}
    <Card size="small" className="pem-study-picker"><Space wrap className="pem-full-width"><Select aria-label="已有 PEM 研究" placeholder="选择已有研究" value={study?.study_id} style={{ minWidth: 300, maxWidth: '100%' }} disabled={disabled} onChange={studyId => operate('select', async () => loadStudy(studyId))} options={studies.map(record => ({ value: record.study_id, label: `${record.definition?.title || record.title || record.study_id} · v${record.study_version || 1}` }))} /><Button disabled={disabled || !study} onClick={editVersion}>编辑当前研究为新版本</Button>{study && <Tag>研究 v{study.study_version} · {study.definition?.side === 'anode' ? '阳极' : '阴极'} · {study.definition?.physics_model}</Tag>}</Space>{study && <><p className="pem-code">{study.study_id} · 输入 SHA-256 {study.input_hash}</p>{(study.warnings || []).map((warning, index) => <Alert key={index} type="warning" title={String(warning)} />)}<details><summary>当前研究设定、范围来源与版本</summary><pre>{JSON.stringify(study, null, 2)}</pre></details></>}</Card>
    <Tabs activeKey={activeTab} onChange={setActiveTab} items={[{ key: 'research', label: '1 · 研究与参数', children: research }, { key: 'doe', label: '2 · DOE 候选', children: doePanel }, { key: 'results', label: '3 · 结果导入与质量', children: resultsPanel }, { key: 'compare', label: '4 · 对比与报告', children: comparePanel }]} />
  </section>;
}
