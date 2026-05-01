import os
import json
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, asdict, field


@dataclass
class Config:
    SILICONFLOW_API_KEY: str = ""
    SILICONFLOW_MODEL: str = "Qwen/Qwen2.5-7B-Instruct"

    KEYWORDS: List[str] = field(default_factory=lambda: ["LLM", "large language model", "transformer"])
    CATEGORIES: List[str] = field(default_factory=lambda: ["cs.CL", "cs.AI", "cs.CV", "cs.LG"])

    MAX_RESULTS_PER_SEARCH: int = 10

    PDF_CACHE_DIR: str = "./pdf_cache"
    MARKDOWN_OUTPUT_DIR: str = "./output/markdown"
    PAGE_DIR: str = "./page"
    PROMPT_DIR: str = "./markdown"

    ENABLE_SCHEDULER: bool = False
    SCHEDULE_TIME: str = "08:00"

    SITE_NAME: str = "arXiv Sentinel"
    SITE_DESCRIPTION: str = "每日arXiv论文总结"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Config":
        return cls(
            SILICONFLOW_API_KEY=data.get("SILICONFLOW_API_KEY", ""),
            SILICONFLOW_MODEL=data.get("SILICONFLOW_MODEL", "Qwen/Qwen2.5-7B-Instruct"),
            KEYWORDS=data.get("KEYWORDS", ["LLM", "large language model", "transformer"]),
            CATEGORIES=data.get("CATEGORIES", ["cs.CL", "cs.AI", "cs.CV", "cs.LG"]),
            MAX_RESULTS_PER_SEARCH=data.get("MAX_RESULTS_PER_SEARCH", 10),
            PDF_CACHE_DIR=data.get("PDF_CACHE_DIR", "./pdf_cache"),
            MARKDOWN_OUTPUT_DIR=data.get("MARKDOWN_OUTPUT_DIR", "./output/markdown"),
            PAGE_DIR=data.get("PAGE_DIR", "./page"),
            PROMPT_DIR=data.get("PROMPT_DIR", "./markdown"),
            ENABLE_SCHEDULER=data.get("ENABLE_SCHEDULER", False),
            SCHEDULE_TIME=data.get("SCHEDULE_TIME", "08:00"),
            SITE_NAME=data.get("SITE_NAME", "arXiv Sentinel"),
            SITE_DESCRIPTION=data.get("SITE_DESCRIPTION", "每日arXiv论文总结"),
        )


class ConfigManager:
    DEFAULT_CONFIG_FILE = "./config.json"
    ENV_API_KEY = "SILICONFLOW_API_KEY"

    def __init__(self, config_file: Optional[str] = None):
        self.config_file = config_file or self.DEFAULT_CONFIG_FILE
        self.config = self._load()

    def _load(self) -> Config:
        config = Config()

        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    config = Config.from_dict(data)
            except (json.JSONDecodeError, KeyError) as e:
                print(f"Warning: Failed to load config file: {e}")

        env_api_key = os.environ.get(self.ENV_API_KEY)
        if env_api_key:
            config.SILICONFLOW_API_KEY = env_api_key

        return config

    def save(self) -> bool:
        try:
            os.makedirs(os.path.dirname(self.config_file) or ".", exist_ok=True)
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self.config.to_dict(), f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Failed to save config: {e}")
            return False

    def get(self) -> Config:
        return self.config

    def update(self, **kwargs) -> Config:
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
        self.save()
        return self.config

    def validate(self) -> List[str]:
        errors = []

        if not self.config.SILICONFLOW_API_KEY:
            errors.append("SILICONFLOW_API_KEY is not set. Please set it in config.json or as an environment variable.")

        if not self.config.KEYWORDS:
            errors.append("KEYWORDS is empty. Please specify at least one keyword to search.")

        if self.config.MAX_RESULTS_PER_SEARCH <= 0:
            errors.append("MAX_RESULTS_PER_SEARCH must be a positive integer.")

        if self.config.ENABLE_SCHEDULER:
            import re
            time_pattern = r"^([01]?[0-9]|2[0-3]):[0-5][0-9]$"
            if not re.match(time_pattern, self.config.SCHEDULE_TIME):
                errors.append(f"SCHEDULE_TIME '{self.config.SCHEDULE_TIME}' is invalid. Use format 'HH:MM'.")

        return errors
