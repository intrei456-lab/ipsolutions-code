"""
IPSolutions agent system - entry point.

Runs a FastAPI app (for webhooks + manual triggers) alongside an
in-process APScheduler instance covering all three agents' scheduled
jobs. Each agent has its own SQLite database file; cross-agent reads
happen via direct same-box file access (see each agent's handoff/ingest
modules).

Run locally for testing:
    uvicorn main:app --reload --port 8000

Trigger jobs manually while testing:
    curl -X POST http://localhost:8000/chris/scouts/tax_delinquent_md/run
    curl -X POST http://localhost:8000/alex/kpi/run
    curl -X POST http://localhost:8000/taylor/sweeps/pending_followups/run

Deploy: see README.md for the systemd service setup on a VPS.
"""

from contextlib import asynccontextmanager
from datetime import date

from dotenv import load_dotenv
load_dotenv()  # Must run before any module reads os.environ (e.g. shared/llm_client.py)

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from chris.db.db import init_db as chris_init_db, seed_market_zips
from chris.scouts import tax_delinquent_md
from alex.db.db import init_db as alex_init_db
from alex.dispo.kpi_rollup import compute_daily_kpi as alex_compute_kpi
from taylor.db.db import init_db as taylor_init_db, seed_node_template, seed_title_company_directory
from taylor.sweeps.daily_sweeps import pending_followups_sweep, closing_day_sweep, stall_detection_sweep
from taylor.nodes.kpi_and_archive import compute_kpi as taylor_compute_kpi

scheduler = AsyncIOScheduler(timezone="America/New_York")


# ---------------------------------------------------------------------------
# Chris's scheduled jobs
# ---------------------------------------------------------------------------

def run_chris_scout_pass_a():
    """7am ET daily. Currently runs the one live scout module; more get
    added here as they're built (see architecture doc build order)."""
    print("[scheduler] Chris: 7am scout pass A")
    tax_delinquent_md.run()
    # TODO as more scouts come online:
    # water_shutoff_md.run()
    # code_violations_md.run()
    # fl_county_rotation.run()
    # d4d_zip_rotation.run()


# ---------------------------------------------------------------------------
# Alex's scheduled jobs
# ---------------------------------------------------------------------------

def run_alex_daily_kpi():
    """End-of-day KPI rollup for Alex."""
    print("[scheduler] Alex: daily KPI rollup")
    alex_compute_kpi()
    # TODO: Mode 1/2 pipeline review (9am), touch sweep (4pm) once the
    # actual outreach-sending loop is wired to a real channel (email/SMS provider).


# ---------------------------------------------------------------------------
# Taylor's scheduled jobs
# ---------------------------------------------------------------------------

def run_taylor_pending_followups():
    """3pm ET daily."""
    print("[scheduler] Taylor: pending follow-ups sweep")
    pending_followups_sweep()


def run_taylor_closing_day():
    """5pm ET daily."""
    print("[scheduler] Taylor: closing day sweep")
    today = date.today().isoformat()
    closing_day_sweep(today)
    stall_detection_sweep()
    taylor_compute_kpi("daily")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup - initialize all three agent databases
    chris_init_db()
    seed_market_zips()
    alex_init_db()
    taylor_init_db()
    seed_node_template()
    seed_title_company_directory()

    scheduler.add_job(run_chris_scout_pass_a, CronTrigger(hour=7, minute=0),
                       id="chris_scout_pass_a", replace_existing=True)
    scheduler.add_job(run_alex_daily_kpi, CronTrigger(hour=20, minute=0),
                       id="alex_daily_kpi", replace_existing=True)
    scheduler.add_job(run_taylor_pending_followups, CronTrigger(hour=15, minute=0),
                       id="taylor_pending_followups", replace_existing=True)
    scheduler.add_job(run_taylor_closing_day, CronTrigger(hour=17, minute=0),
                       id="taylor_closing_day", replace_existing=True)
    scheduler.start()

    print("[startup] All 3 agent DBs initialized. Scheduler running:")
    print("  - Chris scout pass A: 7am ET")
    print("  - Alex daily KPI: 8pm ET")
    print("  - Taylor pending follow-ups: 3pm ET")
    print("  - Taylor closing day + stall detection + KPI: 5pm ET")
    yield
    # Shutdown
    scheduler.shutdown()


app = FastAPI(title="IPSolutions Agents", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def dashboard():
    return FileResponse("static/index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


def _gather_workspace_context() -> str:
    """Pulls a live snapshot across all three agents' real databases so the
    workspace chat has actual current numbers, not stale training knowledge."""
    from chris.db.db import get_connection as chris_conn
    from alex.db.db import get_connection as alex_conn
    from taylor.db.db import get_connection as taylor_conn

    lines = []
    try:
        conn = chris_conn()
        leads = conn.execute("SELECT COUNT(*) c FROM leads WHERE is_test_data = 0").fetchone()["c"]
        conn.close()
        lines.append(f"Chris: {leads} lead(s) in the system.")
    except Exception:  # noqa: BLE001
        lines.append("Chris: database not yet queryable.")

    try:
        conn = alex_conn()
        deals = conn.execute("SELECT COUNT(*) c FROM deals").fetchone()["c"]
        fps = conn.execute("SELECT COUNT(*) c FROM financial_partners WHERE is_test_data = 0").fetchone()["c"]
        conn.close()
        lines.append(f"Alex: {deals} deal(s) in the pipeline, {fps} financial partners loaded.")
    except Exception:  # noqa: BLE001
        lines.append("Alex: database not yet queryable.")

    try:
        conn = taylor_conn()
        closings = conn.execute("SELECT COUNT(*) c FROM closings").fetchone()["c"]
        conn.close()
        lines.append(f"Taylor: {closings} closing(s) in the pipeline.")
    except Exception:  # noqa: BLE001
        lines.append("Taylor: database not yet queryable.")

    return "\n".join(lines)


class WorkspaceChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class WorkspaceChatRequest(BaseModel):
    messages: list[WorkspaceChatMessage]


@app.post("/workspace/chat")
def workspace_chat(req: WorkspaceChatRequest):
    """
    The 'Chief of Staff' chat, embedded directly in the command center.
    Not a separate agent - a live conversational layer with real-time
    visibility into Chris/Alex/Taylor's actual current data, running on
    the same server, using the same API key already configured.
    """
    from shared.llm_client import get_client, MODEL

    live_context = _gather_workspace_context()

    system_prompt = f"""You are the Workspace Chat inside Thomas's IPSolutions
command center - his Chief of Staff for the business. You have live
visibility into Chris (Acquisitions), Alex (Dispositions), and Taylor
(Transaction Coordinator) - three AI agents that run this real estate
wholesaling/novation business.

CURRENT LIVE STATE OF THE BUSINESS (as of this message):
{live_context}

You are not one of the three agents - you're the layer above them, the
way Twin's "Workspace Chat" used to work: Thomas talks to you about
strategy, deal updates, questions, and you have context on what's
actually happening across all three agents. You do not run in the
background 24/7 - you only exist while Thomas is actively chatting with
you, unlike the three agents which run continuously via a scheduler on
the server.

Be direct, concise, and grounded in the real numbers above - don't
invent activity that hasn't happened. If asked about something outside
your visibility (e.g. a call that hasn't been logged), say so plainly
rather than guessing."""

    try:
        client = get_client()
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            system=system_prompt,
            messages=[{"role": m.role, "content": m.content} for m in req.messages],
        )
        text = "".join(block.text for block in response.content if hasattr(block, "text"))
        return {"success": True, "reply": text}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Chris endpoints
# ---------------------------------------------------------------------------

@app.post("/chris/scouts/tax_delinquent_md/run")
def trigger_tax_delinquent_md():
    result = tax_delinquent_md.run()
    return {"triggered": True, "result": result}


@app.get("/chris/leads")
def list_leads(limit: int = 50):
    from chris.db.db import get_connection

    conn = get_connection()
    rows = conn.execute(
        "SELECT lead_id, address, city, state, zip, source, status, motivation, "
        "arv, is_test_data, created_at FROM leads ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return {"leads": [dict(r) for r in rows]}


class NewLeadRequest(BaseModel):
    address: str
    city: str
    zip: str
    source: str = "MANUAL"
    owner_name: str | None = None
    owner_phone: str | None = None
    owner_email: str | None = None
    motivation: str | None = None
    arv: float | None = None
    repairs_estimate: float | None = None
    asking_price: float | None = None
    mortgage_balance: float = 0


@app.post("/chris/leads/add")
def add_lead(lead: NewLeadRequest):
    from chris.intake.zip_filter import insert_lead

    result = insert_lead(
        address=lead.address,
        city=lead.city,
        raw_zip=lead.zip,
        source=lead.source,
        owner_name=lead.owner_name,
        owner_phone=lead.owner_phone,
        owner_email=lead.owner_email,
        motivation=lead.motivation,
        arv=lead.arv,
        repairs_estimate=lead.repairs_estimate,
        asking_price=lead.asking_price,
        mortgage_balance=lead.mortgage_balance,
    )
    if not result.accepted:
        return {"accepted": False, "reason": result.reason}
    return {"accepted": True, "lead_id": result.lead_id}


@app.get("/chris/scout_runs")
def list_scout_runs(limit: int = 20):
    from chris.db.db import get_connection

    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM scout_runs ORDER BY run_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return {"scout_runs": [dict(r) for r in rows]}


@app.post("/chris/leads/{lead_id}/generate_brief")
def generate_brief(lead_id: int):
    """
    Pulls a real lead, computes the offer ladder from its ARV/repairs,
    calls Claude to draft the narrative sections, assembles the full
    12-section brief, and stores it in conversations (matching how the
    real system stores briefs: channel=EMAIL, outcome=BRIEF_DELIVERED).
    """
    from chris.db.db import get_connection
    from chris.conversation.offer_engine import compute_cash_ladder, decide_exit_strategy
    from chris.conversation.brief_generator import generate_llm_sections
    from chris.templates.pre_call_brief import (
        BriefInputs, PropertySnapshot, OwnerIntel, OfferLadder, assemble_full_brief,
    )

    conn = get_connection()
    lead = conn.execute("SELECT * FROM leads WHERE lead_id = ?", (lead_id,)).fetchone()
    if lead is None:
        conn.close()
        return {"success": False, "error": "lead_not_found"}
    lead = dict(lead)

    arv = lead["arv"] or 0
    if arv <= 0:
        conn.close()
        return {"success": False, "error": "Lead needs an ARV before a brief can be generated."}

    # Reasonable default if repairs weren't provided when the lead was added
    repairs = lead["repairs_estimate"] or (arv * 0.25)
    assignment_fee_target = 15000

    ladder = compute_cash_ladder(arv=arv, repairs=repairs, assignment_fee_target=assignment_fee_target)
    exit_strategy = decide_exit_strategy(rehab_cost=repairs, seller_wants_retail=False)

    inputs = BriefInputs(
        lead_id=str(lead_id),
        snapshot=PropertySnapshot(
            address=lead["address"], city=lead["city"] or "", state=lead["state"] or "",
            zip_code=lead["zip"] or "", source=lead["source"], property_type="Residential",
            days_on_market=0, risk_tier=lead["risk_tier"] or "STANDARD",
        ),
        owner=OwnerIntel(
            name=lead["owner_name"] or "Unknown - Discovery Required",
            phone=lead["owner_phone"], email=lead["owner_email"],
        ),
        offer=OfferLadder(
            arv=arv, repairs=repairs, t1_lowball=ladder.t1, mao_ceiling=ladder.mao_ceiling,
            novation_target=arv * 0.90, ask=lead["asking_price"],
        ),
        exit_strategy=exit_strategy,
        personality_hypothesis=None,
    )

    try:
        llm_result = generate_llm_sections(inputs)
    except Exception as exc:  # noqa: BLE001
        conn.close()
        return {"success": False, "error": f"LLM call failed: {exc}"}

    full_brief = assemble_full_brief(inputs, llm_result["text"])

    conn.execute(
        """
        INSERT INTO conversations (lead_id, channel, direction, outcome, body)
        VALUES (?, 'EMAIL', 'OUTBOUND', 'BRIEF_DELIVERED', ?)
        """,
        (lead_id, full_brief),
    )
    conn.execute("UPDATE leads SET status = 'RESEARCHED' WHERE lead_id = ?", (lead_id,))
    conn.commit()
    conn.close()

    return {
        "success": True,
        "brief": full_brief,
        "terminology_clean": llm_result["terminology_clean"],
        "spread_safety_clean": llm_result["spread_safety_clean"],
        "warnings": llm_result["warnings"],
    }


# ---------------------------------------------------------------------------
# Chris's daily KPI computation (mirrors alex/dispo/kpi_rollup.py's pattern -
# Chris never had an equivalent module built, so /chris/kpi computes live
# as a fallback when no daily_kpi row exists yet for today, rather than
# silently returning null.)
# ---------------------------------------------------------------------------

def _compute_chris_kpi_live(today: str) -> dict:
    from chris.db.db import get_connection

    conn = get_connection()
    leads_today = conn.execute(
        "SELECT COUNT(*) as c FROM leads WHERE date(created_at) = ? AND is_test_data = 0", (today,)
    ).fetchone()["c"]
    conversations_today = conn.execute(
        "SELECT COUNT(*) as c FROM conversations WHERE date(timestamp) = ?", (today,)
    ).fetchone()["c"]
    offers_today = conn.execute(
        "SELECT COUNT(*) as c FROM offers WHERE date(created_at) = ?", (today,)
    ).fetchone()["c"]
    contracts_today = conn.execute(
        "SELECT COUNT(*) as c FROM contracts WHERE date(signed_at) = ?", (today,)
    ).fetchone()["c"]
    fb_ad_leads = conn.execute(
        "SELECT COUNT(*) as c FROM leads WHERE date(created_at) = ? AND source = 'FB_AD'", (today,)
    ).fetchone()["c"]
    fsbo_leads = conn.execute(
        "SELECT COUNT(*) as c FROM leads WHERE date(created_at) = ? AND source = 'FSBO'", (today,)
    ).fetchone()["c"]
    scout_leads = conn.execute(
        "SELECT COUNT(*) as c FROM leads WHERE date(created_at) = ? AND source NOT IN ('FB_AD', 'FSBO')",
        (today,),
    ).fetchone()["c"]
    mat_beard_touches = conn.execute(
        "SELECT COUNT(*) as c FROM mat_beard_touches WHERE date(sent_at) = ?", (today,)
    ).fetchone()["c"]
    conn.close()

    return {
        "kpi_date": today,
        "leads_today": leads_today,
        "conversations_today": conversations_today,
        "offers_today": offers_today,
        "contracts_today": contracts_today,
        "fb_ad_leads": fb_ad_leads,
        "fsbo_leads": fsbo_leads,
        "scout_leads": scout_leads,
        "mat_beard_touches": mat_beard_touches,
    }


@app.get("/chris/kpi")
def chris_kpi():
    from chris.db.db import get_connection

    today = date.today().isoformat()
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM daily_kpi WHERE kpi_date = ?", (today,)
    ).fetchone()
    conn.close()

    if row:
        return {"kpi": dict(row)}
    # No scheduled rollup has run yet today - compute live rather than
    # returning null, so the dashboard always shows something real.
    return {"kpi": _compute_chris_kpi_live(today)}


# ---------------------------------------------------------------------------
# Alex endpoints
# ---------------------------------------------------------------------------

@app.post("/alex/kpi/run")
def trigger_alex_kpi():
    return {"triggered": True, "result": alex_compute_kpi()}


@app.get("/alex/deals")
def list_alex_deals(limit: int = 50):
    from alex.db.db import get_connection

    conn = get_connection()
    rows = conn.execute(
        "SELECT deal_id, dispo_status, exit_strategy, dispo_day, "
        "fp_facing_price, created_at FROM deals ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return {"deals": [dict(r) for r in rows]}


@app.get("/alex/financial_partners")
def list_financial_partners(limit: int = 50):
    from alex.db.db import get_connection

    conn = get_connection()
    rows = conn.execute(
        "SELECT fp_id, entity_name, vip_tier, dispo_tier, relationship_stage, "
        "total_deals_closed, phone, email FROM financial_partners WHERE is_test_data = 0 "
        "ORDER BY fp_id LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return {"financial_partners": [dict(r) for r in rows]}


@app.get("/alex/kpi")
def alex_kpi():
    from alex.db.db import get_connection

    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM dispo_kpi ORDER BY kpi_date DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return {"kpi": dict(row) if row else None}


@app.get("/alex/ceo_alerts")
def alex_ceo_alerts(limit: int = 20):
    from alex.db.db import get_connection

    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM ceo_alerts ORDER BY fired_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return {"alerts": [dict(r) for r in rows]}


# ---------------------------------------------------------------------------
# Taylor endpoints
# ---------------------------------------------------------------------------

@app.post("/taylor/sweeps/pending_followups/run")
def trigger_taylor_followups():
    return {"triggered": True, "result": pending_followups_sweep()}


@app.post("/taylor/sweeps/closing_day/run")
def trigger_taylor_closing_day():
    today = date.today().isoformat()
    return {"triggered": True, "result": closing_day_sweep(today)}


@app.get("/taylor/closings")
def list_closings(limit: int = 50):
    from taylor.db.db import get_connection

    conn = get_connection()
    rows = conn.execute(
        "SELECT closing_id, address, current_node, status, risk_tier, "
        "close_date_target, started_at FROM closings ORDER BY started_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return {"closings": [dict(r) for r in rows]}


@app.get("/taylor/closings/{closing_id}/nodes")
def get_closing_nodes(closing_id: int):
    from taylor.db.db import get_connection

    conn = get_connection()
    rows = conn.execute(
        """
        SELECT cn.node_number, cn.status, cn.blocking_reason, cn.notes,
               nt.title, nt.phase
        FROM closing_nodes cn
        JOIN node_template nt ON nt.node_number = cn.node_number
        WHERE cn.closing_id = ?
        ORDER BY cn.node_number
        """,
        (closing_id,),
    ).fetchall()
    conn.close()
    return {"nodes": [dict(r) for r in rows]}


@app.get("/taylor/ceo_alerts")
def taylor_ceo_alerts(limit: int = 20):
    from taylor.db.db import get_connection

    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM ceo_alerts ORDER BY fired_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return {"alerts": [dict(r) for r in rows]}
