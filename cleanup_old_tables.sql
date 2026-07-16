-- Cleanup: remove the redundant agent_leads / agent_lead_tier_history tables.
-- These duplicated functionality that already existed on the `agents` table
-- (tier column + AgentTier enum in chris/scouts/mat_beard.py).
-- Run against chris.db: sqlite3 chris/db/chris.db < cleanup_old_tables.sql

DROP TABLE IF EXISTS agent_lead_tier_history;
DROP TABLE IF EXISTS agent_leads;
