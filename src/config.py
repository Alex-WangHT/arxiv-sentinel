"""
arXiv Sentinel - 配置管理模块
============================
本模块提供配置管理功能，支持从JSON文件和环境变量加载配置。

主要类：
- DeployMode: 部署模式枚举
- SearchStrategy: 搜索策略枚举
- Config: 配置数据类（使用dataclass）
- ConfigManager: 配置管理器

使用示例：
    from src.config import ConfigManager, DeployMode, SearchStrategy
    
    # 加载配置
    manager = ConfigManager("./config.json")
    config = manager.get()
    
    # 访问配置
    print(f"API Key: {config.SILICONFLOW_API_KEY}")
    print(f"关键词: {config.KEYWORDS}")
    
    # 更新配置
    manager.update(MAX_RESULTS_PER_SEARCH=20)
    manager.save()
"""

import os
import json
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, asdict, field
from enum import Enum


class DeployMode(str, Enum):
    """
    部署模式枚举类。
    
    定义三种不同的部署方式，控制MkDocs网站的发布行为。
    
    Attributes:
        BUILD_ONLY (str): 仅本地构建模式
            - 只执行 mkdocs build
            - 不执行任何Git操作
            - 适用于本地开发和测试
        
        PUSH_TO_BRANCH (str): 推送到指定分支模式
            - 克隆/拉取远程仓库
            - 复制Markdown文件
            - 提交更改
            - 推送到指定分支（如 gh-pages）
            - 适用于需要精确控制部署分支的场景
        
        GH_DEPLOY (str): 使用mkdocs gh-deploy命令
            - 调用 mkdocs gh-deploy 命令
            - 自动构建并部署到GitHub Pages
            - 适用于标准GitHub Pages部署
    
    Example:
        from src.config import DeployMode
        
        # 仅本地构建
        mode = DeployMode.BUILD_ONLY
        
        # 推送到gh-pages分支
        mode = DeployMode.PUSH_TO_BRANCH
        
        # 使用gh-deploy命令
        mode = DeployMode.GH_DEPLOY
        
        # 检查值
        if mode == DeployMode.BUILD_ONLY:
            print("本地开发模式")
    """
    
    BUILD_ONLY = "build-only"
    PUSH_TO_BRANCH = "push-to-branch"
    GH_DEPLOY = "gh-deploy"


class SearchStrategy(str, Enum):
    """
    搜索策略枚举类。
    
    定义三种不同的搜索严格程度，控制arXiv API的搜索行为。
    
    Attributes:
        STRICT (str): 严格策略
            - 使用精确短语匹配（带双引号）
            - 查询示例: all:"LLM" 或 ti:"large language model"
            - 适用场景: 需要精确匹配特定术语，避免误匹配时
            - 优点: 结果精确度高
            - 缺点: 可能遗漏一些相关结果
        
        MODERATE (str): 中等策略（默认）
            - 使用普通关键词匹配
            - 查询示例: all:LLM 或 ti:transformer
            - 适用场景: 大多数常规搜索场景
            - 优点: 平衡精确度和召回率
        
        BROAD (str): 宽松策略
            - 搜索所有字段
            - 查询示例: all:LLM
            - 适用场景: 需要尽可能多的结果时
            - 优点: 召回率最高
            - 缺点: 可能包含较多不相关结果
    
    示例配置对比：
        假设关键词是 "LLM"：
        
        STRICT:     all:"LLM" 或 ti:"LLM" AND abs:"LLM"
                  - 必须精确匹配短语 "LLM"
        
        MODERATE:   all:LLM 或 ti:LLM OR abs:LLM
                  - 匹配包含单词 LLM 的内容
        
        BROAD:      all:LLM
                  - 搜索所有字段中的 LLM
    
    Example:
        from src.config import SearchStrategy
        
        # 严格搜索（精确匹配）
        strategy = SearchStrategy.STRICT
        
        # 默认策略
        strategy = SearchStrategy.MODERATE
        
        # 宽松搜索
        strategy = SearchStrategy.BROAD
        
        # 在配置中使用
        config = Config(
            SEARCH_STRATEGY=SearchStrategy.MODERATE.value,
            ...
        )
    """
    
    STRICT = "strict"
    MODERATE = "moderate"
    BROAD = "broad"


@dataclass
class Config:
    """
    配置数据类。
    
    使用Python dataclass定义所有配置项，包括：
    - API相关配置
    - 搜索相关配置
    - 路径相关配置
    - MkDocs相关配置
    - Git相关配置
    - 筛选和总结相关配置
    
    所有配置项都有默认值，可以通过config.json文件或环境变量覆盖。
    
    Attributes:
        SILICONFLOW_API_KEY (str): 硅基流动API密钥
            - 必需配置项
            - 可以通过环境变量 SILICONFLOW_API_KEY 设置
            - 获取地址: https://siliconflow.cn
        
        SILICONFLOW_MODEL (str): 文本模型名称
            - 默认: "Qwen/Qwen2.5-7B-Instruct"（免费）
            - 可选模型:
              - "Qwen/Qwen2.5-14B-Instruct"
              - "deepseek-ai/deepseek-v3"
              - "THUDM/glm-4-9b-chat"
        
        KEYWORDS (List[str]): 搜索关键词列表
            - 默认: ["LLM", "large language model", "transformer"]
            - 用于arXiv论文搜索
            - 多个关键词之间是OR关系
        
        CATEGORIES (List[str]): arXiv分类列表
            - 默认: ["cs.CL", "cs.AI", "cs.CV", "cs.LG"]
            - 常用分类:
              - cs.CL: 计算语言学
              - cs.AI: 人工智能
              - cs.CV: 计算机视觉
              - cs.LG: 机器学习
              - cs.IR: 信息检索
              - cs.RO: 机器人学
            - 多个分类之间是OR关系
        
        MAX_RESULTS_PER_SEARCH (int): 每次搜索的最大结果数
            - 默认: 10
            - 建议范围: 1-50
        
        PDF_CACHE_DIR (str): PDF文件缓存目录
            - 默认: "./pdf_cache"
            - 下载的PDF临时存储在此
            - 总结完成后会自动清理
        
        MARKDOWN_OUTPUT_DIR (str): Markdown输出目录
            - 默认: "./output/markdown"
            - 生成的论文总结Markdown文件存储在此
        
        PROMPT_DIR (str): Prompt模板目录
            - 默认: "./markdown"
            - 包含各种Prompt模板文件
        
        SITE_NAME (str): MkDocs网站名称
            - 默认: "arXiv Sentinel"
            - 显示在网站标题栏
        
        SITE_DESCRIPTION (str): MkDocs网站描述
            - 默认: "每日arXiv论文总结"
            - 显示在网站元数据中
        
        MKDOCS_REPO_URL (str): MkDocs仓库URL
            - 默认: ""
            - 必需配置项（当部署模式不是build-only时）
            - 示例: "https://github.com/username/repo.git"
        
        MKDOCS_REPO_BRANCH (str): MkDocs仓库分支
            - 默认: "gh-pages"
            - 推送到的目标分支
        
        MKDOCS_WORKING_DIR (str): MkDocs工作目录
            - 默认: "./mkdocs_repo"
            - 克隆的仓库和生成的文件存储在此
        
        MKDOCS_DEPLOY_MODE (str): 部署模式
            - 默认: DeployMode.BUILD_ONLY.value
            - 可选值: "build-only", "push-to-branch", "gh-deploy"
            - 参见 DeployMode 枚举类
        
        GIT_COMMIT_MESSAGE (str): Git提交消息模板
            - 默认: "自动更新: 新增{count}篇论文总结"
            - {count} 会被替换为实际新增论文数量
        
        GIT_AUTHOR_NAME (str): Git提交作者名称
            - 默认: "arXiv Sentinel Bot"
        
        GIT_AUTHOR_EMAIL (str): Git提交作者邮箱
            - 默认: "bot@arxiv-sentinel.local"
        
        ENABLE_LLM_FILTER (bool): 是否启用AI论文筛选
            - 默认: True
            - 启用后会在下载PDF前使用LLM判断论文相关性
            - 可以节省API成本和下载时间
        
        USE_VISION_MODE (bool): 是否使用视觉模式
            - 默认: False
            - True: 使用多模态模型（视觉模型）处理PDF图像
            - False: 使用文本模型处理提取的文本
        
        VISION_MODEL (str): 视觉模型名称
            - 默认: "Qwen/Qwen2-VL-72B-Instruct"
            - 可选模型:
              - "Qwen/Qwen2-VL-72B-Instruct"
              - "Qwen/Qwen3-VL"
              - "deepseek-ai/deepseek-vl2"
        
        VISION_MAX_PAGES (int): 视觉模式最大转换页数
            - 默认: 10
            - 避免超出模型上下文窗口限制
        
        VISION_DPI (int): 视觉模式图像分辨率
            - 默认: 150
            - 建议范围: 72 (低质量) - 300 (高质量)
            - 影响文件大小和API成本
        
        API_TIMEOUT (int): API请求超时时间（秒）
            - 默认: 180
            - 大模型推理可能需要较长时间
        
        API_MAX_RETRIES (int): API最大重试次数
            - 默认: 3
            - 网络不稳定时会自动重试
        
        SEARCH_STRATEGY (str): 搜索策略
            - 默认: SearchStrategy.MODERATE.value
            - 可选值: "strict", "moderate", "broad"
            - 参见 SearchStrategy 枚举类
        
        SEARCH_ALL_FIELDS (bool): 是否搜索所有字段
            - 默认: False
            - True: 搜索所有字段 (all:keyword)
            - False: 仅搜索标题和摘要 (ti:keyword OR abs:keyword)
        
        USE_OR_FOR_CATEGORIES (bool): 关键词和分类的逻辑关系
            - 默认: False (AND关系)
            - True: 关键词 OR 分类（更宽松）
            - False: 关键词 AND 分类（更严格）
            - 建议使用 False 以确保结果相关性
    
    Example:
        # 创建配置实例
        config = Config(
            SILICONFLOW_API_KEY="your-api-key",
            KEYWORDS=["LLM", "transformer", "attention"],
            CATEGORIES=["cs.CL", "cs.AI"],
            MAX_RESULTS_PER_SEARCH=15,
            SEARCH_STRATEGY=SearchStrategy.MODERATE.value,
            USE_OR_FOR_CATEGORIES=False,  # AND关系，更严格
        )
        
        # 转换为字典
        config_dict = config.to_dict()
        
        # 从字典加载
        config = Config.from_dict(config_dict)
    """
    
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

    SEARCH_STRATEGY: str = SearchStrategy.MODERATE.value
    SEARCH_ALL_FIELDS: bool = False
    USE_OR_FOR_CATEGORIES: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """
        将配置转换为字典。
        
        用于保存到JSON文件或序列化。
        
        Returns:
            包含所有配置项的字典
        
        Example:
            config = Config()
            config_dict = config.to_dict()
            
            # 保存到文件
            import json
            with open("config.json", "w") as f:
                json.dump(config_dict, f, indent=2)
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Config":
        """
        从字典创建配置实例。
        
        用于从JSON文件加载配置。对于缺失的键，使用默认值。
        
        Args:
            data: 包含配置项的字典
        
        Returns:
            Config实例
        
        Example:
            import json
            
            # 从文件加载
            with open("config.json", "r") as f:
                data = json.load(f)
            
            config = Config.from_dict(data)
        """
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
            SEARCH_STRATEGY=data.get("SEARCH_STRATEGY", SearchStrategy.MODERATE.value),
            SEARCH_ALL_FIELDS=data.get("SEARCH_ALL_FIELDS", False),
            USE_OR_FOR_CATEGORIES=data.get("USE_OR_FOR_CATEGORIES", False),
        )


class ConfigManager:
    """
    配置管理器。
    
    提供配置的加载、保存、更新和验证功能。支持：
    - 从JSON文件加载配置
    - 从环境变量加载敏感配置（API密钥）
    - 保存配置到JSON文件
    - 运行时更新配置
    - 配置验证
    
    Attributes:
        DEFAULT_CONFIG_FILE (str): 默认配置文件路径
            - 默认值: "./config.json"
        
        ENV_API_KEY (str): API密钥环境变量名
            - 默认值: "SILICONFLOW_API_KEY"
        
        ENV_GITHUB_TOKEN (str): GitHub Token环境变量名
            - 默认值: "GITHUB_TOKEN"
        
        config_file (str): 配置文件路径
        config (Config): 当前配置实例
    
    配置优先级（从高到低）：
    1. 环境变量 SILICONFLOW_API_KEY
    2. config.json 文件中的配置
    3. Config 类的默认值
    
    Example:
        from src.config import ConfigManager
        
        # 使用默认配置文件
        manager = ConfigManager()
        
        # 指定配置文件路径
        manager = ConfigManager("./config.json")
        
        # 获取配置
        config = manager.get()
        print(f"API Key: {config.SILICONFLOW_API_KEY}")
        
        # 更新配置
        manager.update(MAX_RESULTS_PER_SEARCH=20, KEYWORDS=["LLM", "RAG"])
        
        # 保存配置
        manager.save()
        
        # 验证配置
        errors = manager.validate()
        if errors:
            for error in errors:
                print(f"错误: {error}")
    """
    
    DEFAULT_CONFIG_FILE = "./config.json"
    ENV_API_KEY = "SILICONFLOW_API_KEY"
    ENV_GITHUB_TOKEN = "GITHUB_TOKEN"

    def __init__(self, config_file: Optional[str] = None):
        """
        初始化配置管理器。
        
        从指定的配置文件加载配置，如果文件不存在则使用默认值。
        环境变量中的API密钥会覆盖配置文件中的值。
        
        Args:
            config_file: 配置文件路径，为None则使用默认路径
        
        Example:
            # 使用默认路径
            manager = ConfigManager()
            
            # 指定路径
            manager = ConfigManager("/path/to/config.json")
        """
        self.config_file = config_file or self.DEFAULT_CONFIG_FILE
        self.config = self._load()

    def _load(self) -> Config:
        """
        内部方法：加载配置。
        
        执行以下步骤：
        1. 创建默认配置实例
        2. 如果配置文件存在，从文件加载
        3. 从环境变量加载API密钥（覆盖文件配置）
        
        Returns:
            加载完成的Config实例
        """
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
        """
        保存当前配置到文件。
        
        将当前配置序列化为JSON格式并保存到配置文件。
        
        Returns:
            保存成功返回True，失败返回False
        
        Example:
            manager.update(KEYWORDS=["LLM", "transformer"])
            success = manager.save()
            if success:
                print("配置已保存")
        """
        try:
            os.makedirs(os.path.dirname(self.config_file) or ".", exist_ok=True)
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self.config.to_dict(), f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Failed to save config: {e}")
            return False

    def get(self) -> Config:
        """
        获取当前配置实例。
        
        Returns:
            当前Config实例
        
        Example:
            config = manager.get()
            print(f"关键词: {config.KEYWORDS}")
            print(f"最大结果数: {config.MAX_RESULTS_PER_SEARCH}")
        """
        return self.config

    def update(self, **kwargs) -> Config:
        """
        更新配置项。
        
        允许运行时更新配置项，并自动保存到文件。
        
        Args:
            **kwargs: 要更新的配置项键值对
        
        Returns:
            更新后的Config实例
        
        Example:
            # 更新单个配置
            manager.update(MAX_RESULTS_PER_SEARCH=20)
            
            # 更新多个配置
            manager.update(
                KEYWORDS=["LLM", "RAG", "agent"],
                CATEGORIES=["cs.CL", "cs.AI"],
                SEARCH_STRATEGY="strict"
            )
        """
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
        self.save()
        return self.config

    def validate(self) -> List[str]:
        """
        验证配置项。
        
        检查配置的有效性，返回错误列表。
        
        验证规则：
        1. SILICONFLOW_API_KEY 不能为空
        2. KEYWORDS 不能为空列表
        3. MAX_RESULTS_PER_SEARCH 必须大于0
        4. MKDOCS_DEPLOY_MODE 必须是有效值
        5. 如果部署模式不是build-only，MKDOCS_REPO_URL 不能为空
        6. SEARCH_STRATEGY 必须是有效值
        
        Returns:
            错误信息列表，配置有效则返回空列表
        
        Example:
            errors = manager.validate()
            if errors:
                print("配置验证失败:")
                for error in errors:
                    print(f"  - {error}")
            else:
                print("配置验证通过")
        """
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

        valid_strategies = [s.value for s in SearchStrategy]
        if self.config.SEARCH_STRATEGY not in valid_strategies:
            errors.append(f"SEARCH_STRATEGY '{self.config.SEARCH_STRATEGY}' is invalid. Valid strategies: {', '.join(valid_strategies)}")

        return errors

    def get_github_token(self) -> Optional[str]:
        """
        从环境变量获取GitHub Token。
        
        用于Git操作时的身份认证。
        
        Returns:
            GitHub Token字符串，未设置则返回None
        
        Example:
            token = manager.get_github_token()
            if token:
                print("GitHub Token已设置")
            else:
                print("警告: GitHub Token未设置，Git操作可能失败")
        """
        return os.environ.get(self.ENV_GITHUB_TOKEN)
