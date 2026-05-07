"""AbstractFilter — 摘要级初筛（SPEC §4 Step 3 / §5.3）。"""
from __future__ import annotations

import logging
from pathlib import Path

from src.llm_client import LLMClient
from src.sniffer import PaperObject

logger = logging.getLogger(__name__)

_LEVEL_RANK = {"IRRELEVANT": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}


class AbstractFilter:
    def __init__(
        self,
        llm_client: LLMClient,
        model: str,
        threshold: str,
        prompts_dir: Path,
        pdf_cache_dir: Path,
    ) -> None:
        self.llm = llm_client
        self.model = model
        self.threshold = threshold
        self.prompts_dir = prompts_dir
        self.pdf_cache_dir = pdf_cache_dir
        self._system_prompt = self._load_prompt("system.md")
        self._user_template = self._load_prompt("user.md")

    def filter(self, papers: list[PaperObject]) -> list[PaperObject]:
        kept: list[PaperObject] = []
        for paper in papers:
            verdict = self._score(paper)
            if self._passes_threshold(verdict["score"]):
                self._download_pdf(paper)
                kept.append(paper)
        return kept

    def _score(self, paper: PaperObject) -> dict:
        """组装 prompt 调用 LLM，返回 {"score": "HIGH", "reason": "..."}。"""
        raise NotImplementedError

    def _passes_threshold(self, level: str) -> bool:
        return _LEVEL_RANK.get(level, -1) >= _LEVEL_RANK.get(self.threshold, 99)

    def _download_pdf(self, paper: PaperObject) -> None:
        """下载 PDF 至 pdf_cache_dir，写回 paper.pdf_path。"""
        raise NotImplementedError

    def _load_prompt(self, filename: str) -> str:
        return (self.prompts_dir / filename).read_text(encoding="utf-8")
