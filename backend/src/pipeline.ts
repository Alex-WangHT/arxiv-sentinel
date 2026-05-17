import { Config } from './config';
import { LlmClient } from './llm_client';
import { PaperAnalyzer } from './paper_analyzer';
import { ArxivSniffer } from './arxiv_sniffer';
import {
  AnalysisResult,
  Paper,
  PipelineResult,
  PaperSniffer,
} from './models';

const BEIJING_TIME_OFFSET_MS = 8 * 60 * 60 * 1000;

export type PipelineRunStatus = 'queued' | 'running' | 'completed' | 'failed';
export type PipelineLogLevel = 'info' | 'warn' | 'error';

export interface PipelineProgressUpdate {
  targetDate: string;
  status: PipelineRunStatus;
  progress: number;
  step: string;
  message: string;
  level?: PipelineLogLevel;
  totalFetched?: number;
  totalAnalyzed?: number;
  error?: string;
}

export interface PipelineProgressSink {
  update(update: PipelineProgressUpdate): Promise<void>;
}

/*
 * Pipeline 是业务流程的总调度器。
 *
 * 它把整个任务拆成四步：
 * 1. 从各数据源 (arXiv 等) 嗅探论文；
 * 2. 对新论文进行去重和历史过滤；
 * 3. 用 LLM 分析论文；
 * 4. 保存分析结果并更新已处理历史。
 */

// 保存结果时不直接保存完整 AnalysisResult，是因为 AnalysisResult 里嵌套了 paper。
// 这里把它拍平成更适合 JSON 存储和前端读取的结构。
export interface SerializedAnalysisResult {
  id: string;
  title: string;
  abstract: string;
  authors: string[];
  categories: string[];
  paper_url: string;
  published: string;
  score: string;
  reason: string;
  core_methods: string;
  problem: string;
  keywords: string[];
}

/** HTTP `GET /api/analysis-results` 查询参数，与 D1 `analysis_results` 表对应。须提供 `YYYY-MM-DD` 的 `target_date`。 */
export interface AnalysisResultsQuery {
  target_date: string;
}

/** D1 中一行分析结果（在 SerializedAnalysisResult 基础上带主键与审计字段）。 */
export interface AnalysisResultRecord extends SerializedAnalysisResult {
  record_id: number;
  target_date: string;
  created_at: string;
  updated_at: string;
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
  /** 读取已持久化的分析结果；无后端存储时返回空数组。 */
  listAnalysisResults(query: AnalysisResultsQuery): Promise<AnalysisResultRecord[]>;
}

// 内存存储主要用于本地测试或没有绑定 D1 的情况。
// 注意：内存数据会随着 Worker 实例重启而丢失，生产环境不要依赖它保存历史。
export class MemoryPipelineStorage implements PipelineStorage {
  private history: string[] = [];
  private lastResults: SerializedAnalysisResult[] = [];
  private lastTargetDate = '';

  async loadHistory(): Promise<string[]> {
    return [...this.history];
  }

  async saveResults(
    results: SerializedAnalysisResult[],
    targetDate: string,
    config: Config,
  ): Promise<string> {
    this.lastResults = results;
    this.lastTargetDate = targetDate;
    return `memory://${config.output_dir}/analysis_results_${targetDate}.json`;
  }

  async saveHistory(_historyKey: string, ids: string[], _config: Config): Promise<void> {
    this.history = [...new Set([...this.history, ...ids])];
  }

  async listAnalysisResults(query: AnalysisResultsQuery): Promise<AnalysisResultRecord[]> {
    if (query.target_date !== this.lastTargetDate) {
      return [];
    }
    return this.lastResults.map((row, i) => ({
      ...row,
      record_id: i + 1,
      target_date: this.lastTargetDate,
      created_at: '',
      updated_at: '',
    }));
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
  private sniffers: PaperSniffer[] = [];
  private progress = 0;

  constructor(
    config: Config,
    storage: PipelineStorage = new MemoryPipelineStorage(),
    private progressSink?: PipelineProgressSink,
  ) {
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

    this.registerConfiguredSniffers();
  }

  /** 注册新的论文嗅探器（如未来的 Semantic Scholar） */
  registerSniffer(sniffer: PaperSniffer): void {
    this.sniffers.push(sniffer);
  }

  private registerConfiguredSniffers(): void {
    const enabledSources = this.config.sources.filter(source => source.enabled);

    for (const source of enabledSources) {
      const rules = this.config.domain_rules.filter(rule => rule.source === source.id);
      if (rules.length === 0) {
        console.info(`来源 ${source.name} (${source.id}) 没有领域规则，跳过注册`);
        continue;
      }

      if (source.type === 'arxiv') {
        this.registerSniffer(new ArxivSniffer(
          rules,
          undefined,
          source.id,
          source.name,
        ));
        continue;
      }

      console.warn(`来源 ${source.name} (${source.type}) 暂未实现嗅探器，已跳过`);
    }
  }

  // 第一步：从所有注册的嗅探器中获取论文，并进行去重和历史过滤。
  async sniffPapers(targetDate?: Date): Promise<Paper[]> {
    let allPapers: Paper[] = [];

    for (const sniffer of this.sniffers) {
      try {
        const papers = await sniffer.sniff(targetDate);
        allPapers = allPapers.concat(papers);
      } catch (error) {
        console.error(`嗅探器 ${sniffer.name} 运行失败: ${(error as Error).message}`);
        throw error;
      }
    }

    // 1. 全局去重（防止不同数据源抓到同一篇论文）
    const seenIds = new Set<string>();
    const deduped: Paper[] = [];
    for (const paper of allPapers) {
      if (!seenIds.has(paper.id)) {
        seenIds.add(paper.id);
        deduped.push(paper);
      }
    }

    // 2. 历史过滤（排除已经处理过的论文）
    const processedIds = new Set(this.config.processed_ids);
    const newPapers = deduped.filter(paper => !processedIds.has(paper.id));

    console.info(`嗅探完成: 原始总数=${allPapers.length}, 去重后=${deduped.length}, 过滤历史后=${newPapers.length}`);
    return newPapers;
  }

  // 第二步：把论文交给大模型分析。
  // keywords 现在表示“重点关注关键词”，用于评估和前端重点推送排序，
  // 不再作为后端丢弃论文的过滤条件。
  async analyzePapers(
    papers: Paper[],
    progress?: (completed: number, total: number) => Promise<void>,
  ): Promise<AnalysisResult[]> {
    if (papers.length === 0) {
      console.info('没有论文需要分析');
      return [];
    }

    console.info(`开始分析 ${papers.length} 篇论文`);

    const results = await this.analyzer.analyzePapers(
      papers,
      3,
      10,
      progress,
    );

    return results;
  }

  // 第三步：保存完整的分析结果。
  // 在 Worker 环境下，实际会由 WorkerD1Storage 写入 D1；对外读取见 GET /api/analysis-results。
  async saveResults(results: AnalysisResult[], targetDate: string): Promise<string> {
    const resultsData = this.serializeResults(results);
    const location = await this.storage.saveResults(resultsData, targetDate, this.config);
    console.info(`分析结果已保存到: ${location}`);
    return location;
  }

  // 第四步：把这次处理过的论文 id 写入历史。
  // 下次运行时会跳过这些 id，避免重复分析和重复花费模型调用成本。
  async updateHistory(papers: Paper[]): Promise<void> {
    const newIds = [...new Set(papers.map(paper => paper.id))];

    // 只持久化本次新增的论文 ID，避免每次运行都把全部历史重新写入 D1，
    // 否则历史数据一多会在单次 Worker invocation 内制造大量 subrequests。
    await this.storage.saveHistory(this.config.history_file, newIds, this.config);
    this.config.processed_ids = [...new Set([...this.config.processed_ids, ...newIds])];
    console.info(`历史记录已更新，新增 ${newIds.length} 条记录`);
  }

  private async reportProgress(update: PipelineProgressUpdate): Promise<void> {
    this.progress = update.progress;
    if (!this.progressSink) {
      return;
    }

    await this.progressSink.update(update);
  }

  // 主入口：按固定顺序执行整个论文嗅探和分析流程。
  // 返回 PipelineResult，方便 HTTP 接口直接返回给调试者。
  async run(targetDate?: Date): Promise<PipelineResult> {
    console.info('='.repeat(60));
    console.info('开始执行 PaperSniffer 流水线');
    console.info('='.repeat(60));

    const targetDateStr = this.resolveTargetDate(targetDate);
    this.progress = 0;

    try {
      await this.reportProgress({
        targetDate: targetDateStr,
        status: 'running',
        progress: 5,
        step: '初始化',
        message: '流水线已启动，正在加载配置和历史记录',
      });

      console.info('步骤 1: 开始嗅探论文');
      await this.reportProgress({
        targetDate: targetDateStr,
        status: 'running',
        progress: 15,
        step: '嗅探论文',
        message: '正在从已启用来源查找当日论文',
      });
      const papers = await this.sniffPapers(targetDate);
      const totalFetched = papers.length;
      console.info(`步骤 1 完成: 获取到 ${totalFetched} 篇新论文`);
      await this.reportProgress({
        targetDate: targetDateStr,
        status: 'running',
        progress: 35,
        step: '嗅探完成',
        message: `获取到 ${totalFetched} 篇新论文`,
        totalFetched,
      });

      if (papers.length === 0) {
        console.info('没有新论文，流水线提前结束');
        await this.reportProgress({
          targetDate: targetDateStr,
          status: 'completed',
          progress: 100,
          step: '完成',
          message: '没有新论文需要分析，流水线已结束',
          totalFetched: 0,
          totalAnalyzed: 0,
        });
        return {
          date: targetDateStr,
          total_fetched: 0,
          total_analyzed: 0,
          total_filtered: 0,
          results: [],
        };
      }

      console.info('步骤 2: 开始分析论文摘要');
      await this.reportProgress({
        targetDate: targetDateStr,
        status: 'running',
        progress: 45,
        step: '分析论文',
        message: `正在调用模型分析 ${papers.length} 篇论文`,
        totalFetched,
      });
      const analyzedResults = await this.analyzePapers(
        papers,
        async (completed, batchTotal) => {
          await this.reportProgress({
            targetDate: targetDateStr,
            status: 'running',
            progress: 45 + Math.round((completed / Math.max(1, batchTotal)) * 30),
            step: '分析论文',
            message: `当前队列批次正在分析论文，已完成 ${completed}/${batchTotal} 篇`,
            totalFetched,
            totalAnalyzed: completed,
          });
        },
      );
      const totalAnalyzed = analyzedResults.length;
      console.info(`步骤 2 完成: 已分析 ${totalAnalyzed} 篇，未按重点关注词丢弃论文`);
      await this.reportProgress({
        targetDate: targetDateStr,
        status: 'running',
        progress: 75,
        step: '分析完成',
        message: `已完成 ${totalAnalyzed} 篇论文分析`,
        totalFetched,
        totalAnalyzed,
      });

      console.info('步骤 3: 保存分析结果');
      await this.reportProgress({
        targetDate: targetDateStr,
        status: 'running',
        progress: 88,
        step: '保存结果',
        message: '正在保存分析结果到数据库',
        totalFetched,
        totalAnalyzed,
      });
      await this.saveResults(analyzedResults, targetDateStr);

      console.info('步骤 4: 更新处理历史');
      await this.reportProgress({
        targetDate: targetDateStr,
        status: 'running',
        progress: 95,
        step: '更新历史',
        message: '正在更新已处理论文历史',
        totalFetched,
        totalAnalyzed,
      });
      await this.updateHistory(papers);

      console.info('='.repeat(60));
      console.info('流水线执行完成');
      console.info('='.repeat(60));

      await this.reportProgress({
        targetDate: targetDateStr,
        status: 'completed',
        progress: 100,
        step: '完成',
        message: `流水线已完成，共分析 ${totalAnalyzed} 篇论文`,
        totalFetched,
        totalAnalyzed,
      });

      return {
        date: targetDateStr,
        total_fetched: totalFetched,
        total_analyzed: totalAnalyzed,
        total_filtered: totalAnalyzed,
        results: analyzedResults,
      };
    } catch (error) {
      await this.reportProgress({
        targetDate: targetDateStr,
        status: 'failed',
        progress: this.progress,
        step: '失败',
        message: (error as Error).message,
        level: 'error',
        error: (error as Error).message,
      });
      throw error;
    }
  }

  // 把内部结果转换成更直观的 JSON 结构，方便保存和后续展示。
  private serializeResults(results: AnalysisResult[]): SerializedAnalysisResult[] {
    return results.map(result => ({
      id: result.paper.id,
      title: result.paper.title,
      abstract: result.paper.abstract,
      authors: result.paper.authors,
      categories: result.paper.categories,
      paper_url: result.paper.paper_url,
      published: result.paper.published,
      score: result.score,
      reason: result.reason,
      core_methods: result.core_methods,
      problem: result.problem,
      keywords: result.keywords,
    }));
  }

  // 如果用户没有指定日期，默认处理北京时间当日论文。
  // 这个逻辑和 ArxivSniffer 保持一致，避免日期显示和实际查询不一致。
  private resolveTargetDate(targetDate?: Date): string {
    if (targetDate) {
      return this.formatDate(targetDate);
    }

    return this.formatDate(new Date(Date.now() + BEIJING_TIME_OFFSET_MS));
  }

  // 统一使用 UTC 日期，减少本地时区和 Worker 部署地区带来的差异。
  private formatDate(date: Date): string {
    const year = date.getUTCFullYear();
    const month = String(date.getUTCMonth() + 1).padStart(2, '0');
    const day = String(date.getUTCDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }
}
