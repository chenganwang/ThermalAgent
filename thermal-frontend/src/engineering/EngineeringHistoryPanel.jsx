import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Card, Input, Select, Space, Table, Tabs, Typography } from 'antd';
import { compareEngineeringRuns, createEngineeringProject, getEngineeringArtifact, getEngineeringProjects, getEngineeringRun, getEngineeringRuns, resumeEngineeringRun, solveReferenceWall } from '../api/client.js';
import { canResumeRun, downloadArtifact, historyError, runStatus } from './engineeringHistory.js';
import RunComparison from './RunComparison.jsx';
import RunDetails from './RunDetails.jsx';
import ReferenceWallForm from './ReferenceWallForm.jsx';
import { assertRunIdentity } from '../resultIdentity.js';

export default function EngineeringHistoryPanel({ active = true, useMockResponses = false }) {
  const [projects, setProjects] = useState([]);
  const [projectId, setProjectId] = useState('local');
  const [projectTitle, setProjectTitle] = useState('');
  const [page, setPage] = useState(1);
  const [reload, setReload] = useState(0);
  const [runs, setRuns] = useState([]);
  const [total, setTotal] = useState(0);
  const [selection, setSelection] = useState([]);
  const [detail, setDetail] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [reference, setReference] = useState(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const epoch = useRef(0);
  const action = useRef(null);

  useEffect(() => {
    const generation = ++epoch.current;
    const controller = new AbortController();
    // This ref tracks the latest request, rather than a rendered DOM node.
    const cancelAction = () => { action.current?.abort(); action.current = null; };
    setDetail(null); setComparison(null); setSelection([]); setRuns([]); setTotal(0); setError(''); setBusy(false);
    if (!active || useMockResponses) { setLoading(false); return; }
    setLoading(true);
    Promise.all([getEngineeringProjects({ signal: controller.signal }), getEngineeringRuns({ projectId, offset: (page - 1) * 30 }, { signal: controller.signal })])
      .then(([projectResponse, history]) => {
        if (epoch.current === generation) { setProjects(projectResponse?.projects || []); setRuns(history?.runs || []); setTotal(history?.total || 0); }
      })
      .catch(failure => { if (epoch.current === generation && !controller.signal.aborted) setError(historyError(failure)); })
      .finally(() => { if (epoch.current === generation) setLoading(false); });
    return () => {
      epoch.current = generation + 1;
      controller.abort();
      cancelAction();
    };
  }, [active, useMockResponses, projectId, page, reload]);

  const perform = async (operation, success) => {
    if (!active || useMockResponses || loading || action.current) return;
    const controller = new AbortController();
    const generation = epoch.current;
    action.current = controller; setBusy(true); setError('');
    try {
      const result = await operation({ signal: controller.signal });
      if (generation === epoch.current) success(result);
    } catch (failure) {
      if (generation === epoch.current) setError(historyError(failure));
    } finally {
      if (action.current === controller) { action.current = null; setBusy(false); }
    }
  };
  const disabled = busy || loading || useMockResponses;
  const resume = run => {
    if (!canResumeRun(run)) return;
    void perform(options => resumeEngineeringRun(run.run_id, run.revision, options), updated => { setDetail(updated); setRuns(previous => [updated, ...previous.filter(item => item.run_id !== updated.run_id)]); setTotal(previous => previous + 1); });
  };
  const download = (run, artifact) => perform(options => getEngineeringArtifact(run.run_id, artifact.artifact_id, options), blob => downloadArtifact(blob, `${artifact.artifact_id}.${artifact.kind === 'report' ? 'md' : 'json'}`));

  return <section data-testid="engineering-history-panel" aria-label="工程运行历史" style={{ padding: 20 }}>
    <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
      <Alert type="info" title="工程运行历史保存在后端，刷新网页后可查询。普通聊天的确定性计算当前归入 local 项目。" description="历史与对比展示可核查的执行记录；Mock 演示不等于真实 CFD。" />
      {useMockResponses && <Alert type="warning" title="前端离线示例模式不连接工程历史服务。" />}
      {error && <Alert type="error" showIcon title={error} />}
      <Space wrap>
        <Select aria-label="工程项目" style={{ minWidth: 180 }} value={projectId} options={projects.length ? projects.map(project => ({ value: project.project_id, label: project.title || project.project_id })) : [{ value: 'local', label: 'local' }]} disabled={disabled} onChange={value => { setProjectId(value); setPage(1); setReference(null); }} />
        <Button disabled={disabled} onClick={() => setReload(value => value + 1)}>刷新历史</Button>
      </Space>
      <details><summary>新建工程项目</summary><Space wrap style={{ marginTop: 8 }}>
        <Input aria-label="项目名称" placeholder="项目名称" value={projectTitle} maxLength={160} disabled={disabled} onChange={event => setProjectTitle(event.target.value)} />
        <Button disabled={disabled || !projectTitle.trim()} onClick={() => perform(options => createEngineeringProject({ title: projectTitle.trim() }, options), project => { setProjectTitle(''); setProjectId(project.project_id); setPage(1); setReference(null); })}>创建项目</Button>
      </Space></details>
      <Tabs items={[
        { key: 'history', label: '运行与方案对比', children: <Space orientation="vertical" style={{ width: '100%' }}>
          <Card title="运行记录" size="small" extra={<Button disabled={disabled || selection.length !== 2} onClick={() => perform(options => compareEngineeringRuns(selection, options), setComparison)}>对比所选 2 个方案</Button>}>
            <Table size="small" rowKey="run_id" loading={loading} dataSource={runs} scroll={{ x: 650 }} locale={{ emptyText: '当前项目暂无已保存运行' }} pagination={{ current: page, pageSize: 30, total, showSizeChanger: false, onChange: setPage, disabled }} rowSelection={{ selectedRowKeys: selection, onChange: keys => { setSelection(keys); setComparison(null); }, getCheckboxProps: run => ({ disabled: disabled || (selection.length >= 2 && !selection.includes(run.run_id)) }) }} columns={[
              { title: '工具 / 运行', render: (_, run) => <><div>{run.tool_name}</div><Typography.Text type="secondary" style={{ fontSize: 11 }}>{run.run_id}</Typography.Text></> },
              { title: '状态', dataIndex: 'status', render: runStatus },
              { title: '创建时间', dataIndex: 'created_at' },
              { title: '操作', render: (_, run) => <Button size="small" disabled={disabled} onClick={() => perform(async options => assertRunIdentity(await getEngineeringRun(run.run_id, options), run.run_id), setDetail)}>详情</Button> },
            ]} />
          </Card>
          <RunComparison comparison={comparison} />
          <RunDetails run={detail} busy={disabled} onResume={resume} onDownload={download} />
        </Space> },
        { key: 'reference', label: '平壁参考求解', children: <ReferenceWallForm busy={disabled} response={reference} onSolve={inputs => perform(options => solveReferenceWall(inputs, projectId, options), result => { setReference(result); setReload(value => value + 1); })} /> },
      ]} />
    </Space>
  </section>;
}
