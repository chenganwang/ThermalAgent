import { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Card, Descriptions, Drawer, Input, InputNumber, Popconfirm, Space, Table, Tabs, Tag, Typography } from 'antd';
import { DownloadOutlined, EyeOutlined, LeftOutlined, ReloadOutlined } from '@ant-design/icons';
import { useNavigate, useParams } from 'react-router-dom';
import {
  fetchDocumentContent,
  applyPageReparsePreview,
  buildKnowledgeIndexCandidate,
  createPageReparsePreview,
  editDocumentChunk,
  getDocumentChunk,
  getDocumentChunks,
  getKnowledgeIndexSync,
  getKnowledgeDocument,
  releaseKnowledgeIndexCandidate,
  restoreDocumentChunk,
  restoreDocumentOriginalChunk,
  validateKnowledgeIndexCandidate,
} from '../api/adminClient.js';
import { adminErrorMessage } from '../api/contracts.js';
import { useAdminAuth } from '../auth/AdminAuthState.js';
import JsonPreview from '../components/JsonPreview.jsx';
import AdminStatusBadge from '../components/AdminStatusBadge.jsx';
import PageState from '../components/PageState.jsx';
import {
  documentStatusPresentation,
  formatDate,
  normalizeChunk,
  normalizeDocument,
  qualityPresentation,
} from '../presentation/adminPresentation.js';
import { revisionIndexStatus as indexStatusPresentation } from '../presentation/experience.js';

export default function KnowledgeDocumentPage() {
  const { documentId } = useParams();
  const navigate = useNavigate();
  const { token, workflowWriteToken } = useAdminAuth();
  const [detail, setDetail] = useState(null);
  const [chunks, setChunks] = useState([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedChunk, setSelectedChunk] = useState(null);
  const [chunkDraft, setChunkDraft] = useState('');
  const [chunkReason, setChunkReason] = useState('');
  const [busy, setBusy] = useState('');
  const [reparsePage, setReparsePage] = useState(1);
  const [reparsePreview, setReparsePreview] = useState(null);
  const [indexSync, setIndexSync] = useState({ status: 'unknown', candidates: [] });

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [document, chunkResult, indexResult] = await Promise.all([
        getKnowledgeDocument(token, documentId),
        getDocumentChunks(token, documentId, { query, page: 1, page_size: 100 }),
        getKnowledgeIndexSync(token),
      ]);
      setDetail({ ...normalizeDocument(document), raw: document });
      setChunks((chunkResult.items || []).map(normalizeChunk));
      setIndexSync(indexResult || { status: 'unknown', candidates: [] });
    } catch (requestError) {
      setError(requestError);
    } finally {
      setLoading(false);
    }
  }, [token, documentId, query]);

  useEffect(() => { refresh(); }, [refresh]);

  const run = async (key, operation) => {
    setBusy(key);
    setError(null);
    try {
      return await operation();
    } catch (requestError) {
      setError(requestError);
      return null;
    } finally {
      setBusy('');
    }
  };

  const openChunk = async item => {
    const value = await run(`chunk-${item.chunkId}`, () => getDocumentChunk(token, documentId, item.chunkId));
    if (!value) return;
    const normalized = normalizeChunk(value);
    setSelectedChunk(normalized);
    setChunkDraft(normalized.effectiveText);
    setChunkReason('');
    if (normalized.pageStart) setReparsePage(normalized.pageStart);
  };

  const saveChunkRevision = async () => {
    if (!selectedChunk) return;
    const value = await run(`revise-${selectedChunk.chunkId}`, () => editDocumentChunk(token, workflowWriteToken, documentId, selectedChunk.chunkId, {
      effective_text: chunkDraft,
      reason: chunkReason,
      base_version: selectedChunk.version,
      idempotency_key: `chunk-edit-${Date.now()}-${selectedChunk.chunkId}`,
    }));
    if (!value) return;
    const normalized = normalizeChunk(value);
    setSelectedChunk(normalized);
    setChunkDraft(normalized.effectiveText);
    await refresh();
  };

  const restoreRevision = async revisionId => {
    if (!selectedChunk) return;
    const value = await run(`restore-${revisionId}`, () => restoreDocumentChunk(token, workflowWriteToken, documentId, selectedChunk.chunkId, {
      revision_id: revisionId,
      reason: chunkReason || '恢复历史修订',
      base_version: selectedChunk.version,
      idempotency_key: `chunk-restore-${Date.now()}-${selectedChunk.chunkId}`,
    }));
    if (!value) return;
    const normalized = normalizeChunk(value);
    setSelectedChunk(normalized);
    setChunkDraft(normalized.effectiveText);
    await refresh();
  };

  const restoreOriginal = async () => {
    if (!selectedChunk) return;
    const value = await run(`restore-original-${selectedChunk.chunkId}`, () => restoreDocumentOriginalChunk(token, workflowWriteToken, documentId, selectedChunk.chunkId, {
      reason: chunkReason || '恢复原始解析文本',
      base_version: selectedChunk.version,
      idempotency_key: `chunk-restore-original-${Date.now()}-${selectedChunk.chunkId}`,
    }));
    if (!value) return;
    const normalized = normalizeChunk(value);
    setSelectedChunk(normalized);
    setChunkDraft(normalized.effectiveText);
    await refresh();
  };

  const previewPageReparse = async () => {
    const value = await run('reparse-preview', () => createPageReparsePreview(token, workflowWriteToken, documentId, {
      page_number: reparsePage,
      strategy: detail?.reparse?.strategies?.[0] || 'standard_pdf_text',
    }));
    if (value) setReparsePreview(value);
  };

  const applyReparse = async () => {
    if (!reparsePreview) return;
    const value = await run('reparse-apply', () => applyPageReparsePreview(token, workflowWriteToken, reparsePreview.preview_id, `reparse-apply-${Date.now()}`));
    if (value) {
      setReparsePreview(value);
      await refresh();
    }
  };

  const buildIndex = async () => {
    const value = await run('index-build', () => buildKnowledgeIndexCandidate(token, workflowWriteToken));
    if (value) await refresh();
  };

  const validateIndex = async candidateId => {
    const value = await run('index-validate', () => validateKnowledgeIndexCandidate(token, workflowWriteToken, candidateId));
    if (value) await refresh();
  };

  const releaseIndex = async candidateId => {
    const value = await run('index-release', () => releaseKnowledgeIndexCandidate(token, workflowWriteToken, candidateId));
    if (value) await refresh();
  };

  const openContent = async (download) => {
    try {
      const { blob } = await fetchDocumentContent(token, documentId, { download });
      const url = URL.createObjectURL(blob);
      if (download) {
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = detail?.filename || `document-${documentId}`;
        anchor.click();
      } else {
        window.open(url, '_blank', 'noopener,noreferrer');
      }
      globalThis.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (requestError) {
      setError(requestError);
    }
  };

  return (
    <section>
      <div className="admin-page-heading">
        <div>
          <Button type="link" icon={<LeftOutlined />} onClick={() => navigate('/admin/knowledge')}>返回知识库</Button>
          <Typography.Title level={2}>{detail?.title || '文档详情'}</Typography.Title>
          <Typography.Text type="secondary">查看文档信息、原始文件与内容片段。</Typography.Text>
        </div>
        <Space wrap>
          <Button icon={<EyeOutlined />} disabled={!detail?.originalOpenSupported} onClick={() => openContent(false)}>打开原文</Button>
          <Button icon={<DownloadOutlined />} disabled={!detail?.originalDownloadSupported} onClick={() => openContent(true)}>下载</Button>
          <Button icon={<ReloadOutlined />} onClick={refresh}>刷新</Button>
        </Space>
      </div>
      {error && <Alert className="admin-section-alert" type="error" showIcon title={adminErrorMessage(error)} />}
      {detail && !detail.originalAvailable && (
        <Alert
          className="admin-section-alert"
          type={detail.originalFileState === 'integrity_error' ? 'error' : 'info'}
          showIcon
          title={detail.originalFileMessage}
        />
      )}
      <PageState loading={loading} error={error} onRetry={refresh}>
        {detail && (
          <Tabs items={[
            {
              key: 'metadata', label: '文档信息', children: (
                <Card>
                  <Descriptions bordered column={{ xs: 1, lg: 2 }}>
                    <Descriptions.Item label="状态"><AdminStatusBadge value={detail.status} presentation={documentStatusPresentation} /></Descriptions.Item>
                    <Descriptions.Item label="文件名">{detail.filename}</Descriptions.Item>
                    <Descriptions.Item label="类型">{detail.sourceType}</Descriptions.Item>
                    <Descriptions.Item label="页数">{detail.pages ?? '—'}</Descriptions.Item>
                    <Descriptions.Item label="内容片段数">{detail.chunks}</Descriptions.Item>
                    <Descriptions.Item label="入库时间">{formatDate(detail.createdAt)}</Descriptions.Item>
                    <Descriptions.Item label="内容质量">疑似异常 {detail.quality?.suspected_parse_error || 0} · 建议复核 {detail.quality?.needs_review || 0}</Descriptions.Item>
                    <Descriptions.Item label="文本修订同步"><AdminStatusBadge value={detail.indexStatus} presentation={indexStatusPresentation} /></Descriptions.Item>
                  </Descriptions>
                  <Alert className="admin-detail-actions" type="info" showIcon title="文本修订同步与检索覆盖分别统计" description="无待同步修订并不代表片段已进入当前索引。请返回知识库查看真实覆盖状态。" />
                  <JsonPreview label="高级信息" value={{ document_id: detail.documentId, sha256: detail.sha256, parser: detail.raw.parser, provenance: detail.raw.provenance }} />
                </Card>
              ),
            },
            {
              key: 'chunks', label: `内容片段 (${chunks.length})`, children: (
                <Card>
                  <Input.Search aria-label="搜索文档内容片段" placeholder="关键词搜索" allowClear value={query} onChange={event => setQuery(event.target.value)} onSearch={refresh} className="admin-search" />
                  <Table
                    rowKey="chunkId"
                    dataSource={chunks}
                    pagination={{ pageSize: 20 }}
                    onRow={item => ({ onClick: () => openChunk(item) })}
                    rowClassName="admin-clickable-row"
                    columns={[
                      { title: '片段', dataIndex: 'chunkIndex', width: 100, render: value => `片段 ${Number(value) + 1}` },
                      { title: '页码', dataIndex: 'pageStart', width: 90, render: value => value ? `第 ${value} 页` : '—' },
                      { title: '章节', dataIndex: 'section', width: 180 },
                      { title: '预览', dataIndex: 'preview', ellipsis: true },
                      { title: '质量', dataIndex: 'qualityState', width: 125, render: value => <AdminStatusBadge value={value} presentation={qualityPresentation} /> },
                      { title: '索引', dataIndex: 'indexStatus', width: 125, render: value => <AdminStatusBadge value={value} presentation={indexStatusPresentation} /> },
                      { title: '长度', dataIndex: 'length', width: 90 },
                    ]}
                  />
                </Card>
              ),
            },
            {
              key: 'maintenance', label: '内容维护', children: (
                <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
                  <Card title="重新解析本页">
                    <Space wrap align="center">
                      <label htmlFor="reparse-page">页码</label>
                      <InputNumber id="reparse-page" min={1} value={reparsePage} onChange={value => setReparsePage(Number(value || 1))} />
                      <Button disabled={!workflowWriteToken || !detail.reparse?.available} loading={busy === 'reparse-preview'} onClick={previewPageReparse}>生成重新解析预览</Button>
                    </Space>
                    {!detail.reparse?.available && <Alert className="admin-section-alert" type="info" showIcon title="当前原文件不支持安全的单页重新解析。" />}
                    {reparsePreview && (
                      <Card size="small" title={`第 ${reparsePreview.page_number} 页预览`} className="admin-nested-card">
                        <Descriptions size="small" column={2}>
                          <Descriptions.Item label="原片段数">{reparsePreview.old_chunk_count}</Descriptions.Item>
                          <Descriptions.Item label="新片段数">{reparsePreview.new_chunk_count}</Descriptions.Item>
                          <Descriptions.Item label="原字符数">{reparsePreview.diff?.old_characters}</Descriptions.Item>
                          <Descriptions.Item label="新字符数">{reparsePreview.diff?.new_characters}</Descriptions.Item>
                        </Descriptions>
                        <Typography.Paragraph type="secondary">预览不会修改已入库内容；确认后仅替换本页，且检索索引会标记为待更新。</Typography.Paragraph>
                        <Popconfirm title="应用本页重新解析结果？" description="将创建内容修订；其他页保持不变。" onConfirm={applyReparse}>
                          <Button type="primary" disabled={!workflowWriteToken || reparsePreview.applied} loading={busy === 'reparse-apply'}>确认应用</Button>
                        </Popconfirm>
                      </Card>
                    )}
                  </Card>
                  <Card title="检索索引">
                    <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
                      <Alert type="info" showIcon title="内容修订后显示“索引待更新”。生成候选索引不会修改当前线上索引。" />
                      <Space wrap>
                        <AdminStatusBadge value={indexSync.status || 'unknown'} presentation={indexStatusPresentation} />
                        <Button disabled={!workflowWriteToken} loading={busy === 'index-build'} onClick={buildIndex}>生成候选索引</Button>
                      </Space>
                      {(indexSync.candidates || []).map(candidate => (
                        <Card key={candidate.candidate_id} size="small" title={candidate.version || '候选索引'}>
                          <Space wrap>
                            <AdminStatusBadge value={candidate.status} presentation={indexStatusPresentation} />
                            <Button disabled={!workflowWriteToken || candidate.status !== 'candidate_ready'} loading={busy === 'index-validate'} onClick={() => validateIndex(candidate.candidate_id)}>验证候选索引</Button>
                            <Popconfirm title="发布候选索引？" description="只有现有发布门禁和线上切换能力均可用时才会生效。" onConfirm={() => releaseIndex(candidate.candidate_id)}>
                              <Button disabled={!workflowWriteToken || candidate.status !== 'ready_to_release'} loading={busy === 'index-release'}>发布</Button>
                            </Popconfirm>
                            {candidate.error_code && <Tag color="error">发布条件未满足</Tag>}
                          </Space>
                        </Card>
                      ))}
                    </Space>
                  </Card>
                </Space>
              ),
            },
          ]} />
        )}
      </PageState>
      <Drawer title={selectedChunk ? `片段 ${Number(selectedChunk.chunkIndex) + 1}` : '内容片段'} size="large" open={Boolean(selectedChunk)} onClose={() => setSelectedChunk(null)}>
        {selectedChunk && (
          <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
            <Space wrap>
              <AdminStatusBadge value={selectedChunk.qualityState} presentation={qualityPresentation} />
              <AdminStatusBadge value={selectedChunk.indexStatus} presentation={indexStatusPresentation} />
              <Tag>修订 {selectedChunk.version}</Tag>
            </Space>
            {selectedChunk.rawText !== selectedChunk.effectiveText && <Card size="small" title="原始解析文本"><Typography.Paragraph className="admin-chunk-text">{selectedChunk.rawText}</Typography.Paragraph></Card>}
            <label htmlFor="persisted-chunk-editor">修订片段</label>
            <Input.TextArea id="persisted-chunk-editor" aria-label="修订片段" autoSize={{ minRows: 9, maxRows: 22 }} value={chunkDraft} onChange={event => setChunkDraft(event.target.value)} disabled={!workflowWriteToken} />
            <Input aria-label="修订原因" placeholder="填写修订原因" value={chunkReason} onChange={event => setChunkReason(event.target.value)} disabled={!workflowWriteToken} />
            <Space wrap>
              <Button type="primary" disabled={!workflowWriteToken || !chunkDraft.trim() || chunkDraft === selectedChunk.effectiveText} loading={busy === `revise-${selectedChunk.chunkId}`} onClick={saveChunkRevision}>保存修订</Button>
              <Popconfirm title="恢复原始解析文本？" description="恢复操作会创建一条新的修订记录。" onConfirm={restoreOriginal}>
                <Button disabled={!workflowWriteToken || selectedChunk.effectiveText === selectedChunk.rawText} loading={busy === `restore-original-${selectedChunk.chunkId}`}>恢复原始解析文本</Button>
              </Popconfirm>
            </Space>
            <Card size="small" title="修订历史">
              {selectedChunk.revisions.length ? selectedChunk.revisions.slice().reverse().map(revision => (
                <Card key={revision.revision_id} size="small" className="admin-nested-card">
                  <Space orientation="vertical" size="small">
                    <Typography.Text>{revision.reason || '内容修订'} · {formatDate(revision.edited_at)}</Typography.Text>
                    <Typography.Text type="secondary">修订 {revision.version} · {revision.editor || '管理员'}</Typography.Text>
                    <Popconfirm title="恢复此修订内容？" description="恢复操作会创建一条新的修订记录。" onConfirm={() => restoreRevision(revision.revision_id)}>
                      <Button size="small" disabled={!workflowWriteToken}>恢复此版本</Button>
                    </Popconfirm>
                  </Space>
                </Card>
              )) : <Typography.Text type="secondary">暂无修订记录。</Typography.Text>}
            </Card>
          </Space>
        )}
      </Drawer>
    </section>
  );
}
