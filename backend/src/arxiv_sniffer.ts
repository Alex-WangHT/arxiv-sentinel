import * as https from 'https';
import { DomainRule, Paper } from './models';

interface ArxivEntry {
  id: string;
  title: string;
  summary: string;
  author: { name: string }[] | { name: string };
  category: { term: string }[];
  link: { href: string; title?: string }[];
  published: string;
}

interface ArxivResponse {
  feed: {
    entry: ArxivEntry[];
  };
}

export class ArxivSniffer {
  private domainRules: DomainRule[];
  private maxResults: number;
  private processedIds: Set<string>;
  private targetDate: Date;
  private targetStr: string;

  constructor(
    domainRules: DomainRule[],
    maxResults: number,
    processedIds: string[],
    targetDate?: Date,
  ) {
    this.domainRules = domainRules;
    this.maxResults = maxResults;
    this.processedIds = new Set(processedIds);

    const today = new Date();
    const twoDaysAgo = new Date(today);
    twoDaysAgo.setDate(twoDaysAgo.getDate() - 2);

    if (targetDate) {
      this.targetDate = new Date(Math.min(targetDate.getTime(), twoDaysAgo.getTime()));
    } else {
      this.targetDate = twoDaysAgo;
    }

    this.targetStr = this.formatDate(this.targetDate);
  }

  private formatDate(date: Date): string {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  private parseDate(dateStr: string): string {
    const match = dateStr.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (match) {
      return `${match[1]}-${match[2]}-${match[3]}`;
    }
    const date = new Date(dateStr);
    return this.formatDate(date);
  }

  private matchesFilterCategories(paper: Paper, ruleCategory: string, filterCategories: string[]): boolean {
    const paperCats = new Set(paper.categories);
    const otherCats = new Set([...paperCats].filter(cat => cat !== ruleCategory));
    
    if (otherCats.size === 0) {
      return true;
    }

    return [...otherCats].some(cat => filterCategories.includes(cat));
  }

  private async fetchCategory(rule: DomainRule): Promise<Paper[]> {
    return new Promise((resolve) => {
      const query = encodeURIComponent(`cat:${rule.category}`);
      const url = `https://export.arxiv.org/api/query?search_query=${query}&max_results=${this.maxResults}&sortBy=submittedDate&sortOrder=descending`;

      https.get(url, (res) => {
        let data = '';
        res.on('data', (chunk) => {
          data += chunk;
        });
        res.on('end', () => {
          try {
            const xmlData = data;
            const papers = this.parseArxivXml(xmlData, rule);
            console.info(
              `分类 ${rule.category} (模式=${rule.mode}): 获取 ${papers.length} 篇 (日期=${this.targetStr})`,
            );
            resolve(papers);
          } catch (e) {
            console.warn(`解析分类 ${rule.category} 时发生异常: ${(e as Error).message}`);
            resolve([]);
          }
        });
      }).on('error', (e) => {
        console.warn(`获取分类 ${rule.category} 时发生异常: ${(e as Error).message}`);
        resolve([]);
      });
    });
  }

  private parseArxivXml(xmlData: string, rule: DomainRule): Paper[] {
    const papers: Paper[] = [];
    
    const entryRegex = /<entry[\s\S]*?<\/entry>/g;
    let match;
    
    while ((match = entryRegex.exec(xmlData)) !== null) {
      const entryXml = match[0];
      
      try {
        const idMatch = entryXml.match(/<id>([^<]+)<\/id>/);
        const titleMatch = entryXml.match(/<title[^>]*>([^<]+)<\/title>/);
        const summaryMatch = entryXml.match(/<summary[^>]*>([\s\S]*?)<\/summary>/);
        const publishedMatch = entryXml.match(/<published>([^<]+)<\/published>/);
        const categoryMatches = entryXml.match(/<category[^>]*term="([^"]+)"/g);
        const linkMatches = entryXml.match(/<link[^>]*href="([^"]+)"/g);
        
        if (!idMatch || !titleMatch || !summaryMatch || !publishedMatch) {
          continue;
        }
        
        let arxivId = idMatch[1].replace(/\/$/, '').split('/').pop() || '';
        if (arxivId.includes('v')) {
          arxivId = arxivId.split('v')[0];
        }
        
        const publishedStr = this.parseDate(publishedMatch[1]);
        if (publishedStr !== this.targetStr) {
          continue;
        }
        
        const authors: string[] = [];
        const authorRegex = /<author[\s\S]*?<name>([^<]+)<\/name>[\s\S]*?<\/author>/g;
        let authorMatch;
        while ((authorMatch = authorRegex.exec(entryXml)) !== null) {
          authors.push(authorMatch[1]);
        }
        
        const categories: string[] = [];
        if (categoryMatches) {
          categoryMatches.forEach(catMatch => {
            const catTerm = catMatch.match(/term="([^"]+)"/);
            if (catTerm) {
              categories.push(catTerm[1]);
            }
          });
        }
        
        let pdfUrl = '';
        if (linkMatches) {
          for (const linkMatch of linkMatches) {
            const href = linkMatch.match(/href="([^"]+)"/);
            if (href && href[1].endsWith('.pdf')) {
              pdfUrl = href[1];
              break;
            }
          }
        }
        
        const paper: Paper = {
          arxiv_id: arxivId,
          title: titleMatch[1].trim(),
          abstract: summaryMatch[1].trim(),
          authors,
          categories,
          pdf_url: pdfUrl,
          published: publishedStr,
        };
        
        if (rule.mode === 'accept_all') {
          papers.push(paper);
        } else if (rule.mode === 'categories_filter') {
          if (this.matchesFilterCategories(paper, rule.category, rule.filter_categories)) {
            papers.push(paper);
          }
        }
        
      } catch (e) {
        console.warn(`解析论文条目时发生异常: ${(e as Error).message}`);
        continue;
      }
    }
    
    return papers;
  }

  async sniff(): Promise<Paper[]> {
    console.info(`开始嗅探，目标日期: ${this.targetStr}`);

    const tasks = this.domainRules.map(rule => this.fetchCategory(rule));
    const results = await Promise.all(tasks);

    const allPapers: Paper[] = results.flat();
    return this.postProcess(allPapers);
  }

  sniffAsync = this.sniff;

  private postProcess(allPapers: Paper[]): Paper[] {
    const totalFetched = allPapers.length;

    const seenIds = new Set<string>();
    const deduped: Paper[] = [];
    for (const paper of allPapers) {
      if (!seenIds.has(paper.arxiv_id)) {
        seenIds.add(paper.arxiv_id);
        deduped.push(paper);
      }
    }

    const dedupCount = deduped.length;

    const newPapers = deduped.filter(p => !this.processedIds.has(p.arxiv_id));
    const finalCount = newPapers.length;

    console.info(
      `嗅探完成：获取总数=${totalFetched}，去重后=${dedupCount}，历史去重后=${finalCount} (目标日期=${this.targetStr})`,
    );

    if (allPapers.length === 0 && this.domainRules.length > 0) {
      throw new Error('所有分类嗅探均失败');
    }

    return newPapers;
  }
}

if (require.main === module) {
  const runTest = async () => {
    const sniffer = new ArxivSniffer(
      [
        { category: 'cs.CV', mode: 'categories_filter', filter_categories: ['cs.AI', 'cs.CL', 'cs.RO', 'cs.LG'] },
        { category: 'cs.RO', mode: 'accept_all', filter_categories: [] },
      ],
      10,
      [],
    );

    const papers = await sniffer.sniff();
    console.log(`嗅探到 ${papers.length} 篇论文`);
    for (const paper of papers) {
      console.log(`论文编号：${paper.arxiv_id}，分类：${paper.categories}，标题：${paper.title}`);
    }
  };

  runTest().catch(console.error);
}