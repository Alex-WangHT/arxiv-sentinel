import logging
import time

from .llm_client import LlmClient
from .models import Paper, SummaryResult

logger = logging.getLogger(__name__)


class PaperSummarizer:
    """基于 LLM 的论文总结器，对论文标题和摘要进行深度分析"""

    def __init__(
        self,
        llm_client: LlmClient,
        prompts_dir: str,
    ) -> None:
        self.llm_client = llm_client

        system_path = f"{prompts_dir}/paper_summary/system.md"
        user_path = f"{prompts_dir}/paper_summary/user.md"
        with open(system_path, encoding="utf-8") as f:
            self.system_prompt = f.read()
        with open(user_path, encoding="utf-8") as f:
            self.user_template = f.read()

    def summarize(self, paper: Paper) -> SummaryResult:
        """对单篇论文进行总结，提取核心技术方法、问题和关键词"""
        user_content = self.user_template.format(
            title=paper.title,
            abstract=paper.abstract,
        )

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]

        response = self.llm_client.chat(messages=messages)

        if response.error:
            return SummaryResult(
                paper=paper,
                core_methods="",
                problem="",
                keywords=[],
                error=response.error,
            )

        data = response.data
        if not data:
            return SummaryResult(
                paper=paper,
                core_methods="",
                problem="",
                keywords=[],
                error="LLM 返回数据为空",
            )

        core_methods = data.get("core_methods", "")
        problem = data.get("problem", "")
        keywords = data.get("keywords", [])

        if not isinstance(keywords, list):
            keywords = []
        else:
            keywords = keywords[:5]

        return SummaryResult(
            paper=paper,
            core_methods=core_methods,
            problem=problem,
            keywords=keywords,
            error=None,
        )

    def summarize_papers(self, papers: list[Paper]) -> list[SummaryResult]:
        """批量总结论文，逐篇调用 summarize，每次间隔 0.5 秒"""
        results: list[SummaryResult] = []
        for i, paper in enumerate(papers):
            logger.info(f"正在总结论文 {i+1}/{len(papers)}: {paper.arxiv_id}")
            result = self.summarize(paper)
            results.append(result)
            if i < len(papers) - 1:
                time.sleep(0.5)
        return results


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
    summarizer = PaperSummarizer(
        llm_client=llm,
        prompts_dir="./prompts",
    )

    test_paper = Paper(
        arxiv_id="test-123",
        title="Deep Learning for Image Classification",
        abstract="This paper proposes a novel deep learning architecture for image classification tasks. The model uses a combination of convolutional neural networks and attention mechanisms to achieve state-of-the-art performance on several benchmark datasets.",
        authors=["John Doe"],
        categories=["cs.CV"],
        pdf_url="https://arxiv.org/pdf/test.pdf",
        published="2024-01-01",
    )

    result = summarizer.summarize(test_paper)
    print(f"核心方法: {result.core_methods}")
    print(f"解决问题: {result.problem}")
    print(f"关键词: {result.keywords}")