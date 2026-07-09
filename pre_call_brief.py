"""
Pre-call brief generator — the real 12-section format confirmed against
actual sent briefs (not the 10-section summary from the original spec
doc, which undercounted). Sections:

  1. Property Snapshot     7. Objection Handlers
  2. Owner Intel           8. Box Technique Sequence
  3. Market Position       9. Soft Yes -> Contract Push
  4. Offer Ladder         10. Voicemail Script
  5. Call Opener          11. Risk Flags & Compliance Notes
  6. 7-Pain Discovery Qs  12. Next Action

This module assembles the numeric/structural pieces deterministically
(offer ladder math, personality calibration hints, follow-up cadence
schedule) and leaves the narrative sections (pain hypothesis prose,
objection rebuttal customization) as clearly marked LLM fill-in points -
that's the part genuinely suited to a live LLM call, not a template.
"""

from dataclasses import dataclass, field

from chris.conversation.pain_dig import PAIN_DIG_SEQUENCE
from shared.config import BRAND


@dataclass
class PropertySnapshot:
    address: str
    city: str
    state: str
    zip_code: str
    source: str
    property_type: str
    days_on_market: int
    risk_tier: str = "STANDARD"
    lien_status: str = "UNKNOWN"
    mls_status: str = "NOT listed"


@dataclass
class OwnerIntel:
    name: str = "Unknown - Discovery Required"
    phone: str | None = None
    email: str | None = None
    mailing_address: str | None = None
    secondary_contact: str | None = None  # e.g. co-occupant flag from skip trace


@dataclass
class OfferLadder:
    arv: float
    repairs: float
    t1_lowball: float
    mao_ceiling: float
    novation_target: float
    ask: float | None = None
    soft_stretch: float | None = None
    novation_min_profit: float = 15000
    jb_fee_estimate: float | None = None


@dataclass
class BriefInputs:
    lead_id: str
    snapshot: PropertySnapshot
    owner: OwnerIntel
    offer: OfferLadder
    exit_strategy: str = "CASH"          # CASH / NOVATION / NURTURE
    pain_flags: list[str] = field(default_factory=list)
    personality_hypothesis: str | None = None  # e.g. "YELLOW/BLUE Blend"


# ---------------------------------------------------------------------------
# Follow-up cadence used in every brief's "Next Action" section
# ---------------------------------------------------------------------------

STANDARD_FOLLOWUP_CADENCE = [
    ("D1 (Today)", "Live call attempt #1 + voicemail + text"),
    ("D2", "Call attempt #2 - different time of day than D1, reference voicemail"),
    ("D4", "Call attempt #3 - add urgency angle specific to this lead's pain"),
    ("D7", "Call attempt #4 - final warm follow-up tone, consider a drive-by"),
    ("D14", "Handwritten letter if applicable, reference specific case/notice numbers for credibility"),
    ("D30", "Final follow-up call - softer tone, check if circumstances changed"),
]


def render_section_1_snapshot(inputs: BriefInputs) -> str:
    s = inputs.snapshot
    return f"""1. PROPERTY SNAPSHOT

Address: {s.address}, {s.city} {s.state} {s.zip_code}
Source: {s.source}
Property Type: {s.property_type}
Days on Market: {s.days_on_market}
Risk Tier: {s.risk_tier}
Lien Status: {s.lien_status}
MLS Status: {s.mls_status}
Exit Strategy: {inputs.exit_strategy}

[LLM FILL-IN: 2-3 sentence "Key Context" paragraph synthesizing why this
property/situation matters right now - reference the ONE most urgent
signal (violation, DOM, price gap, etc).]"""


def render_section_2_owner_intel(inputs: BriefInputs) -> str:
    o = inputs.owner
    lines = [f"Primary Contact: {o.name}"]
    if o.phone:
        lines.append(f"Phone: {o.phone}")
    if o.email:
        lines.append(f"Email: {o.email}")
    if o.mailing_address:
        lines.append(f"Mailing Address: {o.mailing_address}")
    if o.secondary_contact:
        lines.append(f"Secondary Contact: {o.secondary_contact} (confirm relationship on call)")

    return "2. OWNER INTEL\n\n" + "\n".join(lines) + (
        "\n\n[LLM FILL-IN: Motivation Profile paragraph + Personality Type "
        "hypothesis with reasoning, using available source/DOM/price signals. "
        f"{'Suggested starting hypothesis: ' + inputs.personality_hypothesis if inputs.personality_hypothesis else ''}]"
    )


def render_section_3_market_position(inputs: BriefInputs) -> str:
    o = inputs.offer
    net_arv_after_repairs = o.arv - o.repairs
    lines = [
        f"ARV (After Repair Value): ${o.arv:,.0f}",
        f"Repair Estimate: ${o.repairs:,.0f}",
        f"Net ARV After Repairs: ${net_arv_after_repairs:,.0f}",
    ]
    if o.ask:
        lines.append(f"Asking Price: ${o.ask:,.0f}")
    return "3. MARKET POSITION\n\n" + "\n".join(lines) + (
        "\n\n[LLM FILL-IN: Spread Analysis paragraph - walk through what "
        "seller nets at T1 vs MAO vs Novation, in plain language.]"
    )


def render_section_4_offer_ladder(inputs: BriefInputs) -> str:
    o = inputs.offer
    rows = [
        f"T1 (Low Ball / Anchor): ${o.t1_lowball:,.0f}",
        f"MAO Ceiling: ${o.mao_ceiling:,.0f}",
    ]
    if o.soft_stretch:
        rows.append(f"Soft Stretch (Walk-Away Max, requires approval): ${o.soft_stretch:,.0f}")
    rows.append(f"Novation Listing Target: ${o.novation_target:,.0f}")
    rows.append(f"Novation Min IPS Profit: ${o.novation_min_profit:,.0f}")
    if o.jb_fee_estimate:
        rows.append(f"JB/Wholesale Fee Estimate: ${o.jb_fee_estimate:,.0f}")

    return "4. OFFER LADDER\n\n" + "\n".join(rows) + (
        "\n\nDecision Rule: Start at T1. Work up to MAO ceiling maximum on "
        "cash path. If seller is stuck above MAO, pivot to the Novation "
        "conversation."
    )


def render_section_6_pain_discovery() -> str:
    """The 7-pain-dig questions, in order, as they appear in every brief."""
    lines = [f"{q.order}. {q.question}" for q in PAIN_DIG_SEQUENCE]
    return (
        "6. 7-PAIN DISCOVERY QUESTIONS\n\n"
        "Ask in order. Let them answer fully. Do NOT interrupt.\n\n"
        + "\n".join(lines)
    )


def render_section_12_next_action(inputs: BriefInputs) -> str:
    lines = [f"{day}: {action}" for day, action in STANDARD_FOLLOWUP_CADENCE]
    return "12. NEXT ACTION\n\nFOLLOW-UP CADENCE:\n" + "\n".join(lines) + (
        "\n\nIf Soft Yes Achieved: Get PSA signed within 24 hours, order "
        "title search immediately, schedule property walkthrough within "
        "48 hours, notify Keith Everett of acquisition for pipeline tracking."
    )


def render_brief_header(inputs: BriefInputs) -> str:
    s = inputs.snapshot
    return f"""{BRAND['company_name'].upper()}
{BRAND['tagline']}

PRE-CALL BRIEF — LEAD #{inputs.lead_id}
{s.address}, {s.city} {s.state} {s.zip_code}
Generated by CHRIS — Acquisitions Engine"""


def render_full_brief_skeleton(inputs: BriefInputs) -> str:
    """
    Assembles the deterministic sections. Sections 5 (Call Opener),
    7 (Objection Handlers), 8 (Box Technique Sequence), 9 (Soft Yes ->
    Contract Push), 10 (Voicemail Script), and 11 (Risk Flags) are highly
    lead-specific narrative content best generated by an LLM call using
    this skeleton + chris/conversation/{objections,negotiation,call_script}.py
    as reference material - marked as fill-in points rather than
    templated here, since forcing them into string templates would
    produce worse output than a real LLM pass with the right context.
    """
    sections = [
        render_brief_header(inputs),
        render_section_1_snapshot(inputs),
        render_section_2_owner_intel(inputs),
        render_section_3_market_position(inputs),
        render_section_4_offer_ladder(inputs),
        "5. CALL OPENER\n\n[LLM FILL-IN: use chris/conversation/call_script.py OPENERS "
        "matched to source, personalized with owner name + address]",
        render_section_6_pain_discovery(),
        "7. OBJECTION HANDLERS\n\n[LLM FILL-IN: top 3 likely objections for this "
        "lead from chris/conversation/objections.py, customized with this "
        "property's specific numbers]",
        "8. BOX TECHNIQUE SEQUENCE\n\n[LLM FILL-IN: render using this brief's "
        "actual T1/MAO/soft-stretch numbers, following negotiation.py's "
        "PRICE_RANGE_STRATEGY steps]",
        "9. SOFT YES -> CONTRACT PUSH\n\n[LLM FILL-IN: use call_script.py's "
        "get_autograph/closing_handoff steps, personalized]",
        "10. VOICEMAIL SCRIPT\n\n[LLM FILL-IN: under 30 seconds, curiosity-based, "
        "no price/pitch mentioned]",
        "11. RISK FLAGS & COMPLIANCE NOTES\n\n[LLM FILL-IN: title/lien/decision-maker "
        "flags specific to this lead's intake data]",
        render_section_12_next_action(inputs),
    ]
    return "\n\n---\n\n".join(sections)


def assemble_full_brief(inputs: BriefInputs, llm_narrative: str) -> str:
    """
    Real runtime assembly: deterministic sections 1-4 + 6 + the LLM's
    single combined pass covering sections 5, 7-11 (the model is prompted
    to produce all five narrative sections together, with its own
    headers - simpler and more coherent than slotting each one into a
    separate placeholder) + deterministic section 12.
    """
    sections = [
        render_brief_header(inputs),
        render_section_1_snapshot(inputs),
        render_section_2_owner_intel(inputs),
        render_section_3_market_position(inputs),
        render_section_4_offer_ladder(inputs),
        render_section_6_pain_discovery(),
        llm_narrative,
        render_section_12_next_action(inputs),
    ]
    return "\n\n---\n\n".join(sections)
