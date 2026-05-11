from __future__ import annotations

import logging
from datetime import date, timedelta

import arxiv

from src.models import DomainRule, Paper

logger = logging.getLogger(__name__)


class ArxivSniffer:
    """arXiv 论文嗅探器，按领域规则获取前一日论文并做分类交叉筛选"""

    def __init__(
        self,
        domain_rules: list[DomainRule],
        max_results: int,
        processed_ids: list[str],
        target_date: date | None = None,
    ):
        self.domain_rules = domain_rules
        self.max_results = max_results
        self.processed_ids = set(processed_ids)
        self.target_date = target_date or (date.today() - timedelta(days=1))

    def _matches_filter_categories(self, paper: Paper, rule_category: str, filter_categories: list[str]) -> bool:
        """检查论文是否满足 categories_filter 规则：
        - 如果论文只有本领域分类，保留
        - 如果论文有额外分类，且额外分类中至少一个在 filter_categories 中，保留
        - 否则丢弃
        """
        paper_cats = set(paper.categories)
        other_cats = paper_cats - {rule_category}
        if not other_cats:
            return True
        return bool(other_cats & set(filter_categories))

    def sniff_category(self, rule: DomainRule) -> list[Paper]:
        """嗅探指定分类下的论文，按发布日期过滤并做分类交叉筛选"""
        try:
            client = arxiv.Client()
            search = arxiv.Search(
                query=f"cat:{rule.category}",
                max_results=self.max_results,
                sort_by=arxiv.SortCriterion.SubmittedDate,
                sort_order=arxiv.SortOrder.Descending,
            )
            papers: list[Paper] = []
            target_str = self.target_date.strftime("%Y-%m-%d")

            for result in client.results(search):
                arxiv_id = result.entry_id.rstrip("/").split("/")[-1]
                if "v" in arxiv_id:
                    arxiv_id = arxiv_id.rsplit("v", 1)[0]

                published_str = result.published.strftime("%Y-%m-%d")

                if published_str != target_str:
                    continue

                paper = Paper(
                    arxiv_id=arxiv_id,
                    title=result.title,
                    abstract=result.summary,
                    authors=[a.name for a in result.authors],
                    categories=list(result.categories),
                    pdf_url=result.pdf_url,
                    published=published_str,
                )

                if rule.mode == "accept_all":
                    papers.append(paper)
                elif rule.mode == "categories_filter":
                    if self._matches_filter_categories(paper, rule.category, rule.filter_categories):
                        papers.append(paper)
                    else:
                        logger.debug(
                            "论文 %s 未命中交叉分类，跳过 (分类=%s, 需匹配=%s)",
                            paper.arxiv_id,
                            rule.category,
                            rule.filter_categories,
                        )

            logger.info(
                "分类 %s (模式=%s): 获取 %d 篇 (日期=%s)",
                rule.category,
                rule.mode,
                len(papers),
                target_str,
            )
            return papers
        except Exception:
            logger.warning("嗅探分类 %s 时发生异常", rule.category, exc_info=True)
            return []

    def sniff(self) -> list[Paper]:
        """全领域嗅探，合并去重后返回新论文列表"""
        all_papers: list[Paper] = []
        failed_count = 0

        for rule in self.domain_rules:
            papers = self.sniff_category(rule)
            if not papers:
                failed_count += 1
            all_papers.extend(papers)

        total_fetched = len(all_papers)

        seen_ids: set[str] = set()
        deduped: list[Paper] = []
        for paper in all_papers:
            if paper.arxiv_id not in seen_ids:
                seen_ids.add(paper.arxiv_id)
                deduped.append(paper)

        dedup_count = len(deduped)

        new_papers = [p for p in deduped if p.arxiv_id not in self.processed_ids]

        final_count = len(new_papers)

        logger.info(
            "嗅探完成：获取总数=%d，去重后=%d，历史去重后=%d (目标日期=%s)",
            total_fetched,
            dedup_count,
            final_count,
            self.target_date.strftime("%Y-%m-%d"),
        )

        if failed_count == len(self.domain_rules):
            raise RuntimeError("所有分类嗅探均失败")

        return new_papers
