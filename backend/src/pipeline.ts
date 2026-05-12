import * as fs from 'fs';
import * as path from 'path';
import { Config } from './config';
import { LlmClient } from './llm_client';
import { PaperAnalyzer } from './paper_analyzer';
import { ArxivSniffer } from './arxiv_sniffer';
import { AnalysisResult, Paper, PipelineResult } from './models';

export class Pipeline {
  private config: Config;
  private llmClient: LlmClient;
  private analyzer: PaperAnalyzer;

  constructor(config: Config) {
    this.config = config;
    this.llmClient = new LlmClient(
      config.openai_api_key,
      config.openai_model,
      config.openai_base_url,
      undefined,
      undefined,
      20,
    );
    this.analyzer = new PaperAnalyzer(
      this.llmClient,
      config.keywords,
      config.relevance_threshold,
      config.prompts_dir,
    );
  }

  async sniffPapers(targetDate?: Date): Promise<Paper[]> {
    const sniffer = new ArxivSniffer(
      this.config.domain_rules,
      this.config.max_results_per_category,
      this.config.processed_ids,
      targetDate,
    );
    return await sniffer.sniffAsync();
  }

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

  saveResults(results: AnalysisResult[], targetDate: string): string {
    const outputDir = this.config.output_dir;
    const filename = `analysis_results_${targetDate}.json`;
    const filepath = path.join(outputDir, filename);

    const resultsData = results.map(result => ({
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

    fs.writeFileSync(filepath, JSON.stringify(resultsData, null, 2), 'utf-8');
    console.info(`分析结果已保存到: ${filepath}`);
    return filepath;
  }

  updateHistory(papers: Paper[]): void {
    const newIds = papers.map(p => p.arxiv_id);
    const updatedIds = [...new Set([...this.config.processed_ids, ...newIds])];

    fs.writeFileSync(this.config.history_file, JSON.stringify(updatedIds, null, 2), 'utf-8');
    this.config.processed_ids = updatedIds;
    console.info(`历史记录已更新，新增 ${newIds.length} 条记录`);
  }

  private formatDate(date: Date): string {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  async run(targetDate?: Date): Promise<PipelineResult> {
    console.info('='.repeat(60));
    console.info('开始执行 arXiv Sentinel 流水线（异步模式）');
    console.info('='.repeat(60));

    let targetDateStr: string;
    if (targetDate) {
      targetDateStr = this.formatDate(targetDate);
    } else {
      const yesterday = new Date();
      yesterday.setDate(yesterday.getDate() - 1);
      targetDateStr = this.formatDate(yesterday);
    }

    console.info('步骤1: 开始嗅探 arXiv 论文');
    const papers = await this.sniffPapers(targetDate);
    const totalFetched = papers.length;
    console.info(`步骤1完成: 嗅探到 ${totalFetched} 篇新论文`);

    if (papers.length === 0) {
      console.info('没有新论文，流水线提前结束');
      return {
        date: targetDateStr,
        total_fetched: 0,
        total_filtered: 0,
        results: [],
      };
    }

    console.info('步骤2: 开始分析论文摘要');
    const filteredResults = await this.analyzePapers(papers);
    const totalFiltered = filteredResults.length;
    console.info(`步骤2完成: 分析并筛选后保留 ${totalFiltered} 篇`);

    console.info('步骤3: 保存分析结果');
    this.saveResults(filteredResults, targetDateStr);

    console.info('步骤4: 更新处理历史');
    this.updateHistory(papers);

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
}

if (require.main === module) {
  const cfg = Config.fromFile();
  const pipeline = new Pipeline(cfg);

  pipeline.run().then(result => {
    console.log(`日期: ${result.date}`);
    console.log(`获取论文数: ${result.total_fetched}`);
    console.log(`筛选后保留: ${result.total_filtered}`);
  }).catch(console.error);
}