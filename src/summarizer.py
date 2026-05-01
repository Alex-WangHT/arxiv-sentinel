import os
import re
import json
import requests
import fitz
from typing import Dict, Optional, List
from datetime import datetime

from .sniffer import Paper


class PDFExtractor:
    def __init__(self):
        pass

    def extract_text(self, pdf_path: str) -> str:
        doc = fitz.open(pdf_path)
        text_parts = []

        for page_num, page in enumerate(doc):
            page_text = page.get_text()
            text_parts.append(page_text)

        doc.close()
        return "\n\n".join(text_parts)

    def extract_section(self, pdf_path: str, section_name: str) -> Optional[str]:
        text = self.extract_text(pdf_path)

        section_patterns = [
            rf"(?i){section_name}\s*\n\s*[IVX\d]+\.?\s*\n",
            rf"(?i){section_name}\s*\n\s*[A-Z][a-z]+\s*\n",
            rf"(?i)^{section_name}\s*$",
            rf"(?i){section_name}\s*[.:]",
        ]

        for pattern in section_patterns:
            matches = list(re.finditer(pattern, text, re.MULTILINE))
            if matches:
                start_idx = matches[0].end()

                next_section_patterns = [
                    r"(?i)^\s*[IVX\d]+\.?\s+[A-Z]",
                    r"(?i)^\s*(References|Bibliography|Appendix|Conclusion|Results|Discussion)\s*$",
                    r"(?i)^\s*References\s*[.:]",
                    r"(?i)^\s*Acknowledgements\s*$",
                ]

                end_idx = len(text)
                for next_pattern in next_section_patterns:
                    next_match = re.search(next_pattern, text[start_idx:], re.MULTILINE)
                    if next_match:
                        end_idx = start_idx + next_match.start()
                        break

                return text[start_idx:end_idx].strip()

        return None


class SiliconFlowClient:
    BASE_URL = "https://api.siliconflow.cn/v1/chat/completions"

    def __init__(self, api_key: str, model: str = "Qwen/Qwen2.5-7B-Instruct"):
        self.api_key = api_key
        self.model = model
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def chat(self, prompt: str, system_prompt: str = "你是一个专业的学术论文助手。", temperature: float = 0.3) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": 4096,
        }

        response = requests.post(self.BASE_URL, headers=self.headers, json=payload, timeout=120)
        response.raise_for_status()

        result = response.json()
        return result["choices"][0]["message"]["content"]


class Summarizer:
    def __init__(self, siliconflow_api_key: str, prompt_dir: str = "./markdown"):
        self.pdf_extractor = PDFExtractor()
        self.siliconflow_client = SiliconFlowClient(siliconflow_api_key)
        self.prompt_dir = prompt_dir
        self._load_prompts()

    def _load_prompts(self):
        self.prompts = {}
        prompt_files = [
            "summary_prompt.txt",
            "technical_route_prompt.txt",
            "methodology_prompt.txt",
            "experiment_prompt.txt",
            "introduction_prompt.txt",
        ]

        for filename in prompt_files:
            filepath = os.path.join(self.prompt_dir, filename)
            if os.path.exists(filepath):
                with open(filepath, "r", encoding="utf-8") as f:
                    self.prompts[filename] = f.read()
            else:
                self.prompts[filename] = self._get_default_prompt(filename)

    def _get_default_prompt(self, prompt_type: str) -> str:
        defaults = {
            "summary_prompt.txt": """请为以下论文提供一个简洁的摘要总结。要求：
1. 用中文回答
2. 突出论文的核心贡献和创新点
3. 不要超过300字

论文内容：
{content}""",
            "technical_route_prompt.txt": """请分析以下论文的技术路线。要求：
1. 用中文回答
2. 分点列出技术路线的关键步骤
3. 说明各步骤之间的逻辑关系
4. 指出技术路线的创新性

论文内容：
{content}""",
            "methodology_prompt.txt": """请分析以下论文的方法论。要求：
1. 用中文回答
2. 详细描述论文采用的核心方法和技术
3. 说明方法的理论基础
4. 分析方法的优势和局限性

论文内容：
{content}""",
            "experiment_prompt.txt": """请分析以下论文的实验方案。要求：
1. 用中文回答
2. 列出实验设置（数据集、评价指标、基线方法等）
3. 总结主要实验结果
4. 分析实验的有效性和局限性

论文内容：
{content}""",
            "introduction_prompt.txt": """请分析以下论文的Introduction行文逻辑。要求：
1. 用中文回答
2. 梳理作者如何提出问题和背景
3. 分析作者如何引出研究动机
4. 说明论文贡献的组织方式

论文内容：
{content}""",
        }
        return defaults.get(prompt_type, "")

    def summarize(self, paper: Paper) -> Dict:
        if not paper.local_pdf_path:
            raise ValueError(f"Paper {paper.arxiv_id} has no local PDF path")

        full_text = self.pdf_extractor.extract_text(paper.local_pdf_path)

        summary_result = {}
        summary_result["arxiv_id"] = paper.arxiv_id
        summary_result["title"] = paper.title
        summary_result["authors"] = paper.authors
        summary_result["arxiv_url"] = f"https://arxiv.org/abs/{paper.arxiv_id}"
        summary_result["pdf_url"] = paper.pdf_url
        summary_result["published"] = paper.published
        summary_result["categories"] = paper.categories
        summary_result["original_abstract"] = paper.summary

        print(f"Summarizing paper: {paper.arxiv_id}")

        if len(full_text) > 8000:
            full_text = full_text[:8000] + "\n...（内容已截断）"

        summary = self.siliconflow_client.chat(
            prompt=self.prompts["summary_prompt.txt"].format(content=full_text),
            system_prompt="你是一个专业的学术论文助手，擅长总结和分析学术论文。",
        )
        summary_result["summary"] = summary
        print("  - Summary completed")

        technical_route = self.siliconflow_client.chat(
            prompt=self.prompts["technical_route_prompt.txt"].format(content=full_text),
            system_prompt="你是一个专业的学术论文助手，擅长分析论文的技术路线。",
        )
        summary_result["technical_route"] = technical_route
        print("  - Technical route completed")

        methodology = self.siliconflow_client.chat(
            prompt=self.prompts["methodology_prompt.txt"].format(content=full_text),
            system_prompt="你是一个专业的学术论文助手，擅长分析论文的方法论。",
        )
        summary_result["methodology"] = methodology
        print("  - Methodology completed")

        experiment = self.siliconflow_client.chat(
            prompt=self.prompts["experiment_prompt.txt"].format(content=full_text),
            system_prompt="你是一个专业的学术论文助手，擅长分析论文的实验方案。",
        )
        summary_result["experiment"] = experiment
        print("  - Experiment completed")

        intro_analysis = self.siliconflow_client.chat(
            prompt=self.prompts["introduction_prompt.txt"].format(content=full_text),
            system_prompt="你是一个专业的学术论文助手，擅长分析论文的写作结构。",
        )
        summary_result["introduction_analysis"] = intro_analysis
        print("  - Introduction analysis completed")

        return summary_result

    def generate_markdown(self, summary_result: Dict, output_dir: str) -> str:
        template_path = os.path.join(self.prompt_dir, "paper_template.md")
        if os.path.exists(template_path):
            with open(template_path, "r", encoding="utf-8") as f:
                template = f.read()
        else:
            template = self._get_default_template()

        markdown_content = template.format(
            title=summary_result["title"],
            arxiv_id=summary_result["arxiv_id"],
            arxiv_url=summary_result["arxiv_url"],
            authors=", ".join(summary_result["authors"]),
            published=summary_result["published"],
            categories=", ".join(summary_result["categories"]),
            original_abstract=summary_result["original_abstract"],
            summary=summary_result["summary"],
            technical_route=summary_result["technical_route"],
            methodology=summary_result["methodology"],
            experiment=summary_result["experiment"],
            introduction_analysis=summary_result["introduction_analysis"],
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

        safe_title = re.sub(r'[<>:"/\\|?*]', "", summary_result["title"])
        safe_title = safe_title[:50].strip()
        filename = f"{summary_result['arxiv_id']}_{safe_title}.md"

        output_path = os.path.join(output_dir, filename)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        return output_path

    def _get_default_template(self) -> str:
        return """# {title}

> arXiv: [{arxiv_id}]({arxiv_url}) | 发布时间: {published}
>
> 作者: {authors}
>
> 分类: {categories}

---

## 原文摘要

{original_abstract}

---

## 论文总结

{summary}

---

## 技术路线分析

{technical_route}

---

## 方法论分析

{methodology}

---

## 实验方案分析

{experiment}

---

## Introduction行文逻辑分析

{introduction_analysis}

---

*本文由 arXiv Sentinel 自动生成于 {generated_at}*
"""
