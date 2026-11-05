# 开发入口索引

| 职责 | 实际入口 |
| --- | --- |
| 检索与 Agent CLI | `cli.py` 转交给 `services/retrieval_service/cli.py`，`knowledge` 子命令转交给相应脚本 |
| FastAPI | `services/retrieval_service/v11_api_server.py` 导出 `api/v11_api_server.py` 中的 app |
| Agent | `services/retrieval_service/agent_orchestrator.py` 维持兼容入口，编排实现在 `agent/`、`retrieval/`、`answering/` 和 `memory/` |
| 索引与嵌入 | `embed_index.py`、`bm25_index.py`、`bm25_tokenizer.py`、`embeddings/` 与 `indexing/` |
| 导入 | `services/ingest_service/cli.py`、`parsers/`、`chunking/`、`rebuild_embeddings.py` |
| 配置与存储 | `services/retrieval_service/config.py`、`db.py`、`sql/`、`scripts/init_db.py` |
| 样本 | `examples/demo.py` 对随仓 Markdown 段落做检索，或导出供正式导入器读取的 DOCX |

索引表中的相对模块路径均以对应服务目录为基准。完整启动说明见[仓库首页](../README.md)。
