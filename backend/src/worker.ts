import { Config, WorkerConfigEnv } from './config';
import {
  Pipeline,
  PipelineStorage,
  SerializedAnalysisResult,
} from './pipeline';

const DEFAULT_CONFIG_JSON = JSON.stringify({
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
});

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
}

// 放进 Cloudflare Queue 的消息格式。
// Queue 里只放“要跑一次任务”的意图，不直接放论文内容，避免消息过大。
interface RunMessage {
  type: 'run';
  targetDate?: string;
  requestedAt: string;
  source: 'http' | 'scheduled';
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
async function loadConfig(env: Env): Promise<Config> {
  const configKey = env.CONFIG_KV_KEY || 'paper-sniffer/config.json';
  let configJson = env.CONFIG_JSON || DEFAULT_CONFIG_JSON;

  if (env.CONFIG_KV) {
    const storedConfig = await env.CONFIG_KV.get(configKey);
    if (storedConfig) {
      configJson = storedConfig;
    } else {
      console.warn(`CONFIG_KV 中没有找到配置: ${configKey}`);
    }
  } else {
    console.warn('未绑定 CONFIG_KV，将尝试从 env/CONFIG_JSON 读取配置');
  }

  return Config.fromEnv({
    ...env,
    CONFIG_JSON: configJson,
  });
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

// HTTP POST /run 可以带 JSON body；GET /run 则没有 body。
// 这个函数统一处理两种情况，避免每个接口重复写判断。
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
  headers.set('access-control-allow-methods', 'GET,POST,OPTIONS');
  headers.set('access-control-allow-headers', 'content-type');

  return new Response(JSON.stringify(data, null, 2), {
    ...init,
    headers,
  });
}

// Queue 消息里只需要保存 YYYY-MM-DD，不需要保存完整 Date 对象。
function formatDate(date?: Date): string | undefined {
  if (!date) {
    return undefined;
  }

  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, '0');
  const day = String(date.getUTCDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

// /run 和 /queue 都走这里。
// 默认行为：如果绑定了 Queue，就把任务排队并返回 202；
// 调试时加 ?sync=true，可以让请求等待任务完成并直接返回结果。
async function handleRunRequest(request: Request, env: Env): Promise<Response> {
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
      source: 'http',
    });

    if (queued) {
      return jsonResponse(
        {
          ok: true,
          queued: true,
          targetDate: formatDate(targetDate) || 'auto',
        },
        { status: 202 },
      );
    }
  }

  // 没有 Queue 或 sync=true 时，直接在当前 HTTP 请求里跑完整流程。
  const result = await runPipeline(env, targetDate);
  return jsonResponse({ ok: true, queued: false, result });
}

export default {
  // HTTP 入口。
  // 常用路由：
  // - GET /health: 检查服务是否活着
  // - GET /config: 查看脱敏后的配置
  // - POST /run: 排队执行
  // - POST /run?sync=true: 同步执行，适合本地调试
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === 'OPTIONS') {
      return jsonResponse({ ok: true });
    }

    const url = new URL(request.url);

    try {
      if (url.pathname === '/health') {
        return jsonResponse({ ok: true, service: 'PaperSniffer', runtime: 'cloudflare-workers' });
      }

      if (url.pathname === '/config') {
        return jsonResponse((await loadConfig(env)).toSafeJSON());
      }

      if (url.pathname === '/run' || url.pathname === '/queue') {
        return await handleRunRequest(request, env);
      }

      return jsonResponse(
        {
          ok: false,
          message: 'Not found',
          routes: ['GET /health', 'GET /config', 'POST /run', 'POST /run?sync=true'],
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
  async scheduled(_controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    const message: RunMessage = {
      type: 'run',
      requestedAt: new Date().toISOString(),
      source: 'scheduled',
    };

    // waitUntil 告诉 Workers：即使 scheduled 函数返回了，也继续等待这个异步任务完成。
    ctx.waitUntil(
      enqueueRun(env, message).then(async queued => {
        if (!queued) {
          await runPipeline(env);
        }
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
