"""
chris/scouts/agent_tier_transitions.py

Single source of truth for agent tier transitions on the EXISTING
`agents` table (agents.tier, using the AgentTier enum already defined
in chris/scouts/mat_beard.py).

RULE: nothing else in this codebase should ever run
    UPDATE agents SET tier = ...
directly. Every tier change goes through transition_tier() below, so
the hard rules from the agent-outreach model can't be silently
bypassed by some other code path setting the column directly.

This does NOT introduce a new table for leads/agents — it plugs into
what mat_beard.py already defines. It only adds:
  - agents.ever_reached_tier_1  (permanent flag)
  - agents.deal_closed          (permanent flag)
  - agent_tier_history          (audit trail)
See migration_agent_tier_upgrade.sql for the schema change.
"""

import sqlite3
from datetime import datetime
from typing import Optional

from chris.scouts.mat_beard import AgentTier


class InvalidTierTransition(Exception):
    """Raised only for genuinely invalid requests (unknown tier, unknown agent)."""
    pass


def transition_tier(
    db: sqlite3.Connection,
    agent_id: int,
    requested_tier: AgentTier,
    reason: str,
) -> AgentTier:
    """
    Attempt to move an agent to requested_tier. Returns the ACTUAL resulting
    tier — which may differ from requested_tier if a hard rule overrides it.

    Hard rules enforced here (from the agent-outreach model):
      1. deal_closed agents are locked at TIER_1 forever. No further
         transitions of any kind, including DEAD.
      2. DEAD is permanent once set (unless deal_closed already locked it).
      3. Once ever_reached_tier_1 is true, the agent can never be demoted
         to TIER_3 again — a request for TIER_3 is corrected to TIER_2
         instead (agent gave an address once, went cold = human call
         queue, not back into the nurture bucket).
      4. Reaching TIER_1 for the first time sets ever_reached_tier_1.
    """
    if not isinstance(requested_tier, AgentTier):
        raise InvalidTierTransition(f"Unknown tier: {requested_tier}")

    row = db.execute(
        "SELECT tier, ever_reached_tier_1, deal_closed FROM agents WHERE agent_id = ?",
        (agent_id,),
    ).fetchone()
    if row is None:
        raise InvalidTierTransition(f"No agent with id {agent_id}")

    current_tier_str, ever_reached_tier_1, deal_closed = row
    current_tier = AgentTier(current_tier_str)

    # --- Rule 1: closed deals are permanent, full stop ---
    if deal_closed:
        if current_tier != AgentTier.TIER_1:
            _write_tier(db, agent_id, current_tier, AgentTier.TIER_1, "self-heal: deal_closed flag set")
        return AgentTier.TIER_1

    # --- Rule 2: dead is permanent ---
    if current_tier == AgentTier.DEAD:
        return AgentTier.DEAD

    if requested_tier == AgentTier.DEAD:
        _write_tier(db, agent_id, current_tier, AgentTier.DEAD, reason)
        return AgentTier.DEAD

    # --- Marking a deal closed always wins and locks the tier ---
    if reason == "DEAL_CLOSED":
        db.execute("UPDATE agents SET deal_closed = 1 WHERE agent_id = ?", (agent_id,))
        _write_tier(db, agent_id, current_tier, AgentTier.TIER_1, reason)
        return AgentTier.TIER_1

    # --- Rule 3: once tier_1 always reached, block demotion to tier_3 ---
    if ever_reached_tier_1 and requested_tier == AgentTier.TIER_3:
        corrected = AgentTier.TIER_2
        _write_tier(
            db, agent_id, current_tier, corrected,
            f"{reason} (corrected from TIER_3: agent previously reached TIER_1)",
        )
        return corrected

    # --- Rule 4: mark the permanent flag the first time tier_1 is reached ---
    if requested_tier == AgentTier.TIER_1 and not ever_reached_tier_1:
        db.execute("UPDATE agents SET ever_reached_tier_1 = 1 WHERE agent_id = ?", (agent_id,))

    _write_tier(db, agent_id, current_tier, requested_tier, reason)
    return requested_tier


def close_deal(db: sqlite3.Connection, agent_id: int, reason: str = "deal closed") -> AgentTier:
    """Convenience wrapper — call this when a deal actually closes with this agent."""
    return transition_tier(db, agent_id, AgentTier.TIER_1, "DEAL_CLOSED")


def _write_tier(
    db: sqlite3.Connection,
    agent_id: int,
    from_tier: Optional[AgentTier],
    to_tier: AgentTier,
    reason: str,
) -> None:
    now = datetime.utcnow().isoformat()
    db.execute(
        "UPDATE agents SET tier = ? WHERE agent_id = ?",
        (to_tier.value, agent_id),
    )
    db.execute(
        """INSERT INTO agent_tier_history (agent_id, from_tier, to_tier, reason, changed_at)
           VALUES (?, ?, ?, ?, ?)""",
        (agent_id, from_tier.value if from_tier else None, to_tier.value, reason, now),
    )
    db.commit()
