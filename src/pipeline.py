import logging
from datetime import date

from src.abstract_filter import AbstractFilter
from src.config import Config
from src.models import FilterResult, Paper, PipelineRun
from src.publisher import Publisher
from src.sniffer import ArxivSniffer

logger = logging.getLogger(__name__)


class Pipeline:
    """论文监控流水线，串联嗅探、筛选、发布三大阶段"""

    def __init__(self, config: Config):
        self.config = config
        self.status = "idle"
        self.last_run = None
        self.last_error = None

    def run(self) -> PipelineRun:
        """执行完整流水线：嗅探 → 筛选 → 构建 → 发布"""
        self.status = "running"
        try:
            # Step 1: 嗅探论文
            logger.info("Step 1: 开始嗅探 arXiv 论文")
            sniffer = ArxivSniffer(
                categories=self.config.arxiv_categories,
                max_results=self.config.max_results_per_category,
                processed_ids=self.config.processed_ids,
            )
            papers: list[Paper] = sniffer.sniff()
            logger.info("Step 1 完成: 嗅探到 %d 篇新论文", len(papers))

            # Step 2: 筛选论文
            logger.info("Step 2: 开始筛选论文")
            abstract_filter = AbstractFilter(
                api_key=self.config.siliconflow_api_key,
                model=self.config.siliconflow_model,
                keywords=self.config.search_keywords,
                threshold=self.config.relevance_threshold,
                prompts_dir=self.config.prompts_dir,
            )
            results: list[FilterResult] = abstract_filter.filter_papers(papers)
            filtered: list[FilterResult] = abstract_filter.apply_threshold(results)
            logger.info("Step 2 完成: 筛选后保留 %d 篇", len(filtered))

            # Step 3: 构建流水线运行记录
            logger.info("Step 3: 构建流水线运行记录")
            pipeline_run = PipelineRun(
                date=date.today().isoformat(),
                categories=self.config.arxiv_categories,
                total_fetched=len(papers),
                total_filtered=len(filtered),
                papers=filtered,
            )

            # Step 4: 发布结果
            logger.info("Step 4: 发布结果")
            publisher = Publisher(
                output_dir=self.config.output_dir,
                history_file=self.config.history_file,
            )
            publisher.publish(pipeline_run)
            logger.info("Step 4 完成: 结果已发布")

            self.status = "completed"
            self.last_run = pipeline_run
            return pipeline_run

        except Exception as e:
            self.status = "failed"
            self.last_error = str(e)
            logger.error("流水线执行失败: %s", e, exc_info=True)
            raise

    def get_status(self) -> dict:
        """获取流水线当前状态及最近一次运行的摘要信息"""
        result = {
            "status": self.status,
            "last_error": self.last_error,
        }
        if self.last_run is not None:
            result["date"] = self.last_run.date
            result["total_fetched"] = self.last_run.total_fetched
            result["total_filtered"] = self.last_run.total_filtered
        return result
