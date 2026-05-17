import { Config, WorkerConfigEnv } from './config';
import { installStructuredConsoleLogger } from './logger';
import {
  Pipeline,
  PipelineLogLevel,
  PipelineProgressSink,
  PipelineProgressUpdate,
  PipelineStorage,
  PipelineRunStatus,
  SerializedAnalysisResult,
  type AnalysisResultRecord,
  type AnalysisResultsQuery,
} from './pipeline';
import type { Paper } from './models';

installStructuredConsoleLogger();

const BEIJING_TIME_OFFSET_MS = 8 * 60 * 60 * 1000;
const SNIFF_PROGRESS_PERCENT = 10;

function analysisProgressPercent(processed: number, total: number): number {
  if (total <= 0) {
    return 100;
  }
  return SNIFF_PROGRESS_PERCENT + (processed / total) * (100 - SNIFF_PROGRESS_PERCENT);
}

const DEFAULT_CONFIG: Record<string, unknown> = {
  keywords: ['large language model', 'agent', 'reasoning'],
  sources: [
    {
      id: 'arxiv',
      type: 'arxiv',
      name: 'arXiv',
      enabled: true,
    },
  ],
  domain_rules: [
    {
      source: 'arxiv',
      category: 'cs.RO',
      mode: 'accept_all',
      filter_categories: [],
    },
    {
      source: 'arxiv',
      category: 'cs.CV',
      mode: 'categories_filter',
      filter_categories: ['cs.AI', 'cs.CL', 'cs.RO', 'cs.LG'],
    },
  ],
  relevance_threshold: 'MEDIUM',
  openai_model: 'deepseek-v4-flash',
  openai_base_url: 'https://api.deepseek.com/v1',
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
  phase?: 'sniff' | 'analyze';
  runId?: string;
  targetDate?: string;
  requestedAt: string;
  source: 'manual' | 'scheduled';
}

interface StoredConfig {
  key: string;
  source: 'kv' | 'env' | 'default';
  config: Record<string, unknown>;
}

interface AnalysisResultsDbRow {
  id: number;
  target_date: string;
  paper_id: string;
  title: string;
  abstract: string;
  authors_json: string;
  categories_json: string;
  paper_url: string;
  published: string;
  score: string;
  reason: string;
  core_methods: string;
  problem: string;
  keywords_json: string;
  created_at: string;
  updated_at: string;
}

interface PipelineRunLogEntry {
  at: string;
  level: PipelineLogLevel;
  message: string;
  progress: number;
  step: string;
}

interface PipelineRunRecord {
  run_id: string;
  target_date: string;
  status: PipelineRunStatus;
  progress: number;
  current_step: string;
  logs: PipelineRunLogEntry[];
  total_fetched: number;
  total_analyzed: number;
  error?: string;
  created_at: string;
  updated_at: string;
  completed_at?: string;
}

interface PipelineRunDbRow {
  run_id: string;
  target_date: string;
  status: string;
  progress: number;
  current_step: string;
  logs_json: string;
  total_fetched: number;
  total_analyzed: number;
  error: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

function parseJsonStringArray(json: string): string[] {
  try {
    const value = JSON.parse(json) as unknown;
    if (!Array.isArray(value)) {
      return [];
    }
    return value.filter((item): item is string => typeof item === 'string');
  } catch {
    return [];
  }
}

function mapAnalysisResultRow(row: AnalysisResultsDbRow): AnalysisResultRecord {
  return {
    record_id: row.id,
    target_date: row.target_date,
    id: row.paper_id, // 这里的 id 映射自数据库的 paper_id
    title: row.title,
    abstract: row.abstract,
    authors: parseJsonStringArray(row.authors_json),
    categories: parseJsonStringArray(row.categories_json),
    paper_url: row.paper_url,
    published: row.published,
    score: row.score,
    reason: row.reason,
    core_methods: row.core_methods,
    problem: row.problem,
    keywords: parseJsonStringArray(row.keywords_json),
    created_at: row.created_at,
    updated_at: row.updated_at,
  };
}

function parsePipelineRunLogs(json: string): PipelineRunLogEntry[] {
  try {
    const value = JSON.parse(json) as unknown;
    if (!Array.isArray(value)) {
      return [];
    }

    return value
      .map(item => item as Partial<PipelineRunLogEntry>)
      .filter(item => typeof item.message === 'string')
      .map(item => ({
        at: String(item.at || ''),
        level: item.level === 'warn' || item.level === 'error' ? item.level : 'info',
        message: String(item.message || ''),
        progress: Number.isFinite(item.progress) ? Number(item.progress) : 0,
        step: String(item.step || ''),
      }));
  } catch {
    return [];
  }
}

function mapPipelineRunRow(row: PipelineRunDbRow): PipelineRunRecord {
  return {
    run_id: row.run_id,
    target_date: row.target_date,
    status: ['queued', 'running', 'completed', 'failed'].includes(row.status)
      ? row.status as PipelineRunStatus
      : 'running',
    progress: row.progress,
    current_step: row.current_step,
    logs: parsePipelineRunLogs(row.logs_json),
    total_fetched: row.total_fetched,
    total_analyzed: row.total_analyzed,
    error: row.error || undefined,
    created_at: row.created_at,
    updated_at: row.updated_at,
    completed_at: row.completed_at || undefined,
  };
}

// WorkerD1Storage 是 PipelineStorage 的 Cloudflare D1 实现。
// paper_analyzer 的输出是结构化字段，适合落到 SQL 表里，之后可以按日期、score、分类等查询。
class WorkerD1Storage implements PipelineStorage {
  private schemaReady?: Promise<void>;
  // D1's SQLite variable limit is lower than regular SQLite builds.
  // Keep each multi-row INSERT below the limit, then submit chunks via D1 batch()
  // so Workers subrequests stay low even when a run analyzes many papers.
  private static readonly D1_SQL_VARIABLE_LIMIT = 100;
  private static readonly RESULT_INSERT_VARIABLES_PER_ROW = 15;
  private static readonly HISTORY_INSERT_VARIABLES_PER_ROW = 2;
  private static readonly RESULT_INSERT_CHUNK_SIZE = Math.floor(
    WorkerD1Storage.D1_SQL_VARIABLE_LIMIT / WorkerD1Storage.RESULT_INSERT_VARIABLES_PER_ROW,
  );
  private static readonly HISTORY_INSERT_CHUNK_SIZE = Math.floor(
    WorkerD1Storage.D1_SQL_VARIABLE_LIMIT / WorkerD1Storage.HISTORY_INSERT_VARIABLES_PER_ROW,
  );
  private static readonly BATCH_STATEMENT_CHUNK_SIZE = 25;
  private static readonly ANALYSIS_BATCH_SIZE = 5;

  constructor(private db?: D1Database) {}

  private chunkArray<T>(items: T[], size: number): T[][] {
    const chunks: T[][] = [];
    for (let i = 0; i < items.length; i += size) {
      chunks.push(items.slice(i, i + size));
    }
    return chunks;
  }

  private async runStatements(statements: D1PreparedStatement[]): Promise<void> {
    if (!this.db || statements.length === 0) {
      return;
    }

    const batches = this.chunkArray(statements, WorkerD1Storage.BATCH_STATEMENT_CHUNK_SIZE);
    for (const batch of batches) {
      await this.db.batch(batch);
    }
  }

  async loadHistory(_historyKey: string): Promise<string[]> {
    if (!this.db) {
      console.warn('未绑定 PAPER_DB D1，历史记录不会持久化');
      return [];
    }

    await this.ensureSchema();

    try {
      const result = await this.db
        .prepare('SELECT paper_id FROM processed_papers ORDER BY processed_at DESC')
        .all<{ paper_id: string }>();

      return (result.results || [])
        .map(row => row.paper_id)
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
    const chunks = this.chunkArray(results, WorkerD1Storage.RESULT_INSERT_CHUNK_SIZE);
    const statements: D1PreparedStatement[] = [];

    for (const chunk of chunks) {
      if (chunk.length === 0) {
        continue;
      }

      const placeholders = chunk
        .map(() => '(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)')
        .join(', ');

      const values = chunk.flatMap(result => [
        targetDate,
        result.id,
        result.title,
        result.abstract,
        JSON.stringify(result.authors),
        JSON.stringify(result.categories),
        result.paper_url,
        result.published,
        result.score,
        result.reason,
        result.core_methods,
        result.problem,
        JSON.stringify(result.keywords),
        savedAt,
        savedAt,
      ]);

      statements.push(this.db.prepare(`
        INSERT INTO analysis_results (
          target_date,
          paper_id,
          title,
          abstract,
          authors_json,
          categories_json,
          paper_url,
          published,
          score,
          reason,
          core_methods,
          problem,
          keywords_json,
          created_at,
          updated_at
        )
        VALUES ${placeholders}
        ON CONFLICT(target_date, paper_id) DO UPDATE SET
          title = excluded.title,
          abstract = excluded.abstract,
          authors_json = excluded.authors_json,
          categories_json = excluded.categories_json,
          paper_url = excluded.paper_url,
          published = excluded.published,
          score = excluded.score,
          reason = excluded.reason,
          core_methods = excluded.core_methods,
          problem = excluded.problem,
          keywords_json = excluded.keywords_json,
          updated_at = excluded.updated_at
      `).bind(...values));
    }

    await this.runStatements(statements);

    return `d1://analysis_results?target_date=${targetDate}&count=${results.length}`;
  }

  async listAnalysisResults(query: AnalysisResultsQuery): Promise<AnalysisResultRecord[]> {
    if (!this.db) {
      return [];
    }

    await this.ensureSchema();

    const sql = `
      SELECT id, target_date, paper_id, title, abstract, authors_json, categories_json,
             paper_url, published, score, reason, core_methods, problem, keywords_json,
             created_at, updated_at
      FROM analysis_results
      WHERE target_date = ?
      ORDER BY updated_at DESC
    `;

    const { results } = await this.db.prepare(sql).bind(query.target_date).all<AnalysisResultsDbRow>();
    return (results || []).map(mapAnalysisResultRow);
  }

  async saveHistory(_historyKey: string, ids: string[], _config: Config): Promise<void> {
    if (!this.db) {
      return;
    }

    await this.ensureSchema();

    const uniqueIds = [...new Set(ids)].filter(Boolean);
    const processedAt = new Date().toISOString();
    const chunks = this.chunkArray(uniqueIds, WorkerD1Storage.HISTORY_INSERT_CHUNK_SIZE);
    const statements: D1PreparedStatement[] = [];

    for (const chunk of chunks) {
      if (chunk.length === 0) {
        continue;
      }

      const placeholders = chunk.map(() => '(?, ?)').join(', ');
      const values = chunk.flatMap(id => [id, processedAt]);

      statements.push(this.db.prepare(`
        INSERT INTO processed_papers (paper_id, processed_at)
        VALUES ${placeholders}
        ON CONFLICT(paper_id) DO UPDATE SET processed_at = excluded.processed_at
      `).bind(...values));
    }

    await this.runStatements(statements);
  }

  async saveRunPapers(runId: string, papers: Paper[]): Promise<void> {
    if (!this.db) {
      return;
    }

    await this.ensureSchema();

    const now = new Date().toISOString();
    const statements = papers.map((paper, index) => this.db!.prepare(`
      INSERT INTO pipeline_run_papers (
        run_id,
        paper_id,
        paper_json,
        position,
        created_at,
        updated_at
      )
      VALUES (?, ?, ?, ?, ?, ?)
      ON CONFLICT(run_id, paper_id) DO UPDATE SET
        paper_json = excluded.paper_json,
        position = excluded.position,
        updated_at = excluded.updated_at
    `).bind(
      runId,
      paper.id,
      JSON.stringify(paper),
      index,
      now,
      now,
    ));

    await this.runStatements(statements);
  }

  async loadNextRunPaperBatch(
    runId: string,
    limit = WorkerD1Storage.ANALYSIS_BATCH_SIZE,
  ): Promise<Paper[]> {
    if (!this.db) {
      return [];
    }

    await this.ensureSchema();
    const { results } = await this.db.prepare(`
      SELECT paper_json
      FROM pipeline_run_papers
      WHERE run_id = ? AND analyzed_at IS NULL
      ORDER BY position ASC
      LIMIT ?
    `).bind(runId, limit).all<{ paper_json: string }>();

    return (results || [])
      .map(row => {
        try {
          return JSON.parse(row.paper_json) as Paper;
        } catch {
          return undefined;
        }
      })
      .filter((paper): paper is Paper => Boolean(paper?.id));
  }

  async getRunPaperCounts(runId: string): Promise<{ total: number; analyzed: number }> {
    if (!this.db) {
      return { total: 0, analyzed: 0 };
    }

    await this.ensureSchema();
    const row = await this.db.prepare(`
      SELECT
        COUNT(*) AS total,
        SUM(CASE WHEN analyzed_at IS NOT NULL THEN 1 ELSE 0 END) AS analyzed
      FROM pipeline_run_papers
      WHERE run_id = ?
    `).bind(runId).first<{ total: number; analyzed: number | null }>();

    return {
      total: row?.total ?? 0,
      analyzed: row?.analyzed ?? 0,
    };
  }

  async markRunPapersAnalyzed(runId: string, paperIds: string[]): Promise<void> {
    if (!this.db || paperIds.length === 0) {
      return;
    }

    await this.ensureSchema();

    const now = new Date().toISOString();
    const statements = [...new Set(paperIds)].map(paperId => this.db!.prepare(`
      UPDATE pipeline_run_papers
      SET analyzed_at = ?,
          updated_at = ?
      WHERE run_id = ? AND paper_id = ?
    `).bind(now, now, runId, paperId));

    await this.runStatements(statements);
  }

  async createPipelineRun(
    targetDate: string,
    source: RunMessage['source'],
  ): Promise<PipelineRunRecord> {
    const now = new Date().toISOString();
    const runId = crypto.randomUUID();
    const entry: PipelineRunLogEntry = {
      at: now,
      level: 'info',
      message: source === 'scheduled' ? '定时任务已创建' : '手动刷新已创建',
      progress: 0,
      step: '排队',
    };

    if (!this.db) {
      return {
        run_id: runId,
        target_date: targetDate,
        status: 'queued',
        progress: 0,
        current_step: '排队',
        logs: [entry],
        total_fetched: 0,
        total_analyzed: 0,
        created_at: now,
        updated_at: now,
      };
    }

    await this.ensureSchema();
    await this.db.prepare(`
      INSERT INTO pipeline_runs (
        run_id,
        target_date,
        status,
        progress,
        current_step,
        logs_json,
        total_fetched,
        total_analyzed,
        error,
        created_at,
        updated_at,
        completed_at
      )
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      runId,
      targetDate,
      'queued',
      0,
      '排队',
      JSON.stringify([entry]),
      0,
      0,
      null,
      now,
      now,
      null,
    ).run();

    return {
      run_id: runId,
      target_date: targetDate,
      status: 'queued',
      progress: 0,
      current_step: '排队',
      logs: [entry],
      total_fetched: 0,
      total_analyzed: 0,
      created_at: now,
      updated_at: now,
    };
  }

  async getLatestPipelineRun(targetDate: string): Promise<PipelineRunRecord | undefined> {
    if (!this.db) {
      return undefined;
    }

    await this.ensureSchema();
    const row = await this.db.prepare(`
      SELECT run_id, target_date, status, progress, current_step, logs_json,
             total_fetched, total_analyzed, error, created_at, updated_at, completed_at
      FROM pipeline_runs
      WHERE target_date = ?
      ORDER BY updated_at DESC
      LIMIT 1
    `).bind(targetDate).first<PipelineRunDbRow>();

    return row ? mapPipelineRunRow(row) : undefined;
  }

  createProgressSink(runId: string): PipelineProgressSink {
    return {
      update: update => this.updatePipelineRun(runId, update),
    };
  }

  private async updatePipelineRun(runId: string, update: PipelineProgressUpdate): Promise<void> {
    if (!this.db) {
      return;
    }

    await this.ensureSchema();
    const existing = await this.db.prepare(`
      SELECT logs_json FROM pipeline_runs WHERE run_id = ?
    `).bind(runId).first<{ logs_json: string }>();

    const now = new Date().toISOString();
    const logs = parsePipelineRunLogs(existing?.logs_json || '[]');
    logs.push({
      at: now,
      level: update.level || 'info',
      message: update.message,
      progress: update.progress,
      step: update.step,
    });
    const limitedLogs = logs.slice(-80);
    const completedAt = update.status === 'completed' || update.status === 'failed' ? now : null;

    await this.db.prepare(`
      UPDATE pipeline_runs
      SET status = ?,
          progress = ?,
          current_step = ?,
          logs_json = ?,
          total_fetched = COALESCE(?, total_fetched),
          total_analyzed = COALESCE(?, total_analyzed),
          error = ?,
          updated_at = ?,
          completed_at = COALESCE(?, completed_at)
      WHERE run_id = ?
    `).bind(
      update.status,
      Math.max(0, Math.min(100, Math.round(update.progress))),
      update.step,
      JSON.stringify(limitedLogs),
      update.totalFetched ?? null,
      update.totalAnalyzed ?? null,
      update.error ?? null,
      now,
      completedAt,
      runId,
    ).run();
  }

  private async ensureSchema(): Promise<void> {
    if (!this.db) {
      return;
    }

    if (!this.schemaReady) {
      this.schemaReady = this.createSchema().catch(error => {
        this.schemaReady = undefined;
        throw error;
      });
    }

    await this.schemaReady;
  }

  private async createSchema(): Promise<void> {
    if (!this.db) {
      return;
    }

    const statements = [
      `
        CREATE TABLE IF NOT EXISTS analysis_results (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          target_date TEXT NOT NULL,
          paper_id TEXT NOT NULL,
          title TEXT NOT NULL,
          abstract TEXT NOT NULL,
          authors_json TEXT NOT NULL,
          categories_json TEXT NOT NULL,
          paper_url TEXT NOT NULL,
          published TEXT NOT NULL,
          score TEXT NOT NULL,
          reason TEXT NOT NULL,
          core_methods TEXT NOT NULL,
          problem TEXT NOT NULL,
          keywords_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(target_date, paper_id)
        )
      `,
      `
        CREATE INDEX IF NOT EXISTS idx_analysis_results_target_date
          ON analysis_results(target_date)
      `,
      `
        CREATE INDEX IF NOT EXISTS idx_analysis_results_score
          ON analysis_results(score)
      `,
      `
        CREATE TABLE IF NOT EXISTS processed_papers (
          paper_id TEXT PRIMARY KEY,
          processed_at TEXT NOT NULL
        )
      `,
      `
        CREATE TABLE IF NOT EXISTS pipeline_runs (
          run_id TEXT PRIMARY KEY,
          target_date TEXT NOT NULL,
          status TEXT NOT NULL,
          progress INTEGER NOT NULL DEFAULT 0,
          current_step TEXT NOT NULL DEFAULT '',
          logs_json TEXT NOT NULL DEFAULT '[]',
          total_fetched INTEGER NOT NULL DEFAULT 0,
          total_analyzed INTEGER NOT NULL DEFAULT 0,
          error TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          completed_at TEXT
        )
      `,
      `
        CREATE INDEX IF NOT EXISTS idx_pipeline_runs_target_date
          ON pipeline_runs(target_date, updated_at)
      `,
      `
        CREATE TABLE IF NOT EXISTS pipeline_run_papers (
          run_id TEXT NOT NULL,
          paper_id TEXT NOT NULL,
          paper_json TEXT NOT NULL,
          position INTEGER NOT NULL,
          analyzed_at TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY (run_id, paper_id)
        )
      `,
      `
        CREATE INDEX IF NOT EXISTS idx_pipeline_run_papers_pending
          ON pipeline_run_papers(run_id, analyzed_at, position)
      `,
    ];

    for (const statement of statements) {
      await this.db.prepare(statement).run();
    }
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
  if (env.SOURCES !== undefined) {
    config.sources = JSON.parse(env.SOURCES) as unknown;
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

function workerRuntimeConfig(env: Env): Record<string, unknown> {
  const config: Record<string, unknown> = {
    max_concurrent_requests: DEFAULT_CONFIG.max_concurrent_requests,
    log_level: DEFAULT_CONFIG.log_level,
  };

  if (env.MAX_CONCURRENT_REQUESTS !== undefined) {
    config.max_concurrent_requests = env.MAX_CONCURRENT_REQUESTS;
  }
  if (env.LOG_LEVEL !== undefined) {
    config.log_level = env.LOG_LEVEL;
  }

  return config;
}

function publicConfig(config: Record<string, unknown>): Record<string, unknown> {
  const sanitized: Record<string, unknown> = {};
  for (const key of [
    'keywords',
    'sources',
    'domain_rules',
    'relevance_threshold',
    'openai_model',
    'openai_base_url',
    'output_dir',
    'prompts_dir',
    'history_file',
    'prompt_system',
    'prompt_user_template',
  ]) {
    if (config[key] !== undefined) {
      sanitized[key] = config[key];
    }
  }
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
  return Config.fromObject({
    ...storedConfig.config,
    ...workerRuntimeConfig(env),
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
async function runPipeline(env: Env, targetDate?: Date, runId?: string) {
  const config = await loadConfig(env);
  const storage = new WorkerD1Storage(env.PAPER_DB);
  config.processed_ids = await storage.loadHistory(config.history_file);

  const pipeline = new Pipeline(
    config,
    storage,
    runId ? storage.createProgressSink(runId) : undefined,
  );
  return await pipeline.run(targetDate);
}

async function createPipelineContext(env: Env, runId: string) {
  const config = await loadConfig(env);
  const storage = new WorkerD1Storage(env.PAPER_DB);
  config.processed_ids = await storage.loadHistory(config.history_file);
  const progressSink = storage.createProgressSink(runId);
  const pipeline = new Pipeline(config, storage, progressSink);
  return { config, storage, pipeline, progressSink };
}

async function runSniffStage(
  env: Env,
  targetDate: Date | undefined,
  targetDateRaw: string,
  runId: string,
  source: RunMessage['source'],
): Promise<void> {
  const { storage, pipeline, progressSink } = await createPipelineContext(env, runId);

  await progressSink.update({
    targetDate: targetDateRaw,
    status: 'running',
    progress: 2,
    step: '嗅探准备',
    message: '正在读取配置和历史记录，准备一次性嗅探论文',
  });

  await progressSink.update({
    targetDate: targetDateRaw,
    status: 'running',
    progress: 5,
    step: '嗅探论文',
    message: '正在从已启用来源一次性获取当日论文',
  });

  const papers = await pipeline.sniffPapers(targetDate);
  await storage.saveRunPapers(runId, papers);

  if (papers.length === 0) {
    await progressSink.update({
      targetDate: targetDateRaw,
      status: 'completed',
      progress: 100,
      step: '完成',
      message: '嗅探完成，没有新论文需要分析',
      totalFetched: 0,
      totalAnalyzed: 0,
    });
    return;
  }

  await progressSink.update({
    targetDate: targetDateRaw,
    status: 'running',
    progress: SNIFF_PROGRESS_PERCENT,
    step: '嗅探完成',
    message: `一次性嗅探完成，已缓存 ${papers.length} 篇论文；分析批次已进入队列`,
    totalFetched: papers.length,
    totalAnalyzed: 0,
  });

  await env.PAPER_ANALYSIS_QUEUE?.send({
    type: 'run',
    phase: 'analyze',
    runId,
    targetDate: targetDateRaw,
    requestedAt: new Date().toISOString(),
    source,
  });
}

async function runAnalyzeStage(
  env: Env,
  targetDateRaw: string,
  runId: string,
  source: RunMessage['source'],
): Promise<void> {
  const { storage, pipeline, progressSink } = await createPipelineContext(env, runId);
  const countsBefore = await storage.getRunPaperCounts(runId);
  const papers = await storage.loadNextRunPaperBatch(runId);

  if (papers.length === 0) {
    await progressSink.update({
      targetDate: targetDateRaw,
      status: 'completed',
      progress: 100,
      step: '完成',
      message: `所有队列批次已完成，累计分析 ${countsBefore.analyzed} 篇论文`,
      totalFetched: countsBefore.total,
      totalAnalyzed: countsBefore.analyzed,
    });
    return;
  }

  const batchSize = papers.length;
  await progressSink.update({
    targetDate: targetDateRaw,
    status: 'running',
    progress: analysisProgressPercent(countsBefore.analyzed, countsBefore.total),
    step: '队列批次开始',
    message: `Worker 已开始处理下一批论文，本批 ${batchSize} 篇；此前已完成 ${countsBefore.analyzed}/${countsBefore.total} 篇`,
    totalFetched: countsBefore.total,
    totalAnalyzed: countsBefore.analyzed,
  });

  const analyzedResults = await pipeline.analyzePapers(
    papers,
    async (completed, batchTotal) => {
      const cumulativeAnalyzed = countsBefore.analyzed + completed;
      await progressSink.update({
        targetDate: targetDateRaw,
        status: 'running',
        progress: analysisProgressPercent(cumulativeAnalyzed, countsBefore.total),
        step: '分析论文',
        message: `当前队列批次正在分析论文，已完成 ${completed}/${batchTotal} 篇；累计 ${cumulativeAnalyzed}/${countsBefore.total} 篇`,
        totalFetched: countsBefore.total,
        totalAnalyzed: cumulativeAnalyzed,
      });
    },
  );

  await progressSink.update({
    targetDate: targetDateRaw,
    status: 'running',
    progress: analysisProgressPercent(countsBefore.analyzed + analyzedResults.length, countsBefore.total),
    step: '保存结果',
    message: `正在保存本批次 ${analyzedResults.length} 篇论文的分析结果`,
    totalFetched: countsBefore.total,
    totalAnalyzed: countsBefore.analyzed + analyzedResults.length,
  });
  await pipeline.saveResults(analyzedResults, targetDateRaw);

  await progressSink.update({
    targetDate: targetDateRaw,
    status: 'running',
    progress: analysisProgressPercent(countsBefore.analyzed + analyzedResults.length, countsBefore.total),
    step: '更新历史',
    message: '正在标记本批次论文为已处理',
    totalFetched: countsBefore.total,
    totalAnalyzed: countsBefore.analyzed + analyzedResults.length,
  });
  await pipeline.updateHistory(papers);
  await storage.markRunPapersAnalyzed(runId, papers.map(paper => paper.id));

  const countsAfter = await storage.getRunPaperCounts(runId);
  const hasRemaining = countsAfter.analyzed < countsAfter.total;

  if (hasRemaining) {
    await env.PAPER_ANALYSIS_QUEUE?.send({
      type: 'run',
      phase: 'analyze',
      runId,
      targetDate: targetDateRaw,
      requestedAt: new Date().toISOString(),
      source,
    });

    await progressSink.update({
      targetDate: targetDateRaw,
      status: 'running',
      progress: analysisProgressPercent(countsAfter.analyzed, countsAfter.total),
      step: '等待下一批',
      message: `本批次完成 ${analyzedResults.length} 篇，累计完成 ${countsAfter.analyzed}/${countsAfter.total} 篇；下一批已进入队列`,
      totalFetched: countsAfter.total,
      totalAnalyzed: countsAfter.analyzed,
    });
    return;
  }

  await progressSink.update({
    targetDate: targetDateRaw,
    status: 'completed',
    progress: 100,
    step: '完成',
    message: `所有队列批次已完成，累计分析 ${countsAfter.analyzed} 篇论文`,
    totalFetched: countsAfter.total,
    totalAnalyzed: countsAfter.analyzed,
  });
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
  headers.set('access-control-allow-headers', 'content-type, authorization');

  return new Response(JSON.stringify(data, null, 2), {
    ...init,
    headers,
  });
}

// Queue 消息里只需要保存 YYYY-MM-DD，不需要保存完整 Date 对象。
// 与所有受保护 HTTP 路由一致：仅接受 Authorization: Bearer <ADMIN_TOKEN>。
function getAdminToken(request: Request): string {
  const authorization = request.headers.get('authorization') || '';
  if (authorization.toLowerCase().startsWith('bearer ')) {
    return authorization.slice(7).trim();
  }
  return '';
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

function todayBeijing(): string {
  return formatDate(new Date(Date.now() + BEIJING_TIME_OFFSET_MS)) || '';
}

async function handleAnalysisResultsRequest(request: Request, env: Env): Promise<Response> {
  const unauthorized = assertAdmin(request, env);
  if (unauthorized) {
    return unauthorized;
  }

  if (request.method !== 'GET') {
    return jsonResponse(
      {
        ok: false,
        error: 'Method not allowed',
      },
      { status: 405 },
    );
  }

  const url = new URL(request.url);
  const targetDateRaw = url.searchParams.get('target_date')?.trim();
  if (!targetDateRaw) {
    return jsonResponse(
      {
        ok: false,
        error: '必须提供查询参数 target_date（YYYY-MM-DD）',
      },
      { status: 400 },
    );
  }

  try {
    parseTargetDate(targetDateRaw);
  } catch (error) {
    return jsonResponse(
      {
        ok: false,
        error: (error as Error).message,
      },
      { status: 400 },
    );
  }

  const storage = new WorkerD1Storage(env.PAPER_DB);
  const results = await storage.listAnalysisResults({ target_date: targetDateRaw });

  return jsonResponse({
    ok: true,
    results,
  });
}

async function handleRunStatusRequest(request: Request, env: Env): Promise<Response> {
  const unauthorized = assertAdmin(request, env);
  if (unauthorized) {
    return unauthorized;
  }

  if (request.method !== 'GET') {
    return jsonResponse(
      {
        ok: false,
        error: 'Method not allowed',
      },
      { status: 405 },
    );
  }

  const url = new URL(request.url);
  const targetDateRaw = url.searchParams.get('target_date')?.trim();
  if (!targetDateRaw) {
    return jsonResponse(
      {
        ok: false,
        error: '必须提供查询参数 target_date（YYYY-MM-DD）',
      },
      { status: 400 },
    );
  }

  try {
    parseTargetDate(targetDateRaw);
  } catch (error) {
    return jsonResponse(
      {
        ok: false,
        error: (error as Error).message,
      },
      { status: 400 },
    );
  }

  const storage = new WorkerD1Storage(env.PAPER_DB);
  const run = await storage.getLatestPipelineRun(targetDateRaw);

  return jsonResponse({
    ok: true,
    run: run || null,
  });
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
  const targetDateStr = formatDate(targetDate) || todayBeijing();
  const sync = url.searchParams.get('sync') === 'true' || body.sync === true;
  const storage = new WorkerD1Storage(env.PAPER_DB);
  const run = await storage.createPipelineRun(targetDateStr, 'manual');

  if (!sync) {
    try {
      const queued = await enqueueRun(env, {
        type: 'run',
        phase: 'sniff',
        runId: run.run_id,
        targetDate: targetDateStr,
        requestedAt: new Date().toISOString(),
        source: 'manual',
      });

      if (queued) {
        return jsonResponse(
          {
            ok: true,
            queued: true,
            mode: 'manual',
            targetDate: targetDateStr,
            run,
          },
          { status: 202 },
        );
      }
    } catch (error) {
      await storage.createProgressSink(run.run_id).update({
        targetDate: targetDateStr,
        status: 'failed',
        progress: 0,
        step: '入队失败',
        message: (error as Error).message,
        level: 'error',
        error: (error as Error).message,
      });
      throw error;
    }
  }

  if (!sync) {
    await storage.createProgressSink(run.run_id).update({
      targetDate: targetDateStr,
      status: 'failed',
      progress: 0,
      step: '未配置队列',
      message: 'PAPER_ANALYSIS_QUEUE 未绑定；为避免单次 Worker 请求内执行完整 Pipeline 导致 subrequests 超限，已拒绝同步执行',
      level: 'error',
      error: 'PAPER_ANALYSIS_QUEUE 未绑定',
    });

    return jsonResponse(
      {
        ok: false,
        queued: false,
        mode: 'manual',
        targetDate: targetDateStr,
        run,
        error: 'PAPER_ANALYSIS_QUEUE 未绑定。请绑定 Queue 后重试，或仅在小数据量调试时显式使用 /run?sync=true。',
      },
      { status: 503 },
    );
  }

  // sync=true 仅用于小数据量本地/临时调试；生产环境应始终通过 Queue 执行。
  const result = await runPipeline(env, parseTargetDate(targetDateStr), run.run_id);
  return jsonResponse({ ok: true, queued: false, mode: 'manual-sync-debug', result, run });
}

export default {
  // HTTP 入口。
  // 常用路由（除 OPTIONS 预检外，均需 Authorization: Bearer <ADMIN_TOKEN>）：
  // - GET /health: 检查服务是否活着
  // - GET /config: 查看脱敏后的配置
  // - GET /api/analysis-results: 分页读取 D1 analysis_results
  // - POST /run: 管理员手动调试入口
  // - POST /run?sync=true: 管理员同步调试入口
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === 'OPTIONS') {
      return jsonResponse({ ok: true });
    }

    const url = new URL(request.url);

    try {
      if (url.pathname === '/health') {
        const unauthorized = assertAdmin(request, env);
        if (unauthorized) {
          return unauthorized;
        }
        return jsonResponse({ ok: true, service: 'PaperSniffer', runtime: 'cloudflare-workers' });
      }

      if (url.pathname === '/api/config') {
        return await handleConfigApiRequest(request, env);
      }

      if (url.pathname === '/api/config/validate') {
        return await handleConfigValidateRequest(request, env);
      }

      if (url.pathname === '/config') {
        const unauthorized = assertAdmin(request, env);
        if (unauthorized) {
          return unauthorized;
        }
        return jsonResponse((await loadConfig(env)).toSafeJSON());
      }

      if (url.pathname === '/api/analysis-results') {
        return await handleAnalysisResultsRequest(request, env);
      }

      if (url.pathname === '/api/run-status') {
        return await handleRunStatusRequest(request, env);
      }

      if (url.pathname === '/run') {
        return await handleRunRequest(request, env);
      }

      return jsonResponse(
        {
          ok: false,
          message: 'Not found',
          routes: [
            'GET /health (requires ADMIN_TOKEN)',
            'GET /config (requires ADMIN_TOKEN)',
            'GET /api/analysis-results (requires ADMIN_TOKEN)',
            'GET /api/run-status (requires ADMIN_TOKEN)',
            'GET /api/config (requires ADMIN_TOKEN)',
            'PUT /api/config (requires ADMIN_TOKEN)',
            'POST /api/config/validate (requires ADMIN_TOKEN)',
            'POST /run (requires ADMIN_TOKEN)',
            'POST /run?sync=true (requires ADMIN_TOKEN)',
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
    console.info(`Scheduled run triggered by cron: ${controller.cron}`);

    // waitUntil 告诉 Workers：即使 scheduled 函数返回了，也继续等待这个异步任务完成。
    ctx.waitUntil(
      (async () => {
        const targetDate = todayBeijing();
        const storage = new WorkerD1Storage(env.PAPER_DB);
        const run = await storage.createPipelineRun(targetDate, 'scheduled');
        const message: RunMessage = {
          type: 'run',
          phase: 'sniff',
          runId: run.run_id,
          targetDate,
          requestedAt: new Date().toISOString(),
          source: 'scheduled',
        };
        const queued = await enqueueRun(env, message);
        if (queued) {
          console.info('Scheduled run enqueued');
          return;
        }

        console.error('PAPER_ANALYSIS_QUEUE 未绑定；为避免单次 scheduled invocation 内执行完整 Pipeline 导致 subrequests 超限，已跳过本次运行');
        await storage.createProgressSink(run.run_id).update({
          targetDate,
          status: 'failed',
          progress: 0,
          step: '未配置队列',
          message: 'PAPER_ANALYSIS_QUEUE 未绑定，定时任务已跳过；请绑定 Queue 后再运行',
          level: 'error',
          error: 'PAPER_ANALYSIS_QUEUE 未绑定',
        });
      })(),
    );
  },

  // Queue 消费入口。
  // 每条消息触发一次 Pipeline；成功或失败后都 ack，失败状态会写入 run status 供前端停止轮询。
  async queue(batch: MessageBatch<RunMessage>, env: Env): Promise<void> {
    for (const message of batch.messages) {
      let runId = message.body.runId;
      try {
        const targetDate = parseTargetDate(message.body.targetDate);
        const targetDateRaw = message.body.targetDate || formatDate(targetDate) || todayBeijing();
        if (!runId) {
          const storage = new WorkerD1Storage(env.PAPER_DB);
          const run = await storage.createPipelineRun(targetDateRaw, message.body.source);
          runId = run.run_id;
        }

        const phase = message.body.phase || 'sniff';
        if (phase === 'sniff') {
          await runSniffStage(env, targetDate, targetDateRaw, runId, message.body.source);
        } else {
          await runAnalyzeStage(env, targetDateRaw, runId, message.body.source);
        }

        message.ack();
      } catch (error) {
        if (runId) {
          const targetDateRaw = message.body.targetDate || todayBeijing();
          const storage = new WorkerD1Storage(env.PAPER_DB);
          const latestRun = await storage.getLatestPipelineRun(targetDateRaw).catch(() => undefined);
          await storage.createProgressSink(runId).update({
            targetDate: targetDateRaw,
            status: 'failed',
            progress: latestRun?.progress ?? 0,
            step: latestRun?.current_step || '失败',
            message: (error as Error).message,
            level: 'error',
            error: (error as Error).message,
          }).catch(() => undefined);
        }
        console.error(`Queue message failed: ${(error as Error).message}`);
        message.ack();
      }
    }
  },
};
