from dataclasses import dataclass, field


@dataclass
class DomainRule:
    """领域筛选规则：定义某个 arXiv 分类的抓取策略"""

    category: str
    mode: str  # "accept_all" 或 "categories_filter"
    filter_categories: list[str] = field(default_factory=list)


@dataclass
class Paper:
    """arXiv 论文数据模型"""

    arxiv_id: str  # arXiv 论文唯一标识
    title: str  # 论文标题
    abstract: str  # 论文摘要
    authors: list[str]  # 作者列表
    categories: list[str]  # 所属分类
    pdf_url: str  # PDF 下载链接
    published: str  # 发布日期


@dataclass
class AnalysisResult:
    """论文综合分析结果（合并筛选与总结）"""

    paper: Paper  # 论文对象
    score: str  # 相关度评分（HIGH/MEDIUM/LOW/IRRELEVANT）
    reason: str  # AI 给出的评估理由
    core_methods: str  # 核心技术方法
    problem: str  # 需要解决的问题
    keywords: list[str]  # 最多五个关键词


@dataclass
class SummaryResult:
    """论文总结结果"""

    paper: Paper  # 论文对象
    core_methods: str  # 核心技术方法
    problem: str  # 需要解决的问题
    keywords: list[str]  # 最多五个关键词
    error: str | None = None  # 错误信息
