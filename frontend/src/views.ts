import {
  AnalysisResultRecord,
  ConfigResponse,
  EditableConfig,
  Flash,
  HealthResponse,
  RunResponse,
  Score,
  UiFilters,
} from './models';

const SCORE_ORDER: Score[] = ['HIGH', 'MEDIUM', 'LOW', 'IRRELEVANT'];
const SCORE_TEXT: Record<Score, string> = {
  HIGH: 'High',
  MEDIUM: 'Medium',
  LOW: 'Low',
  IRRELEVANT: 'Irrelevant',
};

export function todayUtc(): string {
  return new Date().toISOString().slice(0, 10);
}

export function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function escapeAttr(value: unknown): string {
  return escapeHtml(value);
}

function compactText(value: string, maxLength = 220): string {
  const normalized = value.replace(/\s+/g, ' ').trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }

  return `${normalized.slice(0, maxLength - 3)}...`;
}

function renderFlash(flash?: Flash): string {
  if (!flash) {
    return '';
  }

  return `<div class="flash flash-${escapeAttr(flash.kind)}">${escapeHtml(flash.message)}</div>`;
}

function pageShell(options: {
  title: string;
  current: 'dashboard' | 'config' | 'run' | 'status';
  body: string;
  authEnabled?: boolean;
}): string {
  const nav = [
    ['dashboard', '/', 'Dashboard'],
    ['config', '/config', 'Config'],
    ['run', '/run', 'Run'],
    ['status', '/status', 'Status'],
  ] as const;

  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${escapeHtml(options.title)}</title>
  <style>${APP_CSS}</style>
</head>
<body>
  <div class="app">
    <aside class="sidebar">
      <a class="brand" href="/">
        <span class="brand-mark">PS</span>
        <span>
          <strong>PaperSniffer</strong>
          <small>Research radar</small>
        </span>
      </a>
      <nav class="nav">
        ${nav.map(([key, href, label]) => `<a class="${options.current === key ? 'active' : ''}" href="${href}">${label}</a>`).join('')}
      </nav>
      ${options.authEnabled ? '<form class="logout" method="post" action="/logout"><button type="submit">Sign out</button></form>' : ''}
    </aside>
    <main class="main">
      ${options.body}
    </main>
  </div>
</body>
</html>`;
}

function scoreClass(score: string): string {
  return `score-${score.toLowerCase()}`;
}

function tagList(values: string[], className = 'tag'): string {
  if (values.length === 0) {
    return '<span class="muted">None</span>';
  }

  return values.map(value => `<span class="${className}">${escapeHtml(value)}</span>`).join('');
}

function queryString(filters: UiFilters, overrides: Partial<UiFilters> = {}): string {
  const merged = {
    ...filters,
    ...overrides,
  };
  const params = new URLSearchParams();

  for (const key of ['date', 'q', 'score', 'category', 'keyword', 'selected'] as const) {
    const value = merged[key];
    if (value) {
      params.set(key, value);
    }
  }

  const query = params.toString();
  return query ? `?${query}` : '';
}

function renderScoreOptions(selected: string): string {
  const options = ['ALL', ...SCORE_ORDER];
  return options.map(score => {
    const value = score === 'ALL' ? '' : score;
    const label = score === 'ALL' ? 'All scores' : SCORE_TEXT[score as Score];
    return `<option value="${value}" ${selected === value ? 'selected' : ''}>${label}</option>`;
  }).join('');
}

function renderDashboardToolbar(filters: UiFilters): string {
  const exportMd = `/export.md${queryString(filters, { selected: '' })}`;
  const exportJson = `/export.json${queryString(filters, { selected: '' })}`;

  return `<form class="toolbar" method="get" action="/">
    <label>
      <span>Date</span>
      <input type="date" name="date" value="${escapeAttr(filters.date)}">
    </label>
    <label class="grow">
      <span>Search</span>
      <input type="search" name="q" value="${escapeAttr(filters.q)}" placeholder="title, author, method, problem">
    </label>
    <label>
      <span>Score</span>
      <select name="score">${renderScoreOptions(filters.score)}</select>
    </label>
    <label>
      <span>Category</span>
      <input name="category" value="${escapeAttr(filters.category)}" placeholder="cs.CL">
    </label>
    <label>
      <span>Keyword</span>
      <input name="keyword" value="${escapeAttr(filters.keyword)}" placeholder="agent">
    </label>
    <button type="submit">Refresh</button>
    <a class="button secondary" href="${exportMd}">Markdown</a>
    <a class="button secondary" href="${exportJson}">JSON</a>
  </form>`;
}

function renderStats(results: AnalysisResultRecord[], totalCount: number): string {
  const counts = new Map<Score, number>(SCORE_ORDER.map(score => [score, 0]));
  for (const result of results) {
    counts.set(result.score, (counts.get(result.score) || 0) + 1);
  }

  return `<section class="stats">
    <div><strong>${results.length}</strong><span>Filtered</span></div>
    <div><strong>${totalCount}</strong><span>Total</span></div>
    ${SCORE_ORDER.map(score => `<div><strong>${counts.get(score) || 0}</strong><span>${SCORE_TEXT[score]}</span></div>`).join('')}
  </section>`;
}

function renderPaperList(results: AnalysisResultRecord[], filters: UiFilters, selected?: AnalysisResultRecord): string {
  if (results.length === 0) {
    return `<section class="empty">
      <h2>No papers found</h2>
      <p>Try another date or loosen the filters.</p>
    </section>`;
  }

  return `<section class="paper-list" aria-label="Paper results">
    ${results.map(result => {
      const href = `/${queryString(filters, { selected: result.id })}`;
      const active = selected?.id === result.id ? ' active' : '';
      return `<article class="paper-card${active}">
        <div class="paper-head">
          <span class="score ${scoreClass(result.score)}">${SCORE_TEXT[result.score]}</span>
          <span class="muted">${escapeHtml(result.published.slice(0, 10))}</span>
        </div>
        <h2><a href="${href}">${escapeHtml(result.title)}</a></h2>
        <p>${escapeHtml(compactText(result.reason || result.abstract))}</p>
        <div class="tags">${tagList(result.categories.slice(0, 4))}</div>
        <div class="paper-meta">${escapeHtml(compactText(result.authors.join(', '), 120))}</div>
      </article>`;
    }).join('')}
  </section>`;
}

function renderDetail(result?: AnalysisResultRecord): string {
  if (!result) {
    return `<aside class="detail-panel">
      <h2>Select a paper</h2>
      <p class="muted">Open a result to inspect its methods, problem framing, and keywords.</p>
    </aside>`;
  }

  return `<aside class="detail-panel">
    <div class="paper-head">
      <span class="score ${scoreClass(result.score)}">${SCORE_TEXT[result.score]}</span>
      <a class="button secondary" href="${escapeAttr(result.paper_url)}" target="_blank" rel="noreferrer">Open paper</a>
    </div>
    <h2>${escapeHtml(result.title)}</h2>
    <dl class="details">
      <dt>Authors</dt>
      <dd>${escapeHtml(result.authors.join(', ') || 'Unknown')}</dd>
      <dt>Published</dt>
      <dd>${escapeHtml(result.published.slice(0, 10))}</dd>
      <dt>Categories</dt>
      <dd class="tags">${tagList(result.categories)}</dd>
      <dt>Keywords</dt>
      <dd class="tags">${tagList(result.keywords, 'tag keyword')}</dd>
      <dt>Why it matters</dt>
      <dd>${escapeHtml(result.reason)}</dd>
      <dt>Core methods</dt>
      <dd>${escapeHtml(result.core_methods)}</dd>
      <dt>Problem</dt>
      <dd>${escapeHtml(result.problem)}</dd>
      <dt>Abstract</dt>
      <dd>${escapeHtml(result.abstract)}</dd>
    </dl>
  </aside>`;
}

export function renderDashboardPage(options: {
  filters: UiFilters;
  results: AnalysisResultRecord[];
  totalCount: number;
  selected?: AnalysisResultRecord;
  flash?: Flash;
  authEnabled?: boolean;
}): string {
  const body = `${renderFlash(options.flash)}
  <header class="page-header">
    <div>
      <p class="eyebrow">Paper radar</p>
      <h1>${escapeHtml(options.filters.date)} analysis</h1>
    </div>
    <a class="button" href="/run?date=${encodeURIComponent(options.filters.date)}">Run now</a>
  </header>
  ${renderDashboardToolbar(options.filters)}
  ${renderStats(options.results, options.totalCount)}
  <div class="split">
    ${renderPaperList(options.results, options.filters, options.selected)}
    ${renderDetail(options.selected)}
  </div>`;

  return pageShell({
    title: 'PaperSniffer Dashboard',
    current: 'dashboard',
    body,
    authEnabled: options.authEnabled,
  });
}

function configText(config: EditableConfig, key: keyof EditableConfig): string {
  const value = config[key];
  if (value === undefined || value === null) {
    return '';
  }
  if (Array.isArray(value)) {
    return value.join('\n');
  }
  return String(value);
}

function renderConfigForm(config: EditableConfig): string {
  const domainRulesJson = JSON.stringify(config.domain_rules || [], null, 2);

  return `<form class="form-grid" method="post">
    <label class="wide">
      <span>Keywords</span>
      <textarea name="keywords" rows="5">${escapeHtml((config.keywords || []).join('\n'))}</textarea>
    </label>
    <label class="wide">
      <span>Domain rules JSON</span>
      <textarea name="domain_rules_json" rows="9">${escapeHtml(domainRulesJson)}</textarea>
    </label>
    <label>
      <span>Relevance threshold</span>
      <select name="relevance_threshold">
        ${SCORE_ORDER.map(score => `<option value="${score}" ${config.relevance_threshold === score ? 'selected' : ''}>${SCORE_TEXT[score]}</option>`).join('')}
      </select>
    </label>
    <label>
      <span>Model</span>
      <input name="openai_model" value="${escapeAttr(configText(config, 'openai_model'))}" required>
    </label>
    <label>
      <span>Base URL</span>
      <input name="openai_base_url" value="${escapeAttr(configText(config, 'openai_base_url'))}" placeholder="https://api.openai.com/v1">
    </label>
    <label>
      <span>Max results per category</span>
      <input type="number" min="1" max="200" name="max_results_per_category" value="${escapeAttr(configText(config, 'max_results_per_category'))}">
    </label>
    <label>
      <span>Max concurrent requests</span>
      <input type="number" min="1" max="50" name="max_concurrent_requests" value="${escapeAttr(configText(config, 'max_concurrent_requests'))}">
    </label>
    <label>
      <span>Log level</span>
      <select name="log_level">
        ${['DEBUG', 'INFO', 'WARNING', 'ERROR'].map(level => `<option value="${level}" ${config.log_level === level ? 'selected' : ''}>${level}</option>`).join('')}
      </select>
    </label>
    <label>
      <span>Output dir</span>
      <input name="output_dir" value="${escapeAttr(configText(config, 'output_dir'))}">
    </label>
    <label>
      <span>Prompts dir</span>
      <input name="prompts_dir" value="${escapeAttr(configText(config, 'prompts_dir'))}">
    </label>
    <label>
      <span>History file</span>
      <input name="history_file" value="${escapeAttr(configText(config, 'history_file'))}">
    </label>
    <label class="wide">
      <span>System prompt</span>
      <textarea name="prompt_system" rows="5">${escapeHtml(configText(config, 'prompt_system'))}</textarea>
    </label>
    <label class="wide">
      <span>User prompt template</span>
      <textarea name="prompt_user_template" rows="6">${escapeHtml(configText(config, 'prompt_user_template'))}</textarea>
    </label>
    <div class="actions wide">
      <button formaction="/config/validate" type="submit">Validate</button>
      <button formaction="/config/save" type="submit">Save to KV</button>
    </div>
  </form>`;
}

export function renderConfigPage(options: {
  config: EditableConfig;
  response?: ConfigResponse;
  flash?: Flash;
  authEnabled?: boolean;
}): string {
  const source = options.response
    ? `<div class="meta-bar"><span>Source: <strong>${escapeHtml(options.response.source)}</strong></span><span>Key: ${escapeHtml(options.response.key)}</span></div>`
    : '';

  const body = `${renderFlash(options.flash)}
  <header class="page-header">
    <div>
      <p class="eyebrow">Runtime config</p>
      <h1>Configuration</h1>
    </div>
  </header>
  ${source}
  <section class="panel">
    ${renderConfigForm(options.config)}
  </section>`;

  return pageShell({
    title: 'PaperSniffer Config',
    current: 'config',
    body,
    authEnabled: options.authEnabled,
  });
}

export function renderRunPage(options: {
  defaultDate: string;
  response?: RunResponse;
  flash?: Flash;
  authEnabled?: boolean;
}): string {
  const response = options.response
    ? `<section class="panel">
        <h2>Run response</h2>
        ${options.response.queued
          ? `<p>Queued for ${escapeHtml(options.response.targetDate)}.</p><a class="button secondary" href="/?date=${encodeURIComponent(options.response.targetDate)}">View results</a>`
          : `<p>Completed ${escapeHtml(options.response.result.date)}. Fetched ${options.response.result.total_fetched}, kept ${options.response.result.total_filtered}.</p><a class="button secondary" href="/?date=${encodeURIComponent(options.response.result.date)}">View results</a>`}
      </section>`
    : '';

  const body = `${renderFlash(options.flash)}
  <header class="page-header">
    <div>
      <p class="eyebrow">Manual control</p>
      <h1>Run pipeline</h1>
    </div>
  </header>
  <section class="panel narrow">
    <form class="form-grid" method="post" action="/run">
      <label>
        <span>Target date</span>
        <input type="date" name="date" value="${escapeAttr(options.defaultDate)}">
      </label>
      <label class="check">
        <input type="checkbox" name="sync" value="true">
        <span>Run synchronously for debugging</span>
      </label>
      <div class="actions wide">
        <button type="submit">Start run</button>
      </div>
    </form>
  </section>
  ${response}`;

  return pageShell({
    title: 'PaperSniffer Run',
    current: 'run',
    body,
    authEnabled: options.authEnabled,
  });
}

export function renderStatusPage(options: {
  health?: HealthResponse;
  config?: ConfigResponse;
  backendBaseUrl?: string;
  errors: string[];
  authEnabled?: boolean;
}): string {
  const body = `${renderFlash(options.errors.length > 0 ? { kind: 'error', message: options.errors.join(' ') } : undefined)}
  <header class="page-header">
    <div>
      <p class="eyebrow">System status</p>
      <h1>Status</h1>
    </div>
  </header>
  <section class="status-grid">
    <div class="panel">
      <h2>Backend</h2>
      <dl class="details compact">
        <dt>Base URL</dt><dd>${escapeHtml(options.backendBaseUrl || 'Not configured')}</dd>
        <dt>Health</dt><dd>${options.health ? 'Online' : 'Unavailable'}</dd>
        <dt>Runtime</dt><dd>${escapeHtml(options.health?.runtime || 'Unknown')}</dd>
      </dl>
    </div>
    <div class="panel">
      <h2>Config</h2>
      <dl class="details compact">
        <dt>Source</dt><dd>${escapeHtml(options.config?.source || 'Unknown')}</dd>
        <dt>KV key</dt><dd>${escapeHtml(options.config?.key || 'Unknown')}</dd>
        <dt>Model</dt><dd>${escapeHtml(options.config?.effective_config.openai_model || 'Unknown')}</dd>
        <dt>Threshold</dt><dd>${escapeHtml(options.config?.effective_config.relevance_threshold || 'Unknown')}</dd>
      </dl>
    </div>
  </section>`;

  return pageShell({
    title: 'PaperSniffer Status',
    current: 'status',
    body,
    authEnabled: options.authEnabled,
  });
}

export function renderLoginPage(flash?: Flash): string {
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sign in - PaperSniffer</title>
  <style>${APP_CSS}</style>
</head>
<body>
  <main class="login">
    <section class="panel narrow">
      <p class="eyebrow">PaperSniffer</p>
      <h1>Sign in</h1>
      ${renderFlash(flash)}
      <form class="form-grid" method="post" action="/login">
        <label class="wide">
          <span>Password</span>
          <input type="password" name="password" autocomplete="current-password" autofocus required>
        </label>
        <div class="actions wide">
          <button type="submit">Continue</button>
        </div>
      </form>
    </section>
  </main>
</body>
</html>`;
}

export function renderErrorPage(title: string, message: string, authEnabled?: boolean): string {
  const body = `<header class="page-header">
    <div>
      <p class="eyebrow">Error</p>
      <h1>${escapeHtml(title)}</h1>
    </div>
  </header>
  <section class="panel">
    <p>${escapeHtml(message)}</p>
  </section>`;

  return pageShell({
    title,
    current: 'status',
    body,
    authEnabled,
  });
}

const APP_CSS = `
:root {
  color-scheme: light;
  --bg: #f6f8f7;
  --surface: #ffffff;
  --surface-2: #eef3f1;
  --text: #17211f;
  --muted: #64716d;
  --line: #d8e0dd;
  --accent: #0f766e;
  --accent-2: #b45309;
  --danger: #b42318;
  --high: #0f766e;
  --medium: #2563eb;
  --low: #b45309;
  --irrelevant: #6b7280;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
}
a { color: inherit; }
.app {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  min-height: 100vh;
}
.sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  border-right: 1px solid var(--line);
  background: #fbfcfb;
  padding: 20px;
}
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  color: inherit;
  text-decoration: none;
  margin-bottom: 28px;
}
.brand-mark {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 8px;
  background: var(--accent);
  color: white;
  font-weight: 800;
}
.brand strong, .brand small { display: block; }
.brand small { color: var(--muted); margin-top: 2px; }
.nav { display: grid; gap: 6px; }
.nav a, .logout button {
  display: block;
  width: 100%;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font: inherit;
  padding: 10px 12px;
  text-align: left;
  text-decoration: none;
}
.nav a.active, .nav a:hover, .logout button:hover {
  background: var(--surface-2);
  color: var(--text);
}
.logout {
  border-top: 1px solid var(--line);
  margin-top: 24px;
  padding-top: 14px;
}
.main {
  width: min(1440px, 100%);
  padding: 28px;
}
.page-header {
  align-items: center;
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}
.eyebrow {
  color: var(--accent);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0;
  margin: 0 0 6px;
  text-transform: uppercase;
}
h1, h2, p { margin-top: 0; }
h1 { font-size: 32px; line-height: 1.15; margin-bottom: 0; }
h2 { font-size: 18px; line-height: 1.25; }
.muted { color: var(--muted); }
.toolbar {
  align-items: end;
  display: grid;
  grid-template-columns: 150px minmax(220px, 1fr) 150px 130px 130px auto auto auto;
  gap: 10px;
  margin-bottom: 16px;
}
label { display: grid; gap: 6px; }
label span {
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}
input, select, textarea {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  min-height: 40px;
  padding: 9px 10px;
}
textarea {
  line-height: 1.45;
  resize: vertical;
}
button, .button {
  align-items: center;
  background: var(--accent);
  border: 1px solid var(--accent);
  border-radius: 8px;
  color: white;
  cursor: pointer;
  display: inline-flex;
  font: inherit;
  font-weight: 700;
  justify-content: center;
  min-height: 40px;
  padding: 9px 12px;
  text-decoration: none;
  white-space: nowrap;
}
.button.secondary {
  background: var(--surface);
  border-color: var(--line);
  color: var(--text);
}
.stats {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}
.stats div, .panel, .empty {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
}
.stats div {
  min-height: 72px;
  padding: 14px;
}
.stats strong, .stats span { display: block; }
.stats strong { font-size: 24px; }
.stats span { color: var(--muted); font-size: 12px; margin-top: 4px; }
.split {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(340px, 420px);
  gap: 16px;
  align-items: start;
}
.paper-list {
  display: grid;
  gap: 10px;
}
.paper-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 16px;
}
.paper-card.active {
  border-color: var(--accent);
  box-shadow: inset 3px 0 0 var(--accent);
}
.paper-card h2 {
  margin: 10px 0 8px;
  overflow-wrap: anywhere;
}
.paper-card h2 a { text-decoration: none; }
.paper-card p {
  color: #33413d;
  line-height: 1.5;
}
.paper-head {
  align-items: center;
  display: flex;
  justify-content: space-between;
  gap: 10px;
}
.score {
  border-radius: 999px;
  color: white;
  display: inline-flex;
  font-size: 12px;
  font-weight: 800;
  min-height: 24px;
  padding: 4px 9px;
}
.score-high { background: var(--high); }
.score-medium { background: var(--medium); }
.score-low { background: var(--low); }
.score-irrelevant { background: var(--irrelevant); }
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.tag {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 999px;
  color: #33413d;
  font-size: 12px;
  min-height: 24px;
  padding: 3px 8px;
}
.keyword {
  background: #fff7ed;
  border-color: #fed7aa;
}
.paper-meta {
  color: var(--muted);
  font-size: 13px;
  margin-top: 10px;
}
.detail-panel {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  max-height: calc(100vh - 56px);
  overflow: auto;
  padding: 18px;
  position: sticky;
  top: 28px;
}
.details {
  display: grid;
  gap: 8px;
  line-height: 1.5;
  margin: 0;
}
.details dt {
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
  margin-top: 10px;
  text-transform: uppercase;
}
.details dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.details.compact {
  grid-template-columns: 130px minmax(0, 1fr);
}
.details.compact dt { margin-top: 0; }
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}
.form-grid .wide, .actions.wide {
  grid-column: 1 / -1;
}
.actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}
.panel, .empty {
  padding: 18px;
}
.panel.narrow, .login .panel {
  max-width: 640px;
}
.meta-bar {
  align-items: center;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 8px;
  display: flex;
  gap: 18px;
  margin-bottom: 16px;
  padding: 10px 12px;
}
.flash {
  border-radius: 8px;
  margin-bottom: 16px;
  padding: 12px 14px;
}
.flash-success {
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  color: #065f46;
}
.flash-error {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #991b1b;
}
.flash-info {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1e40af;
}
.check {
  align-items: center;
  display: flex;
  gap: 10px;
}
.check input {
  width: 18px;
  min-height: 18px;
}
.status-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
.login {
  display: grid;
  min-height: 100vh;
  place-items: center;
  padding: 24px;
}
@media (max-width: 1120px) {
  .toolbar {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .stats {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .split {
    grid-template-columns: 1fr;
  }
  .detail-panel {
    max-height: none;
    position: static;
  }
}
@media (max-width: 760px) {
  .app {
    grid-template-columns: 1fr;
  }
  .sidebar {
    height: auto;
    position: static;
  }
  .nav {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
  .main {
    padding: 18px;
  }
  .page-header {
    align-items: stretch;
    flex-direction: column;
  }
  .toolbar, .form-grid, .status-grid, .stats {
    grid-template-columns: 1fr;
  }
  .actions {
    justify-content: stretch;
  }
  .actions button, .button {
    width: 100%;
  }
}
`;
