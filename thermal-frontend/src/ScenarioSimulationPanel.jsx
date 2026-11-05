import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd';

import {
  getSimulationCatalog,
  getSimulationModel,
  getSimulationModels,
  getSimulationScenario,
  getSimulationScenarios,
  planSimulationScenario,
  runSimulationScenario,
} from './api/client';
import ScenarioSimulationResultCard from './ScenarioSimulationResultCard';
import {
  canRunScenario,
  collectionFromPayload,
  entityFromPayload,
  initialValuesFromSchema,
  inputSchemaOf,
  missingPlanParameters,
  modelId,
  modelName,
  modelSolver,
  normalizedPlanParams,
  outputSchemaOf,
  planExecutionAllowed,
  planReady,
  prepareScenarioParams,
  scenarioDomain,
  scenarioId,
  scenarioName,
  supportedModelIds,
} from './scenarioForm';
import { parseHeatConductionText, safeSimulationError } from './simulationForm';

const { Paragraph, Text } = Typography;
const { TextArea } = Input;

const DOMAIN_LABELS = Object.freeze({
  heat_transfer: '传热',
  fluid: '流体',
  liquid_cooling: '液冷系统',
  thermal_network: '热阻网络',
  thermal_resistance_network: '热阻网络',
  transient: '瞬态分析',
  transient_heat_transfer: '瞬态分析',
  cfd: 'CFD',
  other: '其他',
});

function mergeById(existing, incoming, getId) {
  const merged = new Map(existing.map(item => [getId(item), item]));
  for (const item of incoming) {
    const id = getId(item);
    if (id) merged.set(id, { ...(merged.get(id) || {}), ...item });
  }
  return [...merged.values()];
}

function optionsOf(field) {
  const values = field.options || field.enum || field.allowed_values || [];
  return Array.isArray(values)
    ? values.map(option => (typeof option === 'object'
      ? { value: option.value, label: option.label_zh || option.label || String(option.value) }
      : { value: option, label: String(option) }))
    : [];
}

function schemaFieldLabel(field) {
  return field.label_zh || field.name_zh || field.label || field.name;
}

function DynamicField({ field, value, error, onChange }) {
  const label = schemaFieldLabel(field);
  const type = String(field.type || 'number').toLowerCase();
  const common = { value, onChange, 'aria-label': label };
  let control;

  if (type === 'select' || optionsOf(field).length > 0) {
    control = <Select {...common} options={optionsOf(field)} style={{ width: '100%' }} allowClear />;
  } else if (type === 'array' || type === 'object') {
    control = (
      <TextArea
        {...common}
        onChange={event => onChange(event.target.value)}
        autoSize={{ minRows: 4, maxRows: 12 }}
        placeholder={type === 'array' ? '[\n  { "name": "item_1", "value": 1 }\n]' : '{\n  "key": "value"\n}'}
        style={{ fontFamily: 'ui-monospace, SFMono-Regular, Consolas, monospace' }}
      />
    );
  } else if (['number', 'integer', 'temperature', 'unit', 'unit_input'].includes(type)) {
    control = (
      <div style={{ display: 'flex', alignItems: 'stretch' }}>
        <InputNumber
          {...common}
          step={type === 'integer' ? 1 : 'any'}
          precision={type === 'integer' ? 0 : undefined}
          controls={false}
          style={{ width: '100%' }}
        />
        {field.unit && (
          <span
            style={{
              minWidth: 52,
              padding: '5px 8px',
              border: '1px solid var(--ta-border)',
              borderLeft: 0,
              borderRadius: '0 6px 6px 0',
              color: 'var(--ta-text-muted)',
              textAlign: 'center',
              whiteSpace: 'nowrap',
            }}
          >
            {field.unit}
          </span>
        )}
      </div>
    );
  } else {
    control = <Input {...common} onChange={event => onChange(event.target.value)} />;
  }

  return (
    <Form.Item
      label={`${label}${field.required ? ' *' : ''}`}
      validateStatus={error ? 'error' : undefined}
      help={error || field.description_zh || field.description || null}
    >
      {control}
    </Form.Item>
  );
}

function itemList(values) {
  if (!Array.isArray(values) || values.length === 0) return <Text type="secondary">—</Text>;
  return (
    <ul style={{ margin: '6px 0 0', paddingLeft: 20 }}>
      {values.map((value, index) => <li key={`${index}-${value}`}>{String(value)}</li>)}
    </ul>
  );
}

function errorMessage(error) {
  return safeSimulationError(error).replace(/^MATLAB /, '仿真 ');
}

export default function ScenarioSimulationPanel({ enabled, reason, useMockResponses = false }) {
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState('');
  const [scenarios, setScenarios] = useState([]);
  const [models, setModels] = useState([]);
  const [selectedDomain, setSelectedDomain] = useState('');
  const [selectedScenarioId, setSelectedScenarioId] = useState('');
  const [selectedModelId, setSelectedModelId] = useState('');
  const [scenarioDetail, setScenarioDetail] = useState(null);
  const [modelDetail, setModelDetail] = useState(null);
  const [values, setValues] = useState({});
  const [fieldErrors, setFieldErrors] = useState({});
  const [naturalLanguage, setNaturalLanguage] = useState('');
  const [prefillMessage, setPrefillMessage] = useState('');
  const [plan, setPlan] = useState(null);
  const [planLoading, setPlanLoading] = useState(false);
  const [runLoading, setRunLoading] = useState(false);
  const [requestError, setRequestError] = useState('');
  const [result, setResult] = useState(null);

  useEffect(() => {
    if (useMockResponses) {
      setCatalogLoading(false);
      setCatalogError('Mock 模式不伪造场景目录或仿真结果。');
      return undefined;
    }
    let cancelled = false;
    const load = async () => {
      setCatalogLoading(true);
      setCatalogError('');
      try {
        const [catalogPayload, scenarioPayload, modelPayload] = await Promise.all([
          getSimulationCatalog(),
          getSimulationScenarios(),
          getSimulationModels(),
        ]);
        if (cancelled) return;
        const catalogScenarios = collectionFromPayload(catalogPayload, ['scenarios', 'items']);
        const listedScenarios = collectionFromPayload(scenarioPayload, ['scenarios', 'items']);
        const catalogModels = collectionFromPayload(catalogPayload, ['models', 'items']);
        const listedModels = collectionFromPayload(modelPayload, ['models', 'items']);
        const nextScenarios = mergeById(catalogScenarios, listedScenarios, scenarioId);
        const nextModels = mergeById(catalogModels, listedModels, modelId);
        setScenarios(nextScenarios);
        setModels(nextModels);
        const first = nextScenarios.find(item => item.status === 'available') || nextScenarios[0];
        if (first) {
          setSelectedDomain(scenarioDomain(first));
          setSelectedScenarioId(scenarioId(first));
        }
      } catch (error) {
        if (!cancelled) setCatalogError(errorMessage(error));
      } finally {
        if (!cancelled) setCatalogLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [useMockResponses]);

  useEffect(() => {
    if (!selectedScenarioId) return undefined;
    let cancelled = false;
    setScenarioDetail(null);
    setSelectedModelId('');
    setModelDetail(null);
    setPlan(null);
    setResult(null);
    setRequestError('');
    getSimulationScenario(selectedScenarioId)
      .then(payload => {
        if (cancelled) return;
        const detail = entityFromPayload(payload, 'scenario');
        setScenarioDetail(detail);
        setScenarios(previous => mergeById(previous, detail ? [detail] : [], scenarioId));
      })
      .catch(error => { if (!cancelled) setRequestError(errorMessage(error)); });
    return () => { cancelled = true; };
  }, [selectedScenarioId]);

  const scenario = scenarioDetail || scenarios.find(item => scenarioId(item) === selectedScenarioId) || null;
  const inputSchema = inputSchemaOf(scenario);

  useEffect(() => {
    setValues(initialValuesFromSchema(inputSchemaOf(scenarioDetail)));
    setFieldErrors({});
    setPlan(null);
    setResult(null);
  }, [scenarioDetail]);

  const availableModels = useMemo(() => {
    const supported = new Set(supportedModelIds(scenario));
    return models.filter(model => {
      if (supported.size > 0) return supported.has(modelId(model));
      const modelScenarios = model.supported_scenarios || model.scenario_ids || [];
      return model.scenario_id === selectedScenarioId || modelScenarios.includes(selectedScenarioId);
    });
  }, [models, scenario, selectedScenarioId]);

  useEffect(() => {
    if (!scenario || availableModels.length === 0 || selectedModelId) return;
    const defaultId = scenario.default_model_id;
    const next = availableModels.find(item => modelId(item) === defaultId) || availableModels[0];
    setSelectedModelId(modelId(next));
  }, [availableModels, scenario, selectedModelId]);

  useEffect(() => {
    if (!selectedModelId) return undefined;
    let cancelled = false;
    setModelDetail(null);
    setPlan(null);
    setResult(null);
    getSimulationModel(selectedModelId)
      .then(payload => {
        if (cancelled) return;
        const detail = entityFromPayload(payload, 'model');
        setModelDetail(detail);
        setModels(previous => mergeById(previous, detail ? [detail] : [], modelId));
      })
      .catch(error => { if (!cancelled) setRequestError(errorMessage(error)); });
    return () => { cancelled = true; };
  }, [selectedModelId]);

  const model = modelDetail || availableModels.find(item => modelId(item) === selectedModelId) || null;
  const domains = [...new Set(scenarios.map(scenarioDomain))];
  const visibleScenarios = scenarios.filter(item => scenarioDomain(item) === selectedDomain);

  const resetExecution = () => {
    setPlan(null);
    setResult(null);
    setRequestError('');
  };

  const changeValue = (name, value) => {
    setValues(previous => ({ ...previous, [name]: value }));
    setFieldErrors(previous => ({ ...previous, [name]: null }));
    resetExecution();
  };

  const prefillHeatConduction = () => {
    const parsed = parseHeatConductionText(naturalLanguage);
    const allowed = new Set(inputSchema.map(field => field.name));
    const nextValues = Object.fromEntries(Object.entries(parsed.values).filter(([key]) => allowed.has(key)));
    if (Object.keys(nextValues).length === 0) {
      setPrefillMessage('未识别到当前场景的参数。');
      return;
    }
    setValues(previous => ({ ...previous, ...nextValues }));
    setPrefillMessage(`已预填 ${Object.keys(nextValues).length} 个参数，请核对后生成执行计划。`);
    resetExecution();
  };

  const createPlan = async () => {
    setRequestError('');
    setResult(null);
    const prepared = prepareScenarioParams(inputSchema, values);
    setFieldErrors(prepared.errors);
    if (!prepared.success) return;
    setPlanLoading(true);
    try {
      const response = await planSimulationScenario({
        scenarioId: selectedScenarioId,
        modelId: selectedModelId,
        params: prepared.params,
      });
      setPlan(response);
    } catch (error) {
      setPlan(null);
      setRequestError(errorMessage(error));
    } finally {
      setPlanLoading(false);
    }
  };

  const canRun = canRunScenario({
    plan,
    capabilityEnabled: enabled,
    scenario,
    model,
    useMockResponses,
  });

  const run = async () => {
    if (!canRun) return;
    setRunLoading(true);
    setRequestError('');
    setResult(null);
    try {
      const response = await runSimulationScenario({
        scenarioId: selectedScenarioId,
        modelId: selectedModelId,
        params: normalizedPlanParams(plan),
      });
      setResult(response);
    } catch (error) {
      setRequestError(errorMessage(error));
    } finally {
      setRunLoading(false);
    }
  };

  if (catalogLoading) {
    return <div style={{ flex: 1, display: 'grid', placeItems: 'center' }}><Spin tip="加载仿真场景目录…" /></div>;
  }

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px', textAlign: 'left' }}>
      <Space orientation="vertical" size={16} style={{ width: '100%' }}>
        {catalogError && <Alert type="error" showIcon title="场景目录加载失败" description={catalogError} />}
        {!enabled && <Alert type="warning" showIcon title="仿真功能当前不可执行" description={reason} />}
        {useMockResponses && <Alert type="info" showIcon title="Mock 模式只预览界面，不执行模型。" />}

        <Card title="场景与模型" size="small">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: 16 }}>
            <div>
              <Text strong>仿真领域</Text>
              <Select
                value={selectedDomain || undefined}
                options={domains.map(domain => ({ value: domain, label: DOMAIN_LABELS[domain] || domain }))}
                onChange={domain => {
                  setSelectedDomain(domain);
                  const first = scenarios.find(item => scenarioDomain(item) === domain);
                  setSelectedScenarioId(first ? scenarioId(first) : '');
                }}
                style={{ width: '100%', marginTop: 8 }}
              />
            </div>
            <div>
              <Text strong>仿真场景</Text>
              <Select
                value={selectedScenarioId || undefined}
                options={visibleScenarios.map(item => ({
                  value: scenarioId(item),
                  label: scenarioName(item),
                  disabled: ['blocked', 'unavailable'].includes(String(item.status).toLowerCase()),
                }))}
                onChange={setSelectedScenarioId}
                style={{ width: '100%', marginTop: 8 }}
              />
            </div>
            <div>
              <Text strong>模型</Text>
              <Select
                value={selectedModelId || undefined}
                options={availableModels.map(item => ({
                  value: modelId(item),
                  label: `${modelName(item)} · ${modelSolver(item)}`,
                }))}
                onChange={setSelectedModelId}
                placeholder={availableModels.length ? '选择已登记模型' : '当前场景无已登记模型'}
                disabled={availableModels.length === 0}
                style={{ width: '100%', marginTop: 8 }}
              />
            </div>
          </div>
        </Card>

        {model && (
          <Card title="模型元数据" size="small">
            <Descriptions
              bordered
              size="small"
              column={{ xs: 1, sm: 2 }}
              items={[
                { key: 'name', label: '模型名称', children: modelName(model), span: 2 },
                { key: 'solver', label: '求解器', children: modelSolver(model).replace(/^matlab$/i, 'MATLAB') },
                { key: 'version', label: '版本', children: model.version || '—' },
                { key: 'status', label: '状态', children: <Tag color={model.status === 'available' ? 'success' : 'warning'}>{model.status || '—'}</Tag> },
                { key: 'review', label: '人工复核', children: model.human_validated === true ? '已复核' : '尚未复核' },
              ]}
            />
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 16, marginTop: 14 }}>
              <div><Text strong>假设</Text>{itemList([...(scenario?.assumptions || []), ...(model.assumptions || [])])}</div>
              <div><Text strong>限制</Text>{itemList([...(scenario?.limitations || []), ...(model.limitations || [])])}</div>
            </div>
          </Card>
        )}

        {scenario && (
          <Card title="动态参数表单" size="small">
            {selectedScenarioId === 'plane_wall_steady_conduction' && (
              <Card type="inner" title="自然语言预填（可选）" size="small" style={{ marginBottom: 16 }}>
                <TextArea
                  value={naturalLanguage}
                  onChange={event => setNaturalLanguage(event.target.value)}
                  placeholder="例如：平壁厚度为0.05 m，导热系数为0.8 W/(m·K)，面积为2 m²，热端100℃，冷端40℃。"
                  autoSize={{ minRows: 2, maxRows: 5 }}
                />
                <Button onClick={prefillHeatConduction} disabled={!naturalLanguage.trim()} style={{ marginTop: 10 }}>解析并预填</Button>
                {prefillMessage && <Paragraph type="secondary" style={{ margin: '8px 0 0' }}>{prefillMessage}</Paragraph>}
              </Card>
            )}
            {inputSchema.length === 0 ? (
              <Alert type="warning" showIcon title="当前场景未提供 input_schema，不会构造任意参数。" />
            ) : (
              <Form layout="vertical" requiredMark={false}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))', gap: '0 16px' }}>
                  {inputSchema.map(field => (
                    <DynamicField
                      key={field.name}
                      field={field}
                      value={values[field.name]}
                      error={fieldErrors[field.name]}
                      onChange={value => changeValue(field.name, value)}
                    />
                  ))}
                </div>
              </Form>
            )}
            <Button
              type="primary"
              onClick={createPlan}
              loading={planLoading}
              disabled={!selectedScenarioId || !selectedModelId || inputSchema.length === 0 || planLoading}
            >
              生成执行计划
            </Button>
          </Card>
        )}

        {plan && (
          <Card title="执行计划" size="small">
            <Descriptions
              bordered
              size="small"
              column={{ xs: 1, sm: 2 }}
              items={[
                { key: 'status', label: '计划状态', children: <Tag color={planReady(plan) ? 'success' : 'warning'}>{plan.status || (planReady(plan) ? 'ready' : 'blocked')}</Tag> },
                { key: 'solver', label: '求解器', children: String(plan.solver || plan.model?.solver || plan.model?.backend || modelSolver(model)).replace(/^matlab$/i, 'MATLAB') },
                { key: 'ready', label: '参数就绪', children: planReady(plan) ? '是' : '否' },
                { key: 'allowed', label: '允许执行', children: planExecutionAllowed(plan) ? '是' : '否' },
                { key: 'missing', label: '缺失参数', children: missingPlanParameters(plan).join('、') || '无', span: 2 },
              ]}
            />
            {Array.isArray(plan.warnings) && plan.warnings.length > 0 && (
              <Alert type="warning" showIcon title="计划警告" description={itemList(plan.warnings)} style={{ marginTop: 14 }} />
            )}
            <details style={{ marginTop: 14 }}>
              <summary style={{ color: 'var(--ta-primary)', cursor: 'pointer', fontWeight: 600 }}>查看归一化参数和计划详情</summary>
              <pre style={{ maxHeight: 280, overflow: 'auto', whiteSpace: 'pre-wrap', padding: 12, background: 'rgba(0,0,0,.25)', borderRadius: 8 }}>
                {JSON.stringify({ normalized_params: normalizedPlanParams(plan), plan }, null, 2)}
              </pre>
            </details>
            {!canRun && (
              <Alert
                type="info"
                showIcon
                title="当前计划不可执行"
                description="只有 plan ready、execution_allowed=true、场景/模型可用且 capability 已启用时才能运行。CFD、preparation_only、status=unvalidated 或 user_uploaded_unvalidated 模型不会执行。"
                style={{ marginTop: 14 }}
              />
            )}
            <Button type="primary" onClick={run} loading={runLoading} disabled={!canRun || runLoading} style={{ marginTop: 14 }}>
              运行已登记模型
            </Button>
          </Card>
        )}

        {requestError && <Alert type="error" showIcon title={requestError} />}
        {result && <ScenarioSimulationResultCard result={result} outputSchema={outputSchemaOf(scenario)} />}
      </Space>
    </div>
  );
}
