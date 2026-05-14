import { Config, WorkerConfigEnv } from './config';
import {
  Pipeline,
  PipelineStorage,
  SerializedAnalysisResult,
} from './pipeline';

const DEFAULT_CONFIG: Record<string, unknown> = {
  keywords: ['large language model', 'agent', 'reasoning'],
  domain_rules: [
    {
      category: 'cs.RO',
      mode: 'accept_all',
      filter_categories: [],
    },
    {
      category: 'cs.CV',
      mode: 'categories_filter',
      filter_categories: ['cs.AI', 'cs.CL', 'cs.RO', 'cs.LG'],
    },
  ],
  relevance_threshold: 'MEDIUM',
  openai_model: 'deepseek-v4-flash',
  openai_base_url: 'https://api.deepseek.com/v1',
  max_results_per_category: 5,
  max_concurrent_requests: 3,
  output_dir: 'output',
  prompts_dir: 'prompts',
  log_level: 'INFO',
  history_file: 'history.json',
};

/*
 * 这是 Cloudflare Worker 的入口文件。
 *
 * Cloudflare 会根据 export default 里的方法自动调用：
 * - fetch(): 收到 HTTP 请求时调用
 * - scheduled(): 定时任务触发时调用
 * - queue(): Queue 有消息要消费时调用
 *
 * 你可以把它理解成“Workers 版的后端控制器”。
 */

// Env 描述 Worker 能拿到的所有绑定和环境变量。
// CONFIG_KV 只存配置，PAPER_DB 负责持久化结构化分析结果和运行历史。
interface Env extends WorkerConfigEnv {
  PAPER_ANALYSIS_QUEUE?: Queue<RunMessage>;
  CONFIG_KV?: KVNamespace;
  CONFIG_KV_KEY?: string;
  PAPER_DB?: D1Database;
  ADMIN_TOKEN?: string;
}

// 放进 Cloudflare Queue 的消息格式。
// Queue 里只放“要跑一次任务”的意图，不直接放论文内容，避免消息过大。
interface RunMessage {
  type: 'run';
  targetDate?: string;
  requestedAt: string;
  source: 'manual' | 'scheduled';
}

interface StoredConfig {
  key: string;
  source: 'kv' | 'env' | 'default';
  config: Record<string, unknown>;
}

// WorkerD1Storage 是 PipelineStorage 的 Cloudflare D1 实现。
// paper_analyzer 的输出是结构化字段，适合落到 SQL 表里，之后可以按日期、score、分类等查询。
class WorkerD1Storage implements PipelineStorage {
  private schemaReady?: Promise<void>;

  constructor(private db?: D1Database) {}

  async loadHistory(_historyKey: string): Promise<string[]> {
    if (!this.db) {
      console.warn('未绑定 PAPER_DB D1，历史记录不会持久化');
      return [];
    }

    await this.ensureSchema();

    try {
      const result = await this.db
        .prepare('SELECT arxiv_id FROM processed_papers ORDER BY processed_at DESC')
        .all<{ arxiv_id: string }>();

      return (result.results || [])
        .map(row => row.arxiv_id)
        .filter(Boolean);
    } catch (error) {
      console.warn(`读取历史记录失败，将使用空历史: ${(error as Error).message}`);
      return [];
    }
  }

  async saveResults(
    results: SerializedAnalysisResult[],
    targetDate: string,
    config: Config,
  ): Promise<string> {
    if (!this.db) {
      console.warn('未绑定 PAPER_DB D1，分析结果不会持久化');
      return `memory://${config.output_dir}/analysis_results_${targetDate}.json`;
    }

    await this.ensureSchema();

    const savedAt = new Date().toISOString();
    for (const result of results) {
      await this.db.prepare(`
        INSERT INTO analysis_results (
          target_date,
          arxiv_id,
          title,
          abstract,
          authors_json,
          categories_json,
          pdf_url,
          published,
          score,
          reason,
          core_methods,
          problem,
          keywords_json,
          created_at,
          updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(target_date, arxiv_id) DO UPDATE SET
          title = excluded.title,
          abstract = excluded.abstract,
          authors_json = excluded.authors_json,
          categories_json = excluded.categories_json,
          pdf_url = excluded.pdf_url,
          published = excluded.published,
          score = excluded.score,
          reason = excluded.reason,
          core_methods = excluded.core_methods,
          problem = excluded.problem,
          keywords_json = excluded.keywords_json,
          updated_at = excluded.updated_at
      `).bind(
        targetDate,
        result.arxiv_id,
        result.title,
        result.abstract,
        JSON.stringify(result.authors),
        JSON.stringify(result.categories),
        result.pdf_url,
        result.published,
        result.score,
        result.reason,
        result.core_methods,
        result.problem,
        JSON.stringify(result.keywords),
        savedAt,
        savedAt,
      ).run();
    }

    return `d1://analysis_results?target_date=${targetDate}&count=${results.length}`;
  }

  async saveHistory(_historyKey: string, ids: string[]): Promise<void> {
    if (!this.db) {
      return;
    }

    await this.ensureSchema();

    const processedAt = new Date().toISOString();
    for (const id of ids) {
      await this.db.prepare(`
        INSERT INTO processed_papers (arxiv_id, processed_at)
        VALUES (?, ?)
        ON CONFLICT(arxiv_id) DO UPDATE SET processed_at = excluded.processed_at
      `).bind(id, processedAt).run();
    }
  }

  private async ensureSchema(): Promise<void> {
    if (!this.db) {
      return;
    }

    if (!this.schemaReady) {
      this.schemaReady = this.db.exec(`
        CREATE TABLE IF NOT EXISTS analysis_results (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          target_date TEXT NOT NULL,
          arxiv_id TEXT NOT NULL,
          title TEXT NOT NULL,
          abstract TEXT NOT NULL,
          authors_json TEXT NOT NULL,
          categories_json TEXT NOT NULL,
          pdf_url TEXT NOT NULL,
          published TEXT NOT NULL,
          score TEXT NOT NULL,
          reason TEXT NOT NULL,
          core_methods TEXT NOT NULL,
          problem TEXT NOT NULL,
          keywords_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(target_date, arxiv_id)
        );

        CREATE INDEX IF NOT EXISTS idx_analysis_results_target_date
          ON analysis_results(target_date);

        CREATE INDEX IF NOT EXISTS idx_analysis_results_score
          ON analysis_results(score);

        CREATE TABLE IF NOT EXISTS processed_papers (
          arxiv_id TEXT PRIMARY KEY,
          processed_at TEXT NOT NULL
        );
      `).then(() => undefined);
    }

    await this.schemaReady;
  }
}

// 从 CONFIG_KV 读取配置 JSON。
// OPENAI_API_KEY 仍建议作为 secret/env 注入，不建议明文放进 KV。
function getConfigKey(env: Env): string {
  return env.CONFIG_KV_KEY || 'paper-sniffer/config';
}

function parseConfigJson(json: string): Record<string, unknown> {
  const parsed = JSON.parse(json) as unknown;
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('配置必须是 JSON 对象');
  }
  return parsed as Record<string, unknown>;
}

function envConfigObject(env: Env): Record<string, unknown> {
  const config: Record<string, unknown> = {};

  if (env.KEYWORDS !== undefined) {
    config.keywords = env.KEYWORDS;
  }
  if (env.DOMAIN_RULES !== undefined) {
    config.domain_rules = JSON.parse(env.DOMAIN_RULES) as unknown;
  }
  if (env.RELEVANCE_THRESHOLD !== undefined) {
    config.relevance_threshold = env.RELEVANCE_THRESHOLD;
  }
  if (env.OPENAI_MODEL !== undefined) {
    config.openai_model = env.OPENAI_MODEL;
  }
  if (env.OPENAI_BASE_URL !== undefined) {
    config.openai_base_url = env.OPENAI_BASE_URL;
  }
  if (env.MAX_RESULTS_PER_CATEGORY !== undefined) {
    config.max_results_per_category = env.MAX_RESULTS_PER_CATEGORY;
  }
  if (env.MAX_CONCURRENT_REQUESTS !== undefined) {
    config.max_concurrent_requests = env.MAX_CONCURRENT_REQUESTS;
  }
  if (env.OUTPUT_DIR !== undefined) {
    config.output_dir = env.OUTPUT_DIR;
  }
  if (env.PROMPTS_DIR !== undefined) {
    config.prompts_dir = env.PROMPTS_DIR;
  }
  if (env.LOG_LEVEL !== undefined) {
    config.log_level = env.LOG_LEVEL;
  }
  if (env.HISTORY_FILE !== undefined) {
    config.history_file = env.HISTORY_FILE;
  }
  if (env.PROMPT_SYSTEM !== undefined) {
    config.prompt_system = env.PROMPT_SYSTEM;
  }
  if (env.PROMPT_USER_TEMPLATE !== undefined) {
    config.prompt_user_template = env.PROMPT_USER_TEMPLATE;
  }

  return config;
}

function publicConfig(config: Record<string, unknown>): Record<string, unknown> {
  const sanitized = { ...config };
  delete sanitized.openai_api_key;
  delete sanitized.processed_ids;
  return sanitized;
}

function normalizeConfigForStorage(rawConfig: unknown): Record<string, unknown> {
  if (!rawConfig || typeof rawConfig !== 'object' || Array.isArray(rawConfig)) {
    throw new Error('配置必须是 JSON 对象');
  }

  const config = publicConfig(rawConfig as Record<string, unknown>);
  Config.fromObject({
    ...config,
    openai_api_key: 'config-api-validation-placeholder',
  });

  return config;
}

async function readStoredConfig(env: Env): Promise<StoredConfig> {
  const key = getConfigKey(env);

  if (env.CONFIG_KV) {
    const storedConfig = await env.CONFIG_KV.get(key);
    if (storedConfig) {
      return {
        key,
        source: 'kv',
        config: publicConfig(parseConfigJson(storedConfig)),
      };
    }

    console.warn(`CONFIG_KV 中没有找到配置: ${key}`);
  } else {
    console.warn('未绑定 CONFIG_KV，将尝试从 env 读取配置');
  }

  const envConfig = envConfigObject(env);
  return {
    key,
    source: Object.keys(envConfig).length > 0 ? 'env' : 'default',
    config: publicConfig({
      ...DEFAULT_CONFIG,
      ...envConfig,
    }),
  };
}

function configFromStoredConfig(env: Env, storedConfig: StoredConfig): Config {
  if (storedConfig.source === 'kv') {
    return Config.fromObject({
      ...storedConfig.config,
      openai_api_key: env.OPENAI_API_KEY,
    });
  }

  return Config.fromObject({
    ...storedConfig.config,
    openai_api_key: env.OPENAI_API_KEY,
  });
}

async function loadConfig(env: Env): Promise<Config> {
  const storedConfig = await readStoredConfig(env);
  return configFromStoredConfig(env, storedConfig);

}

// 真正执行一次完整任务：
// 1. 从 CONFIG_KV/env 构造 Config；
// 2. 创建 D1 存储；
// 3. 读取历史记录；
// 4. 启动 Pipeline。
async function runPipeline(env: Env, targetDate?: Date) {
  const config = await loadConfig(env);
  const storage = new WorkerD1Storage(env.PAPER_DB);
  config.processed_ids = await storage.loadHistory(config.history_file);

  const pipeline = new Pipeline(config, storage);
  return await pipeline.run(targetDate);
}

// 尝试把任务发到 Queue。
// 返回 false 表示没有绑定 Queue，此时调用方会直接同步执行。
async function enqueueRun(env: Env, message: RunMessage): Promise<boolean> {
  if (!env.PAPER_ANALYSIS_QUEUE) {
    return false;
  }

  await env.PAPER_ANALYSIS_QUEUE.send(message);
  return true;
}

// 把 URL 或 JSON body 中的 date 字符串转成 Date。
// 为了避免歧义，只接受 YYYY-MM-DD。
function parseTargetDate(value: string | null | undefined): Date | undefined {
  if (!value) {
    return undefined;
  }

  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw new Error('date 必须使用 YYYY-MM-DD 格式');
  }

  const date = new Date(`${value}T00:00:00.000Z`);
  if (Number.isNaN(date.getTime())) {
    throw new Error(`无效日期: ${value}`);
  }
  return date;
}

// 只解析 JSON 请求体；/run 只允许管理员 POST 手动调试。
async function parseRequestBody(request: Request): Promise<Record<string, unknown>> {
  if (request.method === 'GET' || request.method === 'HEAD') {
    return {};
  }

  const contentType = request.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) {
    return {};
  }

  return await request.json() as Record<string, unknown>;
}

// 统一返回 JSON Response，并顺手加上 CORS 头，方便浏览器或前端页面直接调试。
function jsonResponse(data: unknown, init: ResponseInit = {}): Response {
  const headers = new Headers(init.headers);
  headers.set('content-type', 'application/json; charset=utf-8');
  headers.set('access-control-allow-origin', '*');
  headers.set('access-control-allow-methods', 'GET,POST,PUT,OPTIONS');
  headers.set('access-control-allow-headers', 'content-type, authorization, x-admin-token');

  return new Response(JSON.stringify(data, null, 2), {
    ...init,
    headers,
  });
}

// Queue 消息里只需要保存 YYYY-MM-DD，不需要保存完整 Date 对象。
function getAdminToken(request: Request): string {
  const authorization = request.headers.get('authorization') || '';
  if (authorization.toLowerCase().startsWith('bearer ')) {
    return authorization.slice(7).trim();
  }
  return request.headers.get('x-admin-token') || '';
}

function assertAdmin(request: Request, env: Env): Response | undefined {
  if (!env.ADMIN_TOKEN) {
    return jsonResponse(
      {
        ok: false,
        error: 'ADMIN_TOKEN 未配置，管理接口已禁用',
      },
      { status: 503 },
    );
  }

  if (getAdminToken(request) !== env.ADMIN_TOKEN) {
    return jsonResponse(
      {
        ok: false,
        error: '未授权',
      },
      { status: 401 },
    );
  }

  return undefined;
}

function configResponseBody(storedConfig: StoredConfig, effectiveConfig: Config) {
  return {
    ok: true,
    key: storedConfig.key,
    source: storedConfig.source,
    config: storedConfig.config,
    effective_config: effectiveConfig.toSafeJSON(),
  };
}

async function handleConfigApiRequest(request: Request, env: Env): Promise<Response> {
  const unauthorized = assertAdmin(request, env);
  if (unauthorized) {
    return unauthorized;
  }

  if (request.method === 'GET') {
    const storedConfig = await readStoredConfig(env);
    return jsonResponse(configResponseBody(storedConfig, await loadConfig(env)));
  }

  if (request.method === 'PUT') {
    if (!env.CONFIG_KV) {
      return jsonResponse(
        {
          ok: false,
          error: 'CONFIG_KV 未绑定，无法保存配置',
        },
        { status: 503 },
      );
    }

    const config = normalizeConfigForStorage(await request.json());
    const configJson = JSON.stringify(config, null, 2);
    const key = getConfigKey(env);
    await env.CONFIG_KV.put(key, configJson);

    const storedConfig: StoredConfig = {
      key,
      source: 'kv',
      config,
    };
    const effectiveConfig = configFromStoredConfig(env, storedConfig);

    return jsonResponse(configResponseBody(storedConfig, effectiveConfig));
  }

  return jsonResponse(
    {
      ok: false,
      error: 'Method not allowed',
    },
    { status: 405 },
  );
}

async function handleConfigValidateRequest(request: Request, env: Env): Promise<Response> {
  const unauthorized = assertAdmin(request, env);
  if (unauthorized) {
    return unauthorized;
  }

  if (request.method !== 'POST') {
    return jsonResponse(
      {
        ok: false,
        error: 'Method not allowed',
      },
      { status: 405 },
    );
  }

  const config = normalizeConfigForStorage(await request.json());
  const effectiveConfig = Config.fromObject({
    ...config,
    openai_api_key: env.OPENAI_API_KEY || 'config-api-validation-placeholder',
  });

  return jsonResponse({
    ok: true,
    config,
    effective_config: effectiveConfig.toSafeJSON(),
  });
}

function formatDate(date?: Date): string | undefined {
  if (!date) {
    return undefined;
  }

  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, '0');
  const day = String(date.getUTCDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

// /run 是管理员手动调试入口，不是后台任务的常规启动方式。
// 线上常规执行由 scheduled() 通过 Cron Trigger 自动启动。
async function handleRunRequest(request: Request, env: Env): Promise<Response> {
  const unauthorized = assertAdmin(request, env);
  if (unauthorized) {
    return unauthorized;
  }

  if (request.method !== 'POST') {
    return jsonResponse(
      {
        ok: false,
        error: 'Method not allowed',
      },
      { status: 405 },
    );
  }

  const url = new URL(request.url);
  const body = await parseRequestBody(request);
  const bodyDate = typeof body.date === 'string'
    ? body.date
    : typeof body.targetDate === 'string'
      ? body.targetDate
      : undefined;
  const targetDate = parseTargetDate(url.searchParams.get('date') || bodyDate);
  const sync = url.searchParams.get('sync') === 'true' || body.sync === true;

  if (!sync) {
    const queued = await enqueueRun(env, {
      type: 'run',
      targetDate: formatDate(targetDate),
      requestedAt: new Date().toISOString(),
      source: 'manual',
    });

    if (queued) {
      return jsonResponse(
        {
          ok: true,
          queued: true,
          mode: 'manual',
          targetDate: formatDate(targetDate) || 'auto',
        },
        { status: 202 },
      );
    }
  }

  // 没有 Queue 或 sync=true 时，直接在当前 HTTP 请求里跑完整流程。
  const result = await runPipeline(env, targetDate);
  return jsonResponse({ ok: true, queued: false, mode: 'manual', result });
}

export default {
  // HTTP 入口。
  // 常用路由：
  // - GET /health: 检查服务是否活着
  // - GET /config: 查看脱敏后的配置
  // - POST /run: 管理员手动调试入口
  // - POST /run?sync=true: 管理员同步调试入口
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === 'OPTIONS') {
      return jsonResponse({ ok: true });
    }

    const url = new URL(request.url);

    try {
      if (url.pathname === '/health') {
        return jsonResponse({ ok: true, service: 'PaperSniffer', runtime: 'cloudflare-workers' });
      }

      if (url.pathname === '/api/config') {
        return await handleConfigApiRequest(request, env);
      }

      if (url.pathname === '/api/config/validate') {
        return await handleConfigValidateRequest(request, env);
      }

      if (url.pathname === '/config') {
        return jsonResponse((await loadConfig(env)).toSafeJSON());
      }

      if (url.pathname === '/run') {
        return await handleRunRequest(request, env);
      }

      return jsonResponse(
        {
          ok: false,
          message: 'Not found',
          routes: [
            'GET /health',
            'GET /config',
            'GET /api/config',
            'PUT /api/config',
            'POST /api/config/validate',
            'POST /run (admin manual only)',
            'POST /run?sync=true (admin manual only)',
          ],
        },
        { status: 404 },
      );
    } catch (error) {
      console.error((error as Error).stack || String(error));
      return jsonResponse(
        {
          ok: false,
          error: (error as Error).message,
        },
        { status: 500 },
      );
    }
  },

  // Cron 定时入口。
  // wrangler.toml 里的 [triggers].crons 会决定它什么时候触发。
  async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    const message: RunMessage = {
      type: 'run',
      requestedAt: new Date().toISOString(),
      source: 'scheduled',
    };

    console.info(`Scheduled run triggered by cron: ${controller.cron}`);

    // waitUntil 告诉 Workers：即使 scheduled 函数返回了，也继续等待这个异步任务完成。
    ctx.waitUntil(
      enqueueRun(env, message).then(async queued => {
        if (queued) {
          console.info('Scheduled run enqueued');
          return;
        }

        console.warn('PAPER_ANALYSIS_QUEUE 未绑定，scheduled 将直接执行 Pipeline');
        await runPipeline(env);
      }),
    );
  },

  // Queue 消费入口。
  // 每条消息触发一次 Pipeline；成功 ack，失败 retry。
  async queue(batch: MessageBatch<RunMessage>, env: Env): Promise<void> {
    for (const message of batch.messages) {
      try {
        const targetDate = parseTargetDate(message.body.targetDate);
        await runPipeline(env, targetDate);
        message.ack();
      } catch (error) {
        console.error(`Queue message failed: ${(error as Error).message}`);
        message.retry({ delaySeconds: 60 });
      }
    }
  },
};
