USE rag_agent;

SELECT COUNT(*) AS total_chunks FROM chunks;
SELECT COUNT(*) AS active_chunks FROM chunks WHERE is_active=1;
SELECT COUNT(*) AS total_embeddings FROM embeddings;
SELECT COUNT(*) AS total_docs FROM documents;
SELECT COUNT(*) AS total_knowledge_units FROM knowledge_units;

SHOW COLUMNS FROM documents;
SHOW COLUMNS FROM chunks;
SHOW COLUMNS FROM embeddings;

SELECT id, source, title, doc_type, organization, language, publish_year, url, local_path
FROM documents
ORDER BY id DESC
LIMIT 20;

SELECT id, doc_id, chunk_index, chunk_type, section_path, page_start, page_end, token_len, quality_score
FROM chunks
ORDER BY id DESC
LIMIT 50;

SELECT * FROM retrieval_log ORDER BY id DESC LIMIT 20;
