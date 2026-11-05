-- Deprecated older migration retained for compatibility.
-- New deployments should use 001_init_schema.sql against database rag_agent.
USE rag_agent;

SELECT DATABASE();
SHOW COLUMNS FROM documents;
SHOW COLUMNS FROM chunks;
SHOW COLUMNS FROM embeddings;
SELECT COUNT(*) FROM documents;
SELECT COUNT(*) FROM chunks;
SELECT COUNT(*) FROM embeddings;
SELECT id, source, title, sha256 FROM documents ORDER BY id DESC LIMIT 3;
