import os
import json
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, asdict, field
from enum import Enum


class DeployMode(str, Enum):
    BUILD_ONLY = "build-only"
    PUSH_TO_BRANCH = "push-to-branch"
    GH_DEPLOY = "gh-deploy"


@dataclass
class Config:
    SILICONFLOW_API_KEY: str = ""
    SILICONFLOW_MODEL: str = "Qwen/Qwen2.5-7B-Instruct"

    KEYWORDS: List[str] = field(default_factory=lambda: ["LLM", "large language model", "transformer"])
    CATEGORIES: List[str] = field(default_factory=lambda: ["cs.CL", "cs.AI", "cs.CV", "cs.LG"])

    MAX_RESULTS_PER_SEARCH: int = 10

    PDF_CACHE_DIR: str = "./pdf_cache"
    MARKDOWN_OUTPUT_DIR: str = "./output/markdown"
    PROMPT_DIR: str = "./markdown"

    SITE_NAME: str = "arXiv Sentinel"
    SITE_DESCRIPTION: str = "每日arXiv论文总结"

    MKDOCS_REPO_URL: str = ""
    MKDOCS_REPO_BRANCH: str = "gh-pages"
    MKDOCS_WORKING_DIR: str = "./mkdocs_repo"
    MKDOCS_DEPLOY_MODE: str = DeployMode.BUILD_ONLY.value

    GIT_COMMIT_MESSAGE: str = "自动更新: 新增{count}篇论文总结"
    GIT_AUTHOR_NAME: str = "arXiv Sentinel Bot"
    GIT_AUTHOR_EMAIL: str = "bot@arxiv-sentinel.local"

    ENABLE_LLM_FILTER: bool = True

    USE_VISION_MODE: bool = False
    VISION_MODEL: str = "Qwen/Qwen2-VL-72B-Instruct"
    VISION_MAX_PAGES: int = 10
    VISION_DPI: int = 150

    API_TIMEOUT: int = 180
    API_MAX_RETRIES: int = 3

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
            PROMPT_DIR=data.get("PROMPT_DIR", "./markdown"),
            SITE_NAME=data.get("SITE_NAME", "arXiv Sentinel"),
            SITE_DESCRIPTION=data.get("SITE_DESCRIPTION", "每日arXiv论文总结"),
            MKDOCS_REPO_URL=data.get("MKDOCS_REPO_URL", ""),
            MKDOCS_REPO_BRANCH=data.get("MKDOCS_REPO_BRANCH", "gh-pages"),
            MKDOCS_WORKING_DIR=data.get("MKDOCS_WORKING_DIR", "./mkdocs_repo"),
            MKDOCS_DEPLOY_MODE=data.get("MKDOCS_DEPLOY_MODE", DeployMode.BUILD_ONLY.value),
            GIT_COMMIT_MESSAGE=data.get("GIT_COMMIT_MESSAGE", "自动更新: 新增{count}篇论文总结"),
            GIT_AUTHOR_NAME=data.get("GIT_AUTHOR_NAME", "arXiv Sentinel Bot"),
            GIT_AUTHOR_EMAIL=data.get("GIT_AUTHOR_EMAIL", "bot@arxiv-sentinel.local"),
            ENABLE_LLM_FILTER=data.get("ENABLE_LLM_FILTER", True),
            USE_VISION_MODE=data.get("USE_VISION_MODE", False),
            VISION_MODEL=data.get("VISION_MODEL", "Qwen/Qwen2-VL-72B-Instruct"),
            VISION_MAX_PAGES=data.get("VISION_MAX_PAGES", 10),
            VISION_DPI=data.get("VISION_DPI", 150),
            API_TIMEOUT=data.get("API_TIMEOUT", 180),
            API_MAX_RETRIES=data.get("API_MAX_RETRIES", 3),
        )


class ConfigManager:
    DEFAULT_CONFIG_FILE = "./config.json"
    ENV_API_KEY = "SILICONFLOW_API_KEY"
    ENV_GITHUB_TOKEN = "GITHUB_TOKEN"

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

        valid_modes = [mode.value for mode in DeployMode]
        if self.config.MKDOCS_DEPLOY_MODE not in valid_modes:
            errors.append(f"MKDOCS_DEPLOY_MODE '{self.config.MKDOCS_DEPLOY_MODE}' is invalid. Valid modes: {', '.join(valid_modes)}")

        if self.config.MKDOCS_DEPLOY_MODE in [DeployMode.PUSH_TO_BRANCH.value, DeployMode.GH_DEPLOY.value]:
            if not self.config.MKDOCS_REPO_URL:
                errors.append("MKDOCS_REPO_URL is required when deploy mode is 'push-to-branch' or 'gh-deploy'")

        return errors

    def get_github_token(self) -> Optional[str]:
        return os.environ.get(self.ENV_GITHUB_TOKEN)
