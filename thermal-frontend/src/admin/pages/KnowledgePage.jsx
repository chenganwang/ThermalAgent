import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Drawer,
  Input,
  Popconfirm,
  Space,
  Steps,
  Table,
  Tabs,
  Tag,
  Typography,
  Upload,
} from 'antd';
import { FileSearchOutlined, InboxOutlined, ReloadOutlined } from '@ant-design/icons';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  commitKnowledgeDocument,
  dryRunKnowledgeDocument,
  editStagedChunk,
  excludeStagedChunk,
  getKnowledgeDocuments,
  getKnowledgeCoverage,
  getKnowledgeStaging,
  getStagedChunk,
  getStagedChunks,
  includeStagedChunk,
  preflightKnowledgeDocument,
  restoreStagedChunk,
  uploadKnowledgeDocument,
  withdrawKnowledgeStaging,
} from '../api/adminClient.js';
import { adminErrorMessage } from '../api/contracts.js';
import { useAdminAuth } from '../auth/AdminAuthState.js';
import AdminStatusBadge from '../components/AdminStatusBadge.jsx';
import PageState from '../components/PageState.jsx';
import WorkflowCredential from '../components/WorkflowCredential.jsx';
import KnowledgeCoverage from '../components/KnowledgeCoverage.jsx';
import useAdminResource from '../hooks/useAdminResource.js';
import {
  candidateParticipationPresentation,
  documentStatusPresentation,
  formatBytes,
  formatDate,
  normalizeChunk,
  normalizeDocument,
  qualityPresentation,
} from '../presentation/adminPresentation.js';

const { Dragger } = Upload;

export default function KnowledgePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { token, workflowWriteToken } = useAdminAuth();
  const [staging, setStaging] = useState([]);
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState('');
  const [query, setQuery] = useState('');
  const [searchDraft, setSearchDraft] = useState('');
  const [page, setPage] = useState(1);
  const [documentTotal, setDocumentTotal] = useState(null);
  const requestSequence = useRef(0);
  const coverageLoader = useCallback(() => getKnowledgeCoverage(token), [token]);
  const coverage = useAdminResource(coverageLoader);
  const [chunkDrawer, setChunkDrawer] = useState(null);
  const [chunkDetail, setChunkDetail] = useState(null);
  const [chunkDraft, setChunkDraft] = useState('');
  const [chunkReason, setChunkReason] = useState('');
  const [notice, setNotice] = useState('');

  const refresh = useCallback(async () => {
    const sequence = ++requestSequence.current;
    setLoading(true);
    setError(null);
    const results = await Promise.allSettled([
      getKnowledgeStaging(token),
      getKnowledgeDocuments(token, { query, page, page_size: 20 }),
    ]);
    if (sequence !== requestSequence.current) return;
    if (results[0].status === 'fulfilled') setStaging((results[0].value.items || []).map(normalizeDocument));
    if (results[1].status === 'fulfilled') {
      setDocuments((results[1].value.items || []).map(normalizeDocument));
      setDocumentTotal(Number.isInteger(results[1].value.total) ? results[1].value.total : null);
    }
    const firstError = results.find(result => result.status === 'rejected');
    if (firstError) setError(firstError.reason);
    setLoading(false);
  }, [token, query, page]);

  useEffect(() => { refresh(); return () => { requestSequence.current += 1; }; }, [refresh]);

  const run = async (key, operation) => {
    setBusy(key);
    setError(null);
    try {
      await operation();
      await refresh();
      coverage.refresh();
    } catch (requestError) {
      setError(requestError);
    } finally {
      setBusy('');
    }
  };

  const upload = () => run('upload', async () => {
    if (!file) return;
    const form = new FormData();
    form.append('file', file, file.name);
    await uploadKnowledgeDocument(token, workflowWriteToken, form);
    setFile(null);
  });

  const loadStagedChunks = async (item, { query: chunkQuery = '', page = 1, pageSize = 10 } = {}) => {
    setChunkDrawer(current => ({
      item,
      chunks: [],
      loading: true,
      query: chunkQuery,
      page,
      pageSize,
      total: 0,
      summary: current?.item?.stagingId === item.stagingId ? current.summary : null,
    }));
    setChunkDetail(null);
    try {
      const value = await getStagedChunks(token, item.stagingId, { query: chunkQuery, page, page_size: pageSize });
      setChunkDrawer({
        item,
        chunks: value.items || [],
        loading: false,
        query: chunkQuery,
        page: value.page || page,
        pageSize: value.page_size || pageSize,
        total: value.total || 0,
        summary: value.candidate_summary || null,
      });
    } catch (requestError) {
      setChunkDrawer({ item, chunks: [], loading: false, error: requestError, query: chunkQuery, page, pageSize, total: 0, summary: null });
    }
  };

  const openChunks = item => loadStagedChunks(item);

  const selectStagedChunk = async item => {
    try {
      const value = normalizeChunk(await getStagedChunk(token, chunkDrawer.item.stagingId, item.chunk_index));
      setChunkDetail(value);
      setChunkDraft(value.effectiveText);
      setChunkReason('');
    } catch (requestError) {
      setError(requestError);
    }
  };

  const saveStagedChunk = async () => {
    if (!chunkDrawer || !chunkDetail) return;
    await run(`edit-staged-${chunkDetail.chunkIndex}`, async () => {
      const value = await editStagedChunk(token, workflowWriteToken, chunkDrawer.item.stagingId, chunkDetail.chunkIndex, {
        effective_text: chunkDraft,
        reason: chunkReason,
        base_version: chunkDetail.version,
        idempotency_key: `staged-edit-${Date.now()}-${chunkDetail.chunkIndex}`,
      });
      const normalized = normalizeChunk(value);
      await loadStagedChunks(chunkDrawer.item, { query: chunkDrawer.query, page: chunkDrawer.page, pageSize: chunkDrawer.pageSize });
      setChunkDetail(normalized);
      setChunkDraft(normalized.effectiveText);
    });
  };

  const restoreStaged = async () => {
    if (!chunkDrawer || !chunkDetail) return;
    await run(`restore-staged-${chunkDetail.chunkIndex}`, async () => {
      const value = await restoreStagedChunk(token, workflowWriteToken, chunkDrawer.item.stagingId, chunkDetail.chunkIndex, {
        reason: chunkReason || '恢复原始解析文本',
        base_version: chunkDetail.version,
        idempotency_key: `staged-restore-${Date.now()}-${chunkDetail.chunkIndex}`,
      });
      const normalized = normalizeChunk(value);
      await loadStagedChunks(chunkDrawer.item, { query: chunkDrawer.query, page: chunkDrawer.page, pageSize: chunkDrawer.pageSize });
      setChunkDetail(normalized);
      setChunkDraft(normalized.effectiveText);
    });
  };

  const excludeStaged = async () => {
    if (!chunkDrawer || !chunkDetail) return;
    await run(`exclude-staged-${chunkDetail.chunkIndex}`, async () => {
      const value = await excludeStagedChunk(token, workflowWriteToken, chunkDrawer.item.stagingId, chunkDetail.chunkIndex, {
        reason: chunkReason || '从本次入库中移除',
        idempotency_key: `staged-exclude-${Date.now()}-${chunkDetail.chunkIndex}`,
      });
      const normalized = normalizeChunk(value);
      await loadStagedChunks(chunkDrawer.item, { query: chunkDrawer.query, page: chunkDrawer.page, pageSize: chunkDrawer.pageSize });
      setChunkDetail(normalized);
      setChunkDraft(normalized.effectiveText);
    });
  };

  const includeStaged = async () => {
    if (!chunkDrawer || !chunkDetail) return;
    await run(`include-staged-${chunkDetail.chunkIndex}`, async () => {
      const value = await includeStagedChunk(token, workflowWriteToken, chunkDrawer.item.stagingId, chunkDetail.chunkIndex, {
        reason: chunkReason || '恢复参与本次入库',
        idempotency_key: `staged-include-${Date.now()}-${chunkDetail.chunkIndex}`,
      });
      const normalized = normalizeChunk(value);
      await loadStagedChunks(chunkDrawer.item, { query: chunkDrawer.query, page: chunkDrawer.page, pageSize: chunkDrawer.pageSize });
      setChunkDetail(normalized);
      setChunkDraft(normalized.effectiveText);
    });
  };

  const withdrawStaging = item => run(`withdraw-${item.stagingId}`, async () => {
    await withdrawKnowledgeStaging(token, workflowWriteToken, item.stagingId, {
      reason: '管理员撤回待入库文件',
      idempotency_key: `staging-withdraw-${Date.now()}-${item.stagingId}`,
    });
    if (chunkDrawer?.item?.stagingId === item.stagingId) {
      setChunkDrawer(null);
      setChunkDetail(null);
    }
    setNotice('文件已撤回。');
  });

  const stagingColumns = [
    { title: '文件', dataIndex: 'filename', ellipsis: true },
    { title: '大小', dataIndex: 'raw', width: 100, render: raw => formatBytes(raw.size_bytes) },
    { title: 'SHA-256', dataIndex: 'sha256', width: 170, render: value => <Typography.Text code>{value?.slice(0, 16)}…</Typography.Text> },
    { title: '状态', dataIndex: 'status', width: 130, render: value => <AdminStatusBadge value={value} presentation={documentStatusPresentation} /> },
    { title: '重复', dataIndex: 'duplicate', width: 90, render: value => value ? <Tag color="warning">是</Tag> : '否' },
    { title: '总片段', dataIndex: 'totalChunks', width: 90 },
    { title: '参与入库', dataIndex: 'includedChunks', width: 90 },
    { title: '已排除', dataIndex: 'excludedChunks', width: 80 },
    {
      title: '操作', key: 'actions', width: 410,
      render: (_, item) => (
        <Space wrap>
          <Button size="small" disabled={!workflowWriteToken || item.duplicate || item.status !== 'uploaded'} loading={busy === `preflight-${item.stagingId}`} onClick={() => run(`preflight-${item.stagingId}`, () => preflightKnowledgeDocument(token, workflowWriteToken, item.stagingId))}>检查内容</Button>
          <Button size="small" disabled={!workflowWriteToken || !['preflight_passed', 'dry_run_ready'].includes(item.status)} loading={busy === `dry-${item.stagingId}`} onClick={() => run(`dry-${item.stagingId}`, () => dryRunKnowledgeDocument(token, workflowWriteToken, item.stagingId))}>预览切分</Button>
          <Button size="small" icon={<FileSearchOutlined />} disabled={!['preflight_passed', 'dry_run_ready'].includes(item.status)} onClick={() => openChunks(item)}>查看片段</Button>
          <Popconfirm title="确认将当前内容写入知识库？" description={`总片段 ${item.totalChunks}，参与入库 ${item.includedChunks}，已排除 ${item.excludedChunks}。`} onConfirm={() => run(`commit-${item.stagingId}`, () => commitKnowledgeDocument(token, workflowWriteToken, item.stagingId))}>
            <Button size="small" type="primary" disabled={!workflowWriteToken || item.status !== 'dry_run_ready' || item.includedChunks === 0} loading={busy === `commit-${item.stagingId}`}>确认入库</Button>
          </Popconfirm>
          <Popconfirm title="确认撤回该待入库文件？" description="撤回后将清理本次上传产生的预览和修改，不会影响已经入库的知识。" okText="确认撤回" cancelText="取消" onConfirm={() => withdrawStaging(item)}>
            <Button size="small" danger disabled={!workflowWriteToken || item.status === 'ingested'} loading={busy === `withdraw-${item.stagingId}`}>撤回文件</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const documentColumns = [
    { title: '标题', dataIndex: 'title', ellipsis: true },
    { title: '文件', dataIndex: 'filename', ellipsis: true },
    { title: '来源类型', dataIndex: 'sourceType', width: 150 },
    { title: '页数', dataIndex: 'pages', width: 80, render: value => value ?? '—' },
    { title: '内容片段', dataIndex: 'chunks', width: 100 },
    { title: '状态', dataIndex: 'status', width: 110, render: value => <AdminStatusBadge value={value} presentation={documentStatusPresentation} /> },
    { title: '更新时间', dataIndex: 'updatedAt', width: 190, render: formatDate },
  ];

  return (
    <section>
      <div className="admin-page-heading">
        <div>
          <Typography.Title level={2}>知识库</Typography.Title>
          <Typography.Text type="secondary">上传资料、检查内容并管理已入库文档。</Typography.Text>
        </div>
        <Space wrap><WorkflowCredential /><Button icon={<ReloadOutlined />} onClick={() => { refresh(); coverage.refresh(); }}>刷新</Button></Space>
      </div>
      <Alert className="admin-section-alert" type="info" showIcon title="上传后需确认入库" description="文件上传后会先检查内容并生成切分预览，确认后才会写入知识库。" />
      {error && <Alert className="admin-section-alert" type="error" showIcon title={adminErrorMessage(error)} closable onClose={() => setError(null)} />}
      {notice && <Alert className="admin-section-alert" type="success" showIcon title={notice} closable onClose={() => setNotice('')} />}
      <Tabs
        defaultActiveKey={location.pathname.endsWith('/upload') ? 'workspace' : 'coverage'}
        items={[
          { key: 'coverage', label: '检索覆盖状态', children: <PageState loading={coverage.loading} error={coverage.error} onRetry={coverage.refresh}><KnowledgeCoverage data={coverage.loading ? null : coverage.data} /></PageState> },
          {
            key: 'workspace', label: `上传文件 (${staging.length})`, children: (
              <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
                <Card title="入库进度">
                  <Steps size="small" responsive items={[
                    { title: '1 上传文件' },
                    { title: '2 检查内容' },
                    { title: '3 预览切分' },
                    { title: '4 确认入库' },
                    { title: '5 完成' },
                  ]} />
                </Card>
                <Card title="选择文件">
                  <Dragger
                    accept=".pdf,.docx"
                    maxCount={1}
                    fileList={file ? [{ uid: 'selected', name: file.name, status: 'done' }] : []}
                    beforeUpload={candidate => { setFile(candidate); return false; }}
                    onRemove={() => setFile(null)}
                    disabled={!workflowWriteToken}
                  >
                    <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                    <p>拖放 PDF 或 DOCX，或点击选择</p>
                    <p className="ant-upload-hint">支持 PDF 和 DOCX，上传后将自动检查内容。</p>
                  </Dragger>
                  <Button type="primary" className="admin-upload-button" disabled={!file || !workflowWriteToken} loading={busy === 'upload'} onClick={upload}>上传文件</Button>
                </Card>
                <Card title="待处理文件">
                  <PageState loading={loading} empty={!loading && !staging.length} onRetry={refresh}>
                    <Table rowKey="stagingId" dataSource={staging} columns={stagingColumns} pagination={{ pageSize: 20 }} scroll={{ x: 1100 }} />
                  </PageState>
                </Card>
              </Space>
            ),
          },
          {
            key: 'library', label: `已入库文档 (${documentTotal ?? '—'})`, children: (
              <Card>
                <Input.Search aria-label="搜索已入库文档" placeholder="按标题或文件名搜索" allowClear value={searchDraft} onChange={event => setSearchDraft(event.target.value)} onSearch={value => { setQuery(value); setPage(1); if (value === query && page === 1) refresh(); }} className="admin-search" />
                <PageState loading={loading} empty={!loading && !documents.length} onRetry={refresh}>
                  <Table rowKey="documentId" loading={loading} dataSource={documents} columns={documentColumns} pagination={{ current: page, pageSize: 20, total: documentTotal ?? 0, onChange: setPage, showSizeChanger: false }} onRow={item => ({ onClick: () => navigate(`/admin/knowledge/${item.documentId}`) })} rowClassName="admin-clickable-row" scroll={{ x: 960 }} />
                </PageState>
              </Card>
            ),
          },
        ]}
      />
      <Drawer title={chunkDrawer ? `${chunkDrawer.item.filename} · 内容片段预览` : '内容片段预览'} size="large" open={Boolean(chunkDrawer)} onClose={() => { setChunkDrawer(null); setChunkDetail(null); }}>
        {chunkDrawer?.error && <Alert type="error" title={adminErrorMessage(chunkDrawer.error)} />}
        {chunkDrawer?.summary && (
          <Card size="small" title="本次入库汇总" className="admin-section-alert">
            <Space wrap>
              <Tag>总片段：{chunkDrawer.summary.total_chunks}</Tag>
              <Tag color="blue">参与入库：{chunkDrawer.summary.included_chunks}</Tag>
              <Tag>已排除：{chunkDrawer.summary.excluded_chunks}</Tag>
              <Tag color="orange">建议复核：{chunkDrawer.summary.review_recommended_chunks}</Tag>
              <Tag color="red">疑似解析异常：{chunkDrawer.summary.suspected_parse_error_chunks}</Tag>
            </Space>
            {chunkDrawer.summary.included_chunks === 0 && <Alert type="warning" showIcon title="当前没有可入库内容。" />}
          </Card>
        )}
        <Input.Search
          aria-label="搜索待处理文件内容片段"
          placeholder="按关键词搜索内容片段"
          allowClear
          value={chunkDrawer?.query || ''}
          onChange={event => setChunkDrawer(current => current ? { ...current, query: event.target.value } : current)}
          onSearch={value => chunkDrawer && loadStagedChunks(chunkDrawer.item, { query: value, page: 1, pageSize: chunkDrawer.pageSize })}
          className="admin-search"
        />
        <Table
          loading={chunkDrawer?.loading}
          rowKey="chunk_index"
          dataSource={chunkDrawer?.chunks || []}
          pagination={{
            current: chunkDrawer?.page || 1,
            pageSize: chunkDrawer?.pageSize || 10,
            total: chunkDrawer?.total || 0,
            showSizeChanger: true,
          }}
          onChange={pagination => chunkDrawer && loadStagedChunks(chunkDrawer.item, {
            query: chunkDrawer.query,
            page: pagination.current,
            pageSize: pagination.pageSize,
          })}
          onRow={item => ({ onClick: () => selectStagedChunk(item) })}
          rowClassName="admin-clickable-row"
          columns={[
            { title: '片段', dataIndex: 'chunk_index', width: 80, render: value => `片段 ${Number(value) + 1}` },
            { title: '页码', dataIndex: 'page_start', width: 80, render: value => value ? `第 ${value} 页` : '—' },
            { title: '章节', dataIndex: 'section', width: 150 },
            { title: '预览', dataIndex: 'preview', ellipsis: true },
            { title: '质量状态', dataIndex: ['quality', 'state'], width: 120, render: value => <AdminStatusBadge value={value || 'normal'} presentation={qualityPresentation} /> },
            { title: '入库状态', dataIndex: 'participation_state', width: 110, render: value => <AdminStatusBadge value={value || 'included'} presentation={candidateParticipationPresentation} /> },
            { title: '长度', dataIndex: 'length', width: 80 },
          ]}
        />
        {chunkDetail && (
          <Card title={`片段 ${Number(chunkDetail.chunkIndex) + 1}`}>
            <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
              <Space wrap>
                <AdminStatusBadge value={chunkDetail.qualityState} presentation={qualityPresentation} />
                <Tag>{chunkDetail.editState === 'edited' ? `已编辑 · 修订 ${chunkDetail.version}` : '原始解析文本'}</Tag>
                <AdminStatusBadge value={chunkDetail.participationState} presentation={candidateParticipationPresentation} />
              </Space>
              {chunkDetail.rawText !== chunkDetail.effectiveText && (
                <Card size="small" title="原始解析文本"><Typography.Paragraph className="admin-chunk-text">{chunkDetail.rawText}</Typography.Paragraph></Card>
              )}
              {chunkDetail.participationState === 'excluded' ? (
                <>
                  <Alert type="info" showIcon title="已排除" description="该片段不会写入知识库。原始解析文本、当前编辑和来源信息均已保留。" />
                  <Card size="small" title="当前保留内容"><Typography.Paragraph className="admin-chunk-text">{chunkDetail.effectiveText}</Typography.Paragraph></Card>
                  <Button type="primary" disabled={!workflowWriteToken} loading={busy === `include-staged-${chunkDetail.chunkIndex}`} onClick={includeStaged}>恢复片段</Button>
                </>
              ) : (
                <>
                  <label htmlFor="staged-chunk-editor">编辑片段</label>
                  <Input.TextArea id="staged-chunk-editor" aria-label="编辑片段" autoSize={{ minRows: 8, maxRows: 20 }} value={chunkDraft} onChange={event => setChunkDraft(event.target.value)} disabled={!workflowWriteToken} />
                  <Input aria-label="修订原因" placeholder="填写修订原因" value={chunkReason} onChange={event => setChunkReason(event.target.value)} disabled={!workflowWriteToken} />
                  <Space wrap>
                    <Button type="primary" disabled={!workflowWriteToken || !chunkDraft.trim() || chunkDraft === chunkDetail.effectiveText} loading={busy === `edit-staged-${chunkDetail.chunkIndex}`} onClick={saveStagedChunk}>保存编辑</Button>
                    <Popconfirm title="恢复解析文本？" description="当前编辑将作为修订记录保留。" onConfirm={restoreStaged}>
                      <Button disabled={!workflowWriteToken || chunkDetail.effectiveText === chunkDetail.rawText} loading={busy === `restore-staged-${chunkDetail.chunkIndex}`}>恢复解析文本</Button>
                    </Popconfirm>
                    <Popconfirm title="确认从本次入库中移除此片段？" description="该操作不会修改原始文件，可以在确认入库前恢复。" okText="确认移除" cancelText="取消" onConfirm={excludeStaged}>
                      <Button danger disabled={!workflowWriteToken} loading={busy === `exclude-staged-${chunkDetail.chunkIndex}`}>从本次入库中移除</Button>
                    </Popconfirm>
                  </Space>
                </>
              )}
            </Space>
          </Card>
        )}
      </Drawer>
    </section>
  );
}
