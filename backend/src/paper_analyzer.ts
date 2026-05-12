import * as fs from 'fs';
import { Paper, AnalysisResult, LlmResponse } from './models';
import { LlmClient } from './llm_client';

const VALID_SCORES = ['HIGH', 'MEDIUM', 'LOW', 'IRRELEVANT'] as const;
const SCORE_PRIORITY: Record<string, number> = { HIGH: 3, MEDIUM: 2, LOW: 1, IRRELEVANT: 0 };

export class PaperAnalyzer {
  private llmClient: LlmClient;
  private keywords: string[];
  private threshold: string;
  private systemPrompt: string;
  private userTemplate: string;

  constructor(
    llmClient: LlmClient,
    keywords: string[],
    threshold: string,
    promptsDir: string,
  ) {
    this.llmClient = llmClient;
    this.keywords = keywords;
    this.threshold = threshold;

    const systemPath = `${promptsDir}/paper_analyzer/system.md`;
    const userPath = `${promptsDir}/paper_analyzer/user.md`;

    this.systemPrompt = fs.readFileSync(systemPath, 'utf-8');
    this.userTemplate = fs.readFileSync(userPath, 'utf-8');
  }

  private buildMessages(paper: Paper): Array<{ role: string; content: string }> {
    const userContent = this.userTemplate
      .replace('{keywords}', this.keywords.join(', '))
      .replace('{title}', paper.title)
      .replace('{abstract}', paper.abstract);

    return [
      { role: 'system', content: this.systemPrompt },
      { role: 'user', content: userContent },
    ];
  }

  private parseResponse(paper: Paper, response: LlmResponse): AnalysisResult {
    if (response.error) {
      return {
        paper,
        score: 'IRRELEVANT',
        reason: response.error,
        core_methods: '',
        problem: '',
        keywords: [],
      };
    }

    const data = response.data;
    if (!data) {
      return {
        paper,
        score: 'IRRELEVANT',
        reason: 'LLM 返回数据为空',
        core_methods: '',
        problem: '',
        keywords: [],
      };
    }

    const score = (data.score as string) || 'IRRELEVANT';
    const validScore = VALID_SCORES.includes(score as typeof VALID_SCORES[number])
      ? (score as AnalysisResult['score'])
      : 'IRRELEVANT';

    return {
      paper,
      score: validScore,
      reason: String(data.reason || ''),
      core_methods: String(data.core_methods || ''),
      problem: String(data.problem || ''),
      keywords: this.parseKeywords(data.keywords),
    };
  }

  private parseKeywords(keywords: unknown): string[] {
    if (Array.isArray(keywords)) {
      return keywords.slice(0, 5).map(k => String(k).trim()).filter(Boolean);
    } else if (typeof keywords === 'string') {
      return keywords.trim() ? [keywords.trim()] : [];
    }
    return [];
  }

  async analyzePaper(paper: Paper): Promise<AnalysisResult> {
    const messages = this.buildMessages(paper);
    const response = await this.llmClient.achat(messages, undefined, true);
    return this.parseResponse(paper, response);
  }

  async analyzePapers(
    papers: Paper[],
    requestInterval: number = 0.5,
    queueInterval: number = 20.0,
  ): Promise<AnalysisResult[]> {
    console.info(`开始异步分析 ${papers.length} 篇论文，请求间隔: ${requestInterval} 秒，队列间隔: ${queueInterval} 秒`);

    const messagesList = papers.map(paper => this.buildMessages(paper));

    const responses = await this.llmClient.batchAchat(
      messagesList,
      undefined,
      true,
      requestInterval,
      queueInterval,
    );

    const results = papers.map((paper, index) =>
      this.parseResponse(paper, responses[index]),
    );

    console.info(`异步分析完成，共处理 ${results.length} 篇论文`);
    return results;
  }

  applyThreshold(results: AnalysisResult[]): AnalysisResult[] {
    const thresholdPriority = SCORE_PRIORITY[this.threshold] || 0;
    const filtered = results.filter(r => (SCORE_PRIORITY[r.score] || 0) >= thresholdPriority);

    console.info(`阈值过滤: 过滤前 ${results.length} 篇，过滤后 ${filtered.length} 篇`);
    return filtered;
  }
}

if (require.main === module) {
  const runTest = async () => {
    const llm = new LlmClient(
      'sk-yswnbelwichutfnaqifoltczsydrijivpazpkjumpawlupzd',
      'deepseek-ai/DeepSeek-V4-Flash',
      'https://api.siliconflow.cn/v1',
    );

    const analyzer = new PaperAnalyzer(
      llm,
      ['Deep Learning'],
      'MEDIUM',
      './prompts',
    );

    const testPaper: Paper = {
      arxiv_id: '2605.06498',
      title: 'Lie Group Formulation of Recursive Dynamics Algorithms of Higher Order for Floating-Base Robots',
      abstract: 'In this paper, we describe procedures for computing higher-order time derivatives of the Lie-group Newton-Euler, Articulated-Body Inertia, and hybrid dynamics algorithms for floating-base trees, where the base configuration evolves on SE(3) and the attached mechanism is an open kinematic tree with configuration on the (n1+n2)-dimensional manifold T^{n1} \\times R^{n2}, using spatial representation of twists.',
      authors: ['Gabellieri'],
      categories: ['cs.RO', 'eecs.SY'],
      pdf_url: 'https://arxiv.org/pdf/test.pdf',
      published: '2026-05-21',
    };

    const result = await analyzer.analyzePaper(testPaper);
    console.log(`评分: ${result.score}`);
    console.log(`理由: ${result.reason}`);
    console.log(`核心方法: ${result.core_methods}`);
    console.log(`解决问题: ${result.problem}`);
    console.log(`关键词: ${result.keywords}`);
  };

  runTest().catch(console.error);
}