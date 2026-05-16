import { DomainRule, PaperSource } from './models';

/*
 * 这个文件负责“把外部配置变成程序能安全使用的 Config 对象”。
 *
 * 原来的 Node.js 版本通常会从本地 config.json 读取配置；现在不再使用外部 config.json 文件。
 * Cloudflare Workers 没有稳定的本地文件系统，所以这里改成主要从 env 读取。
 *
 * env 可以来自：
 * 1. wrangler.toml 里的 [vars]
 * 2. 本地调试用的 backend/script/config/.dev.vars（由 backend/script/deploy.sh 根据 shell 环境变量生成）
 * 3. Cloudflare Dashboard / wrangler secret put 设置的密钥
 */

const RELEVANCE_LEVELS = ['IRRELEVANT', 'LOW', 'MEDIUM', 'HIGH'] as const;
const LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR'] as const;
const DOMAIN_MODES = ['accept_all', 'categories_filter'] as const;
const SOURCE_TYPES = ['arxiv', 'custom'] as const;

// 这里用 typeof ...[number] 从数组里自动推导联合类型。
// 例如 RelevanceLevel 等价于 'IRRELEVANT' | 'LOW' | 'MEDIUM' | 'HIGH'。
type RelevanceLevel = typeof RELEVANCE_LEVELS[number];
type LogLevel = typeof LOG_LEVELS[number];

// ConfigData 是程序内部真正想要的配置形状。
// 它比 WorkerConfigEnv 更“干净”：数组已经是数组，数字已经是 number，不再是字符串。
export interface ConfigData {
  keywords: string[];
  sources: PaperSource[];
  domain_rules: DomainRule[];
  relevance_threshold: RelevanceLevel;
  openai_api_key: string;
  openai_model: string;
  openai_base_url?: string;
  max_results_per_category?: number;
  max_concurrent_requests?: number;
  output_dir?: string;
  prompts_dir?: string;
  log_level?: LogLevel;
  history_file?: string;
  prompt_system?: string;
  prompt_user_template?: string;
}

// Cloudflare Workers 传进来的 env 里的变量通常是字符串。
// 比如 MAX_RESULTS_PER_CATEGORY 在 wrangler.toml 中写成 "5"，这里先按 string 接收，
// 后面 parseRawConfig / optionalNumber 会把它转成 number。
export interface WorkerConfigEnv {
  KEYWORDS?: string;
  SOURCES?: string;
  DOMAIN_RULES?: string;
  RELEVANCE_THRESHOLD?: string;
  OPENAI_API_KEY?: string;
  OPENAI_MODEL?: string;
  OPENAI_BASE_URL?: string;
  MAX_RESULTS_PER_CATEGORY?: string;
  MAX_CONCURRENT_REQUESTS?: string;
  OUTPUT_DIR?: string;
  PROMPTS_DIR?: string;
  LOG_LEVEL?: string;
  HISTORY_FILE?: string;
  PROMPT_SYSTEM?: string;
  PROMPT_USER_TEMPLATE?: string;
}

type RawConfig = Record<string, unknown>;

// Config 是一个经过解析和校验后的配置对象。
// 业务代码只依赖这个类，不需要关心配置到底来自 KV、环境变量还是 secret。
export class Config {
  keywords: string[];
  sources: PaperSource[];
  domain_rules: DomainRule[];
  relevance_threshold: RelevanceLevel;
  openai_api_key: string;
  openai_model: string;
  openai_base_url: string;
  max_results_per_category: number;
  max_concurrent_requests: number;
  output_dir: string;
  prompts_dir: string;
  log_level: LogLevel;
  history_file: string;
  processed_ids: string[];
  prompt_system?: string;
  prompt_user_template?: string;

  constructor(data: ConfigData) {
    this.keywords = data.keywords;
    this.sources = data.sources;
    this.domain_rules = data.domain_rules;
    this.relevance_threshold = data.relevance_threshold;
    this.openai_api_key = data.openai_api_key;
    this.openai_model = data.openai_model;
    this.openai_base_url = data.openai_base_url || 'https://api.openai.com/v1';
    this.max_results_per_category = data.max_results_per_category || 50;
    this.max_concurrent_requests = data.max_concurrent_requests || 5;
    this.output_dir = data.output_dir || 'output';
    this.prompts_dir = data.prompts_dir || 'prompts';
    this.log_level = data.log_level || 'INFO';
    this.history_file = data.history_file || 'history.json';
    this.processed_ids = [];
    this.prompt_system = data.prompt_system;
    this.prompt_user_template = data.prompt_user_template;
  }

  // 从普通 JS 对象创建配置，适合 KV/API 读取后的配置对象。
  static fromObject(raw: RawConfig): Config {
    const parsed = this.parseRawConfig(raw);
    const cfg = new Config(parsed);
    this.validate(cfg);
    return cfg;
  }

  static fromEnv(env: WorkerConfigEnv): Config {
    const merged: RawConfig = {
      keywords: this.envList(env.KEYWORDS, undefined),
      sources: this.envJson(env.SOURCES, undefined),
      domain_rules: this.envJson(env.DOMAIN_RULES, undefined),
      relevance_threshold: env.RELEVANCE_THRESHOLD,
      openai_api_key: env.OPENAI_API_KEY,
      openai_model: env.OPENAI_MODEL,
      openai_base_url: env.OPENAI_BASE_URL,
      max_results_per_category: this.envNumber(
        env.MAX_RESULTS_PER_CATEGORY,
        undefined,
      ),
      max_concurrent_requests: this.envNumber(
        env.MAX_CONCURRENT_REQUESTS,
        undefined,
      ),
      output_dir: env.OUTPUT_DIR,
      prompts_dir: env.PROMPTS_DIR,
      log_level: env.LOG_LEVEL,
      history_file: env.HISTORY_FILE,
      prompt_system: env.PROMPT_SYSTEM,
      prompt_user_template: env.PROMPT_USER_TEMPLATE,
    };

    return this.fromObject(merged);
  }

  // 给 /config 调试接口使用。API Key 属于敏感信息，返回时只显示 ***。
  toSafeJSON(): Omit<Config, 'openai_api_key'> & { openai_api_key: string } {
    return {
      ...this,
      openai_api_key: this.openai_api_key ? '***' : '',
    };
  }

  // 把来源不确定的 raw 配置规整成 ConfigData。
  // unknown 表示“我现在还不知道它是什么类型”，所以这里会逐项转换。
  private static parseRawConfig(raw: RawConfig): ConfigData {
    const sources = this.parseSources(raw.sources);
    const domainRules = this.parseDomainRules(raw.domain_rules);
    const threshold = String(raw.relevance_threshold || 'MEDIUM').toUpperCase();
    const logLevel = String(raw.log_level || 'INFO').toUpperCase();

    return {
      keywords: this.asStringArray(raw.keywords),
      sources,
      domain_rules: domainRules,
      relevance_threshold: threshold as RelevanceLevel,
      openai_api_key: String(raw.openai_api_key || ''),
      openai_model: String(raw.openai_model || ''),
      openai_base_url: this.optionalString(raw.openai_base_url),
      max_results_per_category: this.optionalNumber(raw.max_results_per_category),
      max_concurrent_requests: this.optionalNumber(raw.max_concurrent_requests),
      output_dir: this.optionalString(raw.output_dir),
      prompts_dir: this.optionalString(raw.prompts_dir),
      log_level: logLevel as LogLevel,
      history_file: this.optionalString(raw.history_file),
      prompt_system: this.optionalString(raw.prompt_system),
      prompt_user_template: this.optionalString(raw.prompt_user_template),
    };
  }

  private static defaultSources(): PaperSource[] {
    return [{
      id: 'arxiv',
      type: 'arxiv',
      name: 'arXiv',
      enabled: true,
    }];
  }

  private static parseSources(value: unknown): PaperSource[] {
    const sourceData = Array.isArray(value) ? value : [];
    if (sourceData.length === 0) {
      return this.defaultSources();
    }

    const sources = sourceData
      .map(item => {
        const record = item as Record<string, unknown>;
        const type = String(record.type || 'custom').trim().toLowerCase();
        const id = String(record.id || type || '').trim();
        const name = String(record.name || id || type).trim();
        return {
          id,
          type: type as PaperSource['type'],
          name,
          enabled: record.enabled !== false && record.enabled !== 'false',
        };
      })
      .filter(source => source.id);

    return sources.length > 0 ? sources : this.defaultSources();
  }

  // 解析 domain_rules。这个配置决定每个来源要抓哪些领域分类，以及是否使用交叉分类过滤。
  private static parseDomainRules(value: unknown): DomainRule[] {
    const rulesData = Array.isArray(value) ? value : [];

    return rulesData.map((item) => {
      const record = item as Record<string, unknown>;
      return {
        source: String(record.source || record.source_id || 'arxiv').trim() || 'arxiv',
        category: String(record.category || ''),
        mode: record.mode as DomainRule['mode'],
        filter_categories: this.asStringArray(record.filter_categories),
      };
    });
  }

  // 集中做配置校验。尽早失败比运行到一半才失败更容易排查。
  private static validate(cfg: Config): void {
    const errors: string[] = [];

    if (!Array.isArray(cfg.keywords) || cfg.keywords.length === 0) {
      errors.push('重点关注关键词(keywords): 必填，且至少包含 1 项');
    } else {
      cfg.keywords.forEach((keyword, index) => {
        if (typeof keyword !== 'string' || !keyword.trim()) {
          errors.push(`重点关注关键词 keywords[${index}]: 必须为非空字符串`);
        }
      });
    }

    const sourceIds = new Set<string>();
    if (!Array.isArray(cfg.sources) || cfg.sources.length === 0) {
      errors.push('sources: 必填，且至少包含 1 个来源');
    } else {
      cfg.sources.forEach((source, index) => {
        if (typeof source.id !== 'string' || !source.id.trim()) {
          errors.push(`sources[${index}].id: 必须为非空字符串`);
        } else if (!/^[a-zA-Z0-9._-]+$/.test(source.id)) {
          errors.push(`sources[${index}].id: 只能包含字母、数字、点、下划线和连字符`);
        } else if (sourceIds.has(source.id)) {
          errors.push(`sources[${index}].id: 来源标识重复 (${source.id})`);
        } else {
          sourceIds.add(source.id);
        }

        if (!SOURCE_TYPES.includes(source.type)) {
          errors.push(
            `sources[${index}].type: 必须为 ${SOURCE_TYPES.join(', ')} 之一，当前值: ${source.type}`,
          );
        }

        if (typeof source.name !== 'string' || !source.name.trim()) {
          errors.push(`sources[${index}].name: 必须为非空字符串`);
        }
      });

      if (!cfg.sources.some(source => source.enabled)) {
        errors.push('sources: 至少启用 1 个来源');
      }
    }

    if (!Array.isArray(cfg.domain_rules) || cfg.domain_rules.length === 0) {
      errors.push('domain_rules: 必填，且不能为空数组');
    } else {
      cfg.domain_rules.forEach((rule, index) => {
        if (typeof rule.source !== 'string' || !rule.source.trim()) {
          errors.push(`domain_rules[${index}].source: 必须选择来源`);
        } else if (!sourceIds.has(rule.source)) {
          errors.push(`domain_rules[${index}].source: 未注册的来源 (${rule.source})`);
        } else if (!cfg.sources.find(source => source.id === rule.source)?.enabled) {
          errors.push(`domain_rules[${index}].source: 来源已停用 (${rule.source})`);
        }

        if (typeof rule.category !== 'string' || !rule.category.trim()) {
          errors.push(`domain_rules[${index}].category: 必须为非空字符串`);
        }
        if (!DOMAIN_MODES.includes(rule.mode)) {
          errors.push(
            `domain_rules[${index}].mode: 必须为 ${DOMAIN_MODES.join(', ')} 之一，当前值: ${rule.mode}`,
          );
        }
        if (rule.mode === 'categories_filter') {
          if (!Array.isArray(rule.filter_categories) || rule.filter_categories.length === 0) {
            errors.push(
              `domain_rules[${index}].filter_categories: categories_filter 模式下至少包含 1 项`,
            );
          } else {
            rule.filter_categories.forEach((category, categoryIndex) => {
              if (typeof category !== 'string' || !category.trim()) {
                errors.push(
                  `domain_rules[${index}].filter_categories[${categoryIndex}]: 必须为非空字符串`,
                );
              }
            });
          }
        }
      });
    }

    if (!RELEVANCE_LEVELS.includes(cfg.relevance_threshold)) {
      errors.push(
        `relevance_threshold: 必须为 ${RELEVANCE_LEVELS.join(', ')} 之一，当前值: ${cfg.relevance_threshold}`,
      );
    }

    if (
      !Number.isInteger(cfg.max_results_per_category)
      || cfg.max_results_per_category < 1
      || cfg.max_results_per_category > 200
    ) {
      errors.push('max_results_per_category: 必须为 1-200 之间的整数');
    }

    if (
      !Number.isInteger(cfg.max_concurrent_requests)
      || cfg.max_concurrent_requests < 1
      || cfg.max_concurrent_requests > 500
    ) {
      errors.push('max_concurrent_requests: 必须为 1-500 之间的整数');
    }

    if (typeof cfg.openai_api_key !== 'string' || !cfg.openai_api_key.trim()) {
      errors.push('openai_api_key: 必填，且不能为空');
    }

    if (typeof cfg.openai_model !== 'string' || !cfg.openai_model.trim()) {
      errors.push('openai_model: 必填，且不能为空');
    }

    if (typeof cfg.output_dir !== 'string' || !cfg.output_dir.trim()) {
      errors.push('output_dir: 必须为非空字符串');
    }

    if (typeof cfg.prompts_dir !== 'string' || !cfg.prompts_dir.trim()) {
      errors.push('prompts_dir: 必须为非空字符串');
    }

    if (!LOG_LEVELS.includes(cfg.log_level)) {
      errors.push(`log_level: 必须为 ${LOG_LEVELS.join(', ')} 之一，当前值: ${cfg.log_level}`);
    }

    if (typeof cfg.history_file !== 'string' || !cfg.history_file.trim()) {
      errors.push('history_file: 必须为非空字符串');
    }

    if (errors.length > 0) {
      throw new Error(`配置校验失败:\n${errors.map(error => `  - ${error}`).join('\n')}`);
    }
  }

  // 把数组或逗号分隔字符串统一变成 string[]。
  // Workers env 只能方便地传字符串，所以这个函数会经常用到。
  private static asStringArray(value: unknown): string[] {
    if (Array.isArray(value)) {
      return value.map(item => String(item).trim()).filter(Boolean);
    }
    if (typeof value === 'string') {
      return value.split(',').map(item => item.trim()).filter(Boolean);
    }
    return [];
  }

  // 可选字符串：空字符串会被当作 undefined，这样构造函数可以使用默认值。
  private static optionalString(value: unknown): string | undefined {
    if (typeof value !== 'string') {
      return undefined;
    }
    const trimmed = value.trim();
    return trimmed || undefined;
  }

  // 可选数字：既支持真正的 number，也支持 env 中传来的数字字符串。
  private static optionalNumber(value: unknown): number | undefined {
    if (typeof value === 'number') {
      return Number.isFinite(value) ? value : undefined;
    }
    if (typeof value === 'string' && value.trim()) {
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : undefined;
    }
    return undefined;
  }

  // 下面三个 env* helper 的作用是表达“env 没传就用 fallback，传了就覆盖”。
  private static envList(envValue: string | undefined, fallback: unknown): unknown {
    return envValue === undefined ? fallback : envValue;
  }

  private static envJson(envValue: string | undefined, fallback: unknown): unknown {
    if (envValue === undefined) {
      return fallback;
    }
    return JSON.parse(envValue);
  }

  private static envNumber(envValue: string | undefined, fallback: unknown): unknown {
    return envValue === undefined ? fallback : envValue;
  }
}
