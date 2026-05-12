import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from models import DomainRule

_RELEVANCE_LEVELS = ("IRRELEVANT", "LOW", "MEDIUM", "HIGH")
_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
_DOMAIN_MODES = ("accept_all", "categories_filter")


@dataclass
class Config:
    """应用配置，从 config.json 加载并校验"""

    categories: list[str]
    keywords: list[str]
    domain_rules: list[DomainRule]
    relevance_threshold: str
    openai_api_key: str
    openai_model: str
    openai_base_url: str = "https://api.siliconflow.cn/v1"
    max_results_per_category: int = 50
    output_dir: str = "./output"
    prompts_dir: str = "./prompts"
    log_level: str = "INFO"
    history_file: str = "./output/history.json"
    processed_ids: list[str] = field(default_factory=list, repr=False)

    @classmethod
    def from_file(cls, path: str = "./config.json") -> 'Config':
        """从 JSON 文件加载配置，执行校验、目录创建、日志初始化与历史加载"""
        raw = _load_json(path)
        raw = _parse_domain_rules(raw)
        cfg = cls(**raw)
        _validate(cfg)
        _ensure_dirs(cfg)
        _init_logging(cfg)
        cfg.processed_ids = _load_history(cfg.history_file)
        return cfg


def _parse_domain_rules(raw: dict) -> dict:
    """将 JSON 中的 domain_rules 列表转换为 DomainRule 对象列表"""
    rules_data = raw.pop("domain_rules", [])
    domain_rules: list[DomainRule] = []
    for item in rules_data:
        domain_rules.append(DomainRule(
            category=item["category"],
            mode=item["mode"],
            filter_categories=item.get("filter_categories", []),
        ))
    raw["domain_rules"] = domain_rules
    return raw


def _load_json(path: str) -> dict:
    """读取 JSON 文件并返回字典"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _validate(cfg: Config) -> None:
    """校验配置字段，失败时抛出 ValueError"""
    errors: list[str] = []

    if not isinstance(cfg.categories, list) or len(cfg.categories) == 0:
        errors.append("categories: 必填且不能为空列表")
    else:
        for i, cat in enumerate(cfg.categories):
            if not isinstance(cat, str) or not cat.strip():
                errors.append(f"categories[{i}]: 须为非空字符串")

    if not isinstance(cfg.keywords, list) or len(cfg.keywords) == 0:
        errors.append("keywords: 必填且至少包含 1 项")
    else:
        for i, kw in enumerate(cfg.keywords):
            if not isinstance(kw, str) or not kw.strip():
                errors.append(f"keywords[{i}]: 须为非空字符串")

    if not isinstance(cfg.domain_rules, list) or len(cfg.domain_rules) == 0:
        errors.append("domain_rules: 必填且不能为空列表")
    else:
        for i, rule in enumerate(cfg.domain_rules):
            if not isinstance(rule, DomainRule):
                errors.append(f"domain_rules[{i}]: 须为 DomainRule 对象")
                continue
            if not isinstance(rule.category, str) or not rule.category.strip():
                errors.append(f"domain_rules[{i}].category: 须为非空字符串")
            if rule.mode not in _DOMAIN_MODES:
                errors.append(f"domain_rules[{i}].mode: 须为 {_DOMAIN_MODES} 之一，当前值: {rule.mode!r}")
            if rule.mode == "categories_filter":
                if not isinstance(rule.filter_categories, list) or len(rule.filter_categories) == 0:
                    errors.append(f"domain_rules[{i}].filter_categories: categories_filter 模式下至少包含 1 项")
                else:
                    for j, fc in enumerate(rule.filter_categories):
                        if not isinstance(fc, str) or not fc.strip():
                            errors.append(f"domain_rules[{i}].filter_categories[{j}]: 须为非空字符串")

    if cfg.relevance_threshold not in _RELEVANCE_LEVELS:
        errors.append(
            f"relevance_threshold: 须为 {_RELEVANCE_LEVELS} 之一，当前值: {cfg.relevance_threshold!r}"
        )

    if not isinstance(cfg.max_results_per_category, int) or not (1 <= cfg.max_results_per_category <= 200):
        errors.append("max_results_per_category: 须为整数且范围 1-200")

    if not isinstance(cfg.openai_api_key, str) or not cfg.openai_api_key.strip():
        errors.append("openai_api_key: 必填且不能为空")

    if not isinstance(cfg.openai_model, str) or not cfg.openai_model.strip():
        errors.append("openai_model: 必填且不能为空")

    if not isinstance(cfg.output_dir, str) or not cfg.output_dir.strip():
        errors.append("output_dir: 须为非空字符串")

    if not isinstance(cfg.prompts_dir, str) or not cfg.prompts_dir.strip():
        errors.append("prompts_dir: 须为非空字符串")

    if cfg.log_level not in _LOG_LEVELS:
        errors.append(f"log_level: 须为 {_LOG_LEVELS} 之一，当前值: {cfg.log_level!r}")

    if not isinstance(cfg.history_file, str) or not cfg.history_file.strip():
        errors.append("history_file: 须为非空字符串")

    if errors:
        raise ValueError("配置校验失败:\n" + "\n".join(f"  - {e}" for e in errors))


def _ensure_dirs(cfg: Config) -> None:
    """确保所需目录存在，不存在则递归创建"""
    dirs = [
        cfg.output_dir,
        os.path.join(cfg.prompts_dir, "paper_analyzer"),
        os.path.join(cfg.output_dir, "reports"),
    ]
    for d in dirs:
        p = Path(d)
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            logging.getLogger(__name__).info(f"已创建目录: {d}")


def _init_logging(cfg: Config) -> None:
    """初始化日志系统：控制台 + 文件输出"""
    log_format = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
    level = getattr(logging, cfg.log_level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    if root.handlers:
        return

    formatter = logging.Formatter(log_format)

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

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

if __name__ == "__main__":
    cfg = Config.from_file()
    print(cfg)