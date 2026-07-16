"""
shared/lead_tiers.py

Single source of truth for agent-lead tier transitions.

RULE: No other code in this codebase should ever write directly to
agent_leads.tier. Every tier change — from Chris's categorization bot,
from a manual dashboard action, from the setup-call outcome, anywhere —
must go through transition_tier() below. This is what makes the rules
in the training doc unbreakable instead of "best effort."

Valid tiers:
    no_answer  - default state, agent hasn't responded yet
    dead       - hostile/rude response, PERMANENT, never re-contacted
    tier_3     - agent responded, has nothing right now (long-term nurture)
    tier_1     - agent gave an address, actively being worked
    tier_2     - was tier_1, went cold / didn't move forward (human call queue)
    closed     - a deal closed with this agent (PERMANENT tier_1-equivalent,
                 kept as its own value so you can filter "proven repeat agents"
                 without re-deriving it from deal history every time)
"""

import sqlite3
from datetime import datetime
from typing import Optional

VALID_TIERS = {"no_answer", "dead", "tier_3", "tier_1", "tier_2", "closed"}


class InvalidTierTransition(Exception):
    """Raised when code tries to make a transition the business rules forbid."""
    pass


def transition_tier(
    db: sqlite3.Connection,
    lead_id: int,
    requested_tier: str,
    reason: str,
) -> str:
    """
    Attempt to move a lead to requested_tier. Returns the ACTUAL resulting
    tier (which may differ from requested_tier if the rules override it —
    e.g. requesting 'tier_3' on a lead that already hit tier_1 will be
    silently corrected to 'tier_2' instead, per the hard rule below).

    Raises InvalidTierTransition only for truly invalid requests (unknown
    tier name, or trying to move a closed/dead lead anywhere).
    """
    if requested_tier not in VALID_TIERS:
        raise InvalidTierTransition(f"Unknown tier: {requested_tier}")

    row = db.execute(
        "SELECT tier, ever_reached_tier_1, deal_closed FROM agent_leads WHERE id = ?",
        (lead_id,),
    ).fetchone()
    if row is None:
        raise InvalidTierTransition(f"No lead with id {lead_id}")

    current_tier, ever_reached_tier_1, deal_closed = row

    # --- Hard rule: closed leads are permanent, full stop ---
    if deal_closed:
        if current_tier != "closed":
            # shouldn't happen, but self-heal rather than throw
            _write_tier(db, lead_id, current_tier, "closed", "self-heal: deal_closed flag set")
        return "closed"

    # --- Hard rule: dead leads are permanent, full stop ---
    if current_tier == "dead":
        return "dead"

    # --- Hard rule: requesting 'dead' always wins (hostile response can happen from any state) ---
    if requested_tier == "dead":
        _write_tier(db, lead_id, current_tier, "dead", reason)
        return "dead"

    # --- Hard rule: requesting 'closed' always wins and sets the permanent flag ---
    if requested_tier == "closed":
        db.execute(
            "UPDATE agent_leads SET deal_closed = 1 WHERE id = ?", (lead_id,)
        )
        _write_tier(db, lead_id, current_tier, "closed", reason)
        return "closed"

    # --- Hard rule: once ever_reached_tier_1, can NEVER go back to tier_3 or no_answer ---
    if ever_reached_tier_1 and requested_tier in ("tier_3", "no_answer"):
        # Correct the request: if they gave an address once and have now gone
        # cold, that's tier_2 (human call queue), not a demotion to nurture.
        corrected = "tier_2"
        _write_tier(
            db, lead_id, current_tier, corrected,
            f"{reason} (corrected from '{requested_tier}': lead previously reached tier_1)",
        )
        return corrected

    # --- Mark the permanent flag the first time a lead reaches tier_1 ---
    if requested_tier == "tier_1" and not ever_reached_tier_1:
        db.execute(
            "UPDATE agent_leads SET ever_reached_tier_1 = 1 WHERE id = ?", (lead_id,)
        )

    # --- Normal transition ---
    _write_tier(db, lead_id, current_tier, requested_tier, reason)
    return requested_tier


def _write_tier(
    db: sqlite3.Connection,
    lead_id: int,
    from_tier: Optional[str],
    to_tier: str,
    reason: str,
) -> None:
    now = datetime.utcnow().isoformat()
    db.execute(
        "UPDATE agent_leads SET tier = ?, updated_at = ? WHERE id = ?",
        (to_tier, now, lead_id),
    )
    db.execute(
        """INSERT INTO agent_lead_tier_history (lead_id, from_tier, to_tier, reason, changed_at)
           VALUES (?, ?, ?, ?, ?)""",
        (lead_id, from_tier, to_tier, reason, now),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Example usage (remove once wired into main.py / Chris's categorization logic)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    conn = sqlite3.connect(":memory:")
    conn.executescript(open("migration_agent_leads.sql").read())

    conn.execute(
        "INSERT INTO agent_leads (agent_phone) VALUES ('+15551234567')"
    )
    lead_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    print(transition_tier(conn, lead_id, "tier_1", "agent sent address"))
    # -> 'tier_1'

    print(transition_tier(conn, lead_id, "tier_3", "went cold, tried to nurture-demote"))
    # -> 'tier_2'  (rule correction: can't go back below tier_2 once tier_1 is hit)

    print(transition_tier(conn, lead_id, "closed", "deal closed 7/16"))
    # -> 'closed', permanent

    print(transition_tier(conn, lead_id, "dead", "trying to kill a closed lead"))
    # -> 'closed'  (closed always wins, dead request is ignored)
