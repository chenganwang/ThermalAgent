-- rag_agent_schema.sql
-- MySQL schema for 高功率芯片液冷散热知识增强智能体
-- Database: rag_agent
-- Recommended MySQL version: 8.0+

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- =========================================================
-- 1. 原文资料层
-- =========================================================

CREATE TABLE IF NOT EXISTS documents (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    source VARCHAR(1024) NOT NULL COMMENT '原始来源，可为文件名、路径或URL',
    title VARCHAR(512) NOT NULL COMMENT '文档标题',
    sha256 CHAR(64) NOT NULL COMMENT '文件哈希，防止重复入库',
    mime VARCHAR(128),
    doc_type VARCHAR(64) COMMENT 'textbook/whitepaper/standard/paper/case/tutorial/simulation/manual',
    organization VARCHAR(255) COMMENT 'OCP/ASHRAE/NVIDIA/Dell/Supermicro/Intel等',
    language VARCHAR(32) DEFAULT 'zh-CN',
    publish_year INT NULL,
    url VARCHAR(1024),
    local_path VARCHAR(1024),
    is_public TINYINT DEFAULT 1 COMMENT '是否公开资料',
    license_note VARCHAR(512) NULL COMMENT '授权/使用限制说明',
    meta_json JSON NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_documents_sha (sha256),
    KEY idx_documents_type (doc_type),
    KEY idx_documents_org (organization),
    KEY idx_documents_title (title),
    KEY idx_documents_public (is_public)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='资料来源表';

CREATE TABLE IF NOT EXISTS chunks (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    doc_id BIGINT NOT NULL,
    chunk_index INT NOT NULL,
    page_start INT NULL,
    page_end INT NULL,
    chunk_type VARCHAR(64) DEFAULT 'text' COMMENT 'text/table/table_summary/figure/formula/case',
    section_path VARCHAR(1024) NULL,
    text MEDIUMTEXT NOT NULL,
    char_len INT NULL,
    token_len INT NULL,
    content_hash CHAR(64) NULL,
    quality_score FLOAT NULL,
    meta_json JSON NULL,
    is_active TINYINT DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_chunks_doc_chunk (doc_id, chunk_index),
    KEY idx_chunks_doc (doc_id),
    KEY idx_chunks_type (chunk_type),
    KEY idx_chunks_active (is_active),
    KEY idx_chunks_page (doc_id, page_start, page_end),
    KEY idx_chunks_hash (content_hash),
    FULLTEXT KEY ftx_chunks_text (text),

    CONSTRAINT fk_chunks_doc
        FOREIGN KEY (doc_id) REFERENCES documents(id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='底层文本块表，兼容现有ingest_service';

CREATE TABLE IF NOT EXISTS source_assets (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    doc_id BIGINT NULL,
    chunk_id BIGINT NULL,
    asset_type VARCHAR(64) NOT NULL COMMENT 'image/table_file/simulation_file/cloud_map/excel/video/other',
    title VARCHAR(512) NULL,
    description TEXT NULL,
    file_path VARCHAR(1024) NOT NULL,
    page_number INT NULL,
    asset_meta JSON NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    KEY idx_assets_doc (doc_id),
    KEY idx_assets_chunk (chunk_id),
    KEY idx_assets_type (asset_type),

    CONSTRAINT fk_assets_doc
        FOREIGN KEY (doc_id) REFERENCES documents(id)
        ON DELETE SET NULL,
    CONSTRAINT fk_assets_chunk
        FOREIGN KEY (chunk_id) REFERENCES chunks(id)
        ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='图表/云图/仿真文件/附件资源表';

-- =========================================================
-- 2. 专业知识层
-- =========================================================

CREATE TABLE IF NOT EXISTS knowledge_units (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    unit_code VARCHAR(128) UNIQUE,
    unit_type VARCHAR(64) NOT NULL COMMENT 'concept/formula/parameter/component/thermal_path/fault/case/standard/visual',
    title VARCHAR(512) NOT NULL,
    summary TEXT NULL,
    content MEDIUMTEXT NULL,
    domain VARCHAR(128) DEFAULT 'chip_liquid_cooling',

    source_doc_id BIGINT NULL,
    source_chunk_id BIGINT NULL,
    page_start INT NULL,
    page_end INT NULL,

    keywords JSON NULL,
    related_formula_ids JSON NULL,
    related_component_ids JSON NULL,
    related_path_ids JSON NULL,
    related_fault_ids JSON NULL,
    related_visual_template_ids JSON NULL,

    confidence_score FLOAT DEFAULT 1.0,
    review_status VARCHAR(64) DEFAULT 'draft' COMMENT 'draft/reviewed/deprecated',
    reviewer VARCHAR(128) NULL,
    meta_json JSON NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    KEY idx_ku_type (unit_type),
    KEY idx_ku_domain (domain),
    KEY idx_ku_doc (source_doc_id),
    KEY idx_ku_chunk (source_chunk_id),
    KEY idx_ku_review (review_status),
    FULLTEXT KEY ftx_ku_text (title, summary, content),

    CONSTRAINT fk_ku_doc
        FOREIGN KEY (source_doc_id) REFERENCES documents(id)
        ON DELETE SET NULL,
    CONSTRAINT fk_ku_chunk
        FOREIGN KEY (source_chunk_id) REFERENCES chunks(id)
        ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='结构化知识单元表';

CREATE TABLE IF NOT EXISTS formulas (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    formula_code VARCHAR(128) UNIQUE,
    name VARCHAR(255) NOT NULL,
    expression VARCHAR(1024) NOT NULL,
    description TEXT NULL,

    variables JSON NOT NULL COMMENT '变量含义',
    units JSON NULL COMMENT '变量单位约束',
    required_inputs JSON NULL COMMENT '必填输入',
    optional_inputs JSON NULL COMMENT '可选输入',
    output_variables JSON NULL COMMENT '输出变量',
    applicable_conditions TEXT NULL COMMENT '适用条件',
    physical_constraints JSON NULL COMMENT '物理边界和校验规则',

    related_tool_name VARCHAR(255) NULL,
    source_doc_id BIGINT NULL,
    source_chunk_id BIGINT NULL,
    meta_json JSON NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    KEY idx_formula_name (name),
    KEY idx_formula_tool (related_tool_name),
    KEY idx_formula_doc (source_doc_id),
    FULLTEXT KEY ftx_formula_text (name, description, expression),

    CONSTRAINT fk_formula_doc
        FOREIGN KEY (source_doc_id) REFERENCES documents(id)
        ON DELETE SET NULL,
    CONSTRAINT fk_formula_chunk
        FOREIGN KEY (source_chunk_id) REFERENCES chunks(id)
        ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='热管理公式表';

CREATE TABLE IF NOT EXISTS tool_registry (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    tool_name VARCHAR(255) NOT NULL UNIQUE,
    tool_type VARCHAR(64) DEFAULT 'calculation' COMMENT 'calculation/retrieval/visualization/evaluation',
    display_name VARCHAR(255) NULL,
    description TEXT NULL,
    input_schema JSON NULL,
    output_schema JSON NULL,
    related_formula_ids JSON NULL,
    implementation_ref VARCHAR(512) NULL COMMENT 'Python函数/服务端点/前端组件引用',
    is_enabled TINYINT DEFAULT 1,
    meta_json JSON NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    KEY idx_tool_type (tool_type),
    KEY idx_tool_enabled (is_enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='智能体工具注册表';

CREATE TABLE IF NOT EXISTS components (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    component_code VARCHAR(128) UNIQUE,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(128) COMMENT 'chip/package/TIM/cold_plate/coolant/pipe/pump/CDU/manifold/quick_connector/heat_exchanger',
    function_desc TEXT NULL,
    key_parameters JSON NULL,
    typical_failure_modes JSON NULL,
    related_formula_ids JSON NULL,

    source_doc_id BIGINT NULL,
    source_chunk_id BIGINT NULL,
    meta_json JSON NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    KEY idx_component_category (category),
    KEY idx_component_name (name),
    FULLTEXT KEY ftx_component_text (name, function_desc),

    CONSTRAINT fk_component_doc
        FOREIGN KEY (source_doc_id) REFERENCES documents(id)
        ON DELETE SET NULL,
    CONSTRAINT fk_component_chunk
        FOREIGN KEY (source_chunk_id) REFERENCES chunks(id)
        ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='液冷散热部件表';

CREATE TABLE IF NOT EXISTS visual_templates (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    template_code VARCHAR(128) UNIQUE,
    name VARCHAR(255) NOT NULL,
    template_type VARCHAR(128) COMMENT 'thermal_network/liquid_loop/server_liquid_structure/trend_chart/fault_chain',
    description TEXT NULL,

    input_schema JSON NULL,
    output_schema JSON NULL,
    render_engine VARCHAR(64) COMMENT 'React/SVG/ECharts/Mermaid/Canvas',
    template_config JSON NULL,
    implementation_ref VARCHAR(512) NULL,
    is_enabled TINYINT DEFAULT 1,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    KEY idx_template_type (template_type),
    KEY idx_template_enabled (is_enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='可视化模板表';

CREATE TABLE IF NOT EXISTS thermal_paths (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    path_code VARCHAR(128) UNIQUE,
    name VARCHAR(255) NOT NULL,
    scenario VARCHAR(128) COMMENT 'chip_to_cold_plate/rack_liquid_cooling/server_loop/facility_loop',

    node_sequence JSON NOT NULL COMMENT '散热路径节点序列',
    edge_types JSON NULL COMMENT 'conduction/contact/convection/fluid_transport等',
    related_component_ids JSON NULL,
    related_formula_ids JSON NULL,
    related_visual_template_id BIGINT NULL,

    description TEXT NULL,
    source_doc_id BIGINT NULL,
    source_chunk_id BIGINT NULL,
    meta_json JSON NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    KEY idx_path_scenario (scenario),
    KEY idx_path_template (related_visual_template_id),
    FULLTEXT KEY ftx_path_text (name, description),

    CONSTRAINT fk_path_template
        FOREIGN KEY (related_visual_template_id) REFERENCES visual_templates(id)
        ON DELETE SET NULL,
    CONSTRAINT fk_path_doc
        FOREIGN KEY (source_doc_id) REFERENCES documents(id)
        ON DELETE SET NULL,
    CONSTRAINT fk_path_chunk
        FOREIGN KEY (source_chunk_id) REFERENCES chunks(id)
        ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='散热路径表';

CREATE TABLE IF NOT EXISTS fault_cases (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    fault_code VARCHAR(128) UNIQUE,
    symptom VARCHAR(512) NOT NULL,
    fault_category VARCHAR(128) COMMENT 'overheat/hotspot/low_flow/high_pressure_drop/contact_failure/pump_failure/CDU_failure',

    related_parameters JSON NULL,
    possible_causes JSON NULL,
    reasoning_chain JSON NULL,
    check_suggestions JSON NULL,
    related_component_ids JSON NULL,
    related_path_ids JSON NULL,
    related_visual_template_id BIGINT NULL,

    source_doc_id BIGINT NULL,
    source_chunk_id BIGINT NULL,
    meta_json JSON NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    KEY idx_fault_category (fault_category),
    KEY idx_fault_template (related_visual_template_id),
    FULLTEXT KEY ftx_fault_text (symptom),

    CONSTRAINT fk_fault_template
        FOREIGN KEY (related_visual_template_id) REFERENCES visual_templates(id)
        ON DELETE SET NULL,
    CONSTRAINT fk_fault_doc
        FOREIGN KEY (source_doc_id) REFERENCES documents(id)
        ON DELETE SET NULL,
    CONSTRAINT fk_fault_chunk
        FOREIGN KEY (source_chunk_id) REFERENCES chunks(id)
        ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='异常分析链表';

-- =========================================================
-- 3. 评估验证层
-- =========================================================

CREATE TABLE IF NOT EXISTS qa_testset (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    question TEXT NOT NULL,
    task_type VARCHAR(128) COMMENT 'concept/calculation/retrieval/visualization/fault_analysis/report',
    difficulty VARCHAR(64) DEFAULT 'medium' COMMENT 'easy/medium/hard',

    reference_answer MEDIUMTEXT NULL,
    expected_formula_ids JSON NULL,
    expected_tool_names JSON NULL,
    expected_visual_template_ids JSON NULL,
    expected_source_doc_ids JSON NULL,
    expected_source_chunk_ids JSON NULL,

    scoring_rubric JSON NULL,
    created_by VARCHAR(128) NULL,
    review_status VARCHAR(64) DEFAULT 'draft',
    meta_json JSON NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    KEY idx_qa_task_type (task_type),
    KEY idx_qa_difficulty (difficulty),
    KEY idx_qa_review (review_status),
    FULLTEXT KEY ftx_qa_question (question, reference_answer)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='CoolingQA-Liquid测试集表';

CREATE TABLE IF NOT EXISTS simulation_cases (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    case_code VARCHAR(128) UNIQUE,
    name VARCHAR(255) NOT NULL,
    software VARCHAR(128) COMMENT 'ANSYS/Fluent/COMSOL/OpenFOAM/SimScale/Python/Other',
    scenario VARCHAR(128) COMMENT 'cold_plate/pipe_flow/heat_exchanger/thermal_network',
    geometry_desc TEXT NULL,
    boundary_conditions JSON NULL,
    input_parameters JSON NULL,
    output_results JSON NULL,
    asset_ids JSON NULL COMMENT '关联source_assets中的云图、模型、表格等',
    source_doc_id BIGINT NULL,
    source_chunk_id BIGINT NULL,
    permission_note VARCHAR(512) NULL COMMENT '公开/脱敏/教学使用说明',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    KEY idx_sim_software (software),
    KEY idx_sim_scenario (scenario),

    CONSTRAINT fk_sim_doc
        FOREIGN KEY (source_doc_id) REFERENCES documents(id)
        ON DELETE SET NULL,
    CONSTRAINT fk_sim_chunk
        FOREIGN KEY (source_chunk_id) REFERENCES chunks(id)
        ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='仿真算例表';

CREATE TABLE IF NOT EXISTS experiment_logs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    log_code VARCHAR(128) UNIQUE,
    name VARCHAR(255) NOT NULL,
    log_type VARCHAR(128) COMMENT 'hwinfo/nvidia_smi/liquid_loop/wind_tunnel/manual_record',
    scenario VARCHAR(128) COMMENT 'GPU_load/CPU_load/cold_plate_test/pipe_flow_test',

    device_desc TEXT NULL,
    test_conditions JSON NULL,
    measured_parameters JSON NULL,
    result_summary JSON NULL,
    raw_file_path VARCHAR(1024) NULL,
    asset_ids JSON NULL,
    operator VARCHAR(128) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    KEY idx_exp_type (log_type),
    KEY idx_exp_scenario (scenario)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='实验与运行日志表';

CREATE TABLE IF NOT EXISTS evaluation_runs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    run_name VARCHAR(255) NOT NULL,
    system_version VARCHAR(128) NULL,
    dataset_name VARCHAR(255) DEFAULT 'CoolingQA-Liquid',
    dataset_size INT NULL,

    top5_recall FLOAT NULL,
    source_trace_rate FLOAT NULL,
    param_extract_accuracy FLOAT NULL,
    tool_call_accuracy FLOAT NULL,
    calculation_accuracy FLOAT NULL,
    visual_template_accuracy FLOAT NULL,
    fault_cause_coverage FLOAT NULL,
    reasoning_chain_score FLOAT NULL,

    notes TEXT NULL,
    metrics_json JSON NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    KEY idx_eval_version (system_version),
    KEY idx_eval_dataset (dataset_name),
    KEY idx_eval_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='系统评估结果表';

-- =========================================================
-- 4. 初始工具与模板示例
-- =========================================================

INSERT IGNORE INTO tool_registry
(tool_name, tool_type, display_name, description, input_schema, output_schema, is_enabled)
VALUES
('junction_temperature_estimator', 'calculation', '芯片结温估算', '根据入口温度/环境温度、功耗和总热阻估算结温。',
 JSON_OBJECT('P_W','number','T_in_C','number','R_total_K_per_W','number'),
 JSON_OBJECT('T_j_C','number','delta_T_K','number'), 1),
('required_thermal_resistance', 'calculation', '所需总热阻计算', '根据最高允许温度、入口温度和功耗计算所需总热阻。',
 JSON_OBJECT('T_max_C','number','T_in_C','number','P_W','number'),
 JSON_OBJECT('R_required_K_per_W','number'), 1),
('conductive_resistance', 'calculation', '导热热阻计算', '根据厚度、导热系数和面积计算导热热阻。',
 JSON_OBJECT('L_m','number','k_W_per_mK','number','A_m2','number'),
 JSON_OBJECT('R_cond_K_per_W','number'), 1),
('coolant_temperature_rise', 'calculation', '冷却液温升计算', '根据热负荷、质量流量和比热容计算冷却液温升。',
 JSON_OBJECT('Q_W','number','m_dot_kg_s','number','cp_J_kgK','number'),
 JSON_OBJECT('delta_T_K','number'), 1),
('liquid_flow_requirement', 'calculation', '液冷流量需求估算', '根据热负荷、允许温升和比热容估算质量流量与体积流量。',
 JSON_OBJECT('Q_W','number','delta_T_K','number','cp_J_kgK','number','rho_kg_m3','number'),
 JSON_OBJECT('m_dot_kg_s','number','V_dot_L_min','number'), 1);

INSERT IGNORE INTO visual_templates
(template_code, name, template_type, description, render_engine, is_enabled)
VALUES
('thermal_network_chip_to_cold_plate', '芯片到冷板热阻网络图', 'thermal_network', '展示芯片、封装、TIM、冷板、冷却液之间的热阻路径。', 'SVG', 1),
('liquid_loop_cold_plate', '冷板液冷回路图', 'liquid_loop', '展示冷板、管路、泵、CDU、换热器与冷却液流向。', 'SVG', 1),
('server_liquid_structure', '服务器液冷系统结构图', 'server_liquid_structure', '展示AI服务器液冷结构和机柜级液冷连接。', 'SVG', 1),
('flow_temp_trend_chart', '流量—温升关系图', 'trend_chart', '展示冷却液流量与温升之间的趋势关系。', 'ECharts', 1),
('fault_reasoning_chain', '液冷散热异常分析链图', 'fault_chain', '展示现象—参数—路径—部件—原因—建议的异常分析链。', 'Mermaid', 1);

SET FOREIGN_KEY_CHECKS = 1;

-- =========================================================
-- 5. 常用检查语句
-- =========================================================
-- USE rag_agent;
-- SHOW TABLES;
-- SELECT COUNT(*) FROM documents;
-- SELECT COUNT(*) FROM chunks WHERE is_active = 1;
-- SELECT COUNT(*) FROM knowledge_units;
-- SELECT COUNT(*) FROM qa_testset;
