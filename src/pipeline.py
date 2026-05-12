import json
import logging
import os
from dataclasses import dataclass
from datetime import date, timedelta

from config import Config
from llm_client import LlmClient
from models import AnalysisResult, Paper
from paper_analyzer import PaperAnalyzer
from sniffer import ArxivSniffer

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """流水线执行结果"""
    date: str
    total_fetched: int
    total_filtered: int
    results: list[AnalysisResult]


class Pipeline:
    """论文追踪流水线：整合嗅探、分析、筛选和保存流程"""

    def __init__(self, config: Config):
        self.config = config
        self.llm_client = LlmClient(
            api_key=config.siliconflow_api_key,
            model=config.siliconflow_model,
        )
        self.analyzer = PaperAnalyzer(
            llm_client=self.llm_client,
            keywords=config.keywords,
            threshold=config.relevance_threshold,
            prompts_dir=config.prompts_dir,
        )

    def sniff_papers(self, target_date: date | None = None) -> list[Paper]:
        """执行嗅探，获取目标日期的新论文"""
        sniffer = ArxivSniffer(
            domain_rules=self.config.domain_rules,
            max_results=self.config.max_results_per_category,
            processed_ids=self.config.processed_ids,
            target_date=target_date,
        )
        return sniffer.sniff()

    def analyze_papers(self, papers: list[Paper]) -> list[AnalysisResult]:
        """批量分析论文并按阈值过滤"""
        if not papers:
            logger.info("没有论文需要分析")
            return []

        # 逐一分析论文
        logger.info(f"开始分析 {len(papers)} 篇论文")
        results = self.analyzer.analyze_papers(papers)

        # 按阈值筛选
        filtered = self.analyzer.apply_threshold(results)
        return filtered

    def save_results(self, results: list[AnalysisResult], target_date: str) -> str:
        """保存分析结果到 JSON 文件"""
        output_dir = self.config.output_dir
        filename = f"analysis_results_{target_date}.json"
        filepath = os.path.join(output_dir, filename)

        # 将分析结果转换为可序列化的字典
        results_data = []
        for result in results:
            paper = result.paper
            result_dict = {
                "arxiv_id": paper.arxiv_id,
                "title": paper.title,
                "abstract": paper.abstract,
                "authors": paper.authors,
                "categories": paper.categories,
                "pdf_url": paper.pdf_url,
                "published": paper.published,
                "score": result.score,
                "reason": result.reason,
                "core_methods": result.core_methods,
                "problem": result.problem,
                "keywords": result.keywords,
            }
            results_data.append(result_dict)

        # 写入 JSON 文件
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(results_data, f, ensure_ascii=False, indent=2)

        logger.info(f"分析结果已保存到: {filepath}")
        return filepath

    def update_history(self, papers: list[Paper]) -> None:
        """更新历史记录，记录已处理的论文 ID"""
        new_ids = [p.arxiv_id for p in papers]
        updated_ids = list(set(self.config.processed_ids + new_ids))
        
        # 保存到历史文件
        with open(self.config.history_file, "w", encoding="utf-8") as f:
            json.dump(updated_ids, f, ensure_ascii=False, indent=2)
        
        # 更新内存中的已处理列表
        self.config.processed_ids = updated_ids
        logger.info(f"历史记录已更新，新增 {len(new_ids)} 条记录")

    def run(self, target_date: date | None = None) -> PipelineResult:
        """执行完整的流水线流程"""
        logger.info("=" * 60)
        logger.info("开始执行 arXiv Sentinel 流水线")
        logger.info("=" * 60)

        # 获取目标日期字符串
        if target_date is None:
            target_date_str = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            target_date_str = target_date.strftime("%Y-%m-%d")

        # 步骤1: 嗅探论文
        logger.info("步骤1: 开始嗅探 arXiv 论文")
        papers = self.sniff_papers(target_date)
        total_fetched = len(papers)
        logger.info(f"步骤1完成: 嗅探到 {total_fetched} 篇新论文")

        if not papers:
            logger.info("没有新论文，流水线提前结束")
            return PipelineResult(
                date=target_date_str,
                total_fetched=0,
                total_filtered=0,
                results=[],
            )

        # 步骤2: 分析论文
        logger.info("步骤2: 开始分析论文摘要")
        filtered_results = self.analyze_papers(papers)
        total_filtered = len(filtered_results)
        logger.info(f"步骤2完成: 分析并筛选后保留 {total_filtered} 篇")

        # 步骤3: 保存分析结果
        logger.info("步骤3: 保存分析结果")
        self.save_results(filtered_results, target_date_str)

        # 步骤4: 更新历史记录
        logger.info("步骤4: 更新处理历史")
        self.update_history(papers)

        logger.info("=" * 60)
        logger.info("流水线执行完成")
        logger.info("=" * 60)

        return PipelineResult(
            date=target_date_str,
            total_fetched=total_fetched,
            total_filtered=total_filtered,
            results=filtered_results,
        )


if __name__ == "__main__":
    # 测试流水线
    from config import Config

    cfg = Config.from_file()
    pipeline = Pipeline(cfg)
    result = pipeline.run()
    print(f"日期: {result.date}")
    print(f"获取论文数: {result.total_fetched}")
    print(f"筛选后保留: {result.total_filtered}")