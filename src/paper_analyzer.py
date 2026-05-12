from __future__ import annotations

import logging
import time

from llm_client import LlmClient
from models import Paper, AnalysisResult

logger = logging.getLogger(__name__)

_VALID_SCORES = ("HIGH", "MEDIUM", "LOW", "IRRELEVANT")
_SCORE_PRIORITY = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "IRRELEVANT": 0}


class PaperAnalyzer:
    """基于 LLM 的论文综合分析器，合并筛选与总结功能

    逻辑流程：
    1. 先让 AI 总结相关度、关键词、评估结果和理由、解决什么问题、用了什么方法
    2. 然后进行筛选逻辑（基于阈值过滤）
    3. 最后保存总结
    """

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

    def analyze_paper(self, paper: Paper) -> AnalysisResult:
        """对单篇论文进行综合分析：评估相关度并提取核心信息"""
        user_content = self.user_template.format(
            keywords=", ".join(self.keywords),
            title=paper.title,
            abstract=paper.abstract,
        )

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]

        response = self.llm_client.chat(messages=messages, json_mode=True)

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

    def analyze_papers(self, papers: list[Paper]) -> list[AnalysisResult]:
        """批量分析论文，逐篇调用 analyze_paper，每次间隔 0.5 秒"""
        results: list[AnalysisResult] = []
        for i, paper in enumerate(papers):
            logger.info(f"正在分析论文 {i+1}/{len(papers)}: {paper.arxiv_id}")
            result = self.analyze_paper(paper)
            results.append(result)
            if i < len(papers) - 1:
                time.sleep(0.5)
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
        abstract="In this paper, we describe procedures for computing higher-order time derivatives of the Lie-group Newton-Euler, Articulated-Body Inertia, and hybrid dynamics algorithms for floating-base trees, where the base configuration evolves on SE(3) and the attached mechanism is an open kinematic tree with configuration on the (n1+n2)-dimensional manifold T^{n1} \times R^{n2}, using spatial representation of twists. After presenting the algorithms, we collect the resulting recursions into closed-form equations of motion, identifying an admissible Coriolis matrix satisfying the passivity property, and showing that the articulated inertia tensor remains unchanged across all time derivatives. We then apply the developed methods to a 12-DoF aerial manipulator to derive analytical expressions for its geometric forward and inverse dynamics along with their first time derivatives whereas the numerical simulations successfully evaluate these dynamics up to fifth order. Finally, to demonstrate their practical utility, we benchmark the proposed extensions and show that, in the considered tests, their computational cost scales quadratically with the derivative order, whereas the automatic-differentiation baseline exhibits exponential scaling.",
        authors=["Gabellieri"],
        categories=["cs.RO","eecs.SY"],
        pdf_url="https://arxiv.org/pdf/test.pdf",
        published="2026-05-21",
    )

    result = analyzer.analyze_paper(test_paper)
    print(f"评分: {result.score}")
    print(f"理由: {result.reason}")
    print(f"核心方法: {result.core_methods}")
    print(f"解决问题: {result.problem}")
    print(f"关键词: {result.keywords}")