-- Migration: agent_leads table
-- Tracks every agent Chris has contacted, their current tier, and full tier history.
-- Run this once against your SQLite DB (e.g. sqlite3 ipsolutions.db < migration_agent_leads.sql)

CREATE TABLE IF NOT EXISTS agent_leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Agent identity
    agent_name TEXT,
    agent_phone TEXT NOT NULL,
    agent_email TEXT,
    brokerage TEXT,

    -- Property context (nullable — only populated once we get an address)
    property_address TEXT,
    listing_url TEXT,

    -- Tier state
    tier TEXT NOT NULL DEFAULT 'no_answer',
    -- allowed values enforced in application code (see shared/lead_tiers.py), not a DB constraint,
    -- since SQLite CHECK constraints are painful to alter later. Valid values:
    -- 'no_answer', 'dead', 'tier_3', 'tier_1', 'tier_2', 'closed'

    -- Call-decision fields (Green/Yellow/Red from the setup call)
    call_decision TEXT,              -- 'green', 'yellow', 'red', or NULL if no call yet
    call_decision_notes TEXT,        -- free text: rehab scope, ARV anchor, seller motivation, etc.

    -- Property analysis (auto-filled on tier_1)
    avm_value REAL,
    asking_price REAL,
    offer_range_low REAL,
    offer_range_high REAL,

    -- Bookkeeping
    ever_reached_tier_1 INTEGER NOT NULL DEFAULT 0,  -- 0/1 flag, permanent once set — this is what blocks demotion below tier_2
    deal_closed INTEGER NOT NULL DEFAULT 0,          -- 0/1 flag, permanent once set — locks tier at 'closed'/'tier_1' forever
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_agent_leads_phone ON agent_leads(agent_phone);
CREATE INDEX IF NOT EXISTS idx_agent_leads_tier ON agent_leads(tier);

-- Full audit trail of every tier change — cheap insurance for debugging later
CREATE TABLE IF NOT EXISTS agent_lead_tier_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL REFERENCES agent_leads(id),
    from_tier TEXT,
    to_tier TEXT NOT NULL,
    reason TEXT,                      -- e.g. 'agent gave address', 'hostile response', 'monthly nurture check-in'
    changed_at TEXT NOT NULL DEFAULT (datetime('now'))
);
