import * as fs from 'fs';
import * as path from 'path';
import { DomainRule } from './models';

const RELEVANCE_LEVELS = ['IRRELEVANT', 'LOW', 'MEDIUM', 'HIGH'];
const LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR'];
const DOMAIN_MODES = ['accept_all', 'categories_filter'] as const;

export interface ConfigData {
  keywords: string[];
  domain_rules: DomainRule[];
  relevance_threshold: string;
  openai_api_key: string;
  openai_model: string;
  openai_base_url?: string;
  max_results_per_category?: number;
  max_concurrent_requests?: number;
  output_dir?: string;
  prompts_dir?: string;
  log_level?: string;
  history_file?: string;
}

export class Config {
  keywords: string[];
  domain_rules: DomainRule[];
  relevance_threshold: string;
  openai_api_key: string;
  openai_model: string;
  openai_base_url: string;
  max_results_per_category: number;
  max_concurrent_requests: number;
  output_dir: string;
  prompts_dir: string;
  log_level: string;
  history_file: string;
  processed_ids: string[];

  constructor(data: ConfigData) {
    this.keywords = data.keywords;
    this.domain_rules = data.domain_rules;
    this.relevance_threshold = data.relevance_threshold;
    this.openai_api_key = data.openai_api_key;
    this.openai_model = data.openai_model;
    this.openai_base_url = data.openai_base_url || 'https://api.siliconflow.cn/v1';
    this.max_results_per_category = data.max_results_per_category || 50;
    this.max_concurrent_requests = data.max_concurrent_requests || 5;
    this.output_dir = data.output_dir || './output';
    this.prompts_dir = data.prompts_dir || './prompts';
    this.log_level = data.log_level || 'INFO';
    this.history_file = data.history_file || './output/history.json';
    this.processed_ids = [];
  }

  static fromFile(configPath: string = path.join(__dirname, '../../config.json')): Config {
    const raw = this._loadJson(configPath);
    const parsed = this._parseDomainRules(raw);
    const cfg = new Config(parsed);
    this._validate(cfg);
    this._ensureDirs(cfg);
    this._initLogging(cfg);
    cfg.processed_ids = this._loadHistory(cfg.history_file);
    return cfg;
  }

  private static _loadJson(path: string): Record<string, unknown> {
    return JSON.parse(fs.readFileSync(path, 'utf-8'));
  }

  private static _parseDomainRules(raw: Record<string, unknown>): ConfigData {
    const rulesData = (raw.domain_rules as Array<Record<string, unknown>>) || [];
    const domain_rules: DomainRule[] = [];
    
    for (const item of rulesData) {
      domain_rules.push({
        category: String(item.category),
        mode: item.mode as DomainRule['mode'],
        filter_categories: (item.filter_categories as string[]) || [],
      });
    }
    
    return {
      ...raw as Omit<ConfigData, 'domain_rules'>,
      domain_rules,
    };
  }

  private static _validate(cfg: Config): void {
    const errors: string[] = [];

    if (!Array.isArray(cfg.keywords) || cfg.keywords.length === 0) {
      errors.push('keywords: 必填且至少包含 1 项');
    } else {
      for (let i = 0; i < cfg.keywords.length; i++) {
        if (typeof cfg.keywords[i] !== 'string' || !cfg.keywords[i].trim()) {
          errors.push(`keywords[${i}]: 须为非空字符串`);
        }
      }
    }

    if (!Array.isArray(cfg.domain_rules) || cfg.domain_rules.length === 0) {
      errors.push('domain_rules: 必填且不能为空列表');
    } else {
      for (let i = 0; i < cfg.domain_rules.length; i++) {
        const rule = cfg.domain_rules[i];
        if (typeof rule.category !== 'string' || !rule.category.trim()) {
          errors.push(`domain_rules[${i}].category: 须为非空字符串`);
        }
        if (!DOMAIN_MODES.includes(rule.mode)) {
          errors.push(`domain_rules[${i}].mode: 须为 ${DOMAIN_MODES.join(', ')} 之一，当前值: ${rule.mode}`);
        }
        if (rule.mode === 'categories_filter') {
          if (!Array.isArray(rule.filter_categories) || rule.filter_categories.length === 0) {
            errors.push(`domain_rules[${i}].filter_categories: categories_filter 模式下至少包含 1 项`);
          } else {
            for (let j = 0; j < rule.filter_categories.length; j++) {
              if (typeof rule.filter_categories[j] !== 'string' || !rule.filter_categories[j].trim()) {
                errors.push(`domain_rules[${i}].filter_categories[${j}]: 须为非空字符串`);
              }
            }
          }
        }
      }
    }

    if (!RELEVANCE_LEVELS.includes(cfg.relevance_threshold)) {
      errors.push(`relevance_threshold: 须为 ${RELEVANCE_LEVELS.join(', ')} 之一，当前值: ${cfg.relevance_threshold}`);
    }

    if (!Number.isInteger(cfg.max_results_per_category) || cfg.max_results_per_category < 1 || cfg.max_results_per_category > 200) {
      errors.push('max_results_per_category: 须为整数且范围 1-200');
    }

    if (typeof cfg.openai_api_key !== 'string' || !cfg.openai_api_key.trim()) {
      errors.push('openai_api_key: 必填且不能为空');
    }

    if (typeof cfg.openai_model !== 'string' || !cfg.openai_model.trim()) {
      errors.push('openai_model: 必填且不能为空');
    }

    if (typeof cfg.output_dir !== 'string' || !cfg.output_dir.trim()) {
      errors.push('output_dir: 须为非空字符串');
    }

    if (typeof cfg.prompts_dir !== 'string' || !cfg.prompts_dir.trim()) {
      errors.push('prompts_dir: 须为非空字符串');
    }

    if (!LOG_LEVELS.includes(cfg.log_level)) {
      errors.push(`log_level: 须为 ${LOG_LEVELS.join(', ')} 之一，当前值: ${cfg.log_level}`);
    }

    if (typeof cfg.history_file !== 'string' || !cfg.history_file.trim()) {
      errors.push('history_file: 须为非空字符串');
    }

    if (errors.length > 0) {
      throw new Error('配置校验失败:\n' + errors.map(e => `  - ${e}`).join('\n'));
    }
  }

  private static _ensureDirs(cfg: Config): void {
    const dirs = [
      cfg.output_dir,
      path.join(cfg.prompts_dir, 'paper_analyzer'),
      path.join(cfg.output_dir, 'reports'),
    ];

    for (const dir of dirs) {
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
        console.log(`已创建目录: ${dir}`);
      }
    }
  }

  private static _initLogging(cfg: Config): void {
    const logPath = path.join(cfg.output_dir, 'sentinel.log');
    console.log(`日志将输出到: ${logPath}`);
  }

  private static _loadHistory(historyFile: string): string[] {
    if (!fs.existsSync(historyFile)) {
      return [];
    }

    try {
      const data = JSON.parse(fs.readFileSync(historyFile, 'utf-8'));
      if (Array.isArray(data)) {
        return data.filter(item => typeof item === 'string');
      }
      return [];
    } catch {
      return [];
    }
  }
}

if (require.main === module) {
  const cfg = Config.fromFile();
  console.log(JSON.stringify(cfg, null, 2));
}