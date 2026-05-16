import { DomainRule, Paper, PaperSniffer } from './models';

/*
 * ArxivSniffer 负责从 arXiv API 拉取论文列表。
 *
 * Worker 适配点：
 * - 旧代码使用 Node.js 的 https 模块；
 * - Cloudflare Workers 没有 Node https；
 * - 所以这里统一改成 Web 标准 fetch。
 *
 * 这个类只负责“找论文”和“初步去重”，不负责调用大模型。
 */

const ARXIV_API_URL = 'https://export.arxiv.org/api/query';
const USER_AGENT = 'PaperSniffer/1.0 (Cloudflare Workers compatible)';
const ARXIV_MIN_REQUEST_INTERVAL_MS = 3500;
const ARXIV_MAX_RETRIES = 3;
const ARXIV_RETRY_BASE_MS = 5000;
const ARXIV_MAX_RETRY_DELAY_MS = 60000;

let arxivRequestQueue: Promise<void> = Promise.resolve();
let lastArxivRequestAt = 0;
let arxivBackoffUntil = 0;

interface CategoryFetchResult {
  rule: DomainRule;
  papers: Paper[];
  ok: boolean;
  error?: string;
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function waitForArxivSlot(): Promise<void> {
  const waitForTurn = async () => {
    const nextAllowedAt = Math.max(
      lastArxivRequestAt + ARXIV_MIN_REQUEST_INTERVAL_MS,
      arxivBackoffUntil,
    );
    const waitMs = Math.max(0, nextAllowedAt - Date.now());

    if (waitMs > 0) {
      await sleep(waitMs);
    }

    lastArxivRequestAt = Date.now();
  };

  const nextRequest = arxivRequestQueue
    .catch(() => undefined)
    .then(waitForTurn);

  arxivRequestQueue = nextRequest.catch(() => undefined);
  await nextRequest;
}

export class ArxivSniffer implements PaperSniffer {
  readonly name = 'arXiv';
  private domainRules: DomainRule[];
  private maxResults: number;
  private targetDate: Date;
  private targetStr: string;

  constructor(
    domainRules: DomainRule[],
    maxResults: number,
    targetDate?: Date,
  ) {
    this.domainRules = domainRules;
    this.maxResults = maxResults;

    // arXiv 的最新数据常常会有发布时间和索引延迟。
    // 默认抓“两天前”的论文，可以减少今天/昨天数据不完整导致的误判。
    const today = new Date();
    const twoDaysAgo = new Date(today);
    twoDaysAgo.setUTCDate(twoDaysAgo.getUTCDate() - 2);

    if (targetDate) {
      this.targetDate = new Date(Math.min(targetDate.getTime(), twoDaysAgo.getTime()));
    } else {
      this.targetDate = twoDaysAgo;
    }

    this.targetStr = this.formatDate(this.targetDate);
  }

  // 主入口：按配置里的每个分类分别抓取，再合并、去重。
  async sniff(): Promise<Paper[]> {
    console.info(`开始嗅探 arXiv，目标日期: ${this.targetStr}`);

    const results: CategoryFetchResult[] = [];
    for (const rule of this.domainRules) {
      results.push(await this.fetchCategory(rule));
    }

    return this.postProcess(results);
  }

  // 使用 UTC 日期，避免 Worker 部署地区、本机时区不同导致日期不一致。
  private formatDate(date: Date): string {
    const year = date.getUTCFullYear();
    const month = String(date.getUTCMonth() + 1).padStart(2, '0');
    const day = String(date.getUTCDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  private formatArxivDateTime(date: Date, time: '0000' | '2359'): string {
    const year = date.getUTCFullYear();
    const month = String(date.getUTCMonth() + 1).padStart(2, '0');
    const day = String(date.getUTCDate()).padStart(2, '0');
    return `${year}${month}${day}${time}`;
  }

  private buildSearchQuery(rule: DomainRule): string {
    const start = this.formatArxivDateTime(this.targetDate, '0000');
    const end = this.formatArxivDateTime(this.targetDate, '2359');
    return `cat:${rule.category} AND submittedDate:[${start} TO ${end}]`;
  }

  private shouldRetryResponse(response: Response): boolean {
    return response.status === 429 || response.status >= 500;
  }

  private parseRetryAfterMs(retryAfter: string | null): number | undefined {
    if (!retryAfter) {
      return undefined;
    }

    const seconds = Number(retryAfter);
    if (Number.isFinite(seconds)) {
      return Math.max(seconds * 1000, ARXIV_MIN_REQUEST_INTERVAL_MS);
    }

    const retryAt = Date.parse(retryAfter);
    if (Number.isFinite(retryAt)) {
      return Math.max(retryAt - Date.now(), ARXIV_MIN_REQUEST_INTERVAL_MS);
    }

    return undefined;
  }

  private retryDelayMs(attempt: number, retryAfter: string | null): number {
    return Math.min(
      this.parseRetryAfterMs(retryAfter) ?? ARXIV_RETRY_BASE_MS * 2 ** attempt,
      ARXIV_MAX_RETRY_DELAY_MS,
    );
  }

  private async fetchArxiv(url: string): Promise<Response> {
    let lastError: Error | undefined;

    for (let attempt = 0; attempt <= ARXIV_MAX_RETRIES; attempt += 1) {
      try {
        await waitForArxivSlot();

        const response = await fetch(url, {
          headers: {
            Accept: 'application/atom+xml, application/xml;q=0.9, text/xml;q=0.8',
            'User-Agent': USER_AGENT,
          },
        });

        if (!this.shouldRetryResponse(response) || attempt === ARXIV_MAX_RETRIES) {
          return response;
        }

        const waitMs = this.retryDelayMs(attempt, response.headers.get('Retry-After'));
        await response.text().catch(() => '');
        arxivBackoffUntil = Math.max(arxivBackoffUntil, Date.now() + waitMs);
        console.warn(
          `arXiv 返回 HTTP ${response.status}，等待 ${(waitMs / 1000).toFixed(1)} 秒后重试 (${attempt + 1}/${ARXIV_MAX_RETRIES})`,
        );
      } catch (error) {
        lastError = error as Error;
        if (attempt === ARXIV_MAX_RETRIES) {
          throw lastError;
        }

        const waitMs = this.retryDelayMs(attempt, null);
        arxivBackoffUntil = Math.max(arxivBackoffUntil, Date.now() + waitMs);
        console.warn(
          `arXiv 请求异常，等待 ${(waitMs / 1000).toFixed(1)} 秒后重试 (${attempt + 1}/${ARXIV_MAX_RETRIES}): ${lastError.message}`,
        );
      }
    }

    throw lastError || new Error('arXiv 请求失败');
  }

  // arXiv 返回的是 ISO 时间字符串，这里只取 YYYY-MM-DD。
  private parseDate(dateStr: string): string {
    const match = dateStr.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (match) {
      return `${match[1]}-${match[2]}-${match[3]}`;
    }
    return this.formatDate(new Date(dateStr));
  }

  // categories_filter 模式：
  // 例如主分类是 cs.CV，但只想要同时带 cs.AI/cs.LG 等标签的论文。
  private matchesFilterCategories(
    paper: Paper,
    ruleCategory: string,
    filterCategories: string[],
  ): boolean {
    const paperCats = new Set(paper.categories);
    const otherCats = new Set([...paperCats].filter(cat => cat !== ruleCategory));

    if (otherCats.size === 0) {
      return true;
    }

    return [...otherCats].some(cat => filterCategories.includes(cat));
  }

  // 抓取单个 arXiv 分类。ok=true 且 papers=[] 表示请求成功但当天没有匹配结果。
  private async fetchCategory(rule: DomainRule): Promise<CategoryFetchResult> {
    const url = new URL(ARXIV_API_URL);
    url.searchParams.set('search_query', this.buildSearchQuery(rule));
    url.searchParams.set('max_results', String(this.maxResults));
    url.searchParams.set('sortBy', 'submittedDate');
    url.searchParams.set('sortOrder', 'descending');

    try {
      const response = await this.fetchArxiv(url.toString());

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${await response.text()}`);
      }

      // arXiv API 返回 Atom XML，不是 JSON，所以后面需要自己解析 XML 字符串。
      const xmlData = await response.text();
      const papers = this.parseArxivXml(xmlData, rule);
      console.info(
        `分类 ${rule.category} (模式=${rule.mode}): 获取 ${papers.length} 篇 (日期=${this.targetStr})`,
      );
      return { rule, papers, ok: true };
    } catch (error) {
      console.warn(`获取分类 ${rule.category} 时发生异常: ${(error as Error).message}`);
      return {
        rule,
        papers: [],
        ok: false,
        error: (error as Error).message,
      };
    }
  }

  // 轻量 XML 解析：
  // arXiv 这个接口结构比较稳定，因此这里用正则提取 entry/title/summary 等字段。
  // 如果后续解析需求变复杂，可以替换成专门的 XML parser。
  private parseArxivXml(xmlData: string, rule: DomainRule): Paper[] {
    const papers: Paper[] = [];
    const entryRegex = /<entry[\s\S]*?<\/entry>/g;
    let match: RegExpExecArray | null;

    while ((match = entryRegex.exec(xmlData)) !== null) {
      const entryXml = match[0];

      try {
        const id = this.firstText(entryXml, /<id>([\s\S]*?)<\/id>/);
        const title = this.firstText(entryXml, /<title[^>]*>([\s\S]*?)<\/title>/);
        const summary = this.firstText(entryXml, /<summary[^>]*>([\s\S]*?)<\/summary>/);
        const published = this.firstText(entryXml, /<published>([\s\S]*?)<\/published>/);

        if (!id || !title || !summary || !published) {
          continue;
        }

        const publishedStr = this.parseDate(published);
        if (publishedStr !== this.targetStr) {
          continue;
        }

        // 把 arXiv XML 条目转换成项目内部统一使用的 Paper 对象。
        const paper: Paper = {
          id: this.normalizeArxivId(id),
          source: 'arxiv',
          title: this.normalizeText(title),
          abstract: this.normalizeText(summary),
          authors: this.extractAuthors(entryXml),
          categories: this.extractCategories(entryXml),
          paper_url: this.extractPaperUrl(entryXml),
          published: publishedStr,
        };

        if (rule.mode === 'accept_all') {
          papers.push(paper);
        } else if (this.matchesFilterCategories(paper, rule.category, rule.filter_categories)) {
          papers.push(paper);
        }
      } catch (error) {
        console.warn(`解析论文条目时发生异常: ${(error as Error).message}`);
      }
    }

    return papers;
  }

  // 后处理：
  // 1. 合并多个分类后的重复论文去重；
  // 2. 只有所有分类请求都失败时才抛错；成功但无论文会交给 Pipeline 正常提前结束。
  private postProcess(results: CategoryFetchResult[]): Paper[] {
    const failedResults = results.filter(result => !result.ok);
    if (failedResults.length === results.length && results.length > 0) {
      const details = failedResults
        .map(result => `${result.rule.category}: ${result.error || 'unknown error'}`)
        .join('; ');
      throw new Error(`所有分类嗅探均失败: ${details}`);
    }

    if (failedResults.length > 0) {
      console.warn(
        `部分分类嗅探失败: ${failedResults.map(result => result.rule.category).join(', ')}`,
      );
    }

    const allPapers = results.flatMap(result => result.papers);
    const totalFetched = allPapers.length;
    const seenIds = new Set<string>();
    const deduped: Paper[] = [];

    for (const paper of allPapers) {
      if (!seenIds.has(paper.id)) {
        seenIds.add(paper.id);
        deduped.push(paper);
      }
    }

    console.info(
      `嗅探完成: 获取总数=${totalFetched}, 去重后=${deduped.length} (目标日期=${this.targetStr})`,
    );

    return deduped;
  }

  // 从 XML 片段里提取第一个匹配文本，并处理 XML 转义字符。
  private firstText(xml: string, pattern: RegExp): string {
    const match = xml.match(pattern);
    return match ? this.decodeXml(match[1].trim()) : '';
  }

  // arXiv id 可能带版本号，如 2401.00001v2。
  // 历史去重时通常不希望 v1/v2 被当成两篇不同论文，所以去掉版本号。
  private normalizeArxivId(id: string): string {
    let arxivId = id.replace(/\/$/, '').split('/').pop() || '';
    if (/v\d+$/.test(arxivId)) {
      arxivId = arxivId.replace(/v\d+$/, '');
    }
    return arxivId;
  }

  // 清理多余空白，并把 &amp; 等 XML 转义还原成人能读的字符。
  private normalizeText(text: string): string {
    return this.decodeXml(text).replace(/\s+/g, ' ').trim();
  }

  // 一个 entry 里可能有多个 author，这里全部提取出来。
  private extractAuthors(entryXml: string): string[] {
    const authors: string[] = [];
    const authorRegex = /<author[\s\S]*?<name>([\s\S]*?)<\/name>[\s\S]*?<\/author>/g;
    authorRegex.lastIndex = 0; // 重置正则状态
    let match: RegExpExecArray | null;

    while ((match = authorRegex.exec(entryXml)) !== null) {
      authors.push(this.normalizeText(match[1]));
    }

    return authors;
  }

  // 提取 arXiv 分类标签，如 cs.AI、cs.CL、cs.LG。
  private extractCategories(entryXml: string): string[] {
    const categories = new Set<string>();
    const categoryRegex = /<category[^>]*term="([^"]+)"/g;
    let match: RegExpExecArray | null;

    while ((match = categoryRegex.exec(entryXml)) !== null) {
      categories.add(this.decodeXml(match[1]));
    }

    return [...categories];
  }

  // arXiv entry 的 <id> 是摘要页链接；如果缺失则回退到非 PDF link，再回退到 PDF。
  private extractPaperUrl(entryXml: string): string {
    const id = this.firstText(entryXml, /<id>([\s\S]*?)<\/id>/);
    if (id) {
      return id;
    }

    const linkRegex = /<link\b([^>]*)>/g;
    let match: RegExpExecArray | null;

    while ((match = linkRegex.exec(entryXml)) !== null) {
      const attributes = match[1];
      const href = attributes.match(/href="([^"]+)"/)?.[1] || '';
      const title = attributes.match(/title="([^"]+)"/)?.[1] || '';
      const type = attributes.match(/type="([^"]+)"/)?.[1] || '';
      if (href && title !== 'pdf' && type !== 'application/pdf' && !href.includes('/pdf/')) {
        return this.decodeXml(href);
      }
    }

    return this.extractPdfUrl(entryXml);
  }

  // arXiv entry 里有多个 link，只有 title=pdf 或 type=application/pdf 的才是 PDF。
  private extractPdfUrl(entryXml: string): string {
    const linkRegex = /<link\b([^>]*)>/g;
    let match: RegExpExecArray | null;

    while ((match = linkRegex.exec(entryXml)) !== null) {
      const attributes = match[1];
      const href = attributes.match(/href="([^"]+)"/)?.[1] || '';
      const title = attributes.match(/title="([^"]+)"/)?.[1] || '';
      const type = attributes.match(/type="([^"]+)"/)?.[1] || '';
      if (href && (title === 'pdf' || type === 'application/pdf' || href.includes('/pdf/'))) {
        return this.decodeXml(href);
      }
    }

    return '';
  }

  // 只处理 arXiv 常见 XML entity，避免标题摘要里出现 &amp; 这类字符。
  private decodeXml(value: string): string {
    return value
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/&apos;/g, "'");
  }
}
