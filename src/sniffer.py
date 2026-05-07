"""ArxivSniffer — arXiv API 嗅探与去重（SPEC §4 Step 2 / §5.3）。"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PaperObject:
    arxiv_id: str
    title: str
    abstract: str
    authors: list[str]
    categories: list[str]
    url: str
    published: str
    keywords: list[str] = field(default_factory=list)
    pdf_path: Path | None = None
    ai_score: float | None = None


class ArxivSniffer:
    def __init__(
        self,
        categories: list[str],
        keywords: list[str],
        history_file: Path,
        papers_dir: Path,
        max_results_per_keyword: int = 50,
        request_interval_seconds: int = 3,
    ) -> None:
        self.categories = categories
        self.keywords = keywords
        self.history_file = history_file
        self.papers_dir = papers_dir
        self.max_results_per_keyword = max_results_per_keyword
        self.request_interval_seconds = request_interval_seconds

    def sniff(self) -> list[PaperObject]:
        """主入口：多关键词检索 → 聚合去重 → 增量过滤。"""
        aggregated = self._fetch_and_aggregate()
        new_papers = self._filter_processed(aggregated)
        return new_papers

    def _fetch_and_aggregate(self) -> dict[str, PaperObject]:
        """遍历 keywords 调用 arXiv API；同 arxiv_id 取并集 keywords；每次请求间隔 ≥3s。"""
        raise NotImplementedError

    def _filter_processed(self, papers: dict[str, PaperObject]) -> list[PaperObject]:
        """优先用 history.json#processed_ids；辅助扫描 docs/papers/*.md 文件名。新版本视为未处理。"""
        raise NotImplementedError

    def _load_processed_ids(self) -> set[str]:
        """读取 cache/history.json 中的 processed_ids。"""
        raise NotImplementedError

    def _scan_existing_papers(self) -> set[str]:
        """扫描 docs/papers/YYYY-MM-DD-[arxiv_id].md 提取 arxiv_id。"""
        raise NotImplementedError
