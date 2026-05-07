"""通用工具函数（YAML 校验、文件名安全化、特殊字符处理等 — SPEC §6）。"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


def safe_yaml_string(value: str) -> str:
    """SPEC §6 格式校验：标题含 :, ', " 时用双引号包裹并转义内部双引号。"""
    if any(ch in value for ch in (":", "'", '"')):
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


def validate_front_matter(meta: dict[str, Any]) -> None:
    """写入前校验：必填字段齐全 + YAML 可序列化。"""
    required = {"title", "date", "arxiv_id", "categories", "keywords", "ai_score", "url", "authors"}
    missing = required - set(meta.keys())
    if missing:
        raise ValueError(f"front matter missing fields: {missing}")
    yaml.safe_dump(meta, allow_unicode=True)


def render_front_matter(meta: dict[str, Any]) -> str:
    """生成 `---` 包裹的 YAML 块。"""
    body = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{body}\n---\n"


def paper_filename(arxiv_id: str, published: str | datetime) -> str:
    """SPEC §4 Step 5: docs/papers/YYYY-MM-DD-[arxiv_id].md。"""
    date_str = published.strftime("%Y-%m-%d") if isinstance(published, datetime) else published[:10]
    return f"{date_str}-{arxiv_id}.md"


_ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")


def extract_arxiv_id(text: str) -> str | None:
    m = _ARXIV_ID_RE.search(text)
    return m.group(1) if m else None


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
