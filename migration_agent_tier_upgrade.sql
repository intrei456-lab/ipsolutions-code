-- Migration: agent tier transition support
-- Extends the EXISTING agents table (does NOT create a new leads table).
-- Run against chris.db: sqlite3 chris/db/chris.db < migration_agent_tier_upgrade.sql

-- Permanent flag: once true, agent can never be demoted below TIER_2 again,
-- even if they later go quiet. This is what enforces "once Tier 1, never
-- back to Tier 3" from the training.
ALTER TABLE agents ADD COLUMN ever_reached_tier_1 INTEGER NOT NULL DEFAULT 0;

-- Permanent flag: once true, tier is locked at TIER_1 forever, no further
-- transitions allowed (not even DEAD). Set this when a deal actually closes
-- with this agent.
ALTER TABLE agents ADD COLUMN deal_closed INTEGER NOT NULL DEFAULT 0;

-- Full audit trail of every tier change, so any weird state six months from
-- now can be traced back to the exact event that caused it.
CREATE TABLE IF NOT EXISTS agent_tier_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER NOT NULL REFERENCES agents(agent_id),
    from_tier TEXT,
    to_tier TEXT NOT NULL,
    reason TEXT,
    changed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_agent_tier_history_agent ON agent_tier_history(agent_id);
