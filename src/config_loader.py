"""ConfigLoader — 解析 config.json，验证必填字段（SPEC §5.3）。"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LLMConfig:
    base_url: str
    api_key: str
    default_text_model: str
    abstract_filter_model: str
    introduction_filter_model: str
    summarizer_multimodal_model: str
    text_timeout_seconds: int
    multimodal_timeout_seconds: int
    retry_max_attempts: int
    retry_initial_backoff_seconds: int


@dataclass
class CacheConfig:
    root_dir: Path
    pdf_dir: Path
    image_dir: Path
    history_file: Path
    cleanup_after_run: bool


@dataclass
class ArxivConfig:
    categories: list[str]
    keywords: list[str]
    max_results_per_keyword: int
    request_interval_seconds: int


@dataclass
class FilterConfig:
    threshold: str
    allowed_levels: list[str]
    pdf_pages_to_extract: int = 3


@dataclass
class SummarizerConfig:
    max_pdf_pages_to_image: int
    fallback_text_pages: int


@dataclass
class DeployConfig:
    mode: str
    output_dir: Path
    git_remote: str
    git_branch: str
    commit_message_prefix: str


@dataclass
class AppConfig:
    llm: LLMConfig
    cache: CacheConfig
    arxiv: ArxivConfig
    abstract_filter: FilterConfig
    introduction_filter: FilterConfig
    summarizer: SummarizerConfig
    deploy: DeployConfig
    raw: dict[str, Any] = field(default_factory=dict)


class ConfigLoader:
    def __init__(self, config_path: Path) -> None:
        self.config_path = Path(config_path)

    def load(self) -> AppConfig:
        raw = self._read_json()
        self._validate_required(raw)
        return self._build(raw)

    def _read_json(self) -> dict[str, Any]:
        if not self.config_path.exists():
            raise FileNotFoundError(f"config not found: {self.config_path}")
        with self.config_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _validate_required(self, raw: dict[str, Any]) -> None:
        required = ["llm", "cache", "arxiv", "abstract_filter", "introduction_filter", "summarizer", "deploy"]
        missing = [k for k in required if k not in raw]
        if missing:
            raise ValueError(f"config.json missing required sections: {missing}")

    def _build(self, raw: dict[str, Any]) -> AppConfig:
        raise NotImplementedError("populate dataclasses from raw dict; resolve api_key via env var")
