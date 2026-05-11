from __future__ import annotations

import json
import logging
import time

import openai

from src.models import Paper, FilterResult

logger = logging.getLogger(__name__)

_VALID_SCORES = ("HIGH", "MEDIUM", "LOW", "IRRELEVANT")
_SCORE_PRIORITY = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "IRRELEVANT": 0}


class AbstractFilter:
    """基于 LLM 的论文摘要筛选器，评估论文与关键词的相关度"""

    def __init__(
        self,
        api_key: str,
        model: str,
        keywords: list[str],
        threshold: str,
        prompts_dir: str,
    ) -> None:
        # 初始化 SiliconFlow OpenAI 兼容客户端
        self.client = openai.OpenAI(
            api_key=api_key, base_url="https://api.siliconflow.cn/v1"
        )
        self.model = model
        self.keywords = keywords
        self.threshold = threshold

        # 加载 prompt 模板
        system_path = f"{prompts_dir}/abstract_filter/system.txt"
        user_path = f"{prompts_dir}/abstract_filter/user.txt"
        with open(system_path, encoding="utf-8") as f:
            self.system_prompt = f.read()
        with open(user_path, encoding="utf-8") as f:
            self.user_template = f.read()

    def filter_paper(self, paper: Paper) -> FilterResult:
        """筛选单篇论文，调用 LLM 评估相关度，含指数退避重试"""
        # 将模板中的占位符替换为实际值
        user_content = self.user_template.format(
            keywords=", ".join(self.keywords),
            title=paper.title,
            abstract=paper.abstract,
        )

        # 最多重试 3 次（attempt 0, 1, 2）
        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=0.1,
                    response_format={"type": "json_object"},
                )
                raw = response.choices[0].message.content
                data = json.loads(raw)
                score = data.get("score", "IRRELEVANT")
                reason = data.get("reason", "")
                # 校验 score 是否合法
                if score not in _VALID_SCORES:
                    score = "IRRELEVANT"
                return FilterResult(paper=paper, score=score, reason=reason)

            except json.JSONDecodeError as e:
                # JSON 解析失败，视为 IRRELEVANT
                return FilterResult(
                    paper=paper,
                    score="IRRELEVANT",
                    reason=f"JSON 解析失败: {e}",
                )

            except Exception as e:
                # API 调用异常，指数退避重试
                if attempt < 2:
                    time.sleep(2**attempt)
                else:
                    # 3 次均失败，标记为 IRRELEVANT 并记录警告
                    logger.warning(
                        "论文 %s 筛选失败（已重试 3 次）: %s", paper.arxiv_id, e
                    )
                    return FilterResult(
                        paper=paper,
                        score="IRRELEVANT",
                        reason=f"API 调用失败（重试 3 次）: {e}",
                    )

        # 理论上不会到达此处，作为兜底
        return FilterResult(
            paper=paper, score="IRRELEVANT", reason="未知错误"
        )

    def filter_papers(self, papers: list[Paper]) -> list[FilterResult]:
        """批量筛选论文，逐篇调用 filter_paper，每次间隔 0.5 秒"""
        results: list[FilterResult] = []
        for i, paper in enumerate(papers):
            result = self.filter_paper(paper)
            results.append(result)
            # 非最后一篇时等待，避免速率限制
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
