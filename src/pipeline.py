"""PipelineOrchestrator — 主控引擎，依赖注入串联所有模块（SPEC §5.1 / §5.3）。"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from src.abstract_filter import AbstractFilter
from src.config_loader import AppConfig
from src.deployer import GithubDeployer
from src.introduction_filter import IntroductionFilter
from src.llm_client import LLMClient
from src.sniffer import ArxivSniffer, PaperObject
from src.summarizer import PaperSummarizer

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.llm = self._build_llm()
        self.sniffer = self._build_sniffer()
        self.abstract_filter = self._build_abstract_filter()
        self.introduction_filter = self._build_introduction_filter()
        self.summarizer = self._build_summarizer()
        self.deployer = self._build_deployer()

    def run(self) -> None:
        """漏斗式流水线：嗅探 → 摘要筛 → 导言筛 → 总结 → 发布。"""
        self._ensure_dirs()

        papers = self.sniffer.sniff()
        logger.info("sniffer: %d new papers", len(papers))
        if not papers:
            return

        papers = self.abstract_filter.filter(papers)
        logger.info("abstract_filter: %d kept", len(papers))
        if not papers:
            return

        papers = self.introduction_filter.filter(papers)
        logger.info("introduction_filter: %d kept", len(papers))
        if not papers:
            return

        produced: list[Path] = []
        for paper in papers:
            try:
                md_path = self.summarizer.summarize(paper)
                produced.append(md_path)
            except Exception:
                logger.exception("summarize failed for %s", paper.arxiv_id)

        if produced:
            pushed = self.deployer.deploy(produced)
            if pushed:
                self._mark_processed(papers)

    def _ensure_dirs(self) -> None:
        self.config.cache.pdf_dir.mkdir(parents=True, exist_ok=True)
        self.config.cache.image_dir.mkdir(parents=True, exist_ok=True)
        self.config.deploy.output_dir.mkdir(parents=True, exist_ok=True)

    def _mark_processed(self, papers: list[PaperObject]) -> None:
        """原子性：仅在 push 成功后写入 history.json#processed_ids（SPEC §6 Atomicity）。"""
        path = self.config.cache.history_file
        history = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"processed_ids": []}
        ids = set(history.get("processed_ids", []))
        ids.update(p.arxiv_id for p in papers)
        history["processed_ids"] = sorted(ids)
        path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

    def _build_llm(self) -> LLMClient:
        c = self.config.llm
        return LLMClient(
            base_url=c.base_url,
            api_key=c.api_key,
            text_timeout=c.text_timeout_seconds,
            multimodal_timeout=c.multimodal_timeout_seconds,
            retry_max_attempts=c.retry_max_attempts,
            retry_initial_backoff=c.retry_initial_backoff_seconds,
        )

    def _build_sniffer(self) -> ArxivSniffer:
        c = self.config.arxiv
        return ArxivSniffer(
            categories=c.categories,
            keywords=c.keywords,
            history_file=self.config.cache.history_file,
            papers_dir=self.config.deploy.output_dir,
            max_results_per_keyword=c.max_results_per_keyword,
            request_interval_seconds=c.request_interval_seconds,
        )

    def _build_abstract_filter(self) -> AbstractFilter:
        return AbstractFilter(
            llm_client=self.llm,
            model=self.config.llm.abstract_filter_model,
            threshold=self.config.abstract_filter.threshold,
            prompts_dir=Path("prompts/abstract_filter"),
            pdf_cache_dir=self.config.cache.pdf_dir,
        )

    def _build_introduction_filter(self) -> IntroductionFilter:
        return IntroductionFilter(
            llm_client=self.llm,
            model=self.config.llm.introduction_filter_model,
            threshold=self.config.introduction_filter.threshold,
            prompts_dir=Path("prompts/introduction_filter"),
            pages_to_extract=self.config.introduction_filter.pdf_pages_to_extract,
        )

    def _build_summarizer(self) -> PaperSummarizer:
        return PaperSummarizer(
            llm_client=self.llm,
            model=self.config.llm.summarizer_multimodal_model,
            prompts_dir=Path("prompts/summarizer"),
            template_path=Path("templates/paper_template.md"),
            output_dir=self.config.deploy.output_dir,
            image_cache_dir=self.config.cache.image_dir,
            max_pdf_pages=self.config.summarizer.max_pdf_pages_to_image,
            fallback_text_pages=self.config.summarizer.fallback_text_pages,
        )

    def _build_deployer(self) -> GithubDeployer:
        return GithubDeployer(
            output_dir=self.config.deploy.output_dir,
            cache_dir=self.config.cache.root_dir,
            remote=self.config.deploy.git_remote,
            branch=self.config.deploy.git_branch,
            commit_prefix=self.config.deploy.commit_message_prefix,
            cleanup_cache=self.config.cache.cleanup_after_run,
        )
