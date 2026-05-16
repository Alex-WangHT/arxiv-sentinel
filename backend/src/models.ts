export interface DomainRule {
  category: string;
  mode: "accept_all" | "categories_filter";
  filter_categories: string[];
}

export interface Paper {
  id: string;        // 唯一标识符。对于 arXiv 是 ID，对于其他来源可能是 DOI 或带前缀的 ID
  source: string;    // 来源标识，如 'arxiv', 'semantic_scholar'
  title: string;
  abstract: string;
  authors: string[];
  categories: string[];
  paper_url: string;
  published: string;
}


export interface PaperSniffer {
  readonly name: string;
  sniff(targetDate?: Date): Promise<Paper[]>;
}

export interface AnalysisResult {
  paper: Paper;
  score: "HIGH" | "MEDIUM" | "LOW" | "IRRELEVANT";
  reason: string;
  core_methods: string;
  problem: string;
  keywords: string[];
}

export interface SummaryResult {
  paper: Paper;
  core_methods: string;
  problem: string;
  keywords: string[];
  error: string | null;
}

export interface LlmResponse {
  model: string;
  data: Record<string, unknown> | null;
  error: string | null;
  elapsed: number;
}

export interface PipelineResult {
  date: string;
  total_fetched: number;
  total_filtered: number;
  results: AnalysisResult[];
}
