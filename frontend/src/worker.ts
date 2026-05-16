import { BackendClient, BackendClientEnv } from './backend_client';
import {
  AnalysisResultRecord,
  BackendApiError,
  ConfigResponse,
  EditableConfig,
  Flash,
  HealthResponse,
  RunResponse,
  Score,
  UiFilters,
} from './models';
import {
  DashboardRefreshState,
  escapeHtml,
  renderConfigPage,
  renderDashboardPage,
  renderErrorPage,
  todayUtc,
} from './views';

interface Env extends BackendClientEnv {
  APP_TITLE?: string;
}

const VALID_DATE = /^\d{4}-\d{2}-\d{2}$/;
const SCORE_VALUES: Score[] = ['HIGH', 'MEDIUM', 'LOW', 'IRRELEVANT'];
const SCORE_TEXT: Record<Score, string> = {
  HIGH: '高',
  MEDIUM: '中',
  LOW: '低',
  IRRELEVANT: '无关',
};
const SCORE_PRIORITY: Record<Score, number> = {
  HIGH: 3,
  MEDIUM: 2,
  LOW: 1,
  IRRELEVANT: 0,
};

function jsonResponse(data: unknown, init: ResponseInit = {}): Response {
  const headers = new Headers(init.headers);
  headers.set('content-type', 'application/json; charset=utf-8');
  headers.set('cache-control', 'no-store');

  return new Response(JSON.stringify(data, null, 2), {
    ...init,
    headers,
  });
}

function htmlResponse(html: string, status = 200): Response {
  return new Response(html, {
    status,
    headers: {
      'content-type': 'text/html; charset=utf-8',
      'cache-control': 'no-store',
    },
  });
}

function textResponse(text: string, contentType: string): Response {
  return new Response(text, {
    headers: {
      'content-type': contentType,
      'cache-control': 'no-store',
    },
  });
}

function errorMessage(error: unknown): string {
  if (error instanceof BackendApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function parseFilters(request: Request): UiFilters {
  const url = new URL(request.url);
  const date = url.searchParams.get('date') || todayUtc();

  return {
    date: VALID_DATE.test(date) ? date : todayUtc(),
    q: url.searchParams.get('q')?.trim() || '',
    score: url.searchParams.get('score')?.trim().toUpperCase() || '',
    keyword: url.searchParams.get('keyword')?.trim() || '',
    selected: url.searchParams.get('selected')?.trim() || '',
    view: url.searchParams.get('view') === 'all' ? 'all' : 'focus',
  };
}

function parseRefreshRequest(request: Request): { ensure: boolean; running: boolean; attempt: number } {
  const url = new URL(request.url);
  const attempt = Number(url.searchParams.get('attempt') || '0');

  return {
    ensure: url.searchParams.get('ensure') === '1',
    running: url.searchParams.get('running') === '1',
    attempt: Number.isInteger(attempt) && attempt > 0 ? Math.min(attempt, 999) : 0,
  };
}

function dashboardPath(filters: UiFilters, extras: Record<string, string | number | undefined> = {}): string {
  const params = new URLSearchParams();
  for (const key of ['date', 'q', 'score', 'keyword', 'selected', 'view'] as const) {
    const value = filters[key];
    if (value) {
      params.set(key, value);
    }
  }

  for (const [key, value] of Object.entries(extras)) {
    if (value !== undefined && value !== '') {
      params.set(key, String(value));
    }
  }

  const query = params.toString();
  return query ? `/?${query}` : '/';
}

function searchableText(result: AnalysisResultRecord): string {
  return [
    result.title,
    result.abstract,
    result.reason,
    result.core_methods,
    result.problem,
    ...result.authors,
    ...result.categories,
    ...result.keywords,
  ].join(' ').toLowerCase();
}

function filterResults(
  results: AnalysisResultRecord[],
  filters: UiFilters,
  options: { includeKeyword?: boolean } = {},
): AnalysisResultRecord[] {
  const q = filters.q.toLowerCase();
  const keyword = filters.keyword.toLowerCase();
  const score = filters.score.toUpperCase();
  const includeKeyword = options.includeKeyword ?? true;

  return results.filter(result => {
    if (score && result.score !== score) {
      return false;
    }
    if (includeKeyword && keyword && !result.keywords.some(value => value.toLowerCase().includes(keyword))) {
      return false;
    }
    if (q && !searchableText(result).includes(q)) {
      return false;
    }
    return true;
  });
}

function focusThreshold(config: ConfigResponse | undefined): Score {
  const value = config?.effective_config.relevance_threshold;
  return value && SCORE_VALUES.includes(value) ? value : 'MEDIUM';
}

function isFocusResult(result: AnalysisResultRecord, threshold: Score): boolean {
  return SCORE_PRIORITY[result.score] >= SCORE_PRIORITY[threshold];
}

function keywordFacets(results: AnalysisResultRecord[]): Array<{ value: string; count: number }> {
  const counts = new Map<string, { value: string; count: number }>();

  for (const result of results) {
    const seen = new Set<string>();
    for (const keyword of result.keywords) {
      const value = keyword.trim();
      const key = value.toLowerCase();
      if (!value || seen.has(key)) {
        continue;
      }

      seen.add(key);
      const current = counts.get(key);
      if (current) {
        current.count += 1;
      } else {
        counts.set(key, { value, count: 1 });
      }
    }
  }

  return [...counts.values()]
    .sort((left, right) => right.count - left.count || left.value.localeCompare(right.value))
    .slice(0, 24);
}

function pickSelected(results: AnalysisResultRecord[], selectedId: string): AnalysisResultRecord | undefined {
  if (!selectedId) {
    return undefined;
  }

  return results.find(result => result.id === selectedId);
}

function markdownEscape(value: string): string {
  return value.replaceAll('\r', '').trim();
}

function renderMarkdown(date: string, results: AnalysisResultRecord[]): string {
  const sections = results.map(result => [
    `## ${SCORE_TEXT[result.score]}: ${markdownEscape(result.title)}`,
    '',
    `- ID: ${markdownEscape(result.id)}`,
    `- 链接: ${markdownEscape(result.paper_url)}`,
    `- 发布日期: ${markdownEscape(result.published.slice(0, 10))}`,
    `- 作者: ${markdownEscape(result.authors.join(', ') || '未知')}`,
    `- 分类: ${markdownEscape(result.categories.join(', '))}`,
    `- 关键词: ${markdownEscape(result.keywords.join(', '))}`,
    '',
    `推荐理由: ${markdownEscape(result.reason)}`,
    '',
    `核心方法: ${markdownEscape(result.core_methods)}`,
    '',
    `问题: ${markdownEscape(result.problem)}`,
    '',
    `摘要: ${markdownEscape(result.abstract)}`,
  ].join('\n'));

  return [`# PaperSniffer ${date} 论文结果`, '', ...sections].join('\n\n');
}

async function loadFilteredResults(
  filters: UiFilters,
  client: BackendClient,
  config: ConfigResponse | undefined,
): Promise<{
  filters: UiFilters;
  allResults: AnalysisResultRecord[];
  results: AnalysisResultRecord[];
  focusTotal: number;
  selected?: AnalysisResultRecord;
  keywordFacets: Array<{ value: string; count: number }>;
}> {
  const response = await client.analysisResults(filters.date);
  const threshold = focusThreshold(config);
  const focusResults = response.results.filter(result => isFocusResult(result, threshold));
  const viewSource = filters.view === 'focus' ? focusResults : response.results;
  const relatedResults = filterResults(viewSource, filters, { includeKeyword: false });
  const results = filterResults(viewSource, filters);

  return {
    filters,
    allResults: response.results,
    results,
    focusTotal: focusResults.length,
    selected: pickSelected(results, filters.selected),
    keywordFacets: keywordFacets(relatedResults),
  };
}

async function loadStatusSummary(client: BackendClient, env: Env): Promise<{
  health?: HealthResponse;
  config?: ConfigResponse;
  backendBaseUrl?: string;
  errors: string[];
}> {
  const errors: string[] = [];
  let health;
  let config;

  try {
    health = await client.health();
  } catch (error) {
    errors.push(`健康检查失败：${errorMessage(error)}`);
  }

  try {
    config = await client.config();
  } catch (error) {
    errors.push(`读取配置失败：${errorMessage(error)}`);
  }

  return {
    health,
    config,
    backendBaseUrl: env.BACKEND_BASE_URL,
    errors,
  };
}

async function handleDashboard(
  request: Request,
  env: Env,
  ctx?: ExecutionContext,
  options: {
    dateOverride?: string;
    runResponse?: RunResponse;
    flash?: Flash;
    status?: number;
  } = {},
): Promise<Response> {
  const client = new BackendClient(env);
  const filters = parseFilters(request);
  const refresh = parseRefreshRequest(request);
  if (options.dateOverride && VALID_DATE.test(options.dateOverride)) {
    filters.date = options.dateOverride;
    filters.selected = '';
  }

  const statusSummary = await loadStatusSummary(client, env);
  let status = options.status || 200;
  let flash = options.flash;
  let refreshState: DashboardRefreshState | undefined;

  try {
    const { allResults, results, focusTotal, selected, keywordFacets } = await loadFilteredResults(
      filters,
      client,
      statusSummary.config,
    );

    if ((refresh.ensure || refresh.running) && allResults.length === 0) {
      status = refresh.running ? 200 : 202;
      const nextAttempt = refresh.attempt + 1;
      refreshState = {
        kind: 'running',
        date: filters.date,
        attempt: nextAttempt,
        nextUrl: dashboardPath(filters, { running: '1', attempt: nextAttempt }),
        message: refresh.running
          ? `${filters.date} 的流水线仍在运行，暂未查询到入库论文。`
          : `${filters.date} 暂无入库论文，已启动抓取和分析流水线。`,
      };

      if (!refresh.running) {
        const runTask = client.run({ date: filters.date, sync: false })
          .catch(error => {
            console.error(`刷新触发流水线失败: ${errorMessage(error)}`);
          });

        if (ctx) {
          ctx.waitUntil(runTask);
        } else {
          void runTask;
        }
      }
    } else if (refresh.running && allResults.length > 0) {
      refreshState = {
        kind: 'completed',
        date: filters.date,
        attempt: refresh.attempt,
        message: `${filters.date} 的流水线已完成，已从数据库读取 ${allResults.length} 篇论文。`,
      };
    } else if (refresh.ensure && allResults.length > 0) {
      refreshState = {
        kind: 'completed',
        date: filters.date,
        attempt: 0,
        message: `数据库中已有 ${filters.date} 的论文，共 ${allResults.length} 篇，已直接刷新。`,
      };
    }

    return htmlResponse(renderDashboardPage({
      filters,
      results,
      totalCount: allResults.length,
      focusTotal,
      selected,
      keywordFacets,
      runResponse: options.runResponse,
      refreshState,
      flash,
    }), status);
  } catch (error) {
    flash = {
      kind: 'error',
      message: flash ? `${flash.message} ${errorMessage(error)}` : errorMessage(error),
    };
    status = status === 200 ? 502 : status;
    return htmlResponse(renderDashboardPage({
      filters,
      results: [],
      totalCount: 0,
      focusTotal: 0,
      keywordFacets: [],
      runResponse: options.runResponse,
      refreshState: (refresh.ensure || refresh.running)
        ? {
          kind: 'error',
          date: filters.date,
          attempt: refresh.attempt,
          message: errorMessage(error),
        }
        : undefined,
      flash,
    }), status);
  }
}

function optionalString(form: FormData, name: string): string | undefined {
  const value = String(form.get(name) || '').trim();
  return value || undefined;
}

function optionalNumber(form: FormData, name: string): number | undefined {
  const raw = String(form.get(name) || '').trim();
  if (!raw) {
    return undefined;
  }

  const value = Number(raw);
  if (!Number.isFinite(value)) {
    throw new Error(`${name} 必须是数字`);
  }
  return value;
}

function formStrings(form: FormData, name: string): string[] {
  return form.getAll(name)
    .map(value => String(value).trim())
    .filter(Boolean);
}

function splitList(value: string): string[] {
  return value
    .split(/[\r\n,，;；]+/)
    .map(item => item.trim())
    .filter(Boolean);
}

function parseSourceForm(form: FormData): NonNullable<EditableConfig['sources']> {
  const ids = form.getAll('source_id').map(value => String(value).trim());
  const types = form.getAll('source_type').map(value => String(value).trim());
  const names = form.getAll('source_name').map(value => String(value).trim());
  const enabledValues = form.getAll('source_enabled').map(value => String(value).trim());

  const sources = ids
    .map((id, index) => ({
      id,
      type: types[index] === 'arxiv' ? 'arxiv' as const : 'custom' as const,
      name: names[index] || id,
      enabled: enabledValues[index] !== 'false',
    }))
    .filter(source => source.id);

  return sources.length > 0
    ? sources
    : [{ id: 'arxiv', type: 'arxiv', name: 'arXiv', enabled: true }];
}

async function parseConfigForm(request: Request): Promise<EditableConfig> {
  const form = await request.formData();
  const keywords = formStrings(form, 'keyword');
  const sources = parseSourceForm(form);
  const fallbackSource = sources.find(source => source.enabled)?.id || sources[0]?.id || 'arxiv';
  const domainSources = form.getAll('domain_source').map(value => String(value).trim());
  const domainCategories = form.getAll('domain_category').map(value => String(value).trim());
  const domainModes = form.getAll('domain_mode').map(value => String(value).trim());
  const domainFilters = form.getAll('domain_filter_categories').map(value => String(value).trim());
  const threshold = String(form.get('relevance_threshold') || 'MEDIUM').toUpperCase() as Score;
  const logLevel = optionalString(form, 'log_level') as EditableConfig['log_level'];

  if (!SCORE_VALUES.includes(threshold)) {
    throw new Error('相关性阈值无效');
  }

  const domainRules = domainCategories
    .map((category, index) => ({
      source: domainSources[index] || fallbackSource,
      category,
      mode: domainModes[index] === 'categories_filter' ? 'categories_filter' : 'accept_all',
      filter_categories: splitList(domainFilters[index] || ''),
    } satisfies EditableConfig['domain_rules'][number]))
    .filter(rule => rule.category);

  return {
    keywords,
    sources,
    domain_rules: domainRules,
    relevance_threshold: threshold,
    openai_model: String(form.get('openai_model') || '').trim(),
    openai_base_url: optionalString(form, 'openai_base_url'),
    max_results_per_category: optionalNumber(form, 'max_results_per_category'),
    max_concurrent_requests: optionalNumber(form, 'max_concurrent_requests'),
    log_level: logLevel,
    prompt_system: optionalString(form, 'prompt_system'),
    prompt_user_template: optionalString(form, 'prompt_user_template'),
  };
}

async function handleConfigGet(env: Env, flash?: Flash, status = 200): Promise<Response> {
  const client = new BackendClient(env);

  try {
    const [response, statusSummary] = await Promise.all([
      client.config(),
      loadStatusSummary(client, env),
    ]);
    return htmlResponse(renderConfigPage({
      response,
      config: response.config,
      health: statusSummary.health,
      backendBaseUrl: statusSummary.backendBaseUrl,
      statusErrors: statusSummary.errors,
      flash,
    }), status);
  } catch (error) {
    return htmlResponse(renderErrorPage('配置不可用', errorMessage(error)), 502);
  }
}

async function handleConfigPost(request: Request, env: Env, mode: 'validate' | 'save'): Promise<Response> {
  const client = new BackendClient(env);
  let draft: EditableConfig;

  try {
    draft = await parseConfigForm(request);
  } catch (error) {
    return htmlResponse(renderErrorPage('表单数据无效', errorMessage(error)), 400);
  }

  try {
    const response = mode === 'validate'
      ? await client.validateConfig(draft)
      : await client.saveConfig(draft);
    const statusSummary = await loadStatusSummary(client, env);
    return htmlResponse(renderConfigPage({
      response,
      config: response.config,
      health: statusSummary.health,
      backendBaseUrl: statusSummary.backendBaseUrl,
      statusErrors: statusSummary.errors,
      flash: {
        kind: 'success',
        message: mode === 'validate' ? '配置校验通过。' : '配置已保存到 KV。',
      },
    }));
  } catch (error) {
    const statusSummary = await loadStatusSummary(client, env);
    return htmlResponse(renderConfigPage({
      config: draft,
      health: statusSummary.health,
      backendBaseUrl: statusSummary.backendBaseUrl,
      statusErrors: statusSummary.errors,
      flash: {
        kind: 'error',
        message: errorMessage(error),
      },
    }), 400);
  }
}

async function handleRunGet(request: Request, _env: Env): Promise<Response> {
  const url = new URL(request.url);
  const date = url.searchParams.get('date') || todayUtc();
  const dashboardUrl = new URL('/', request.url);
  dashboardUrl.searchParams.set('date', VALID_DATE.test(date) ? date : todayUtc());
  dashboardUrl.searchParams.set('ensure', '1');
  return Response.redirect(dashboardUrl, 303);
}

async function handleRunPost(request: Request, env: Env): Promise<Response> {
  const form = await request.formData();
  const date = String(form.get('date') || '').trim();
  const sync = form.get('sync') === 'true';
  const client = new BackendClient(env);
  const requestedDate = VALID_DATE.test(date) ? date : todayUtc();

  try {
    const response = await client.run({
      date: VALID_DATE.test(date) ? date : undefined,
      sync,
    });
    const responseDate = response.queued
      ? VALID_DATE.test(response.targetDate) ? response.targetDate : requestedDate
      : response.result.date;

    return handleDashboard(request, env, undefined, {
      dateOverride: responseDate,
      runResponse: response,
      flash: {
        kind: 'success',
        message: response.queued ? '任务已加入队列。' : '任务已完成。',
      },
      status: response.queued ? 202 : 200,
    });
  } catch (error) {
    return handleDashboard(request, env, undefined, {
      dateOverride: requestedDate,
      flash: {
        kind: 'error',
        message: errorMessage(error),
      },
      status: 502,
    });
  }
}

async function handleStatus(request: Request): Promise<Response> {
  return Response.redirect(new URL('/config#status-panel', request.url), 303);
}

function mapApiPath(pathname: string): string {
  if (pathname === '/api/run') {
    return '/run';
  }
  if (pathname === '/api/health') {
    return '/health';
  }
  return pathname;
}

async function handleApiProxy(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const client = new BackendClient(env);

  try {
    return await client.proxy(request, mapApiPath(url.pathname));
  } catch (error) {
    return jsonResponse({
      ok: false,
      error: errorMessage(error),
    }, { status: 502 });
  }
}

async function handleExport(request: Request, env: Env, format: 'json' | 'markdown'): Promise<Response> {
  const client = new BackendClient(env);
  const filters = parseFilters(request);
  const config = await client.config().catch(() => undefined);
  const { results } = await loadFilteredResults(filters, client, config);

  if (format === 'json') {
    return jsonResponse({
      ok: true,
      filters,
      results,
    });
  }

  return textResponse(renderMarkdown(filters.date, results), 'text/markdown; charset=utf-8');
}

function methodNotAllowed(): Response {
  return jsonResponse({
    ok: false,
    error: '不支持的请求方法',
  }, { status: 405 });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204 });
    }

    if (url.pathname === '/login' || url.pathname === '/logout') {
      return Response.redirect(new URL('/', request.url), 303);
    }

    try {
      if (url.pathname === '/') {
        if (request.method !== 'GET') {
          return methodNotAllowed();
        }
        return handleDashboard(request, env, ctx);
      }

      if (url.pathname === '/config') {
        if (request.method !== 'GET') {
          return methodNotAllowed();
        }
        return handleConfigGet(env);
      }

      if (url.pathname === '/config/validate') {
        if (request.method !== 'POST') {
          return methodNotAllowed();
        }
        return handleConfigPost(request, env, 'validate');
      }

      if (url.pathname === '/config/save') {
        if (request.method !== 'POST') {
          return methodNotAllowed();
        }
        return handleConfigPost(request, env, 'save');
      }

      if (url.pathname === '/run') {
        if (request.method === 'GET') {
          return handleRunGet(request, env);
        }
        if (request.method === 'POST') {
          return handleRunPost(request, env);
        }
        return methodNotAllowed();
      }

      if (url.pathname === '/status') {
        if (request.method !== 'GET') {
          return methodNotAllowed();
        }
        return handleStatus(request);
      }

      if (url.pathname === '/export.json') {
        if (request.method !== 'GET') {
          return methodNotAllowed();
        }
        return handleExport(request, env, 'json');
      }

      if (url.pathname === '/export.md') {
        if (request.method !== 'GET') {
          return methodNotAllowed();
        }
        return handleExport(request, env, 'markdown');
      }

      if (url.pathname.startsWith('/api/')) {
        return handleApiProxy(request, env);
      }

      if (url.pathname === '/favicon.ico') {
        return new Response(null, { status: 204 });
      }

      return htmlResponse(renderErrorPage(
        '页面不存在',
        `前端没有这个路径：${escapeHtml(url.pathname)}。`,
      ), 404);
    } catch (error) {
      return htmlResponse(renderErrorPage(
        '发生错误',
        errorMessage(error),
      ), 500);
    }
  },
};
