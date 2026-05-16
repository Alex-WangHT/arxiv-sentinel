export type Score = 'HIGH' | 'MEDIUM' | 'LOW' | 'IRRELEVANT';
export type ConfigSource = 'kv' | 'env' | 'default';

export type PaperSourceType = 'arxiv' | 'custom';

export interface PaperSourceConfig {
  id: string;
  type: PaperSourceType;
  name: string;
  enabled: boolean;
}

export interface DomainRule {
  source?: string;
  category: string;
  mode: 'accept_all' | 'categories_filter';
  filter_categories: string[];
}

export interface EditableConfig {
  keywords: string[];
  sources?: PaperSourceConfig[];
  domain_rules: DomainRule[];
  relevance_threshold: Score;
  openai_model: string;
  openai_base_url?: string;
  max_results_per_category?: number;
  max_concurrent_requests?: number;
  output_dir?: string;
  prompts_dir?: string;
  log_level?: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR';
  history_file?: string;
  prompt_system?: string;
  prompt_user_template?: string;
}

export interface ConfigResponse {
  ok: true;
  key: string;
  source: ConfigSource;
  config: EditableConfig;
  effective_config: EditableConfig & {
    openai_api_key: string;
    processed_ids?: string[];
  };
}

export interface HealthResponse {
  ok: true;
  service: string;
  runtime: string;
}

export interface AnalysisResultRecord {
  record_id: number;
  target_date: string;
  id: string;
  title: string;
  abstract: string;
  authors: string[];
  categories: string[];
  paper_url: string;
  published: string;
  score: Score;
  reason: string;
  core_methods: string;
  problem: string;
  keywords: string[];
  created_at: string;
  updated_at: string;
}

export interface AnalysisResultsResponse {
  ok: true;
  results: AnalysisResultRecord[];
}

export interface PipelineRunResult {
  date: string;
  total_fetched: number;
  total_analyzed?: number;
  total_filtered: number;
  results: Array<{
    paper: {
      id: string;
      source: string;
      title: string;
      abstract: string;
      authors: string[];
      categories: string[];
      paper_url: string;
      published: string;
    };
    score: Score;
    reason: string;
    core_methods: string;
    problem: string;
    keywords: string[];
  }>;
}

export type PipelineRunStatus = 'queued' | 'running' | 'completed' | 'failed';
export type PipelineLogLevel = 'info' | 'warn' | 'error';

export interface PipelineRunLogEntry {
  at: string;
  level: PipelineLogLevel;
  message: string;
  progress: number;
  step: string;
}

export interface PipelineRunRecord {
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

export interface PipelineRunStatusResponse {
  ok: true;
  run: PipelineRunRecord | null;
}

export type RunResponse =
  | {
      ok: true;
      queued: true;
      mode: 'manual';
      targetDate: string;
      run?: PipelineRunRecord;
    }
  | {
      ok: true;
      queued: false;
      mode: 'manual';
      result: PipelineRunResult;
      run?: PipelineRunRecord;
    };

export interface UiFilters {
  date: string;
  q: string;
  score: string;
  keyword: string;
  selected: string;
  view: 'focus' | 'all';
}

export interface Flash {
  kind: 'success' | 'error' | 'info';
  message: string;
}

export class BackendApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body: unknown,
  ) {
    super(message);
    this.name = 'BackendApiError';
  }
}
