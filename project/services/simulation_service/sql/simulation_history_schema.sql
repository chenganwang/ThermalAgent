-- ThermalAgent Simulation Module Phase 3 schema proposal.
-- This file is additive only and is not executed automatically.
-- It does not alter or repurpose existing project tables.

CREATE TABLE IF NOT EXISTS simulation_runs (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  run_id VARCHAR(128) NOT NULL,
  history_id VARCHAR(128) NULL,
  task_id VARCHAR(128) NOT NULL,
  tool_name VARCHAR(255) NOT NULL,
  adapter_name VARCHAR(128) NOT NULL,
  backend_type VARCHAR(128) NULL,
  status VARCHAR(64) NOT NULL,
  is_mock TINYINT DEFAULT 0,
  user_query TEXT NULL,
  request_json JSON NOT NULL,
  result_json JSON NOT NULL,
  error_json JSON NULL,
  warning_json JSON NULL,
  trace_id VARCHAR(128) NULL,
  software VARCHAR(128) NULL,
  software_version VARCHAR(128) NULL,
  model_version VARCHAR(128) NULL,
  elapsed_ms INT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  started_at TIMESTAMP NULL,
  finished_at TIMESTAMP NULL,
  UNIQUE KEY uq_simulation_runs_run_id (run_id),
  KEY idx_sim_runs_tool (tool_name),
  KEY idx_sim_runs_adapter (adapter_name),
  KEY idx_sim_runs_status (status),
  KEY idx_sim_runs_created (created_at),
  KEY idx_sim_runs_trace (trace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Simulation runtime run history';

CREATE TABLE IF NOT EXISTS simulation_logs (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  run_id VARCHAR(128) NOT NULL,
  level VARCHAR(32) NOT NULL,
  event_type VARCHAR(128) NOT NULL,
  message TEXT NULL,
  payload_json JSON NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  KEY idx_sim_logs_run_id (run_id),
  KEY idx_sim_logs_level (level),
  KEY idx_sim_logs_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Simulation structured logs';

CREATE TABLE IF NOT EXISTS simulation_models (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  model_id VARCHAR(128) NOT NULL,
  model_name VARCHAR(255) NOT NULL,
  model_type VARCHAR(128) NULL,
  adapter_name VARCHAR(128) NULL,
  version VARCHAR(128) NULL,
  metadata_json JSON NULL,
  enabled TINYINT DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_simulation_models_model_id (model_id),
  KEY idx_sim_models_adapter (adapter_name),
  KEY idx_sim_models_enabled (enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Simulation model registry proposal';

CREATE TABLE IF NOT EXISTS simulation_tools (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  tool_name VARCHAR(255) NOT NULL,
  adapter_name VARCHAR(128) NOT NULL,
  category VARCHAR(128) NULL,
  description TEXT NULL,
  input_schema_json JSON NULL,
  output_schema_json JSON NULL,
  enabled TINYINT DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_simulation_tools_tool_adapter (tool_name, adapter_name),
  KEY idx_sim_tools_category (category),
  KEY idx_sim_tools_enabled (enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Simulation tool registry mirror proposal';
