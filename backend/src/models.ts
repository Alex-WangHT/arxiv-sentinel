export interface DomainRule {
  category: string;
  mode: "accept_all" | "categories_filter";
  filter_categories: string[];
}

export interface Paper {
  arxiv_id: string;
  title: string;
  abstract: string;
  authors: string[];
  categories: string[];
  pdf_url: string;
  published: string;
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