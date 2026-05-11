from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

_RELEVANCE_LEVELS = ("IRRELEVANT", "LOW", "MEDIUM", "HIGH")
_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


@dataclass
class Config:
    """应用配置，从 config.json 加载并校验"""

    arxiv_categories: list[str]
    search_keywords: list[str]
    relevance_threshold: str
    siliconflow_api_key: str
    siliconflow_model: str
    max_results_per_category: int = 50
    output_dir: str = "./output"
    prompts_dir: str = "./prompts"
    log_level: str = "INFO"
    history_file: str = "./output/history.json"
    processed_ids: list[str] = field(default_factory=list, repr=False)

    @classmethod
    def from_file(cls, path: str = "./config.json") -> Config:
        """从 JSON 文件加载配置，执行校验、目录创建、日志初始化与历史加载"""
        raw = _load_json(path)
        cfg = cls(**raw)
        _validate(cfg)
        _ensure_dirs(cfg)
        _init_logging(cfg)
        cfg.processed_ids = _load_history(cfg.history_file)
        return cfg


def _load_json(path: str) -> dict:
    """读取 JSON 文件并返回字典"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _validate(cfg: Config) -> None:
    """校验配置字段，失败时抛出 ValueError"""
    errors: list[str] = []

    # arxiv_categories: 必填，每项须为非空字符串
    if not isinstance(cfg.arxiv_categories, list) or len(cfg.arxiv_categories) == 0:
        errors.append("arxiv_categories: 必填且不能为空列表")
    else:
        for i, cat in enumerate(cfg.arxiv_categories):
            if not isinstance(cat, str) or not cat.strip():
                errors.append(f"arxiv_categories[{i}]: 须为非空字符串")

    # search_keywords: 必填，至少 1 项
    if not isinstance(cfg.search_keywords, list) or len(cfg.search_keywords) == 0:
        errors.append("search_keywords: 必填且至少包含 1 项")
    else:
        for i, kw in enumerate(cfg.search_keywords):
            if not isinstance(kw, str) or not kw.strip():
                errors.append(f"search_keywords[{i}]: 须为非空字符串")

    # relevance_threshold: 必填，枚举值
    if cfg.relevance_threshold not in _RELEVANCE_LEVELS:
        errors.append(
            f"relevance_threshold: 须为 {_RELEVANCE_LEVELS} 之一，当前值: {cfg.relevance_threshold!r}"
        )

    # max_results_per_category: 范围 1-200
    if not isinstance(cfg.max_results_per_category, int) or not (1 <= cfg.max_results_per_category <= 200):
        errors.append("max_results_per_category: 须为整数且范围 1-200")

    # siliconflow_api_key: 必填，非空
    if not isinstance(cfg.siliconflow_api_key, str) or not cfg.siliconflow_api_key.strip():
        errors.append("siliconflow_api_key: 必填且不能为空")

    # siliconflow_model: 必填，非空
    if not isinstance(cfg.siliconflow_model, str) or not cfg.siliconflow_model.strip():
        errors.append("siliconflow_model: 必填且不能为空")

    # output_dir: 非空字符串
    if not isinstance(cfg.output_dir, str) or not cfg.output_dir.strip():
        errors.append("output_dir: 须为非空字符串")

    # prompts_dir: 非空字符串
    if not isinstance(cfg.prompts_dir, str) or not cfg.prompts_dir.strip():
        errors.append("prompts_dir: 须为非空字符串")

    # log_level: 枚举值
    if cfg.log_level not in _LOG_LEVELS:
        errors.append(f"log_level: 须为 {_LOG_LEVELS} 之一，当前值: {cfg.log_level!r}")

    # history_file: 非空字符串
    if not isinstance(cfg.history_file, str) or not cfg.history_file.strip():
        errors.append("history_file: 须为非空字符串")

    if errors:
        raise ValueError("配置校验失败:\n" + "\n".join(f"  - {e}" for e in errors))


def _ensure_dirs(cfg: Config) -> None:
    """确保所需目录存在，不存在则递归创建"""
    dirs = [
        cfg.output_dir,
        os.path.join(cfg.prompts_dir, "abstract_filter"),
        os.path.join(cfg.output_dir, "reports"),
    ]
    for d in dirs:
        p = Path(d)
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            # 目录创建的日志在日志系统初始化前，使用临时日志输出
            logging.getLogger(__name__).info(f"已创建目录: {d}")


def _init_logging(cfg: Config) -> None:
    """初始化日志系统：控制台 + 文件输出"""
    log_format = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
    level = getattr(logging, cfg.log_level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    # 避免重复添加 handler（多次调用 from_file 时）
    if root.handlers:
        return

    formatter = logging.Formatter(log_format)

    # 控制台输出
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    # 文件输出
    log_path = os.path.join(cfg.output_dir, "sentinel.log")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


def _load_history(history_file: str) -> list[str]:
    """从历史文件加载已处理的 arxiv_id 列表，文件不存在则返回空列表"""
    path = Path(history_file)
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, str)]
        return []
    except (json.JSONDecodeError, OSError):
        return []
