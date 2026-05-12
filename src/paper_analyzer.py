from __future__ import annotations

import asyncio
import logging
from typing import List

from llm_client import LlmClient, LlmResponse
from models import Paper, AnalysisResult

logger = logging.getLogger(__name__)

_VALID_SCORES = ("HIGH", "MEDIUM", "LOW", "IRRELEVANT")
_SCORE_PRIORITY = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "IRRELEVANT": 0}


class PaperAnalyzer:
    """基于 LLM 的论文综合分析器，合并筛选与总结功能（异步版本）"""

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

        system_path = f"{prompts_dir}/paper_analyzer/system.md"
        user_path = f"{prompts_dir}/paper_analyzer/user.md"
        with open(system_path, encoding="utf-8") as f:
            self.system_prompt = f.read()
        with open(user_path, encoding="utf-8") as f:
            self.user_template = f.read()

    def _build_messages(self, paper: Paper) -> List[dict]:
        """构建单篇论文的消息列表"""
        user_content = self.user_template.format(
            keywords=", ".join(self.keywords),
            title=paper.title,
            abstract=paper.abstract,
        )
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]

    def _parse_response(self, paper: Paper, response: LlmResponse) -> AnalysisResult:
        """解析 LLM 响应并转换为 AnalysisResult"""
        if response.error:
            return AnalysisResult(
                paper=paper,
                score="IRRELEVANT",
                reason=response.error,
                core_methods="",
                problem="",
                keywords=[],
            )

        data = response.data
        if not data:
            return AnalysisResult(
                paper=paper,
                score="IRRELEVANT",
                reason="LLM 返回数据为空",
                core_methods="",
                problem="",
                keywords=[],
            )

        score = data.get("score", "IRRELEVANT")
        if score not in _VALID_SCORES:
            score = "IRRELEVANT"

        return AnalysisResult(
            paper=paper,
            score=score,
            reason=data.get("reason", ""),
            core_methods=data.get("core_methods", ""),
            problem=data.get("problem", ""),
            keywords=self._parse_keywords(data.get("keywords", [])),
        )

    def _parse_keywords(self, keywords: list | str) -> list[str]:
        """解析关键词列表，确保返回最多5个关键词"""
        if isinstance(keywords, list):
            return keywords[:5]
        elif isinstance(keywords, str):
            return [keywords.strip()] if keywords.strip() else []
        return []

    async def analyze_paper(self, paper: Paper) -> AnalysisResult:
        """异步分析单篇论文"""
        messages = self._build_messages(paper)
        response = await self.llm_client.achat(messages=messages, json_mode=True)
        return self._parse_response(paper, response)

    async def analyze_papers(
        self, papers: list[Paper], request_interval: float = 0.5, queue_interval: float = 20.0
    ) -> list[AnalysisResult]:
        """异步批量分析论文，多队列并行模式
        
        队列内串行处理，队列间并行执行，队列间隔默认20秒。
        """
        logger.info(f"开始异步分析 {len(papers)} 篇论文，请求间隔: {request_interval} 秒，队列间隔: {queue_interval} 秒")

        messages_list = [self._build_messages(paper) for paper in papers]

        responses = await self.llm_client.batch_achat(
            messages_list=messages_list,
            json_mode=True,
            request_interval=request_interval,
            queue_interval=queue_interval,
        )

        results = [
            self._parse_response(paper, response)
            for paper, response in zip(papers, responses)
        ]

        logger.info(f"异步分析完成，共处理 {len(results)} 篇论文")
        return results

    def apply_threshold(self, results: list[AnalysisResult]) -> list[AnalysisResult]:
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
    from src.models import Paper

    llm = LlmClient(
        api_key="sk-yswnbelwichutfnaqifoltczsydrijivpazpkjumpawlupzd",
        model="deepseek-ai/DeepSeek-V4-Flash",
        base_url="https://api.siliconflow.cn/v1",
    )
    analyzer = PaperAnalyzer(
        llm_client=llm,
        keywords=["Deep Learning"],
        threshold="MEDIUM",
        prompts_dir="./prompts",
    )

    test_paper = Paper(
        arxiv_id="2605.06498",
        title="Lie Group Formulation of Recursive Dynamics Algorithms of Higher Order for Floating-Base Robots",
        abstract="In this paper, we describe procedures for computing higher-order time derivatives of the Lie-group Newton-Euler, Articulated-Body Inertia, and hybrid dynamics algorithms for floating-base trees, where the base configuration evolves on SE(3) and the attached mechanism is an open kinematic tree with configuration on the (n1+n2)-dimensional manifold T^{n1} \\times R^{n2}, using spatial representation of twists.",
        authors=["Gabellieri"],
        categories=["cs.RO", "eecs.SY"],
        pdf_url="https://arxiv.org/pdf/test.pdf",
        published="2026-05-21",
    )

    async def run_test():
        result = await analyzer.analyze_paper(test_paper)
        print(f"评分: {result.score}")
        print(f"理由: {result.reason}")
        print(f"核心方法: {result.core_methods}")
        print(f"解决问题: {result.problem}")
        print(f"关键词: {result.keywords}")

    asyncio.run(run_test())