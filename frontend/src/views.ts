import {
  AnalysisResultRecord,
  ConfigResponse,
  EditableConfig,
  Flash,
  HealthResponse,
  PaperSourceConfig,
  PipelineRunLogEntry,
  PipelineRunStatus,
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

interface KeywordFacet {
  value: string;
  count: number;
}

export interface DashboardRefreshState {
  kind: PipelineRunStatus | 'error';
  date: string;
  attempt: number;
  progress?: number;
  currentStep?: string;
  logs?: PipelineRunLogEntry[];
  nextUrl?: string;
  message: string;
}

const DEFAULT_SYSTEM_PROMPT = `你是一位学术论文分析专家。你的任务是对给定的论文标题和摘要进行深入分析，同时评估它与给定重点关注关键词的相关度。

请严格按以下 JSON 格式返回分析结果：
{
  "score": "HIGH|MEDIUM|LOW|IRRELEVANT",
  "reason": "评估理由，中文，1-2 句话；如果论文不匹配重点关注关键词，也要说明它的实际主题",
  "core_methods": "核心技术方法，中文，说明论文使用的主要技术、算法、模型或方法论",
  "problem": "要解决的问题，中文，清晰描述论文试图解决的核心问题或挑战",
  "keywords": ["keyword1", "keyword2", "keyword3"]
}

相关度评分标准：
- HIGH: 论文核心主题与重点关注关键词高度相关，是该领域的直接贡献
- MEDIUM: 论文与重点关注关键词有一定关联，但不是核心主题
- LOW: 论文仅边缘性地涉及重点关注关键词相关内容
- IRRELEVANT: 论文与重点关注关键词无实质关联，但仍需要正常总结

请仅返回 JSON 对象，不要包含其他内容。`;

const DEFAULT_USER_TEMPLATE = `重点关注关键词：{keywords}

论文标题：{title}

论文摘要：{abstract}

请对这篇论文进行综合分析，评估与重点关注关键词的相关度并提取核心信息。即使论文不匹配重点关注关键词，也请返回 JSON 格式的完整分析结果。`;

function scoreText(score: string | undefined): string {
  return score && score in SCORE_TEXT ? SCORE_TEXT[score as Score] : '未知';
}

export function todayUtc(): string {
  return new Date(Date.now() + 8 * 60 * 60 * 1000).toISOString().slice(0, 10);
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
    <header class="topbar">
      <a class="brand" href="/">
        <span class="brand-mark">PS</span>
        <span>
          <strong>PaperSniffer</strong>
          <small>科研论文雷达</small>
        </span>
      </a>
      <div class="top-actions">
        <a class="icon-button${options.current === 'config' ? ' active' : ''}" href="/config" aria-label="配置" title="配置">
          <svg aria-hidden="true" viewBox="0 0 24 24">
            <path d="M12 8.2a3.8 3.8 0 1 0 0 7.6 3.8 3.8 0 0 0 0-7.6Z"></path>
            <path d="M19.4 13.5a7.9 7.9 0 0 0 .1-1.5 7.9 7.9 0 0 0-.1-1.5l2-1.5-2-3.5-2.4 1a8.3 8.3 0 0 0-2.6-1.5L14 2.4h-4L9.6 5a8.3 8.3 0 0 0-2.6 1.5l-2.4-1-2 3.5 2 1.5a7.9 7.9 0 0 0-.1 1.5c0 .5 0 1 .1 1.5l-2 1.5 2 3.5 2.4-1a8.3 8.3 0 0 0 2.6 1.5l.4 2.6h4l.4-2.6a8.3 8.3 0 0 0 2.6-1.5l2.4 1 2-3.5-2-1.5Z"></path>
          </svg>
        </a>
      </div>
    </header>
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

function tagList(values: string[], className = 'tag', linkForValue?: (value: string) => string): string {
  if (values.length === 0) {
    return '<span class="muted">无</span>';
  }

  return values.map(value => {
    const body = escapeHtml(value);
    if (!linkForValue) {
      return `<span class="${className}">${body}</span>`;
    }

    return `<a class="${className}" href="${escapeAttr(linkForValue(value))}">${body}</a>`;
  }).join('');
}

function queryString(filters: UiFilters, overrides: Partial<UiFilters> = {}): string {
  const merged = {
    ...filters,
    ...overrides,
  };
  const params = new URLSearchParams();

  for (const key of ['date', 'q', 'score', 'keyword', 'selected', 'view'] as const) {
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

function renderDashboardToolbar(filters: UiFilters, refreshState?: DashboardRefreshState): string {
  const exportMd = `/export.md${queryString(filters, { selected: '' })}`;
  const exportJson = `/export.json${queryString(filters, { selected: '' })}`;
  const runningFields = refreshState?.kind === 'running'
    ? `<input type="hidden" name="running" value="1"><input type="hidden" name="attempt" value="${escapeAttr(refreshState.attempt)}">`
    : '';

  return `<form class="toolbar" method="get" action="/">
    <input type="hidden" name="ensure" value="1">
    ${runningFields}
    <input type="hidden" name="view" value="${escapeAttr(filters.view)}">
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
      <span>结果关键词</span>
      <input name="keyword" value="${escapeAttr(filters.keyword)}" placeholder="agent">
    </label>
    <button type="submit">刷新</button>
    <a class="button secondary" href="${exportMd}">导出 Markdown</a>
    <a class="button secondary" href="${exportJson}">导出 JSON</a>
  </form>`;
}

function renderRefreshStatus(state?: DashboardRefreshState): string {
  if (!state) {
    return '';
  }

  const progressValue = Math.max(0, Math.min(100, Math.round(state.progress ?? 0)));
  const isActive = state.kind === 'queued' || state.kind === 'running';
  const next = state.nextUrl
    ? `<p class="muted">页面会自动检查结果；已检查 ${state.attempt} 次。</p>`
    : '';
  const progress = isActive
    ? `<div class="progress" aria-label="运行进度"><span style="width: ${progressValue}%"></span></div>`
    : '';
  const action = state.nextUrl
    ? `<a class="button secondary mini" href="${escapeAttr(state.nextUrl)}">立即检查</a>`
    : '';
  const logs = (state.logs || []).slice(-6);
  const logList = logs.length > 0
    ? `<ol class="run-log">
        ${logs.map(log => `<li class="log-${escapeAttr(log.level)}">
          <span>${escapeHtml(log.step || '日志')}</span>
          <p>${escapeHtml(log.message)}</p>
        </li>`).join('')}
      </ol>`
    : '';
  const title = state.kind === 'queued'
    ? '流水线已排队'
    : state.kind === 'running'
      ? '正在运行流水线'
      : state.kind === 'completed'
        ? '刷新完成'
        : '刷新失败';

  return `<section class="refresh-status refresh-${escapeAttr(state.kind)}"${state.nextUrl ? ` data-auto-refresh-url="${escapeAttr(state.nextUrl)}"` : ''}>
    <div>
      <h2>${title}</h2>
      ${state.currentStep ? `<strong class="refresh-step">${escapeHtml(state.currentStep)} · ${progressValue}%</strong>` : ''}
      <p>${escapeHtml(state.message)}</p>
      ${next}
      ${progress}
      ${logList}
    </div>
    ${action}
  </section>`;
}

function renderViewTabs(filters: UiFilters, focusTotal: number, totalCount: number): string {
  const focusHref = `/${queryString(filters, { view: 'focus', selected: '' })}`;
  const allHref = `/${queryString(filters, { view: 'all', selected: '' })}`;

  return `<nav class="view-tabs" aria-label="论文视图">
    <a class="${filters.view === 'focus' ? 'active' : ''}" href="${escapeAttr(focusHref)}">
      <span>重点推送</span>
      <strong>${focusTotal}</strong>
    </a>
    <a class="${filters.view === 'all' ? 'active' : ''}" href="${escapeAttr(allHref)}">
      <span>全部论文</span>
      <strong>${totalCount}</strong>
    </a>
  </nav>`;
}

function renderKeywordFacets(facets: KeywordFacet[], filters: UiFilters): string {
  if (facets.length === 0) {
    return '';
  }

  const active = filters.keyword.toLowerCase();
  const clear = filters.keyword
    ? `<a class="keyword-filter clear" href="/${queryString(filters, { keyword: '', selected: '' })}">全部关键词</a>`
    : '';

  return `<section class="keyword-filters" aria-label="结果关键词筛选">
    <div class="keyword-filter-head">
      <h2>结果关键词</h2>
      ${clear}
    </div>
    <div class="keyword-filter-list">
      ${facets.map(facet => {
        const isActive = facet.value.toLowerCase() === active;
        const href = `/${queryString(filters, { keyword: isActive ? '' : facet.value, selected: '' })}`;
        return `<a class="keyword-filter${isActive ? ' active' : ''}" href="${escapeAttr(href)}">
          <span>${escapeHtml(facet.value)}</span>
          <strong>${facet.count}</strong>
        </a>`;
      }).join('')}
    </div>
  </section>`;
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
      const active = selected?.id === result.id ? ' active' : '';
      const anchor = paperAnchorId(result);
      const href = active
        ? `/${queryString(filters, { selected: '' })}#${anchor}`
        : `/${queryString(filters, { selected: result.id })}#${anchor}`;
      return `<article id="${escapeAttr(anchor)}" class="paper-card${active}">
        <div class="paper-head">
          <span class="score ${scoreClass(result.score)}">${SCORE_TEXT[result.score]}</span>
          <span class="paper-head-actions">
            <span class="muted">${escapeHtml(result.published.slice(0, 10))}</span>
            <a class="button secondary mini" href="${href}">${active ? '收起详情' : '查看详情'}</a>
          </span>
        </div>
        <h2><a href="${href}">${escapeHtml(result.title)}</a></h2>
        <p>${escapeHtml(compactText(result.reason || result.abstract))}</p>
        <div class="tags">${tagList(result.categories.slice(0, 4))}</div>
        <div class="paper-meta">${escapeHtml(compactText(result.authors.join(', '), 120))}</div>
        ${active ? renderPaperInlineDetail(result, filters) : ''}
      </article>`;
    }).join('')}
  </section>`;
}

function paperAnchorId(result: AnalysisResultRecord): string {
  return `paper-${result.record_id}`;
}

function renderPaperInlineDetail(result: AnalysisResultRecord, filters: UiFilters): string {
  return `<div class="paper-card-detail">
    <div class="detail-actions">
      <a class="button secondary" href="${escapeAttr(result.paper_url)}" target="_blank" rel="noreferrer">打开论文</a>
    </div>
    <dl class="details">
      <dt>作者</dt>
      <dd>${escapeHtml(result.authors.join(', ') || '未知')}</dd>
      <dt>发布日期</dt>
      <dd>${escapeHtml(result.published.slice(0, 10))}</dd>
      <dt>分类</dt>
      <dd class="tags">${tagList(result.categories)}</dd>
      <dt>关键词</dt>
      <dd class="tags">${tagList(result.keywords, 'tag keyword', keyword => `/${queryString(filters, { keyword, selected: '' })}`)}</dd>
      <dt>推荐理由</dt>
      <dd>${escapeHtml(result.reason)}</dd>
      <dt>核心方法</dt>
      <dd>${escapeHtml(result.core_methods)}</dd>
      <dt>问题</dt>
      <dd>${escapeHtml(result.problem)}</dd>
      <dt>摘要</dt>
      <dd>${escapeHtml(result.abstract)}</dd>
    </dl>
  </div>`;
}

export function renderDashboardPage(options: {
  filters: UiFilters;
  results: AnalysisResultRecord[];
  totalCount: number;
  focusTotal: number;
  selected?: AnalysisResultRecord;
  keywordFacets: KeywordFacet[];
  runResponse?: RunResponse;
  refreshState?: DashboardRefreshState;
  flash?: Flash;
}): string {
  const body = `${renderFlash(options.flash)}
  <header class="page-header">
    <div>
      <p class="eyebrow">论文雷达</p>
      <h1>${escapeHtml(options.filters.date)} 分析结果</h1>
    </div>
  </header>
  ${renderRefreshStatus(options.refreshState)}
  ${renderViewTabs(options.filters, options.focusTotal, options.totalCount)}
  ${renderDashboardToolbar(options.filters, options.refreshState)}
  ${renderKeywordFacets(options.keywordFacets, options.filters)}
  ${renderStats(options.results, options.totalCount)}
  ${renderPaperList(options.results, options.filters, options.selected)}`;

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
        <h2>重点关注关键词</h2>
        <p>用于模型相关性评分和首页重点推送；不匹配的论文仍会保存到全部论文。</p>
      </div>
      <button class="button secondary mini" type="button" data-add-row>添加关注词</button>
    </div>
    <div class="list-rows" data-list-rows>
      ${rows.map(keyword => `<div class="list-row">
        <input name="keyword" value="${escapeAttr(keyword)}" placeholder="例如：agent">
        <button class="button secondary danger mini" type="button" data-remove-row>删除</button>
      </div>`).join('')}
    </div>
  </section>`;
}

function normalizedSources(sources: EditableConfig['sources'] | undefined): PaperSourceConfig[] {
  const usable = (sources || [])
    .filter(source => source.id)
    .map(source => ({
      id: source.id,
      type: source.type === 'arxiv' ? 'arxiv' as const : 'custom' as const,
      name: source.name || source.id,
      enabled: source.enabled !== false,
    }));

  return usable.length > 0
    ? usable
    : [{ id: 'arxiv', type: 'arxiv', name: 'arXiv', enabled: true }];
}

function sourceTypeText(type: PaperSourceConfig['type']): string {
  return type === 'arxiv' ? 'arXiv' : '自定义来源';
}

function sourceOptionLabel(source: PaperSourceConfig): string {
  const state = source.enabled ? '' : '（停用）';
  return `${source.name || source.id} · ${sourceTypeText(source.type)}${state}`;
}

function renderSourceTypeOptions(selected: PaperSourceConfig['type']): string {
  return [
    ['arxiv', 'arXiv'],
    ['custom', '自定义来源'],
  ].map(([value, label]) =>
    `<option value="${value}" ${selected === value ? 'selected' : ''}>${label}</option>`,
  ).join('');
}

function renderSourceRows(sources: EditableConfig['sources'] | undefined): string {
  const displaySources = normalizedSources(sources);

  return `<section class="field-group wide" data-source-registry>
    <div class="subhead">
      <div>
        <h2>论文来源</h2>
        <p>先注册可用来源，再在领域规则里选择来源。当前已实现 arXiv，自定义来源会保留配置，待接入对应嗅探器后启用。</p>
      </div>
      <button class="button secondary mini" type="button" data-add-source>添加来源</button>
    </div>
    <div class="source-list" data-source-list>
      ${displaySources.map(source => `<article class="source-card" data-source-row>
        <label>
          <span>来源标识</span>
          <input name="source_id" value="${escapeAttr(source.id)}" placeholder="例如：arxiv" data-source-id>
        </label>
        <label>
          <span>来源类型</span>
          <select name="source_type" data-source-type>${renderSourceTypeOptions(source.type)}</select>
        </label>
        <label>
          <span>显示名称</span>
          <input name="source_name" value="${escapeAttr(source.name)}" placeholder="例如：arXiv" data-source-name>
        </label>
        <label>
          <span>状态</span>
          <select name="source_enabled" data-source-enabled>
            <option value="true" ${source.enabled ? 'selected' : ''}>启用</option>
            <option value="false" ${!source.enabled ? 'selected' : ''}>停用</option>
          </select>
        </label>
        <button class="button secondary danger mini source-delete" type="button" data-remove-source>删除来源</button>
      </article>`).join('')}
    </div>
  </section>`;
}

function renderSourceOptions(
  sources: PaperSourceConfig[],
  selected: string | undefined,
): string {
  const fallback = sources.find(source => source.enabled)?.id || sources[0]?.id || 'arxiv';
  const selectedSource = selected || fallback;

  return sources.map(source =>
    `<option value="${escapeAttr(source.id)}" ${source.id === selectedSource ? 'selected' : ''}>${escapeHtml(sourceOptionLabel(source))}</option>`,
  ).join('');
}

function renderDomainRuleRow(
  rule: EditableConfig['domain_rules'][number],
  sources: PaperSourceConfig[],
): string {
  const filterHidden = rule.mode === 'categories_filter' ? '' : ' is-hidden';

  return `<article class="rule-card" data-domain-rule>
    <label>
      <span>来源</span>
      <select name="domain_source" data-domain-source>
        ${renderSourceOptions(sources, rule.source)}
      </select>
    </label>
    <label>
      <span>领域分类</span>
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

function renderDomainRuleRows(
  rules: EditableConfig['domain_rules'],
  sources: EditableConfig['sources'] | undefined,
): string {
  const displaySources = normalizedSources(sources);
  const fallbackSource = displaySources.find(source => source.enabled)?.id || displaySources[0]?.id || 'arxiv';
  const displayRules = rules.length > 0
    ? rules
    : [{ source: fallbackSource, category: '', mode: 'accept_all' as const, filter_categories: [] }];

  return `<section class="field-group wide" data-domain-rules>
    <div class="subhead">
      <div>
        <h2>领域规则</h2>
        <p>每条规则先选择来源，再配置该来源下的领域分类和匹配方式。</p>
      </div>
      <button class="button secondary mini" type="button" data-add-domain-rule>添加规则</button>
    </div>
    <div class="rule-list" data-domain-rule-list>
      ${displayRules.map(rule => renderDomainRuleRow(rule, displaySources)).join('')}
    </div>
  </section>`;
}

function renderConfigForm(config: EditableConfig): string {
  const systemPrompt = configText(config, 'prompt_system') || DEFAULT_SYSTEM_PROMPT;
  const userPromptTemplate = configText(config, 'prompt_user_template') || DEFAULT_USER_TEMPLATE;

  return `<form class="form-grid" method="post">
    ${renderKeywordRows(config.keywords || [])}
    ${renderSourceRows(config.sources)}
    ${renderDomainRuleRows(config.domain_rules || [], config.sources)}
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
      <input type="number" min="1" max="500" name="max_concurrent_requests" value="${escapeAttr(configText(config, 'max_concurrent_requests'))}">
    </label>
    <label>
      <span>日志等级</span>
      <select name="log_level">
        ${['DEBUG', 'INFO', 'WARNING', 'ERROR'].map(level => `<option value="${level}" ${config.log_level === level ? 'selected' : ''}>${level}</option>`).join('')}
      </select>
    </label>
    <label class="wide">
      <span>系统提示词</span>
      <textarea name="prompt_system" rows="14">${escapeHtml(systemPrompt)}</textarea>
    </label>
    <label class="wide">
      <span>用户提示词模板</span>
      <textarea name="prompt_user_template" rows="8">${escapeHtml(userPromptTemplate)}</textarea>
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
  health?: HealthResponse;
  backendBaseUrl?: string;
  statusErrors?: string[];
  flash?: Flash;
}): string {
  const source = options.response
    ? `<div class="meta-bar"><span>KV Key：${escapeHtml(options.response.key || '未写入')}</span></div>`
    : '';

  const body = `${renderFlash(options.flash)}
  <header class="page-header">
    <div>
      <p class="eyebrow">运行配置</p>
      <h1>配置管理</h1>
    </div>
  </header>
  ${source}
  ${renderStatusPanel({
    health: options.health,
    config: options.response,
    backendBaseUrl: options.backendBaseUrl,
    errors: options.statusErrors || [],
  })}
  <section class="panel">
    ${renderConfigForm(options.config)}
  </section>`;

  return pageShell({
    title: 'PaperSniffer 配置',
    current: 'config',
    body,
  });
}

function renderRunPanel(defaultDate: string, response?: RunResponse): string {
  const analyzedCount = response && !response.queued
    ? response.result.total_analyzed ?? response.result.total_filtered
    : 0;
  const responseHtml = response
    ? `<div class="run-result">
        <h3>运行结果</h3>
        ${response.queued
          ? `<p>${escapeHtml(response.targetDate)} 的任务已进入队列。</p><a class="button secondary mini" href="/?date=${encodeURIComponent(response.targetDate)}">查看结果</a>`
          : `<p>${escapeHtml(response.result.date)} 已完成。抓取 ${response.result.total_fetched} 篇，分析 ${analyzedCount} 篇。</p><a class="button secondary mini" href="/?date=${encodeURIComponent(response.result.date)}">查看结果</a>`}
      </div>`
    : '';

  return `<section class="panel run-panel" id="run-panel">
    <div class="subhead">
      <div>
        <h2>运行流水线</h2>
        <p>手动触发当前日期的抓取和分析任务：${escapeHtml(defaultDate)}</p>
      </div>
    </div>
    <form class="run-form" method="post" action="/run">
      <input type="hidden" name="date" value="${escapeAttr(defaultDate)}">
      <label class="check">
        <input type="checkbox" name="sync" value="true">
        <span>同步运行</span>
      </label>
      <button type="submit">开始运行</button>
    </form>
    ${responseHtml ? `<div class="run-response">${responseHtml}</div>` : ''}
  </section>`;
}

export function renderRunPage(options: {
  defaultDate: string;
  response?: RunResponse;
  flash?: Flash;
}): string {
  const body = `${renderFlash(options.flash)}
  <header class="page-header">
    <div>
      <p class="eyebrow">手动控制</p>
      <h1>运行流水线</h1>
    </div>
  </header>
  ${renderRunPanel(options.defaultDate, options.response)}`;

  return pageShell({
    title: 'PaperSniffer 运行',
    current: 'run',
    body,
  });
}

function renderStatusPanel(options: {
  health?: HealthResponse;
  config?: ConfigResponse;
  backendBaseUrl?: string;
  errors: string[];
}): string {
  const error = options.errors.length > 0
    ? `<div class="status-error">${escapeHtml(options.errors.join(' '))}</div>`
    : '';

  return `<section class="panel status-panel" id="status-panel">
    <div class="subhead">
      <div>
        <h2>系统状态</h2>
        <p>后端连通性和当前运行参数。</p>
      </div>
      <a class="button secondary mini" href="/config#status-panel">刷新</a>
    </div>
    ${error}
    <dl class="details compact">
      <dt>后端</dt><dd>${options.health ? '在线' : '不可用'}</dd>
      <dt>地址</dt><dd>${escapeHtml(options.backendBaseUrl || '未配置')}</dd>
      <dt>运行时</dt><dd>${escapeHtml(options.health?.runtime || '未知')}</dd>
      <dt>模型</dt><dd>${escapeHtml(options.config?.effective_config.openai_model || '未知')}</dd>
      <dt>阈值</dt><dd>${escapeHtml(scoreText(options.config?.effective_config.relevance_threshold))}</dd>
    </dl>
  </section>`;
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
  ${renderStatusPanel(options)}`;

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
  const autoRefresh = document.querySelector('[data-auto-refresh-url]');
  if (autoRefresh instanceof HTMLElement) {
    const url = autoRefresh.getAttribute('data-auto-refresh-url');
    if (url) {
      window.setTimeout(() => {
        window.location.href = url;
      }, 5000);
    }
  }

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

  function escapeOption(value) {
    return String(value || '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;');
  }

  function sourceTypeLabel(type) {
    return type === 'arxiv' ? 'arXiv' : '自定义来源';
  }

  function collectSources() {
    const rows = Array.from(document.querySelectorAll('[data-source-row]'));
    const sources = rows.map(row => {
      const id = row.querySelector('[data-source-id]')?.value.trim() || '';
      const type = row.querySelector('[data-source-type]')?.value || 'custom';
      const name = row.querySelector('[data-source-name]')?.value.trim() || id;
      const enabled = row.querySelector('[data-source-enabled]')?.value !== 'false';
      return { id, type, name, enabled };
    }).filter(source => source.id);

    return sources.length > 0 ? sources : [{ id: 'arxiv', type: 'arxiv', name: 'arXiv', enabled: true }];
  }

  function sourceOptions(selected) {
    const sources = collectSources();
    const fallback = sources.find(source => source.enabled)?.id || sources[0]?.id || 'arxiv';
    const current = selected || fallback;
    return sources.map(source => {
      const label = (source.name || source.id) + ' · ' + sourceTypeLabel(source.type) + (source.enabled ? '' : '（停用）');
      return '<option value="' + escapeOption(source.id) + '"' + (source.id === current ? ' selected' : '') + '>' + escapeOption(label) + '</option>';
    }).join('');
  }

  function refreshDomainSourceOptions() {
    document.querySelectorAll('[data-domain-source]').forEach(select => {
      const selected = select.value;
      select.innerHTML = sourceOptions(selected);
      if (selected && Array.from(select.options).some(option => option.value === selected)) {
        select.value = selected;
      }
    });
  }

  function sourceRowTemplate() {
    return '<article class="source-card" data-source-row>' +
      '<label><span>来源标识</span><input name="source_id" placeholder="例如：semantic-scholar" data-source-id></label>' +
      '<label><span>来源类型</span><select name="source_type" data-source-type>' +
      '<option value="arxiv">arXiv</option>' +
      '<option value="custom" selected>自定义来源</option>' +
      '</select></label>' +
      '<label><span>显示名称</span><input name="source_name" placeholder="例如：Semantic Scholar" data-source-name></label>' +
      '<label><span>状态</span><select name="source_enabled" data-source-enabled>' +
      '<option value="true" selected>启用</option>' +
      '<option value="false">停用</option>' +
      '</select></label>' +
      '<button class="button secondary danger mini source-delete" type="button" data-remove-source>删除来源</button>' +
      '</article>';
  }

  function bindSourceRegistry(root) {
    const list = root.querySelector('[data-source-list]');

    root.addEventListener('input', refreshDomainSourceOptions);
    root.addEventListener('change', refreshDomainSourceOptions);

    root.addEventListener('click', event => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) {
        return;
      }

      if (target.matches('[data-add-source]')) {
        list.insertAdjacentHTML('beforeend', sourceRowTemplate());
        refreshDomainSourceOptions();
      }

      if (target.matches('[data-remove-source]')) {
        const rows = list.querySelectorAll('[data-source-row]');
        const row = target.closest('[data-source-row]');
        if (row && rows.length > 1) {
          row.remove();
        } else if (row) {
          row.querySelectorAll('input').forEach(input => {
            input.value = '';
          });
          const type = row.querySelector('[data-source-type]');
          const enabled = row.querySelector('[data-source-enabled]');
          if (type) {
            type.value = 'custom';
          }
          if (enabled) {
            enabled.value = 'true';
          }
        }
        refreshDomainSourceOptions();
      }
    });
  }

  function domainRuleTemplate() {
    return '<article class="rule-card" data-domain-rule>' +
      '<label><span>来源</span><select name="domain_source" data-domain-source>' + sourceOptions('') + '</select></label>' +
      '<label><span>领域分类</span><input name="domain_category" placeholder="例如：cs.CL"></label>' +
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
        const rule = list.querySelector('[data-domain-rule]:last-child');
        if (rule) {
          syncDomainRule(rule);
        }
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
  document.querySelectorAll('[data-source-registry]').forEach(bindSourceRegistry);
  document.querySelectorAll('[data-domain-rules]').forEach(bindDomainRules);
  refreshDomainSourceOptions();
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
  min-height: 100vh;
}
.topbar {
  align-items: center;
  background: rgba(251, 252, 251, 0.96);
  border-bottom: 1px solid var(--line);
  display: flex;
  gap: 18px;
  justify-content: space-between;
  min-height: 72px;
  padding: 14px 28px;
  position: sticky;
  top: 0;
  z-index: 10;
}
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  color: inherit;
  text-decoration: none;
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
.top-actions {
  align-items: center;
  display: flex;
  gap: 8px;
}
.icon-button {
  align-items: center;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--text);
  cursor: pointer;
  display: inline-flex;
  height: 40px;
  justify-content: center;
  text-decoration: none;
  width: 40px;
}
.icon-button svg {
  fill: none;
  height: 21px;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.8;
  width: 21px;
}
.icon-button.active, .icon-button:hover {
  background: var(--surface-2);
  color: var(--text);
}
.main {
  width: min(1440px, 100%);
  margin: 0 auto;
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
  grid-template-columns: 150px minmax(220px, 1fr) 150px 150px auto auto auto;
  gap: 10px;
  margin-bottom: 16px;
}
.control-grid {
  display: grid;
  grid-template-columns: minmax(340px, 0.9fr) minmax(420px, 1.1fr);
  gap: 16px;
  margin-bottom: 16px;
}
.run-panel {
  margin-bottom: 16px;
}
.run-form {
  align-items: end;
  display: grid;
  grid-template-columns: auto auto;
  gap: 10px;
  justify-content: start;
}
.run-response {
  margin-top: 12px;
}
.run-result {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
}
.run-result h3 {
  font-size: 15px;
  margin-bottom: 6px;
  margin-top: 0;
}
.run-result p {
  color: #33413d;
  margin-bottom: 10px;
}
.refresh-status {
  align-items: center;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  display: flex;
  gap: 16px;
  justify-content: space-between;
  margin-bottom: 16px;
  padding: 14px 16px;
}
.refresh-status h2 {
  font-size: 16px;
  margin-bottom: 4px;
}
.refresh-status p {
  color: #33413d;
  margin-bottom: 6px;
}
.refresh-running {
  border-color: #93c5fd;
  box-shadow: inset 3px 0 0 var(--medium);
}
.refresh-queued {
  border-color: #fed7aa;
  box-shadow: inset 3px 0 0 var(--accent-2);
}
.refresh-completed {
  border-color: #99f6e4;
  box-shadow: inset 3px 0 0 var(--accent);
}
.refresh-error, .refresh-failed {
  border-color: #fecaca;
  box-shadow: inset 3px 0 0 var(--danger);
}
.refresh-step {
  color: var(--muted);
  display: block;
  font-size: 12px;
  margin-bottom: 6px;
}
.progress {
  background: var(--surface-2);
  border-radius: 999px;
  height: 6px;
  max-width: 360px;
  overflow: hidden;
}
.progress span {
  background: var(--medium);
  border-radius: inherit;
  display: block;
  height: 100%;
  transition: width 0.3s ease;
}
.run-log {
  display: grid;
  gap: 6px;
  list-style: none;
  margin: 12px 0 0;
  max-width: 760px;
  padding: 0;
}
.run-log li {
  border-left: 2px solid var(--line);
  padding-left: 8px;
}
.run-log span {
  color: var(--muted);
  display: block;
  font-size: 12px;
  font-weight: 800;
}
.run-log p {
  margin: 1px 0 0;
}
.run-log .log-error {
  border-left-color: var(--danger);
}
.run-log .log-warn {
  border-left-color: var(--accent-2);
}
.status-error {
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 8px;
  color: #991b1b;
  margin-bottom: 12px;
  padding: 10px 12px;
}
.view-tabs {
  display: inline-flex;
  gap: 8px;
  margin-bottom: 16px;
}
.view-tabs a {
  align-items: center;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--text);
  display: inline-flex;
  gap: 8px;
  min-height: 38px;
  padding: 8px 12px;
  text-decoration: none;
}
.view-tabs a.active,
.view-tabs a:hover {
  background: var(--accent);
  border-color: var(--accent);
  color: white;
}
.view-tabs strong {
  background: rgba(15, 118, 110, 0.12);
  border-radius: 999px;
  font-size: 12px;
  min-width: 24px;
  padding: 2px 7px;
  text-align: center;
}
.view-tabs a.active strong,
.view-tabs a:hover strong {
  background: rgba(255, 255, 255, 0.2);
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
.keyword-filters {
  margin-bottom: 16px;
}
.keyword-filter-head {
  align-items: center;
  display: flex;
  gap: 12px;
  justify-content: space-between;
  margin-bottom: 10px;
}
.keyword-filter-head h2 {
  font-size: 15px;
  margin: 0;
}
.keyword-filter-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.keyword-filter {
  align-items: center;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 999px;
  color: #33413d;
  display: inline-flex;
  gap: 7px;
  min-height: 30px;
  padding: 5px 10px;
  text-decoration: none;
}
.keyword-filter:hover, .keyword-filter.active {
  background: var(--accent);
  border-color: var(--accent);
  color: white;
}
.keyword-filter strong {
  background: rgba(15, 118, 110, 0.12);
  border-radius: 999px;
  font-size: 12px;
  min-width: 22px;
  padding: 2px 6px;
  text-align: center;
}
.keyword-filter.active strong,
.keyword-filter:hover strong {
  background: rgba(255, 255, 255, 0.2);
}
.keyword-filter.clear {
  color: var(--muted);
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
.paper-list {
  display: grid;
  gap: 10px;
}
.paper-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 16px;
  scroll-margin-top: 88px;
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
.paper-head-actions {
  align-items: center;
  display: inline-flex;
  gap: 8px;
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
  text-decoration: none;
}
.tag:hover {
  border-color: #9bb0aa;
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
.paper-card-detail {
  border-top: 1px solid var(--line);
  margin-top: 14px;
  padding-top: 14px;
}
.detail-actions {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 12px;
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
.list-rows, .rule-list, .source-list {
  display: grid;
  gap: 10px;
}
.list-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
}
.source-card, .rule-card {
  align-items: end;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  display: grid;
  gap: 10px;
  padding: 12px;
}
.source-card {
  grid-template-columns: minmax(140px, 1fr) minmax(150px, 0.8fr) minmax(180px, 1fr) minmax(110px, 0.6fr) auto;
}
.rule-card {
  grid-template-columns: minmax(150px, 0.9fr) minmax(140px, 1fr) minmax(220px, 1.3fr) minmax(180px, 1fr) auto;
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
  .toolbar, .control-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .source-card, .rule-card {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .source-delete, .rule-delete {
    grid-column: 1 / -1;
  }
  .stats {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
@media (max-width: 760px) {
  .topbar {
    padding: 12px 18px;
  }
  .main {
    padding: 18px;
  }
  .page-header {
    align-items: stretch;
    flex-direction: column;
  }
  .toolbar, .form-grid, .status-grid, .stats, .control-grid, .run-form {
    grid-template-columns: 1fr;
  }
  .refresh-status {
    align-items: stretch;
    flex-direction: column;
  }
  .list-row, .source-card, .rule-card {
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
