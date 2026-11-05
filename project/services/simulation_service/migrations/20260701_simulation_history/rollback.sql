-- ThermalAgent Simulation Module Phase 4 rollback script.
-- Human review required before production use.
-- Only removes objects created by this migration package.

DROP TABLE IF EXISTS simulation_tools;
DROP TABLE IF EXISTS simulation_models;
DROP TABLE IF EXISTS simulation_logs;
DROP TABLE IF EXISTS simulation_runs;
