// IPSolutions Pipeline Command - vanilla JS, no build step, calls the
// real FastAPI endpoints defined in main.py.

const SUB_TABS = {
  chris: [
    { id: 'leads', label: 'Leads' },
    { id: 'kpi', label: 'Daily KPI' },
    { id: 'scouts', label: 'Scout Runs' },
  ],
  alex: [
    { id: 'deals', label: 'Pipeline' },
    { id: 'fp_network', label: 'FP Network' },
    { id: 'kpi', label: 'KPI' },
    { id: 'alerts', label: 'CEO Alerts' },
  ],
  taylor: [
    { id: 'closings', label: 'Closings' },
    { id: 'alerts', label: 'CEO Alerts' },
  ],
};

let currentAgent = 'chris';
let currentSubTab = 'leads';

function switchAgent(agent) {
  currentAgent = agent;
  currentSubTab = SUB_TABS[agent][0].id;
  document.querySelectorAll('.agent-tab').forEach(el => {
    el.classList.toggle('active', el.dataset.agent === agent);
  });
  renderSubTabs();
  loadView();
}

function renderSubTabs() {
  const nav = document.getElementById('subTabs');
  nav.innerHTML = '';
  SUB_TABS[currentAgent].forEach(tab => {
    const el = document.createElement('div');
    el.className = 'sub-tab' + (tab.id === currentSubTab ? ' active' : '');
    el.textContent = tab.label;
    el.onclick = () => { currentSubTab = tab.id; renderSubTabs(); loadView(); };
    nav.appendChild(el);
  });
}

function refreshCurrent() { loadView(); }

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} returned ${res.status}`);
  return res.json();
}

function emptyState(message) {
  return `<div class="empty-state"><div class="glyph">&mdash;</div>${message}</div>`;
}

function badge(text, kind) {
  return `<span class="badge badge-${kind}">${text}</span>`;
}

function statusBadgeKind(status) {
  const s = (status || '').toUpperCase();
  if (['DONE', 'CLOSED', 'VERIFIED_BUYER', 'ACTIVE', 'REPEAT'].includes(s)) return 'green';
  if (['BLOCKED', 'DEAD', 'CRITICAL', 'SUSPECTED_WHOLESALER'].includes(s)) return 'red';
  if (['IN_PROGRESS', 'WARN', 'PENDING'].includes(s)) return 'amber';
  return 'neutral';
}

async function loadView() {
  const main = document.getElementById('mainContent');
  main.innerHTML = '<div class="loading">Loading...</div>';
  try {
    if (currentAgent === 'chris') await loadChrisView(main);
    else if (currentAgent === 'alex') await loadAlexView(main);
    else if (currentAgent === 'taylor') await loadTaylorView(main);
  } catch (err) {
    main.innerHTML = emptyState(`Could not load data — ${err.message}. Is the server running?`);
  }
}

// ---------------------------------------------------------------------------
// Chris views
// ---------------------------------------------------------------------------

async function loadChrisView(main) {
  if (currentSubTab === 'leads') {
    const { leads } = await fetchJSON('/chris/leads');
    const formHtml = `<div class="node-phase" style="margin-bottom:20px;max-width:500px">
      <h3>Add a Lead</h3>
      <div style="display:flex;flex-direction:column;gap:8px">
        <input id="newLeadAddress" placeholder="Address" style="padding:8px;background:var(--charcoal-lighter);border:1px solid var(--border-subtle);color:var(--text-primary);border-radius:6px">
        <input id="newLeadCity" placeholder="City" style="padding:8px;background:var(--charcoal-lighter);border:1px solid var(--border-subtle);color:var(--text-primary);border-radius:6px">
        <input id="newLeadZip" placeholder="ZIP" style="padding:8px;background:var(--charcoal-lighter);border:1px solid var(--border-subtle);color:var(--text-primary);border-radius:6px">
        <input id="newLeadOwnerName" placeholder="Owner name (optional)" style="padding:8px;background:var(--charcoal-lighter);border:1px solid var(--border-subtle);color:var(--text-primary);border-radius:6px">
        <input id="newLeadOwnerPhone" placeholder="Owner phone (optional)" style="padding:8px;background:var(--charcoal-lighter);border:1px solid var(--border-subtle);color:var(--text-primary);border-radius:6px">
        <input id="newLeadArv" placeholder="ARV (optional)" type="number" style="padding:8px;background:var(--charcoal-lighter);border:1px solid var(--border-subtle);color:var(--text-primary);border-radius:6px">
        <button onclick="submitNewLead()" style="padding:10px;background:var(--gold-light);color:var(--charcoal);border:none;border-radius:6px;font-weight:600;cursor:pointer">Add Lead</button>
        <div id="newLeadStatus"></div>
      </div>
    </div>`;

    if (!leads.length) {
      main.innerHTML = formHtml + emptyState('No leads yet. Add one above, or wait for a scout run.');
      return;
    }
    main.innerHTML = formHtml + `<table class="data-table">
      <tr><th>Address</th><th>City/State</th><th>Source</th><th>Status</th><th>Motivation</th><th>ARV</th></tr>
      ${leads.map(l => `<tr>
        <td>${l.address}</td>
        <td>${l.city || ''}, ${l.state || ''}</td>
        <td>${l.source}</td>
        <td>${badge(l.status, statusBadgeKind(l.status))}</td>
        <td>${l.motivation || '—'}</td>
        <td>${l.arv ? '$' + Number(l.arv).toLocaleString() : '—'}</td>
      </tr>`).join('')}
    </table>`;
  } else if (currentSubTab === 'kpi') {
    const { kpi } = await fetchJSON('/chris/kpi');
    if (!kpi) { main.innerHTML = emptyState('No KPI data for today yet.'); return; }
    main.innerHTML = kpiRow([
      ['Leads Today', kpi.leads_today], ['Conversations', kpi.conversations_today],
      ['Offers', kpi.offers_today], ['Contracts', kpi.contracts_today],
      ['FB Ad Leads', kpi.fb_ad_leads], ['FSBO Leads', kpi.fsbo_leads],
      ['Scout Leads', kpi.scout_leads], ['Mat Beard Touches', kpi.mat_beard_touches],
    ]);
  } else if (currentSubTab === 'scouts') {
    const { scout_runs } = await fetchJSON('/chris/scout_runs');
    if (!scout_runs.length) { main.innerHTML = emptyState('No scout runs logged yet.'); return; }
    main.innerHTML = `<table class="data-table">
      <tr><th>Module</th><th>Ran At</th><th>Raw</th><th>In-Market</th><th>New Leads</th><th>Status</th></tr>
      ${scout_runs.map(r => `<tr>
        <td>${r.module}</td><td>${r.run_at}</td><td>${r.raw_results}</td>
        <td>${r.in_market_results}</td><td>${r.new_leads}</td>
        <td>${badge(r.portal_status, r.portal_status === 'OK' ? 'green' : 'red')}</td>
      </tr>`).join('')}
    </table>`;
  }
}

// ---------------------------------------------------------------------------
// Alex views
// ---------------------------------------------------------------------------

async function loadAlexView(main) {
  if (currentSubTab === 'deals') {
    const { deals } = await fetchJSON('/alex/deals');
    if (!deals.length) { main.innerHTML = emptyState('No deals in the pipeline yet — waiting on a handoff from Chris.'); return; }
    main.innerHTML = `<table class="data-table">
      <tr><th>Deal ID</th><th>Status</th><th>Exit Strategy</th><th>Tier</th><th>Dispo Day</th><th>FP Price</th></tr>
      ${deals.map(d => `<tr>
        <td>${d.deal_id}</td>
        <td>${badge(d.dispo_status, statusBadgeKind(d.dispo_status))}</td>
        <td>${d.exit_strategy}</td>
        <td class="tier-${(d.dispo_tier || 'c').toLowerCase()}">${d.dispo_tier || '—'}</td>
        <td>${d.dispo_day ?? '—'} / 5</td>
        <td>${d.fp_facing_price ? '$' + Number(d.fp_facing_price).toLocaleString() : '—'}</td>
      </tr>`).join('')}
    </table>`;
  } else if (currentSubTab === 'fp_network') {
    const { financial_partners } = await fetchJSON('/alex/financial_partners');
    if (!financial_partners.length) { main.innerHTML = emptyState('No financial partners loaded yet.'); return; }
    window._fpData = financial_partners;
    main.innerHTML = `<table class="data-table">
      <tr><th>Entity</th><th>VIP Tier</th><th>Dispo Tier</th><th>Relationship</th><th>Deals Closed</th></tr>
      ${financial_partners.map((fp, i) => `<tr onclick="showFPDetail(${i})" style="cursor:pointer">
        <td>${fp.entity_name}</td>
        <td>${badge(fp.vip_tier, fp.vip_tier === 'VIP' ? 'green' : fp.vip_tier === 'WARM' ? 'amber' : 'neutral')}</td>
        <td class="tier-${(fp.dispo_tier || 'c').toLowerCase()}">${fp.dispo_tier || 'C'}</td>
        <td>${badge(fp.relationship_stage, statusBadgeKind(fp.relationship_stage))}</td>
        <td>${fp.total_deals_closed}</td>
      </tr>`).join('')}
    </table>
    <div id="fpDetailContainer" style="margin-top:20px"></div>`;
  } else if (currentSubTab === 'kpi') {
    const { kpi } = await fetchJSON('/alex/kpi');
    if (!kpi) { main.innerHTML = emptyState('No KPI data yet.'); return; }
    main.innerHTML = kpiRow([
      ['Active OWN', kpi.active_deals_own], ['Active JV', kpi.active_deals_jv],
      ['Avg DOM', kpi.avg_days_on_market], ['FP Touches Today', kpi.fp_touches_today],
      ['Avg TTB (hrs)', kpi.avg_ttb_hours], ['TTB Breaches', kpi.ttb_breaches],
      ['Tier A', kpi.tier_a_count], ['Tier B', kpi.tier_b_count], ['Tier C', kpi.tier_c_count],
    ]);
  } else if (currentSubTab === 'alerts') {
    await renderAlerts(main, '/alex/ceo_alerts');
  }
}

// ---------------------------------------------------------------------------
// Taylor views
// ---------------------------------------------------------------------------

async function loadTaylorView(main) {
  if (currentSubTab === 'closings') {
    const { closings } = await fetchJSON('/taylor/closings');
    if (!closings.length) { main.innerHTML = emptyState('No closings in the pipeline yet — waiting on a handoff from Alex.'); return; }
    main.innerHTML = `<table class="data-table">
      <tr><th>Address</th><th>Node</th><th>Status</th><th>Risk Tier</th><th>Close Date</th></tr>
      ${closings.map(c => `<tr onclick="loadNodeBoard(${c.closing_id})" style="cursor:pointer">
        <td>${c.address}</td>
        <td>${c.current_node} / 36</td>
        <td>${badge(c.status, statusBadgeKind(c.status))}</td>
        <td>${badge(c.risk_tier, c.risk_tier === 'PROTECT_SPREAD' ? 'amber' : 'green')}</td>
        <td>${c.close_date_target || '—'}</td>
      </tr>`).join('')}
    </table>
    <div id="nodeBoardContainer" style="margin-top:20px"></div>`;
  } else if (currentSubTab === 'alerts') {
    await renderAlerts(main, '/taylor/ceo_alerts');
  }
}

async function loadNodeBoard(closingId) {
  const container = document.getElementById('nodeBoardContainer');
  container.innerHTML = '<div class="loading">Loading node board...</div>';
  const { nodes } = await fetchJSON(`/taylor/closings/${closingId}/nodes`);

  const phases = {};
  nodes.forEach(n => { (phases[n.phase] ||= []).push(n); });

  container.innerHTML = `<div class="node-board">
    ${Object.entries(phases).map(([phase, phaseNodes]) => `
      <div class="node-phase">
        <h3>${phase.replace('_', ' ')}</h3>
        ${phaseNodes.map(n => `<div class="node-row">
          <span>${n.node_number}. ${n.title}</span>
          ${badge(n.status, statusBadgeKind(n.status))}
        </div>`).join('')}
      </div>
    `).join('')}
  </div>`;
}

function showFPDetail(index) {
  const fp = window._fpData[index];
  const container = document.getElementById('fpDetailContainer');
  const phoneLine = fp.phone
    ? `<div class="node-row"><span>Phone</span><a href="tel:${fp.phone}" style="color:var(--gold-light)">${fp.phone}</a></div>`
    : `<div class="node-row"><span>Phone</span><span>—</span></div>`;
  const emailLine = fp.email
    ? `<div class="node-row"><span>Email</span><a href="mailto:${fp.email}" style="color:var(--gold-light)">${fp.email}</a></div>`
    : `<div class="node-row"><span>Email</span><span>—</span></div>`;

  container.innerHTML = `<div class="node-phase" style="max-width:400px">
    <h3>${fp.entity_name}</h3>
    ${phoneLine}
    ${emailLine}
    <div class="node-row"><span>VIP Tier</span>${badge(fp.vip_tier, fp.vip_tier === 'VIP' ? 'green' : fp.vip_tier === 'WARM' ? 'amber' : 'neutral')}</div>
    <div class="node-row"><span>Dispo Tier</span><span class="tier-${(fp.dispo_tier || 'c').toLowerCase()}">${fp.dispo_tier || 'C'}</span></div>
    <div class="node-row"><span>Relationship</span>${badge(fp.relationship_stage, statusBadgeKind(fp.relationship_stage))}</div>
    <div class="node-row"><span>Deals Closed</span><span>${fp.total_deals_closed}</span></div>
  </div>`;
}

// ---------------------------------------------------------------------------
// Shared render helpers
// ---------------------------------------------------------------------------

async function submitNewLead() {
  const statusEl = document.getElementById('newLeadStatus');
  const address = document.getElementById('newLeadAddress').value.trim();
  const city = document.getElementById('newLeadCity').value.trim();
  const zip = document.getElementById('newLeadZip').value.trim();
  const ownerName = document.getElementById('newLeadOwnerName').value.trim();
  const ownerPhone = document.getElementById('newLeadOwnerPhone').value.trim();
  const arv = document.getElementById('newLeadArv').value.trim();

  if (!address || !city || !zip) {
    statusEl.innerHTML = '<span style="color:var(--status-red)">Address, city, and ZIP are required.</span>';
    return;
  }

  statusEl.innerHTML = '<span style="color:var(--text-secondary)">Adding...</span>';

  try {
    const res = await fetch('/chris/leads/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        address, city, zip,
        owner_name: ownerName || null,
        owner_phone: ownerPhone || null,
        arv: arv ? Number(arv) : null,
      }),
    });
    const data = await res.json();

    if (data.accepted) {
      statusEl.innerHTML = '<span style="color:var(--status-green)">Lead added successfully.</span>';
      setTimeout(() => loadView(), 800);
    } else {
      statusEl.innerHTML = `<span style="color:var(--status-red)">Not added: ${data.reason || 'unknown error'}</span>`;
    }
  } catch (err) {
    statusEl.innerHTML = `<span style="color:var(--status-red)">Error: ${err.message}</span>`;
  }
}

function kpiRow(pairs) {
  return `<div class="kpi-row">
    ${pairs.map(([label, value]) => `<div class="kpi-card">
      <div class="kpi-label">${label}</div>
      <div class="kpi-value numeral">${value ?? 0}</div>
    </div>`).join('')}
  </div>`;
}

async function renderAlerts(main, url) {
  const { alerts } = await fetchJSON(url);
  if (!alerts.length) { main.innerHTML = emptyState('No alerts fired — pipeline is clean.'); return; }
  main.innerHTML = `<table class="data-table">
    <tr><th>Type</th><th>Severity</th><th>Message</th><th>Fired At</th></tr>
    ${alerts.map(a => `<tr>
      <td>${a.alert_type}</td>
      <td>${badge(a.severity, a.severity === 'CRITICAL' || a.severity === 'HIGH' ? 'red' : a.severity === 'WARN' || a.severity === 'MEDIUM' ? 'amber' : 'neutral')}</td>
      <td>${a.message || ''}</td>
      <td>${a.fired_at}</td>
    </tr>`).join('')}
  </table>`;
}

// Init
renderSubTabs();
loadView();
