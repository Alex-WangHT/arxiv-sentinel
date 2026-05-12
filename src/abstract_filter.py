from __future__ import annotations

import logging
import time

from .llm_client import LlmClient
from .models import Paper, FilterResult

logger = logging.getLogger(__name__)

_VALID_SCORES = ("HIGH", "MEDIUM", "LOW", "IRRELEVANT")
_SCORE_PRIORITY = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "IRRELEVANT": 0}


class AbstractFilter:
    """基于 LLM 的论文摘要筛选器，评估论文与关键词的相关度"""

    def __init__(
        self,
        llm_client: LlmClient,
        keywords: list[str],
        threshold: str,
        prompts_dir: str,
    ) -> None:
        self.llm_client = llm_client
        self.keywords = keywords
        self.threshold = threshold

        system_path = f"{prompts_dir}/abstract_filter/system.md"
        user_path = f"{prompts_dir}/abstract_filter/user.md"
        with open(system_path, encoding="utf-8") as f:
            self.system_prompt = f.read()
        with open(user_path, encoding="utf-8") as f:
            self.user_template = f.read()

    def filter_paper(self, paper: Paper) -> FilterResult:
        """筛选单篇论文，调用 LLM 评估相关度"""
        user_content = self.user_template.format(
            keywords=", ".join(self.keywords),
            title=paper.title,
            abstract=paper.abstract,
        )

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]

        response = self.llm_client.chat(messages=messages)

        if response.error:
            return FilterResult(
                paper=paper,
                score="IRRELEVANT",
                reason=response.error,
            )

        score = response.data.get("score", "IRRELEVANT") if response.data else "IRRELEVANT"
        reason = response.data.get("reason", "") if response.data else ""

        if score not in _VALID_SCORES:
            score = "IRRELEVANT"

        return FilterResult(paper=paper, score=score, reason=reason)

    def filter_papers(self, papers: list[Paper]) -> list[FilterResult]:
        """批量筛选论文，逐篇调用 filter_paper，每次间隔 0.5 秒"""
        results: list[FilterResult] = []
        for i, paper in enumerate(papers):
            result = self.filter_paper(paper)
            results.append(result)
            if i < len(papers) - 1:
                time.sleep(0.5)
        return results

    def apply_threshold(self, results: list[FilterResult]) -> list[FilterResult]:
        """按阈值过滤，仅保留 score 优先级 >= threshold 的结果"""
        threshold_priority = _SCORE_PRIORITY.get(self.threshold, 0)
        filtered = [
            r for r in results if _SCORE_PRIORITY.get(r.score, 0) >= threshold_priority
        ]
        logger.info(
            "阈值过滤: 过滤前 %d 篇，过滤后 %d 篇", len(results), len(filtered)
        )
        return filtered

if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.llm_client import LlmClient
    llm = LlmClient(
        api_key="sk-yswnbelwichutfnaqifoltczsydrijivpazpkjumpawlupzd",
        model="deepseek-ai/DeepSeek-V4-Flash",
    )
    filter = AbstractFilter(
        llm_client=llm,
        keywords=["deep learning", "machine learning"],
        threshold="MEDIUM",
        prompts_dir="./prompts",
    )