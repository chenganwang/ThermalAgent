USE rag_agent;

-- Safe additive migration from older retrieval-service deployments to rag_agent schema.
-- Run only if your database was created by an older retrieval_service package.

ALTER TABLE documents
  ADD COLUMN doc_type VARCHAR(64) NULL AFTER mime,
  ADD COLUMN organization VARCHAR(255) NULL AFTER doc_type,
  ADD COLUMN language VARCHAR(32) DEFAULT 'zh-CN' AFTER organization,
  ADD COLUMN publish_year INT NULL AFTER language,
  ADD COLUMN url VARCHAR(1024) NULL AFTER publish_year,
  ADD COLUMN local_path VARCHAR(1024) NULL AFTER url,
  ADD COLUMN is_public TINYINT DEFAULT 1 AFTER local_path,
  ADD COLUMN license_note VARCHAR(512) NULL AFTER is_public,
  ADD COLUMN meta_json JSON NULL AFTER license_note,
  ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP AFTER created_at;

ALTER TABLE chunks
  ADD COLUMN token_len INT NULL AFTER char_len,
  ADD COLUMN section_path VARCHAR(1024) NULL AFTER chunk_type,
  ADD COLUMN content_hash CHAR(64) NULL AFTER token_len,
  ADD COLUMN quality_score FLOAT NULL AFTER content_hash,
  ADD COLUMN meta_json JSON NULL AFTER quality_score,
  ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP AFTER created_at;

CREATE TABLE IF NOT EXISTS embeddings (
  chunk_id BIGINT PRIMARY KEY,
  model_name VARCHAR(255) NOT NULL,
  dim INT NOT NULL,
  vector_pos BIGINT NOT NULL,
  build_id VARCHAR(64) NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_vector_pos (vector_pos),
  CONSTRAINT fk_embed_chunk FOREIGN KEY (chunk_id) REFERENCES chunks(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS retrieval_log (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  query_text TEXT NOT NULL,
  topk INT NOT NULL,
  faiss_topn INT NOT NULL,
  latency_ms INT NOT NULL,
  model_name VARCHAR(255) NOT NULL,
  hit_vector_pos TEXT NULL,
  hit_chunk_ids TEXT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
