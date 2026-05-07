"""PaperSummarizer — 多模态全文总结 + Jinja2 渲染（SPEC §4 Step 5 / §5.3）。"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from src.llm_client import LLMClient
from src.sniffer import PaperObject

logger = logging.getLogger(__name__)

_TAG_PATTERNS = {
    "relative_work": re.compile(r"<relative_work>(.*?)</relative_work>", re.DOTALL),
    "intro_summary": re.compile(r"<intro_summary>(.*?)</intro_summary>", re.DOTALL),
    "methodology": re.compile(r"<methodology>(.*?)</methodology>", re.DOTALL),
    "technical_route_text": re.compile(r"<technical_route>\s*<text>(.*?)</text>", re.DOTALL),
    "mermaid": re.compile(r"<mermaid>(.*?)</mermaid>", re.DOTALL),
    "experiments": re.compile(r"<experiments>(.*?)</experiments>", re.DOTALL),
}


@dataclass
class SummarySections:
    relative_work: str
    intro_summary: str
    methodology: str
    technical_route_text: str
    mermaid: str
    experiments: str


class PaperSummarizer:
    def __init__(
        self,
        llm_client: LLMClient,
        model: str,
        prompts_dir: Path,
        template_path: Path,
        output_dir: Path,
        image_cache_dir: Path,
        max_pdf_pages: int = 5,
        fallback_text_pages: int = 2,
    ) -> None:
        self.llm = llm_client
        self.model = model
        self.prompts_dir = prompts_dir
        self.template_path = template_path
        self.output_dir = output_dir
        self.image_cache_dir = image_cache_dir
        self.max_pdf_pages = max_pdf_pages
        self.fallback_text_pages = fallback_text_pages
        self._system_prompt = self._load_prompt("system.md")
        self._user_template = self._load_prompt("user.md")
        self._jinja_env = self._build_jinja_env()

    def summarize(self, paper: PaperObject) -> Path:
        """主入口：图片化 → 多模态调用 → 解析 → Jinja2 渲染 → 写文件。"""
        try:
            images_b64 = self._pdf_to_base64_images(paper.pdf_path)
            response = self.llm.chat_multimodal(
                model=self.model,
                system_prompt=self._system_prompt,
                user_prompt=self._render_user_prompt(paper),
                image_b64_list=images_b64,
            )
            del images_b64
        except Exception as exc:
            logger.warning("multimodal failed for %s: %s — falling back to text-only", paper.arxiv_id, exc)
            response = self._fallback_text_summarize(paper)

        sections = self._parse_response(response)
        return self._write_markdown(paper, sections)

    def _pdf_to_base64_images(self, pdf_path: Path) -> list[str]:
        """pdf2image 转前 max_pdf_pages 页 → base64 列表。"""
        raise NotImplementedError

    def _fallback_text_summarize(self, paper: PaperObject) -> str:
        """降级：仅发送前 fallback_text_pages 页文本，调 chat_json。"""
        raise NotImplementedError

    def _parse_response(self, response_text: str) -> SummarySections:
        def grab(key: str) -> str:
            m = _TAG_PATTERNS[key].search(response_text)
            return m.group(1).strip() if m else ""

        return SummarySections(
            relative_work=grab("relative_work"),
            intro_summary=grab("intro_summary"),
            methodology=grab("methodology"),
            technical_route_text=grab("technical_route_text"),
            mermaid=grab("mermaid"),
            experiments=grab("experiments"),
        )

    def _write_markdown(self, paper: PaperObject, sections: SummarySections) -> Path:
        """渲染 paper_template.md → docs/papers/YYYY-MM-DD-[arxiv_id].md；含 YAML Front Matter 校验。"""
        raise NotImplementedError

    def _render_user_prompt(self, paper: PaperObject) -> str:
        raise NotImplementedError

    def _build_jinja_env(self):
        raise NotImplementedError

    def _load_prompt(self, filename: str) -> str:
        return (self.prompts_dir / filename).read_text(encoding="utf-8")
