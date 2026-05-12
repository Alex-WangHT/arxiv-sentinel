import asyncio
import logging
from datetime import date, timedelta
from typing import Optional

import arxiv

from models import DomainRule, Paper

logger = logging.getLogger(__name__)


class ArxivSniffer:
    """arXiv 论文嗅探器，按领域规则获取前一日论文并做分类交叉筛选"""

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
            self.target_date = today - timedelta(days=1)
        else:
            self.target_date = min(target_date, today - timedelta(days=1))
        self.target_str = self.target_date.strftime("%Y-%m-%d")

    def _matches_filter_categories(self, paper: Paper, rule_category: str, filter_categories: list[str]) -> bool:
        """检查论文是否满足 categories_filter 规则：
        - 如果论文只有本领域分类，保留
        - 如果论文有其他领域分类，至少有一个额外分类在 filter_categories 中就保留
        - 所有额外分类都不在 filter_categories 中，就丢弃
        """
        paper_cats = set(paper.categories)
        other_cats = paper_cats - {rule_category}
        if not other_cats:
            return True
        return bool(other_cats & set(filter_categories))

    def _fetch_category(self, rule: DomainRule) -> list[Paper]:
        """获取单个分类的论文"""
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
                self.target_str,
            )
            return papers

        except Exception as e:
            logger.warning("获取分类 %s 时发生异常: %s", rule.category, str(e))
            return []

    def sniff(self) -> list[Paper]:
        """全领域嗅探，合并去重后返回新论文列表"""
        logger.info("开始嗅探，目标日期: %s", self.target_str)

        # 使用线程池并发获取所有分类的论文
        all_papers: list[Paper] = []
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # 将同步任务包装为异步任务
            async def async_fetch():
                tasks = []
                for rule in self.domain_rules:
                    task = loop.run_in_executor(None, self._fetch_category, rule)
                    tasks.append(task)
                
                results = await asyncio.gather(*tasks)
                return results
            
            results = loop.run_until_complete(async_fetch())
            
            # 合并所有结果
            for papers in results:
                all_papers.extend(papers)
        finally:
            loop.close()

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


if __name__ == "__main__":
    # 测试嗅探器
    sniffer = ArxivSniffer(
        domain_rules=[
            DomainRule(category="cs.CV", mode="categories_filter", filter_categories=["cs.AI", "cs.CL", "cs.RO", "cs.LG"]),
            DomainRule(category="cs.RO", mode="accept_all", filter_categories=[]),
        ],
        max_results=100,
        processed_ids=[],
    )
    papers = sniffer.sniff()
    print(f"嗅探到 {len(papers)} 篇论文")
    for paper in papers:
        print(f"论文编号：{paper.arxiv_id}，分类：{paper.categories}，标题：{paper.title}")