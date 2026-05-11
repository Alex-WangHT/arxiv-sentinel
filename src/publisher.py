from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from src.models import FilterResult, PipelineRun


# score 降序排列优先级映射
_SCORE_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "IRRELEVANT": 3}

class Publisher:
    """负责将流水线运行结果发布为 JSON / Markdown 报告，并维护历史记录"""

    def __init__(self, output_dir: str, history_file: str):
        self.output_dir = Path(output_dir)
        self.history_file = Path(history_file)

    def publish_json(self, run: PipelineRun) -> str:
        """将 PipelineRun 序列化为 JSON 报告并保存，返回文件路径"""
        reports_dir = self.output_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        # 将 FilterResult 列表展平为 JSON 所需格式
        papers = []
        for fr in run.papers:
            papers.append({
                "arxiv_id": fr.paper.arxiv_id,
                "title": fr.paper.title,
                "abstract": fr.paper.abstract,
                "score": fr.score,
                "reason": fr.reason,
                "pdf_url": fr.paper.pdf_url,
            })

        report = {
            "date": run.date,
            "categories": run.categories,
            "total_fetched": run.total_fetched,
            "total_filtered": run.total_filtered,
            "papers": papers,
        }

        path = reports_dir / f"{run.date}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    def publish_markdown(self, run: PipelineRun) -> str:
        """将 PipelineRun 生成 Markdown 报告并保存，返回文件路径"""
        reports_dir = self.output_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        # 按 score 降序排列
        sorted_papers = sorted(run.papers, key=lambda fr: _SCORE_ORDER.get(fr.score, 99))

        lines: list[str] = []
        lines.append(f"# 论文筛选报告 — {run.date}")
        lines.append("")
        lines.append(f"- 分类：{', '.join(run.categories)}")
        lines.append(f"- 获取总数：{run.total_fetched}")
        lines.append(f"- 筛选保留：{run.total_filtered}")
        lines.append("")
        lines.append("---")
        lines.append("")

        for fr in sorted_papers:
            lines.append(f"## {fr.paper.title}")
            lines.append("")
            lines.append(f"- **相关度**：{fr.score}")
            lines.append(f"- **理由**：{fr.reason}")
            lines.append(f"- **PDF**：[{fr.paper.arxiv_id}]({fr.paper.pdf_url})")
            lines.append("")

        path = reports_dir / f"{run.date}.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        return str(path)

    def update_history(self, run: PipelineRun) -> None:
        """将本次处理的 arxiv_id 追加到历史文件（去重）"""
        # 读取已有历史
        if self.history_file.exists():
            existing: list[str] = json.loads(self.history_file.read_text(encoding="utf-8"))
        else:
            existing = []

        # 收集本次新增的 arxiv_id
        new_ids = [fr.paper.arxiv_id for fr in run.papers]

        # 合并并去重
        merged = list(dict.fromkeys(existing + new_ids))

        # 确保父目录存在后写入
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        self.history_file.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    def publish(self, run: PipelineRun) -> dict:
        """统一发布：依次生成 JSON 报告、Markdown 报告、更新历史记录"""
        json_path = self.publish_json(run)
        md_path = self.publish_markdown(run)
        self.update_history(run)
        return {"json_path": json_path, "md_path": md_path}
