"""
Embedded HTML view for citation validation results.

Renders as an interactive MCP App in supported hosts (Claude.ai, Claude Desktop,
VS Code Insiders). Falls back gracefully to text response in non-Apps clients.

Uses @modelcontextprotocol/ext-apps SDK from unpkg CDN for host communication.
"""

CITATION_VIEW_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Citation Validation Results</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #fafafa;
    color: #1a1a1a;
    padding: 16px;
    line-height: 1.5;
  }

  .header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 2px solid #e0e0e0;
  }

  .header h1 {
    font-size: 18px;
    font-weight: 600;
    color: #1a1a1a;
  }

  .header .badge {
    font-size: 12px;
    padding: 2px 8px;
    border-radius: 12px;
    font-weight: 500;
  }

  .summary {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
    gap: 8px;
    margin-bottom: 16px;
  }

  .stat {
    text-align: center;
    padding: 10px 8px;
    border-radius: 8px;
    background: white;
    border: 1px solid #e8e8e8;
  }

  .stat .number {
    font-size: 24px;
    font-weight: 700;
    display: block;
  }

  .stat .label {
    font-size: 11px;
    color: #666;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .stat.valid { border-left: 4px solid #22c55e; }
  .stat.valid .number { color: #16a34a; }

  .stat.ambiguous { border-left: 4px solid #f59e0b; }
  .stat.ambiguous .number { color: #d97706; }

  .stat.not-found { border-left: 4px solid #ef4444; }
  .stat.not-found .number { color: #dc2626; }

  .stat.invalid { border-left: 4px solid #94a3b8; }
  .stat.invalid .number { color: #64748b; }

  .stat.total { border-left: 4px solid #3b82f6; }
  .stat.total .number { color: #2563eb; }

  .risk-banner {
    padding: 10px 14px;
    border-radius: 8px;
    margin-bottom: 16px;
    font-size: 13px;
    font-weight: 500;
  }

  .risk-low { background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; }
  .risk-medium { background: #fffbeb; color: #92400e; border: 1px solid #fde68a; }
  .risk-high { background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; }
  .risk-critical { background: #fef2f2; color: #7f1d1d; border: 1px solid #fca5a5; }

  .citations-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .citation-card {
    background: white;
    border: 1px solid #e8e8e8;
    border-radius: 8px;
    padding: 12px 14px;
    display: flex;
    align-items: flex-start;
    gap: 10px;
    transition: box-shadow 0.15s;
  }

  .citation-card:hover {
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  }

  .status-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
    margin-top: 5px;
  }

  .status-200 .status-dot { background: #22c55e; }
  .status-300 .status-dot { background: #f59e0b; }
  .status-400 .status-dot { background: #94a3b8; }
  .status-404 .status-dot { background: #ef4444; }
  .status-429 .status-dot { background: #8b5cf6; }

  .citation-info { flex: 1; min-width: 0; }

  .citation-text {
    font-family: 'Georgia', serif;
    font-size: 14px;
    font-weight: 500;
    color: #1a1a1a;
    margin-bottom: 4px;
  }

  .citation-meta {
    font-size: 12px;
    color: #666;
  }

  .citation-meta .status-label {
    font-weight: 600;
    padding: 1px 6px;
    border-radius: 4px;
    font-size: 11px;
  }

  .status-200 .status-label { background: #dcfce7; color: #166534; }
  .status-300 .status-label { background: #fef3c7; color: #92400e; }
  .status-400 .status-label { background: #f1f5f9; color: #475569; }
  .status-404 .status-label { background: #fee2e2; color: #991b1b; }
  .status-429 .status-label { background: #ede9fe; color: #5b21b6; }

  .citation-links {
    display: flex;
    gap: 6px;
    margin-top: 6px;
    flex-wrap: wrap;
  }

  .citation-links button {
    font-size: 12px;
    color: #2563eb;
    text-decoration: none;
    padding: 2px 8px;
    border: 1px solid #bfdbfe;
    border-radius: 4px;
    background: #eff6ff;
    transition: background 0.15s;
    cursor: pointer;
    font-family: inherit;
  }

  .citation-links button:hover {
    background: #dbeafe;
  }

  /* Case detail card (lookup_mode) */
  .case-detail-header {
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 2px solid #e0e0e0;
  }

  .case-detail-header h1 {
    font-size: 18px;
    font-weight: 600;
    margin-bottom: 4px;
  }

  .query-label {
    font-size: 12px;
    color: #888;
  }

  .query-label span {
    font-family: 'Georgia', serif;
    color: #444;
    font-weight: 500;
  }

  .case-card {
    background: white;
    border: 1px solid #e8e8e8;
    border-radius: 10px;
    padding: 16px;
    margin-bottom: 10px;
  }

  .case-card:hover {
    box-shadow: 0 2px 10px rgba(0,0,0,0.08);
  }

  .case-name {
    font-size: 16px;
    font-weight: 600;
    color: #1a1a1a;
    margin-bottom: 8px;
  }

  .case-meta-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: 6px;
    margin-bottom: 12px;
  }

  .case-meta-item {
    font-size: 12px;
    color: #555;
  }

  .case-meta-item strong {
    display: block;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #999;
    margin-bottom: 2px;
  }

  .open-cl-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: #1d4ed8;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 14px;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    font-family: inherit;
    transition: background 0.15s;
  }

  .open-cl-btn:hover {
    background: #1e40af;
  }

  .no-results {
    text-align: center;
    padding: 30px;
    background: #fff8f8;
    border: 1px solid #fecaca;
    border-radius: 10px;
    color: #991b1b;
    font-size: 14px;
  }

  .no-results .no-results-title {
    font-size: 16px;
    font-weight: 600;
    margin-bottom: 6px;
  }

  .citation-badge {
    display: inline-block;
    font-family: 'Georgia', serif;
    background: #f1f5f9;
    border: 1px solid #e2e8f0;
    border-radius: 4px;
    padding: 1px 7px;
    font-size: 13px;
    color: #334155;
    margin-left: 6px;
    vertical-align: middle;
  }

  .loading {
    text-align: center;
    padding: 40px;
    color: #666;
  }

  .loading .spinner {
    display: inline-block;
    width: 24px;
    height: 24px;
    border: 3px solid #e0e0e0;
    border-top-color: #3b82f6;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    margin-bottom: 8px;
  }

  @keyframes spin { to { transform: rotate(360deg); } }

  .empty-state {
    text-align: center;
    padding: 30px;
    color: #888;
    font-size: 14px;
  }

  @media (prefers-color-scheme: dark) {
    body { background: #1a1a2e; color: #e0e0e0; }
    .header { border-bottom-color: #333; }
    .header h1 { color: #e0e0e0; }
    .stat { background: #16213e; border-color: #333; }
    .stat .label { color: #999; }
    .citation-card { background: #16213e; border-color: #333; }
    .citation-text { color: #e0e0e0; }
    .citation-meta { color: #999; }
    .citation-links button { background: #1e3a5f; border-color: #2563eb; color: #60a5fa; }
    .citation-links button:hover { background: #1e40af; }
    /* Case detail dark mode */
    .case-detail-header { border-bottom-color: #333; }
    .case-detail-header h1 { color: #e0e0e0; }
    .query-label { color: #777; }
    .query-label span { color: #bbb; }
    .case-card { background: #16213e; border-color: #333; }
    .case-name { color: #e0e0e0; }
    .case-meta-item { color: #aaa; }
    .citation-badge { background: #1e3a5f; border-color: #334155; color: #93c5fd; }
    .no-results { background: #2d1515; border-color: #7f1d1d; color: #fca5a5; }
  }
</style>
</head>
<body>
<div id="app">
  <div class="loading">
    <div class="spinner"></div>
    <div>Validating citations...</div>
  </div>
</div>

<script type="module">
import { App } from 'https://cdn.jsdelivr.net/npm/@modelcontextprotocol/ext-apps@1.2.0/dist/src/app-with-deps.js';

const appEl = document.getElementById('app');
const app = new App({ name: 'Citation Validation Results', version: '1.0.0' });

const STATUS_LABELS = {
  200: 'Verified',
  300: 'Ambiguous',
  400: 'Invalid Reporter',
  404: 'Not Found',
  429: 'Overflow',
};

function getRiskLevel(total, notFound) {
  if (total === 0) return null;
  const pct = (notFound / total) * 100;
  if (pct > 20) return { level: 'critical', text: 'CRITICAL RISK: >' + Math.round(pct) + '% citations not found - likely fabricated' };
  if (pct > 10) return { level: 'high', text: 'HIGH RISK: ' + Math.round(pct) + '% citations not found - review carefully' };
  if (pct > 5) return { level: 'medium', text: 'MEDIUM RISK: ' + Math.round(pct) + '% citations not found - some may be coverage gaps' };
  if (notFound > 0) return { level: 'low', text: 'LOW RISK: ' + notFound + ' citation(s) not found - likely coverage gaps' };
  return { level: 'low', text: 'All citations verified successfully' };
}

function buildClusterLinks(clusters) {
  if (!clusters || !Array.isArray(clusters) || clusters.length === 0) return '';
  return clusters.map(c => {
    const url = c.absolute_url
      ? 'https://www.courtlistener.com' + c.absolute_url
      : '';
    const name = c.case_name || c.caseName || 'View Case';
    if (!url) return '';
    return '<button data-url="' + escapeHtml(url) + '">' + escapeHtml(name) + '</button>';
  }).filter(Boolean).join('');
}

function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

// URL safety check (sandboxed iframe blocks target="_blank" — use ui/openLink instead)
function isValidHttpUrl(str) {
  try { const u = new URL(str); return u.protocol === 'http:' || u.protocol === 'https:'; }
  catch { return false; }
}

// ── Case-detail view (rendered by courtlistener_open_citation) ──────────────
function renderLookup(parsed) {
  const query = parsed.query || 'Unknown citation';
  const cases = parsed.results || [];

  let html = '<div class="case-detail-header">';
  html += '<h1>CourtListener Lookup</h1>';
  html += '<div class="query-label">Query: <span>' + escapeHtml(query) + '</span></div>';
  html += '</div>';

  if (cases.length === 0) {
    html += '<div class="no-results">';
    html += '<div class="no-results-title">Not Found on CourtListener</div>';
    html += '<div>No cases matched <strong>' + escapeHtml(query) + '</strong>.</div>';
    html += '<div style="margin-top:8px;font-size:12px;color:#666;">This citation is likely fabricated or not yet indexed.</div>';
    html += '</div>';
    appEl.innerHTML = html;
    requestAnimationFrame(() => {
      app.sendNotification('ui/notifications/size-changed', { height: document.documentElement.scrollHeight });
    });
    return;
  }

  for (const c of cases) {
    const clUrl = c.courtlistener_url || '';
    const citations = Array.isArray(c.citation) ? c.citation.join(', ') : (c.citation || '');

    html += '<div class="case-card">';
    html += '<div class="case-name">' + escapeHtml(c.case_name || 'Unknown') + '</div>';
    html += '<div class="case-meta-grid">';
    if (c.court)         html += '<div class="case-meta-item"><strong>Court</strong>' + escapeHtml(c.court) + '</div>';
    if (c.date_filed)    html += '<div class="case-meta-item"><strong>Date Filed</strong>' + escapeHtml(c.date_filed) + '</div>';
    if (c.docket_number) html += '<div class="case-meta-item"><strong>Docket</strong>' + escapeHtml(c.docket_number) + '</div>';
    if (c.status)        html += '<div class="case-meta-item"><strong>Status</strong>' + escapeHtml(c.status) + '</div>';
    if (citations)       html += '<div class="case-meta-item"><strong>Citations</strong><span class="citation-badge">' + escapeHtml(citations) + '</span></div>';
    html += '</div>';
    if (clUrl && isValidHttpUrl(clUrl)) {
      html += '<button class="open-cl-btn" data-url="' + escapeHtml(clUrl) + '">&#8599; Open in CourtListener</button>';
    }
    html += '</div>';
  }

  appEl.innerHTML = html;
}

// ── Validation summary view (rendered by courtlistener_validate_citations) ───
function renderValidation(parsed) {
  const total = parsed.total_citations || parsed.citations.length;
  const valid = parsed.valid || 0;
  const ambiguous = parsed.ambiguous || 0;
  const notFound = parsed.not_found || 0;
  const invalid = parsed.invalid_reporter || 0;
  const overflow = parsed.overflow || 0;
  const risk = getRiskLevel(total, notFound);

  let html = '<div class="header">';
  html += '<h1>Citation Validation</h1>';
  html += '<span class="badge" style="background:#eff6ff;color:#2563eb;">' + total + ' citations</span>';
  html += '</div>';

  html += '<div class="summary">';
  html += '<div class="stat total"><span class="number">' + total + '</span><span class="label">Total</span></div>';
  html += '<div class="stat valid"><span class="number">' + valid + '</span><span class="label">Verified</span></div>';
  if (ambiguous > 0) html += '<div class="stat ambiguous"><span class="number">' + ambiguous + '</span><span class="label">Ambiguous</span></div>';
  html += '<div class="stat not-found"><span class="number">' + notFound + '</span><span class="label">Not Found</span></div>';
  if (invalid > 0) html += '<div class="stat invalid"><span class="number">' + invalid + '</span><span class="label">Invalid</span></div>';
  if (overflow > 0) html += '<div class="stat invalid"><span class="number">' + overflow + '</span><span class="label">Overflow</span></div>';
  html += '</div>';

  if (risk) {
    html += '<div class="risk-banner risk-' + risk.level + '">' + escapeHtml(risk.text) + '</div>';
  }

  html += '<div class="citations-list">';
  for (const cit of parsed.citations) {
    const status = cit.status || 0;
    const citText = cit.citation || cit.normalized_citations?.[0] || 'Unknown citation';
    const statusLabel = STATUS_LABELS[status] || 'Unknown';
    const links = buildClusterLinks(cit.clusters);
    const searchUrl = (status === 404 && cit.search_url && isValidHttpUrl(cit.search_url)) ? cit.search_url : null;

    html += '<div class="citation-card status-' + status + '">';
    html += '<div class="status-dot"></div>';
    html += '<div class="citation-info">';
    html += '<div class="citation-text">' + escapeHtml(citText) + '</div>';
    html += '<div class="citation-meta"><span class="status-label">' + statusLabel + '</span></div>';
    if (links) html += '<div class="citation-links">' + links + '</div>';
    if (searchUrl) html += '<div class="citation-links"><button data-url="' + escapeHtml(searchUrl) + '">Search CourtListener &rarr;</button></div>';
    html += '</div></div>';
  }
  html += '</div>';

  appEl.innerHTML = html;
}

// ── Router ───────────────────────────────────────────────────────────────────
function render(data) {
  let parsed;
  try {
    const text = data.content?.find(c => c.type === 'text')?.text;
    parsed = text ? JSON.parse(text) : null;
  } catch (e) {
    appEl.innerHTML = '<div class="empty-state">Could not parse results.</div>';
    return;
  }

  if (!parsed) {
    appEl.innerHTML = '<div class="empty-state">No data received.</div>';
    return;
  }

  // open_citation result → case detail card
  if (parsed.lookup_mode) {
    renderLookup(parsed);
    return;
  }

  // validate_citations result → citation summary
  if (!parsed.citations || parsed.citations.length === 0) {
    appEl.innerHTML = '<div class="empty-state">' + escapeHtml(parsed.summary || 'No citations found.') + '</div>';
    return;
  }

  renderValidation(parsed);
}

// ── Click handler: open CourtListener URLs via the host (iframe can't do it) ─
document.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-url]');
  if (btn) {
    const url = btn.getAttribute('data-url');
    if (url && isValidHttpUrl(url)) {
      app.openLink({ url });
    }
  }
});

app.ontoolresult = (result) => render(result);
app.connect();
</script>
</body>
</html>"""
