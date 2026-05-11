import logging

import arxiv

from src.models import Paper

logger = logging.getLogger(__name__)


class ArxivSniffer:
    """arXiv 论文嗅探器，负责从指定分类获取最新论文"""

    def __init__(self, categories: list[str], max_results: int, processed_ids: list[str]):
        self.categories = categories
        self.max_results = max_results
        self.processed_ids = set(processed_ids)

    def sniff_category(self, category: str) -> list[Paper]:
        """嗅探指定分类下的最新论文"""
        try:
            client = arxiv.Client()
            search = arxiv.Search(
                query=f"cat:{category}",
                max_results=self.max_results,
                sort_by=arxiv.SortCriterion.SubmittedDate,
                sort_order=arxiv.SortOrder.Descending,
            )
            papers: list[Paper] = []
            for result in client.results(search):
                # 从 entry_id 提取 arxiv_id，取路径最后一部分并去掉版本号
                arxiv_id = result.entry_id.rstrip("/").split("/")[-1]
                # 去除版本后缀（如 v1）
                if "v" in arxiv_id:
                    arxiv_id = arxiv_id.rsplit("v", 1)[0]
                paper = Paper(
                    arxiv_id=arxiv_id,
                    title=result.title,
                    abstract=result.summary,
                    authors=[a.name for a in result.authors],
                    categories=list(result.categories),
                    pdf_url=result.pdf_url,
                    published=result.published.strftime("%Y-%m-%d"),
                )
                papers.append(paper)
            return papers
        except Exception:
            logger.warning("嗅探分类 %s 时发生异常", category, exc_info=True)
            return []

    def sniff(self) -> list[Paper]:
        """全领域嗅探，合并去重后返回新论文列表"""
        all_papers: list[Paper] = []
        failed_count = 0

        for category in self.categories:
            papers = self.sniff_category(category)
            if not papers:
                failed_count += 1
            all_papers.extend(papers)

        total_fetched = len(all_papers)

        # 按 arxiv_id 去重，保留第一次出现的
        seen_ids: set[str] = set()
        deduped: list[Paper] = []
        for paper in all_papers:
            if paper.arxiv_id not in seen_ids:
                seen_ids.add(paper.arxiv_id)
                deduped.append(paper)

        dedup_count = len(deduped)

        # 移除已处理过的论文
        new_papers = [p for p in deduped if p.arxiv_id not in self.processed_ids]

        final_count = len(new_papers)

        logger.info(
            "嗅探完成：获取总数=%d，去重后=%d，历史去重后=%d",
            total_fetched,
            dedup_count,
            final_count,
        )

        # 所有领域均失败时抛出异常
        if failed_count == len(self.categories):
            raise RuntimeError("所有分类嗅探均失败")

        return new_papers
