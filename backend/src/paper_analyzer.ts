import { Paper, AnalysisResult, LlmResponse } from './models';
import { LlmClient } from './llm_client';

/*
 * PaperAnalyzer 负责把论文转换成大模型能理解的 prompt，
 * 并把大模型返回的 JSON 解析成项目内部的 AnalysisResult。
 *
 * 它不关心模型接口怎么调用，那是 LlmClient 的职责；
 * 它也不关心结果保存到哪里，那是 Pipeline/Storage 的职责。
 */

const VALID_SCORES = ['HIGH', 'MEDIUM', 'LOW', 'IRRELEVANT'] as const;
// 默认系统提示词。
// 现在 prompt 推荐放在 CONFIG_KV 的配置里（prompt_system / prompt_user_template）统一管理；
// 如果没有配置，则回退到这里的默认 prompt。
const DEFAULT_SYSTEM_PROMPT = `你是一位学术论文分析专家。你的任务是对给定的论文标题和摘要进行深入分析，同时评估它与给定重点关注关键词的相关度。

请严格按以下 JSON 格式返回分析结果：
{
  "score": "HIGH|MEDIUM|LOW|IRRELEVANT",
  "reason": "评估理由，中文，1-2 句话；如果论文不匹配重点关注关键词，也要说明它的实际主题",
  "core_methods": "核心技术方法，中文，说明论文使用的主要技术、算法、模型或方法论",
  "problem": "要解决的问题，中文，清晰描述论文试图解决的核心问题或挑战",
  "keywords": ["keyword1", "keyword2", "keyword3"]
}

相关度评分标准：
- HIGH: 论文核心主题与重点关注关键词高度相关，是该领域的直接贡献
- MEDIUM: 论文与重点关注关键词有一定关联，但不是核心主题
- LOW: 论文仅边缘性地涉及重点关注关键词相关内容
- IRRELEVANT: 论文与重点关注关键词无实质关联，但仍需要正常总结

请仅返回 JSON 对象，不要包含其他内容。`;

const DEFAULT_USER_TEMPLATE = `重点关注关键词：{keywords}

论文标题：{title}

论文摘要：{abstract}

请对这篇论文进行综合分析，评估与重点关注关键词的相关度并提取核心信息。即使论文不匹配重点关注关键词，也请返回 JSON 格式的完整分析结果。`;

// PromptSource 用来允许外部替换默认 prompt。
// 例如你想调整评分标准，不需要改代码，只要在 Worker env 里覆盖 prompt。
export interface PromptSource {
  systemPrompt?: string;
  userTemplate?: string;
}

export class PaperAnalyzer {
  private llmClient: LlmClient;
  private keywords: string[];
  private systemPrompt: string;
  private userTemplate: string;

  constructor(
    llmClient: LlmClient,
    keywords: string[],
    _threshold: string,
    prompts: PromptSource = {},
  ) {
    this.llmClient = llmClient;
    this.keywords = keywords;
    this.systemPrompt = prompts.systemPrompt || DEFAULT_SYSTEM_PROMPT;
    this.userTemplate = prompts.userTemplate || DEFAULT_USER_TEMPLATE;
  }

  // 分析单篇论文：构造 prompt -> 调用 LLM -> 解析结果。
  async analyzePaper(paper: Paper): Promise<AnalysisResult> {
    const messages = this.buildMessages(paper);
    const response = await this.llmClient.achat(messages, undefined, true);
    return this.parseResponse(paper, response);
  }

  // 分析多篇论文：先给每篇论文构造 messages，再交给 LlmClient 做批量调用。
  async analyzePapers(
    papers: Paper[],
    requestInterval: number = 0.5,
    queueInterval: number = 20.0,
  ): Promise<AnalysisResult[]> {
    console.info(
      `开始异步分析 ${papers.length} 篇论文，请求间隔: ${requestInterval} 秒，队列间隔: ${queueInterval} 秒`,
    );

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

  // 把一篇论文变成 Chat API 的 messages。
  // system 消息定义模型角色和输出格式，user 消息放具体论文内容。
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

  // 把 LlmClient 返回的通用结果转换为论文分析结果。
  // 如果模型调用失败，就把这篇论文标记为 IRRELEVANT，保证流水线不中断。
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

    // 模型可能返回拼写错误或意料外的 score，这里做一次兜底校验。
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

  // 模型返回的 keywords 可能是数组，也可能是字符串。
  // 这里统一转成最多 5 个关键词的 string[]。
  private parseKeywords(keywords: unknown): string[] {
    if (Array.isArray(keywords)) {
      return keywords.slice(0, 5).map(keyword => String(keyword).trim()).filter(Boolean);
    }
    if (typeof keywords === 'string') {
      return keywords.trim() ? [keywords.trim()] : [];
    }
    return [];
  }
}
