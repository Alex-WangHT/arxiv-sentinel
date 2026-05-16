import { BackendClient, BackendClientEnv } from './backend_client';
import {
  clearSessionCookie,
  frontendAuthEnabled,
  htmlResponse,
  isAuthenticated,
  loginResponse,
  redirectWithCookie,
  requireLoginRedirect,
} from './auth';
import {
  AnalysisResultRecord,
  BackendApiError,
  EditableConfig,
  Flash,
  Score,
  UiFilters,
} from './models';
import {
  escapeHtml,
  renderConfigPage,
  renderDashboardPage,
  renderErrorPage,
  renderLoginPage,
  renderRunPage,
  renderStatusPage,
  todayUtc,
} from './views';

interface Env extends BackendClientEnv {
  APP_TITLE?: string;
  FRONTEND_PASSWORD?: string;
  SESSION_SECRET?: string;
}

const VALID_DATE = /^\d{4}-\d{2}-\d{2}$/;
const SCORE_VALUES: Score[] = ['HIGH', 'MEDIUM', 'LOW', 'IRRELEVANT'];

function jsonResponse(data: unknown, init: ResponseInit = {}): Response {
  const headers = new Headers(init.headers);
  headers.set('content-type', 'application/json; charset=utf-8');
  headers.set('cache-control', 'no-store');

  return new Response(JSON.stringify(data, null, 2), {
    ...init,
    headers,
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
    category: url.searchParams.get('category')?.trim() || '',
    keyword: url.searchParams.get('keyword')?.trim() || '',
    selected: url.searchParams.get('selected')?.trim() || '',
  };
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

function filterResults(results: AnalysisResultRecord[], filters: UiFilters): AnalysisResultRecord[] {
  const q = filters.q.toLowerCase();
  const category = filters.category.toLowerCase();
  const keyword = filters.keyword.toLowerCase();
  const score = filters.score.toUpperCase();

  return results.filter(result => {
    if (score && result.score !== score) {
      return false;
    }
    if (category && !result.categories.some(value => value.toLowerCase().includes(category))) {
      return false;
    }
    if (keyword && !result.keywords.some(value => value.toLowerCase().includes(keyword))) {
      return false;
    }
    if (q && !searchableText(result).includes(q)) {
      return false;
    }
    return true;
  });
}

function pickSelected(results: AnalysisResultRecord[], selectedId: string): AnalysisResultRecord | undefined {
  if (selectedId) {
    const selected = results.find(result => result.id === selectedId);
    if (selected) {
      return selected;
    }
  }

  return results[0];
}

function markdownEscape(value: string): string {
  return value.replaceAll('\r', '').trim();
}

function renderMarkdown(date: string, results: AnalysisResultRecord[]): string {
  const sections = results.map(result => [
    `## ${result.score}: ${markdownEscape(result.title)}`,
    '',
    `- ID: ${markdownEscape(result.id)}`,
    `- URL: ${markdownEscape(result.paper_url)}`,
    `- Published: ${markdownEscape(result.published.slice(0, 10))}`,
    `- Authors: ${markdownEscape(result.authors.join(', ') || 'Unknown')}`,
    `- Categories: ${markdownEscape(result.categories.join(', '))}`,
    `- Keywords: ${markdownEscape(result.keywords.join(', '))}`,
    '',
    `Reason: ${markdownEscape(result.reason)}`,
    '',
    `Core methods: ${markdownEscape(result.core_methods)}`,
    '',
    `Problem: ${markdownEscape(result.problem)}`,
    '',
    `Abstract: ${markdownEscape(result.abstract)}`,
  ].join('\n'));

  return [`# PaperSniffer results for ${date}`, '', ...sections].join('\n\n');
}

async function loadFilteredResults(
  request: Request,
  client: BackendClient,
): Promise<{
  filters: UiFilters;
  allResults: AnalysisResultRecord[];
  results: AnalysisResultRecord[];
  selected?: AnalysisResultRecord;
}> {
  const filters = parseFilters(request);
  const response = await client.analysisResults(filters.date);
  const results = filterResults(response.results, filters);

  return {
    filters,
    allResults: response.results,
    results,
    selected: pickSelected(results, filters.selected),
  };
}

async function handleDashboard(request: Request, env: Env): Promise<Response> {
  const client = new BackendClient(env);
  const authEnabled = frontendAuthEnabled(env);

  try {
    const { filters, allResults, results, selected } = await loadFilteredResults(request, client);
    return htmlResponse(renderDashboardPage({
      filters,
      results,
      totalCount: allResults.length,
      selected,
      authEnabled,
    }));
  } catch (error) {
    const filters = parseFilters(request);
    return htmlResponse(renderDashboardPage({
      filters,
      results: [],
      totalCount: 0,
      flash: {
        kind: 'error',
        message: errorMessage(error),
      },
      authEnabled,
    }), 502);
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
    throw new Error(`${name} must be a number`);
  }
  return value;
}

async function parseConfigForm(request: Request): Promise<EditableConfig> {
  const form = await request.formData();
  const keywords = String(form.get('keywords') || '')
    .split(/\r?\n|,/)
    .map(value => value.trim())
    .filter(Boolean);
  const domainRulesRaw = String(form.get('domain_rules_json') || '[]').trim();
  const domainRules = JSON.parse(domainRulesRaw || '[]') as EditableConfig['domain_rules'];
  const threshold = String(form.get('relevance_threshold') || 'MEDIUM').toUpperCase() as Score;
  const logLevel = optionalString(form, 'log_level') as EditableConfig['log_level'];

  if (!SCORE_VALUES.includes(threshold)) {
    throw new Error('relevance_threshold is invalid');
  }

  return {
    keywords,
    domain_rules: domainRules,
    relevance_threshold: threshold,
    openai_model: String(form.get('openai_model') || '').trim(),
    openai_base_url: optionalString(form, 'openai_base_url'),
    max_results_per_category: optionalNumber(form, 'max_results_per_category'),
    max_concurrent_requests: optionalNumber(form, 'max_concurrent_requests'),
    output_dir: optionalString(form, 'output_dir'),
    prompts_dir: optionalString(form, 'prompts_dir'),
    log_level: logLevel,
    history_file: optionalString(form, 'history_file'),
    prompt_system: optionalString(form, 'prompt_system'),
    prompt_user_template: optionalString(form, 'prompt_user_template'),
  };
}

async function handleConfigGet(env: Env, flash?: Flash, status = 200): Promise<Response> {
  const client = new BackendClient(env);
  const authEnabled = frontendAuthEnabled(env);

  try {
    const response = await client.config();
    return htmlResponse(renderConfigPage({
      response,
      config: response.config,
      flash,
      authEnabled,
    }), status);
  } catch (error) {
    return htmlResponse(renderErrorPage('Configuration unavailable', errorMessage(error), authEnabled), 502);
  }
}

async function handleConfigPost(request: Request, env: Env, mode: 'validate' | 'save'): Promise<Response> {
  const client = new BackendClient(env);
  const authEnabled = frontendAuthEnabled(env);
  let draft: EditableConfig;

  try {
    draft = await parseConfigForm(request);
  } catch (error) {
    return htmlResponse(renderErrorPage('Invalid form data', errorMessage(error), authEnabled), 400);
  }

  try {
    const response = mode === 'validate'
      ? await client.validateConfig(draft)
      : await client.saveConfig(draft);
    return htmlResponse(renderConfigPage({
      response,
      config: response.config,
      flash: {
        kind: 'success',
        message: mode === 'validate' ? 'Configuration is valid.' : 'Configuration saved to KV.',
      },
      authEnabled,
    }));
  } catch (error) {
    return htmlResponse(renderConfigPage({
      config: draft,
      flash: {
        kind: 'error',
        message: errorMessage(error),
      },
      authEnabled,
    }), 400);
  }
}

async function handleRunGet(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const date = url.searchParams.get('date') || todayUtc();
  return htmlResponse(renderRunPage({
    defaultDate: VALID_DATE.test(date) ? date : todayUtc(),
    authEnabled: frontendAuthEnabled(env),
  }));
}

async function handleRunPost(request: Request, env: Env): Promise<Response> {
  const form = await request.formData();
  const date = String(form.get('date') || '').trim();
  const sync = form.get('sync') === 'true';
  const client = new BackendClient(env);

  try {
    const response = await client.run({
      date: VALID_DATE.test(date) ? date : undefined,
      sync,
    });
    return htmlResponse(renderRunPage({
      defaultDate: VALID_DATE.test(date) ? date : todayUtc(),
      response,
      flash: {
        kind: 'success',
        message: response.queued ? 'Run was queued.' : 'Run completed.',
      },
      authEnabled: frontendAuthEnabled(env),
    }), response.queued ? 202 : 200);
  } catch (error) {
    return htmlResponse(renderRunPage({
      defaultDate: VALID_DATE.test(date) ? date : todayUtc(),
      flash: {
        kind: 'error',
        message: errorMessage(error),
      },
      authEnabled: frontendAuthEnabled(env),
    }), 502);
  }
}

async function handleStatus(env: Env): Promise<Response> {
  const client = new BackendClient(env);
  const errors: string[] = [];
  const authEnabled = frontendAuthEnabled(env);
  let health;
  let config;

  try {
    health = await client.health();
  } catch (error) {
    errors.push(`Health check failed: ${errorMessage(error)}`);
  }

  try {
    config = await client.config();
  } catch (error) {
    errors.push(`Config read failed: ${errorMessage(error)}`);
  }

  return htmlResponse(renderStatusPage({
    health,
    config,
    backendBaseUrl: env.BACKEND_BASE_URL,
    errors,
    authEnabled,
  }), errors.length > 0 ? 502 : 200);
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
  const { filters, results } = await loadFilteredResults(request, client);

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
    error: 'Method not allowed',
  }, { status: 405 });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204 });
    }

    if (url.pathname === '/login') {
      if (request.method === 'GET') {
        if (await isAuthenticated(request, env)) {
          return Response.redirect(new URL('/', request.url), 303);
        }
        return htmlResponse(renderLoginPage());
      }
      if (request.method === 'POST') {
        return loginResponse(request, env);
      }
      return methodNotAllowed();
    }

    if (url.pathname === '/logout') {
      if (request.method !== 'POST') {
        return methodNotAllowed();
      }
      return redirectWithCookie('/login', request, clearSessionCookie());
    }

    if (!(await isAuthenticated(request, env))) {
      return requireLoginRedirect(request);
    }

    try {
      if (url.pathname === '/') {
        if (request.method !== 'GET') {
          return methodNotAllowed();
        }
        return handleDashboard(request, env);
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
        return handleStatus(env);
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
        'Not found',
        `No frontend route exists for ${escapeHtml(url.pathname)}.`,
        frontendAuthEnabled(env),
      ), 404);
    } catch (error) {
      return htmlResponse(renderErrorPage(
        'Unexpected error',
        errorMessage(error),
        frontendAuthEnabled(env),
      ), 500);
    }
  },
};
