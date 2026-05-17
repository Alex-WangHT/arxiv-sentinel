import { DomainRule, Paper, PaperSniffer, SniffProgressReporter } from './models';

const ARXIV_OAI_URL = 'https://oaipmh.arxiv.org/oai';
const USER_AGENT = 'PaperSniffer/1.0 (Cloudflare Workers compatible)';
const BROWSER_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36';
const ARXIV_REQUEST_TIMEOUT_MS = 30000;
const ARXIV_MAX_RETRIES = 3;
const ARXIV_RETRY_DELAY_MS = 1500;
const BEIJING_TIME_OFFSET_MS = 8 * 60 * 60 * 1000;

interface CategoryFetchResult {
  rule: DomainRule;
  papers: Paper[];
  rawRecordCount: number;
}

interface CategoryFetchContext {
  categoryIndex: number;
  totalCategories: number;
  progress?: SniffProgressReporter;
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

export class ArxivSniffer implements PaperSniffer {
  readonly name: string;
  private domainRules: DomainRule[];
  private sourceId: string;
  private targetDate!: Date;
  private targetStr!: string;

  constructor(
    domainRules: DomainRule[],
    targetDate?: Date,
    sourceId = 'arxiv',
    sourceName = 'arXiv',
  ) {
    this.name = sourceName;
    this.domainRules = domainRules;
    this.sourceId = sourceId;
    this.setTargetDate(targetDate);
  }

  private setTargetDate(targetDate?: Date): void {
    this.targetDate = targetDate ? new Date(targetDate) : new Date(Date.now() + BEIJING_TIME_OFFSET_MS);
    this.targetStr = this.formatDate(this.targetDate);
  }

  async sniff(targetDate?: Date, progress?: SniffProgressReporter): Promise<Paper[]> {
    if (targetDate) {
      this.setTargetDate(targetDate);
    }

    console.info(`Starting ${this.name} OAI-PMH sniff for ${this.targetStr}`);

    const results: CategoryFetchResult[] = [];
    for (const [index, rule] of this.domainRules.entries()) {
      results.push(await this.fetchCategory(rule, {
        categoryIndex: index + 1,
        totalCategories: this.domainRules.length,
        progress,
      }));
    }

    return this.postProcess(results);
  }

  private formatDate(date: Date): string {
    const year = date.getUTCFullYear();
    const month = String(date.getUTCMonth() + 1).padStart(2, '0');
    const day = String(date.getUTCDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  private oaiSetForCategory(category: string): string {
    const [archive, subject] = category.split('.');
    if (archive && subject) {
      return `${archive}:${archive}:${subject}`;
    }
    return category;
  }

  private buildOaiUrl(rule: DomainRule): string {
    const url = new URL(ARXIV_OAI_URL);
    url.searchParams.set('verb', 'ListRecords');
    url.searchParams.set('metadataPrefix', 'arXiv');
    url.searchParams.set('from', this.targetStr);
    url.searchParams.set('until', this.targetStr);
    url.searchParams.set('set', this.oaiSetForCategory(rule.category));
    return url.toString();
  }

  private async fetchArxivXml(url: string): Promise<string> {
    let lastError: Error | undefined;

    for (let attempt = 0; attempt <= ARXIV_MAX_RETRIES; attempt += 1) {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), ARXIV_REQUEST_TIMEOUT_MS);

      try {
        const response = await fetch(url, {
          signal: controller.signal,
          headers: {
            Accept: 'application/xml,text/xml,application/xhtml+xml,text/html;q=0.8,*/*;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            Referer: 'https://arxiv.org/',
            'User-Agent': BROWSER_USER_AGENT,
            'X-PaperSniffer-User-Agent': USER_AGENT,
          },
        });

        const body = await response.text();
        if (response.ok) {
          return body;
        }

        lastError = new Error(`HTTP ${response.status}: ${body.slice(0, 500)}`);
      } catch (error) {
        lastError = error as Error;
      } finally {
        clearTimeout(timeoutId);
      }

      if (attempt < ARXIV_MAX_RETRIES) {
        console.warn(
          `arXiv OAI-PMH request failed; retrying (${attempt + 1}/${ARXIV_MAX_RETRIES}): ${lastError?.message || 'unknown error'}`,
        );
        await sleep(ARXIV_RETRY_DELAY_MS * (attempt + 1));
      }
    }

    throw new Error(
      `arXiv OAI-PMH request failed after ${ARXIV_MAX_RETRIES} retries: ${lastError?.message || 'unknown error'}`,
    );
  }

  private parseDate(dateStr: string): string {
    const match = dateStr.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (match) {
      return `${match[1]}-${match[2]}-${match[3]}`;
    }
    return this.formatDate(new Date(dateStr));
  }

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

  private matchesRuleCategory(paper: Paper, rule: DomainRule): boolean {
    if (!paper.categories.includes(rule.category)) {
      return false;
    }

    return rule.mode === 'accept_all'
      || this.matchesFilterCategories(paper, rule.category, rule.filter_categories);
  }

  private async fetchCategory(
    rule: DomainRule,
    context: CategoryFetchContext,
  ): Promise<CategoryFetchResult> {
    const url = this.buildOaiUrl(rule);
    console.info(`Requesting arXiv OAI-PMH category ${rule.category}: date=${this.targetStr}`);
    console.info(`arXiv OAI-PMH request URL: ${url}`);

    const xmlData = await this.fetchArxivXml(url);
    const rawRecordCount = this.countArxivRecords(xmlData);
    const papers = this.parseArxivXml(xmlData, rule);

    console.info(
      `Category ${rule.category}: OAI raw=${rawRecordCount}, matched=${papers.length}`,
    );

    await context.progress?.({
      source: this.sourceId,
      sourceName: this.name,
      sourceIndex: 1,
      totalSources: 1,
      category: rule.category,
      categoryIndex: context.categoryIndex,
      totalCategories: context.totalCategories,
      page: 1,
      rawEntryCount: rawRecordCount,
      matchedCount: papers.length,
      totalMatched: papers.length,
      message: `${this.name} ${rule.category}: raw ${rawRecordCount}, matched ${papers.length}`,
    });

    return { rule, papers, rawRecordCount };
  }

  private parseArxivXml(xmlData: string, rule: DomainRule): Paper[] {
    const papers: Paper[] = [];
    const recordRegex = /<record[\s\S]*?<\/record>/g;
    let match: RegExpExecArray | null;

    while ((match = recordRegex.exec(xmlData)) !== null) {
      const recordXml = match[0];
      if (/<header\b[^>]*\bstatus="deleted"/.test(recordXml)) {
        continue;
      }

      try {
        const id = this.firstTagText(recordXml, 'id') || this.firstText(recordXml, /<identifier>([\s\S]*?)<\/identifier>/);
        const title = this.firstTagText(recordXml, 'title');
        const summary = this.firstTagText(recordXml, 'abstract');
        const datestamp = this.firstText(recordXml, /<datestamp>([\s\S]*?)<\/datestamp>/);
        const created = this.firstTagText(recordXml, 'created');

        if (!id || !title || !summary) {
          continue;
        }

        const paper: Paper = {
          id: this.normalizeArxivId(id),
          source: this.sourceId,
          title: this.normalizeText(title),
          abstract: this.normalizeText(summary),
          authors: this.extractAuthors(recordXml),
          categories: this.extractCategories(recordXml),
          paper_url: this.extractPaperUrl(recordXml),
          published: this.parseDate(created || datestamp || this.targetStr),
        };

        if (this.matchesRuleCategory(paper, rule)) {
          papers.push(paper);
        }
      } catch (error) {
        console.warn(`Failed to parse arXiv OAI-PMH record: ${(error as Error).message}`);
      }
    }

    return papers;
  }

  private countArxivRecords(xmlData: string): number {
    return xmlData.match(/<record[\s\S]*?<\/record>/g)?.length || 0;
  }

  private postProcess(results: CategoryFetchResult[]): Paper[] {
    const allPapers = results.flatMap(result => result.papers);
    const seenIds = new Set<string>();
    const deduped: Paper[] = [];

    for (const paper of allPapers) {
      if (!seenIds.has(paper.id)) {
        seenIds.add(paper.id);
        deduped.push(paper);
      }
    }

    console.info(
      `Sniff complete: fetched=${allPapers.length}, deduped=${deduped.length} (targetDate=${this.targetStr})`,
    );

    return deduped;
  }

  private firstText(xml: string, pattern: RegExp): string {
    const match = xml.match(pattern);
    return match ? this.decodeXml(match[1].trim()) : '';
  }

  private firstTagText(xml: string, tagName: string): string {
    return this.firstText(
      xml,
      new RegExp(`<(?:[\\w.-]+:)?${tagName}\\b[^>]*>([\\s\\S]*?)<\\/(?:[\\w.-]+:)?${tagName}>`),
    );
  }

  private normalizeArxivId(id: string): string {
    let arxivId = id.replace(/^oai:arXiv\.org:/, '').replace(/\/$/, '').split('/').pop() || '';
    if (/v\d+$/.test(arxivId)) {
      arxivId = arxivId.replace(/v\d+$/, '');
    }
    return arxivId;
  }

  private normalizeText(text: string): string {
    return this.decodeXml(text).replace(/\s+/g, ' ').trim();
  }

  private extractAuthors(recordXml: string): string[] {
    const authors: string[] = [];
    const authorRegex = /<author\b[^>]*>([\s\S]*?)<\/author>/g;
    let match: RegExpExecArray | null;

    while ((match = authorRegex.exec(recordXml)) !== null) {
      const authorXml = match[1];
      const name = this.firstTagText(authorXml, 'name');
      if (name) {
        authors.push(this.normalizeText(name));
        continue;
      }

      const forenames = this.firstTagText(authorXml, 'forenames');
      const keyname = this.firstTagText(authorXml, 'keyname');
      const suffix = this.firstTagText(authorXml, 'suffix');
      const parts = [forenames, keyname, suffix].map(part => this.normalizeText(part)).filter(Boolean);
      if (parts.length > 0) {
        authors.push(parts.join(' '));
      }
    }

    return authors;
  }

  private extractCategories(recordXml: string): string[] {
    const categories = new Set<string>();
    const categoryRegex = /<category[^>]*term="([^"]+)"/g;
    let match: RegExpExecArray | null;

    while ((match = categoryRegex.exec(recordXml)) !== null) {
      categories.add(this.decodeXml(match[1]));
    }

    const categoriesText = this.firstTagText(recordXml, 'categories');
    for (const category of categoriesText.split(/\s+/).map(value => value.trim()).filter(Boolean)) {
      categories.add(category);
    }

    return [...categories];
  }

  private extractPaperUrl(recordXml: string): string {
    const id = this.firstTagText(recordXml, 'id') || this.firstText(recordXml, /<identifier>([\s\S]*?)<\/identifier>/);
    if (id) {
      const trimmed = id.trim();
      if (/^https?:\/\//i.test(trimmed)) {
        return trimmed;
      }
      return `https://arxiv.org/abs/${this.normalizeArxivId(trimmed)}`;
    }

    return '';
  }

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
