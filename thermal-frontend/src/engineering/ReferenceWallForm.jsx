import { useState } from 'react';
import { Alert, Button, Card, Form, InputNumber, Space } from 'antd';
import EngineeringRunCard from '../EngineeringRunCard.jsx';
import HistoryChart from '../HistoryChart.jsx';
import MarkdownContent from '../MarkdownContent.jsx';
import { referenceInputs } from './engineeringHistory.js';

export default function ReferenceWallForm({ busy, onSolve, response }) {
  const [values, setValues] = useState({ area: 0.002, thickness: 0.005, conductivity: 16, left: 350, right: 290 });
  const [errors, setErrors] = useState([]);
  const submit = () => {
    const prepared = referenceInputs(values);
    setErrors(prepared.errors);
    if (prepared.inputs) onSolve(prepared.inputs);
  };
  return <Card title="单层平壁参考计算" size="small">
    <Alert type="info" title="使用以下实际输入执行稳态一维导热参考计算，不是 Mock，也不求解 CFD 流场。" description="常导热系数、均匀截面、无内热源；温度采用绝对 K。计算记录保存到当前所选项目。" />
    <Form layout="vertical" onFinish={submit} style={{ marginTop: 12 }}><Space wrap>
      {[['area', '面积 (m²)'], ['thickness', '厚度 (m)'], ['conductivity', '导热系数 (W/(m·K))'], ['left', '左边界温度 (K)'], ['right', '右边界温度 (K)']].map(([key, label]) => <Form.Item label={label} key={key}><InputNumber aria-label={label} value={values[key]} disabled={busy} onChange={value => { setValues(previous => ({ ...previous, [key]: value })); setErrors([]); }} /></Form.Item>)}
    </Space>{errors.length > 0 && <Alert type="error" title={errors.join(' ')} />}<Space><Button type="primary" htmlType="submit" disabled={busy}>执行并保存参考计算</Button><Button disabled={busy} onClick={() => { setValues({ area: null, thickness: null, conductivity: null, left: null, right: null }); setErrors([]); }}>清空输入</Button></Space></Form>
    {response && <div style={{ marginTop: 16 }}>
      <Alert type="info" title="上次计算结果：输入与状态以回执为准；修改表单不会改变已保存的记录。" />
      <EngineeringRunCard response={{ metadata: { engineering_run: response.engineering_run } }} />
      {(response.result?.histories || []).map((history, index) => <HistoryChart key={index} history={history} isMock={response.result?.is_mock === true} />)}
      {response.result?.errors?.map((error, index) => <Alert key={index} type="error" title={error.message || error.code} />)}
      {response.report && <details style={{ marginTop: 12 }}><summary>查看参考计算报告</summary><MarkdownContent>{response.report}</MarkdownContent></details>}
    </div>}
  </Card>;
}
