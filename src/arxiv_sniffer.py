import asyncio
import logging
from datetime import date, timedelta
from typing import Optional

import arxiv

from models import DomainRule, Paper

logger = logging.getLogger(__name__)


class ArxivSniffer:
    """arXiv 论文嗅探器（异步版本）"""

    def __init__(
        self,
        domain_rules: list[DomainRule],
        max_results: int,
        processed_ids: list[str],
        target_date: Optional[date] = None,
    ):
        self.domain_rules = domain_rules
        self.max_results = max_results
        self.processed_ids = set(processed_ids)
        today = date.today()
        if target_date is None:
            self.target_date = today - timedelta(days=2)
        else:
            self.target_date = min(target_date, today - timedelta(days=2))
        self.target_str = self.target_date.strftime("%Y-%m-%d")

    def _matches_filter_categories(self, paper: Paper, rule_category: str, filter_categories: list[str]) -> bool:
        """检查论文是否满足 categories_filter 规则"""
        paper_cats = set(paper.categories)
        other_cats = paper_cats - {rule_category}
        if not other_cats:
            return True
        return bool(other_cats & set(filter_categories))

    def _fetch_category(self, rule: DomainRule) -> list[Paper]:
        """获取单个分类的论文（同步方法，在后台线程中执行）"""
        try:
            client = arxiv.Client()
            search = arxiv.Search(
                query=f"cat:{rule.category}",
                max_results=self.max_results,
                sort_by=arxiv.SortCriterion.SubmittedDate,
                sort_order=arxiv.SortOrder.Descending,
            )

            papers: list[Paper] = []
            for result in client.results(search):
                arxiv_id = result.entry_id.rstrip("/").split("/")[-1]
                if "v" in arxiv_id:
                    arxiv_id = arxiv_id.rsplit("v", 1)[0]

                published_str = result.published.strftime("%Y-%m-%d")
                if published_str != self.target_str:
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

            logger.info(
                "分类 %s (模式=%s): 获取 %d 篇 (日期=%s)",
                rule.category,
                rule.mode,
                len(papers),
                self.target_str,
            )
            return papers

        except Exception as e:
            logger.warning("获取分类 %s 时发生异常: %s", rule.category, str(e))
            return []

    async def sniff(self) -> list[Paper]:
        """异步全领域嗅探，合并去重后返回新论文列表"""
        logger.info("开始嗅探，目标日期: %s", self.target_str)

        # 使用 asyncio.to_thread 在后台线程中并行执行同步任务
        tasks = [
            asyncio.to_thread(self._fetch_category, rule)
            for rule in self.domain_rules
        ]

        results = await asyncio.gather(*tasks)

        # 合并所有结果
        all_papers: list[Paper] = []
        for papers in results:
            all_papers.extend(papers)

        return self._post_process(all_papers)

    def _post_process(self, all_papers: list[Paper]) -> list[Paper]:
        """后处理：去重和过滤已处理的论文"""
        total_fetched = len(all_papers)

        # 去重
        seen_ids: set[str] = set()
        deduped: list[Paper] = []
        for paper in all_papers:
            if paper.arxiv_id not in seen_ids:
                seen_ids.add(paper.arxiv_id)
                deduped.append(paper)

        dedup_count = len(deduped)

        # 过滤已处理的论文
        new_papers = [p for p in deduped if p.arxiv_id not in self.processed_ids]
        final_count = len(new_papers)

        logger.info(
            "嗅探完成：获取总数=%d，去重后=%d，历史去重后=%d (目标日期=%s)",
            total_fetched,
            dedup_count,
            final_count,
            self.target_str,
        )

        if not all_papers and len(self.domain_rules) > 0:
            raise RuntimeError("所有分类嗅探均失败")

        return new_papers

    # 为了兼容 pipeline 中的调用，保留别名
    sniff_async = sniff


if __name__ == "__main__":
    async def run_test():
        sniffer = ArxivSniffer(
            domain_rules=[
                DomainRule(category="cs.CV", mode="categories_filter", filter_categories=["cs.AI", "cs.CL", "cs.RO", "cs.LG"]),
                DomainRule(category="cs.RO", mode="accept_all", filter_categories=[]),
            ],
            max_results=10,
            processed_ids=[],
        )
        papers = await sniffer.sniff()
        print(f"嗅探到 {len(papers)} 篇论文")
        for paper in papers:
            print(f"论文编号：{paper.arxiv_id}，分类：{paper.categories}，标题：{paper.title}")

    asyncio.run(run_test())