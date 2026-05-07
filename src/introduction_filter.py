"""IntroductionFilter — PDF 导言级深筛（SPEC §4 Step 4 / §5.3）。"""
from __future__ import annotations

import logging
from pathlib import Path

from src.llm_client import LLMClient
from src.sniffer import PaperObject

logger = logging.getLogger(__name__)

_LEVEL_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


class IntroductionFilter:
    def __init__(
        self,
        llm_client: LLMClient,
        model: str,
        threshold: str,
        prompts_dir: Path,
        pages_to_extract: int = 3,
    ) -> None:
        self.llm = llm_client
        self.model = model
        self.threshold = threshold
        self.prompts_dir = prompts_dir
        self.pages_to_extract = pages_to_extract
        self._system_prompt = self._load_prompt("system.md")
        self._user_template = self._load_prompt("user.md")

    def filter(self, papers: list[PaperObject]) -> list[PaperObject]:
        kept: list[PaperObject] = []
        for paper in papers:
            intro_text = self._extract_intro(paper.pdf_path)
            verdict = self._score(paper, intro_text)
            if self._passes_threshold(verdict["score"]):
                kept.append(paper)
        return kept

    def _extract_intro(self, pdf_path: Path) -> str:
        """pdfplumber 双栏裁剪：按页宽切左右两个 bbox，依次提取拼接，仅取前 N 页。"""
        raise NotImplementedError

    def _score(self, paper: PaperObject, intro_text: str) -> dict:
        """组装 prompt 调用 LLM，返回 {"score": "HIGH", "reason": "..."}。"""
        raise NotImplementedError

    def _passes_threshold(self, level: str) -> bool:
        return _LEVEL_RANK.get(level, -1) >= _LEVEL_RANK.get(self.threshold, 99)

    def _load_prompt(self, filename: str) -> str:
        return (self.prompts_dir / filename).read_text(encoding="utf-8")
