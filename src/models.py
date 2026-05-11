from __future__ import annotations

from dataclasses import dataclass


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
class FilterResult:
    """论文筛选结果，包含论文对象与 AI 评估信息"""

    paper: Paper  # 论文对象
    score: str  # 相关度评分（HIGH/MEDIUM/LOW/IRRELEVANT）
    reason: str  # AI 给出的理由


@dataclass
class PipelineRun:
    """一次完整流水线运行的记录"""

    date: str  # 运行日期
    categories: list[str]  # 处理的分类
    total_fetched: int  # 嗅探获取总数
    total_filtered: int  # 筛选后保留数
    papers: list[FilterResult]  # 筛选结果列表
