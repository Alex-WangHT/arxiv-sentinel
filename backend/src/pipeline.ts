import { Config } from './config';
import { LlmClient } from './llm_client';
import { PaperAnalyzer } from './paper_analyzer';
import { ArxivSniffer } from './arxiv_sniffer';
import { AnalysisResult, Paper, PipelineResult } from './models';

/*
 * Pipeline 是业务流程的总调度器。
 *
 * 它把整个任务拆成四步：
 * 1. 从 arXiv 抓论文；
 * 2. 用 LLM 分析论文；
 * 3. 保存分析结果；
 * 4. 更新已处理历史。
 *
 * 为了适配 Cloudflare Workers，这里不再直接 fs.writeFileSync 写本地文件，
 * 而是通过 PipelineStorage 接口把“保存到哪里”交给外部实现。
 */

// 保存结果时不直接保存完整 AnalysisResult，是因为 AnalysisResult 里嵌套了 paper。
// 这里把它拍平成更适合 JSON 存储和前端读取的结构。
export interface SerializedAnalysisResult {
  arxiv_id: string;
  title: string;
  abstract: string;
  authors: string[];
  categories: string[];
  pdf_url: string;
  published: string;
  score: string;
  reason: string;
  core_methods: string;
  problem: string;
  keywords: string[];
}

// 存储接口：Pipeline 只管调用这些方法，不关心底层是 D1、本地内存，还是未来的其他数据库。
export interface PipelineStorage {
  loadHistory(historyKey: string): Promise<string[]>;
  saveResults(
    results: SerializedAnalysisResult[],
    targetDate: string,
    config: Config,
  ): Promise<string>;
  saveHistory(historyKey: string, ids: string[], config: Config): Promise<void>;
}

// 内存存储主要用于本地测试或没有绑定 D1 的情况。
// 注意：内存数据会随着 Worker 实例重启而丢失，生产环境不要依赖它保存历史。
export class MemoryPipelineStorage implements PipelineStorage {
  private history: string[] = [];
  private lastResults: SerializedAnalysisResult[] = [];

  async loadHistory(): Promise<string[]> {
    return [...this.history];
  }

  async saveResults(
    results: SerializedAnalysisResult[],
    targetDate: string,
    config: Config,
  ): Promise<string> {
    this.lastResults = results;
    return `memory://${config.output_dir}/analysis_results_${targetDate}.json`;
  }

  async saveHistory(_historyKey: string, ids: string[]): Promise<void> {
    this.history = [...ids];
  }

  getLastResults(): SerializedAnalysisResult[] {
    return [...this.lastResults];
  }
}

export class Pipeline {
  private config: Config;
  private llmClient: LlmClient;
  private analyzer: PaperAnalyzer;
  private storage: PipelineStorage;

  constructor(config: Config, storage: PipelineStorage = new MemoryPipelineStorage()) {
    this.config = config;
    this.storage = storage;
    // LlmClient 只负责“怎么调用模型”，不知道论文业务。
    this.llmClient = new LlmClient(
      config.openai_api_key,
      config.openai_model,
      config.openai_base_url,
      undefined,
      undefined,
      20,
      config.max_concurrent_requests,
    );
    // PaperAnalyzer 负责“如何把论文变成 prompt，并解析模型返回结果”。
    this.analyzer = new PaperAnalyzer(
      this.llmClient,
      config.keywords,
      config.relevance_threshold,
      {
        systemPrompt: config.prompt_system,
        userTemplate: config.prompt_user_template,
      },
    );
  }

  // 第一步：根据配置里的 domain_rules 去 arXiv 拉论文。
  async sniffPapers(targetDate?: Date): Promise<Paper[]> {
    const sniffer = new ArxivSniffer(
      this.config.domain_rules,
      this.config.max_results_per_category,
      this.config.processed_ids,
      targetDate,
    );
    return await sniffer.sniffAsync();
  }

  // 第二步：把论文交给大模型分析，并按 relevance_threshold 做过滤。
  async analyzePapers(papers: Paper[]): Promise<AnalysisResult[]> {
    if (papers.length === 0) {
      console.info('没有论文需要分析');
      return [];
    }

    console.info(`开始分析 ${papers.length} 篇论文`);

    const results = await this.analyzer.analyzePapers(
      papers,
      3,
      10,
    );

    return this.analyzer.applyThreshold(results);
  }

  // 第三步：保存筛选后的分析结果。
  // 在 Worker 环境下，实际会由 WorkerD1Storage 写入 D1。
  async saveResults(results: AnalysisResult[], targetDate: string): Promise<string> {
    const resultsData = this.serializeResults(results);
    const location = await this.storage.saveResults(resultsData, targetDate, this.config);
    console.info(`分析结果已保存到: ${location}`);
    return location;
  }

  // 第四步：把这次处理过的论文 arxiv_id 写入历史。
  // 下次运行时会跳过这些 id，避免重复分析和重复花费模型调用成本。
  async updateHistory(papers: Paper[]): Promise<void> {
    const newIds = papers.map(paper => paper.arxiv_id);
    const updatedIds = [...new Set([...this.config.processed_ids, ...newIds])];

    await this.storage.saveHistory(this.config.history_file, updatedIds, this.config);
    this.config.processed_ids = updatedIds;
    console.info(`历史记录已更新，新增 ${newIds.length} 条记录`);
  }

  // 主入口：按固定顺序执行整个论文嗅探和分析流程。
  // 返回 PipelineResult，方便 HTTP 接口直接返回给调试者。
  async run(targetDate?: Date): Promise<PipelineResult> {
    console.info('='.repeat(60));
    console.info('开始执行 PaperSniffer 流水线');
    console.info('='.repeat(60));

    const targetDateStr = this.resolveTargetDate(targetDate);

    console.info('步骤 1: 开始嗅探 arXiv 论文');
    const papers = await this.sniffPapers(targetDate);
    const totalFetched = papers.length;
    console.info(`步骤 1 完成: 嗅探到 ${totalFetched} 篇新论文`);

    if (papers.length === 0) {
      console.info('没有新论文，流水线提前结束');
      return {
        date: targetDateStr,
        total_fetched: 0,
        total_filtered: 0,
        results: [],
      };
    }

    console.info('步骤 2: 开始分析论文摘要');
    const filteredResults = await this.analyzePapers(papers);
    const totalFiltered = filteredResults.length;
    console.info(`步骤 2 完成: 分析并筛选后保留 ${totalFiltered} 篇`);

    console.info('步骤 3: 保存分析结果');
    await this.saveResults(filteredResults, targetDateStr);

    console.info('步骤 4: 更新处理历史');
    await this.updateHistory(papers);

    console.info('='.repeat(60));
    console.info('流水线执行完成');
    console.info('='.repeat(60));

    return {
      date: targetDateStr,
      total_fetched: totalFetched,
      total_filtered: totalFiltered,
      results: filteredResults,
    };
  }

  // 把内部结果转换成更直观的 JSON 结构，方便保存和后续展示。
  private serializeResults(results: AnalysisResult[]): SerializedAnalysisResult[] {
    return results.map(result => ({
      arxiv_id: result.paper.arxiv_id,
      title: result.paper.title,
      abstract: result.paper.abstract,
      authors: result.paper.authors,
      categories: result.paper.categories,
      pdf_url: result.paper.pdf_url,
      published: result.paper.published,
      score: result.score,
      reason: result.reason,
      core_methods: result.core_methods,
      problem: result.problem,
      keywords: result.keywords,
    }));
  }

  // 如果用户没有指定日期，默认处理两天前。
  // 这个逻辑和 ArxivSniffer 保持一致，避免日期显示和实际查询不一致。
  private resolveTargetDate(targetDate?: Date): string {
    if (targetDate) {
      return this.formatDate(targetDate);
    }

    const twoDaysAgo = new Date();
    twoDaysAgo.setUTCDate(twoDaysAgo.getUTCDate() - 2);
    return this.formatDate(twoDaysAgo);
  }

  // 统一使用 UTC 日期，减少本地时区和 Worker 部署地区带来的差异。
  private formatDate(date: Date): string {
    const year = date.getUTCFullYear();
    const month = String(date.getUTCMonth() + 1).padStart(2, '0');
    const day = String(date.getUTCDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }
}
