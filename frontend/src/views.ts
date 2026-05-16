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
  HIGH: '高',
  MEDIUM: '中',
  LOW: '低',
  IRRELEVANT: '无关',
};

const CONFIG_SOURCE_TEXT: Record<string, string> = {
  kv: 'KV',
  env: '环境变量',
  default: '默认配置',
};

function sourceText(source: string | undefined): string {
  return source ? CONFIG_SOURCE_TEXT[source] || source : '校验结果';
}

function scoreText(score: string | undefined): string {
  return score && score in SCORE_TEXT ? SCORE_TEXT[score as Score] : '未知';
}

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
}): string {
  const nav = [
    ['dashboard', '/', '论文雷达'],
    ['config', '/config', '配置'],
    ['run', '/run', '运行'],
    ['status', '/status', '状态'],
  ] as const;

  return `<!doctype html>
<html lang="zh-CN">
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
          <small>科研论文雷达</small>
        </span>
      </a>
      <nav class="nav">
        ${nav.map(([key, href, label]) => `<a class="${options.current === key ? 'active' : ''}" href="${href}">${label}</a>`).join('')}
      </nav>
    </aside>
    <main class="main">
      ${options.body}
    </main>
  </div>
  <script>${APP_JS}</script>
</body>
</html>`;
}

function scoreClass(score: string): string {
  return `score-${score.toLowerCase()}`;
}

function tagList(values: string[], className = 'tag'): string {
  if (values.length === 0) {
    return '<span class="muted">无</span>';
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
    const label = score === 'ALL' ? '全部评分' : SCORE_TEXT[score as Score];
    return `<option value="${value}" ${selected === value ? 'selected' : ''}>${label}</option>`;
  }).join('');
}

function renderDashboardToolbar(filters: UiFilters): string {
  const exportMd = `/export.md${queryString(filters, { selected: '' })}`;
  const exportJson = `/export.json${queryString(filters, { selected: '' })}`;

  return `<form class="toolbar" method="get" action="/">
    <label>
      <span>日期</span>
      <input type="date" name="date" value="${escapeAttr(filters.date)}">
    </label>
    <label class="grow">
      <span>搜索</span>
      <input type="search" name="q" value="${escapeAttr(filters.q)}" placeholder="标题、作者、方法、问题">
    </label>
    <label>
      <span>评分</span>
      <select name="score">${renderScoreOptions(filters.score)}</select>
    </label>
    <label>
      <span>分类</span>
      <input name="category" value="${escapeAttr(filters.category)}" placeholder="cs.CL">
    </label>
    <label>
      <span>关键词</span>
      <input name="keyword" value="${escapeAttr(filters.keyword)}" placeholder="agent">
    </label>
    <button type="submit">刷新</button>
    <a class="button secondary" href="${exportMd}">导出 Markdown</a>
    <a class="button secondary" href="${exportJson}">导出 JSON</a>
  </form>`;
}

function renderStats(results: AnalysisResultRecord[], totalCount: number): string {
  const counts = new Map<Score, number>(SCORE_ORDER.map(score => [score, 0]));
  for (const result of results) {
    counts.set(result.score, (counts.get(result.score) || 0) + 1);
  }

  return `<section class="stats">
    <div><strong>${results.length}</strong><span>筛选结果</span></div>
    <div><strong>${totalCount}</strong><span>全部论文</span></div>
    ${SCORE_ORDER.map(score => `<div><strong>${counts.get(score) || 0}</strong><span>${SCORE_TEXT[score]}</span></div>`).join('')}
  </section>`;
}

function renderPaperList(results: AnalysisResultRecord[], filters: UiFilters, selected?: AnalysisResultRecord): string {
  if (results.length === 0) {
    return `<section class="empty">
      <h2>未找到论文</h2>
      <p>可以换一个日期，或者放宽筛选条件。</p>
    </section>`;
  }

  return `<section class="paper-list" aria-label="论文结果">
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
      <h2>请选择一篇论文</h2>
      <p class="muted">打开结果后，可以查看方法、问题定义、关键词和推荐理由。</p>
    </aside>`;
  }

  return `<aside class="detail-panel">
    <div class="paper-head">
      <span class="score ${scoreClass(result.score)}">${SCORE_TEXT[result.score]}</span>
      <a class="button secondary" href="${escapeAttr(result.paper_url)}" target="_blank" rel="noreferrer">打开论文</a>
    </div>
    <h2>${escapeHtml(result.title)}</h2>
    <dl class="details">
      <dt>作者</dt>
      <dd>${escapeHtml(result.authors.join(', ') || '未知')}</dd>
      <dt>发布日期</dt>
      <dd>${escapeHtml(result.published.slice(0, 10))}</dd>
      <dt>分类</dt>
      <dd class="tags">${tagList(result.categories)}</dd>
      <dt>关键词</dt>
      <dd class="tags">${tagList(result.keywords, 'tag keyword')}</dd>
      <dt>推荐理由</dt>
      <dd>${escapeHtml(result.reason)}</dd>
      <dt>核心方法</dt>
      <dd>${escapeHtml(result.core_methods)}</dd>
      <dt>问题</dt>
      <dd>${escapeHtml(result.problem)}</dd>
      <dt>摘要</dt>
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
}): string {
  const body = `${renderFlash(options.flash)}
  <header class="page-header">
    <div>
      <p class="eyebrow">论文雷达</p>
      <h1>${escapeHtml(options.filters.date)} 分析结果</h1>
    </div>
    <a class="button" href="/run?date=${encodeURIComponent(options.filters.date)}">立即运行</a>
  </header>
  ${renderDashboardToolbar(options.filters)}
  ${renderStats(options.results, options.totalCount)}
  <div class="split">
    ${renderPaperList(options.results, options.filters, options.selected)}
    ${renderDetail(options.selected)}
  </div>`;

  return pageShell({
    title: 'PaperSniffer 论文雷达',
    current: 'dashboard',
    body,
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

function renderKeywordRows(keywords: string[]): string {
  const rows = keywords.length > 0 ? keywords : [''];

  return `<section class="field-group wide" data-repeat-list data-input-name="keyword" data-placeholder="例如：large language model">
    <div class="subhead">
      <div>
        <h2>关键词</h2>
        <p>每行一个关键词，用来筛选论文主题。</p>
      </div>
      <button class="button secondary mini" type="button" data-add-row>添加关键词</button>
    </div>
    <div class="list-rows" data-list-rows>
      ${rows.map(keyword => `<div class="list-row">
        <input name="keyword" value="${escapeAttr(keyword)}" placeholder="例如：agent">
        <button class="button secondary danger mini" type="button" data-remove-row>删除</button>
      </div>`).join('')}
    </div>
  </section>`;
}

function renderDomainRuleRow(rule: EditableConfig['domain_rules'][number]): string {
  const filterHidden = rule.mode === 'categories_filter' ? '' : ' is-hidden';

  return `<article class="rule-card" data-domain-rule>
    <label>
      <span>arXiv 分类</span>
      <input name="domain_category" value="${escapeAttr(rule.category)}" placeholder="例如：cs.CL">
    </label>
    <label>
      <span>匹配方式</span>
      <select name="domain_mode" data-domain-mode>
        <option value="accept_all" ${rule.mode === 'accept_all' ? 'selected' : ''}>接收该分类下全部论文</option>
        <option value="categories_filter" ${rule.mode === 'categories_filter' ? 'selected' : ''}>只接收同时属于指定交叉分类的论文</option>
      </select>
    </label>
    <label class="filter-field${filterHidden}" data-filter-field>
      <span>交叉分类</span>
      <input name="domain_filter_categories" value="${escapeAttr((rule.filter_categories || []).join(', '))}" placeholder="例如：cs.AI, cs.LG">
    </label>
    <button class="button secondary danger mini rule-delete" type="button" data-remove-domain-rule>删除规则</button>
  </article>`;
}

function renderDomainRuleRows(rules: EditableConfig['domain_rules']): string {
  const displayRules = rules.length > 0
    ? rules
    : [{ category: '', mode: 'accept_all' as const, filter_categories: [] }];

  return `<section class="field-group wide" data-domain-rules>
    <div class="subhead">
      <div>
        <h2>领域规则</h2>
        <p>用分类和下拉选项控制 arXiv 抓取范围，不需要编辑 JSON。</p>
      </div>
      <button class="button secondary mini" type="button" data-add-domain-rule>添加规则</button>
    </div>
    <div class="rule-list" data-domain-rule-list>
      ${displayRules.map(renderDomainRuleRow).join('')}
    </div>
  </section>`;
}

function renderConfigForm(config: EditableConfig): string {
  return `<form class="form-grid" method="post">
    ${renderKeywordRows(config.keywords || [])}
    ${renderDomainRuleRows(config.domain_rules || [])}
    <label>
      <span>相关性阈值</span>
      <select name="relevance_threshold">
        ${SCORE_ORDER.map(score => `<option value="${score}" ${config.relevance_threshold === score ? 'selected' : ''}>${SCORE_TEXT[score]}</option>`).join('')}
      </select>
    </label>
    <label>
      <span>模型</span>
      <input name="openai_model" value="${escapeAttr(configText(config, 'openai_model'))}" required>
    </label>
    <label>
      <span>模型服务地址</span>
      <input name="openai_base_url" value="${escapeAttr(configText(config, 'openai_base_url'))}" placeholder="https://api.openai.com/v1">
    </label>
    <label>
      <span>每个分类最多抓取</span>
      <input type="number" min="1" max="200" name="max_results_per_category" value="${escapeAttr(configText(config, 'max_results_per_category'))}">
    </label>
    <label>
      <span>最大并发请求</span>
      <input type="number" min="1" max="50" name="max_concurrent_requests" value="${escapeAttr(configText(config, 'max_concurrent_requests'))}">
    </label>
    <label>
      <span>日志等级</span>
      <select name="log_level">
        ${['DEBUG', 'INFO', 'WARNING', 'ERROR'].map(level => `<option value="${level}" ${config.log_level === level ? 'selected' : ''}>${level}</option>`).join('')}
      </select>
    </label>
    <label>
      <span>输出目录</span>
      <input name="output_dir" value="${escapeAttr(configText(config, 'output_dir'))}">
    </label>
    <label>
      <span>提示词目录</span>
      <input name="prompts_dir" value="${escapeAttr(configText(config, 'prompts_dir'))}">
    </label>
    <label>
      <span>历史文件名</span>
      <input name="history_file" value="${escapeAttr(configText(config, 'history_file'))}">
    </label>
    <label class="wide">
      <span>系统提示词</span>
      <textarea name="prompt_system" rows="5">${escapeHtml(configText(config, 'prompt_system'))}</textarea>
    </label>
    <label class="wide">
      <span>用户提示词模板</span>
      <textarea name="prompt_user_template" rows="6">${escapeHtml(configText(config, 'prompt_user_template'))}</textarea>
    </label>
    <div class="actions wide">
      <button formaction="/config/validate" type="submit">校验配置</button>
      <button formaction="/config/save" type="submit">保存到 KV</button>
    </div>
  </form>`;
}

export function renderConfigPage(options: {
  config: EditableConfig;
  response?: ConfigResponse;
  flash?: Flash;
}): string {
  const source = options.response
    ? `<div class="meta-bar"><span>配置来源：<strong>${escapeHtml(sourceText(options.response.source))}</strong></span><span>KV Key：${escapeHtml(options.response.key || '未写入')}</span></div>`
    : '';

  const body = `${renderFlash(options.flash)}
  <header class="page-header">
    <div>
      <p class="eyebrow">运行配置</p>
      <h1>配置管理</h1>
    </div>
  </header>
  ${source}
  <section class="panel">
    ${renderConfigForm(options.config)}
  </section>`;

  return pageShell({
    title: 'PaperSniffer 配置',
    current: 'config',
    body,
  });
}

export function renderRunPage(options: {
  defaultDate: string;
  response?: RunResponse;
  flash?: Flash;
}): string {
  const response = options.response
    ? `<section class="panel">
        <h2>运行结果</h2>
        ${options.response.queued
          ? `<p>${escapeHtml(options.response.targetDate)} 的任务已进入队列。</p><a class="button secondary" href="/?date=${encodeURIComponent(options.response.targetDate)}">查看结果</a>`
          : `<p>${escapeHtml(options.response.result.date)} 已完成。抓取 ${options.response.result.total_fetched} 篇，保留 ${options.response.result.total_filtered} 篇。</p><a class="button secondary" href="/?date=${encodeURIComponent(options.response.result.date)}">查看结果</a>`}
      </section>`
    : '';

  const body = `${renderFlash(options.flash)}
  <header class="page-header">
    <div>
      <p class="eyebrow">手动控制</p>
      <h1>运行流水线</h1>
    </div>
  </header>
  <section class="panel narrow">
    <form class="form-grid" method="post" action="/run">
      <label>
        <span>目标日期</span>
        <input type="date" name="date" value="${escapeAttr(options.defaultDate)}">
      </label>
      <label class="check">
        <input type="checkbox" name="sync" value="true">
        <span>同步运行，用于调试</span>
      </label>
      <div class="actions wide">
        <button type="submit">开始运行</button>
      </div>
    </form>
  </section>
  ${response}`;

  return pageShell({
    title: 'PaperSniffer 运行',
    current: 'run',
    body,
  });
}

export function renderStatusPage(options: {
  health?: HealthResponse;
  config?: ConfigResponse;
  backendBaseUrl?: string;
  errors: string[];
}): string {
  const body = `${renderFlash(options.errors.length > 0 ? { kind: 'error', message: options.errors.join(' ') } : undefined)}
  <header class="page-header">
    <div>
      <p class="eyebrow">系统状态</p>
      <h1>状态</h1>
    </div>
  </header>
  <section class="status-grid">
    <div class="panel">
      <h2>后端</h2>
      <dl class="details compact">
        <dt>地址</dt><dd>${escapeHtml(options.backendBaseUrl || '未配置')}</dd>
        <dt>健康状态</dt><dd>${options.health ? '在线' : '不可用'}</dd>
        <dt>运行时</dt><dd>${escapeHtml(options.health?.runtime || '未知')}</dd>
      </dl>
    </div>
    <div class="panel">
      <h2>配置</h2>
      <dl class="details compact">
        <dt>来源</dt><dd>${escapeHtml(sourceText(options.config?.source))}</dd>
        <dt>KV Key</dt><dd>${escapeHtml(options.config?.key || '未知')}</dd>
        <dt>模型</dt><dd>${escapeHtml(options.config?.effective_config.openai_model || '未知')}</dd>
        <dt>阈值</dt><dd>${escapeHtml(scoreText(options.config?.effective_config.relevance_threshold))}</dd>
      </dl>
    </div>
  </section>`;

  return pageShell({
    title: 'PaperSniffer 状态',
    current: 'status',
    body,
  });
}

export function renderErrorPage(title: string, message: string): string {
  const body = `<header class="page-header">
    <div>
      <p class="eyebrow">错误</p>
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
  });
}

const APP_JS = `
(() => {
  function bindRepeatList(root) {
    const rows = root.querySelector('[data-list-rows]');
    const inputName = root.getAttribute('data-input-name') || 'item';
    const placeholder = root.getAttribute('data-placeholder') || '';

    root.addEventListener('click', event => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) {
        return;
      }

      if (target.matches('[data-add-row]')) {
        const row = document.createElement('div');
        row.className = 'list-row';
        row.innerHTML = '<input name="' + inputName + '" placeholder="' + placeholder + '"><button class="button secondary danger mini" type="button" data-remove-row>删除</button>';
        rows.appendChild(row);
      }

      if (target.matches('[data-remove-row]')) {
        const allRows = rows.querySelectorAll('.list-row');
        const row = target.closest('.list-row');
        if (row && allRows.length > 1) {
          row.remove();
        } else if (row) {
          const input = row.querySelector('input');
          if (input) {
            input.value = '';
          }
        }
      }
    });
  }

  function domainRuleTemplate() {
    return '<article class="rule-card" data-domain-rule>' +
      '<label><span>arXiv 分类</span><input name="domain_category" placeholder="例如：cs.CL"></label>' +
      '<label><span>匹配方式</span><select name="domain_mode" data-domain-mode>' +
      '<option value="accept_all">接收该分类下全部论文</option>' +
      '<option value="categories_filter">只接收同时属于指定交叉分类的论文</option>' +
      '</select></label>' +
      '<label class="filter-field is-hidden" data-filter-field><span>交叉分类</span><input name="domain_filter_categories" placeholder="例如：cs.AI, cs.LG"></label>' +
      '<button class="button secondary danger mini rule-delete" type="button" data-remove-domain-rule>删除规则</button>' +
      '</article>';
  }

  function syncDomainRule(rule) {
    const mode = rule.querySelector('[data-domain-mode]');
    const field = rule.querySelector('[data-filter-field]');
    if (!mode || !field) {
      return;
    }

    field.classList.toggle('is-hidden', mode.value !== 'categories_filter');
    if (mode.value !== 'categories_filter') {
      const input = field.querySelector('input');
      if (input) {
        input.value = '';
      }
    }
  }

  function bindDomainRules(root) {
    const list = root.querySelector('[data-domain-rule-list]');

    root.querySelectorAll('[data-domain-rule]').forEach(syncDomainRule);

    root.addEventListener('change', event => {
      const target = event.target;
      if (target instanceof HTMLElement && target.matches('[data-domain-mode]')) {
        const rule = target.closest('[data-domain-rule]');
        if (rule) {
          syncDomainRule(rule);
        }
      }
    });

    root.addEventListener('click', event => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) {
        return;
      }

      if (target.matches('[data-add-domain-rule]')) {
        list.insertAdjacentHTML('beforeend', domainRuleTemplate());
      }

      if (target.matches('[data-remove-domain-rule]')) {
        const rules = list.querySelectorAll('[data-domain-rule]');
        const rule = target.closest('[data-domain-rule]');
        if (rule && rules.length > 1) {
          rule.remove();
        } else if (rule) {
          rule.querySelectorAll('input').forEach(input => {
            input.value = '';
          });
          const mode = rule.querySelector('[data-domain-mode]');
          if (mode) {
            mode.value = 'accept_all';
          }
          syncDomainRule(rule);
        }
      }
    });
  }

  document.querySelectorAll('[data-repeat-list]').forEach(bindRepeatList);
  document.querySelectorAll('[data-domain-rules]').forEach(bindDomainRules);
})();
`;

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
.nav a {
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
.nav a.active, .nav a:hover {
  background: var(--surface-2);
  color: var(--text);
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
.field-group {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fbfcfb;
  padding: 14px;
}
.subhead {
  align-items: center;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.subhead h2 {
  margin-bottom: 4px;
}
.subhead p {
  color: var(--muted);
  font-size: 13px;
  margin: 0;
}
.list-rows, .rule-list {
  display: grid;
  gap: 10px;
}
.list-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
}
.rule-card {
  align-items: end;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  display: grid;
  grid-template-columns: minmax(140px, 1fr) minmax(220px, 1.4fr) minmax(180px, 1fr) auto;
  gap: 10px;
  padding: 12px;
}
.filter-field.is-hidden {
  visibility: hidden;
}
.mini {
  min-height: 36px;
  padding: 7px 10px;
}
.danger {
  color: var(--danger) !important;
}
.actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}
.panel, .empty {
  padding: 18px;
}
.panel.narrow {
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
@media (max-width: 1120px) {
  .toolbar {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .rule-card {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .rule-delete {
    grid-column: 1 / -1;
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
  .list-row, .rule-card {
    grid-template-columns: 1fr;
  }
  .filter-field.is-hidden {
    display: none;
  }
  .actions {
    justify-content: stretch;
  }
  .actions button, .button {
    width: 100%;
  }
}
`;
