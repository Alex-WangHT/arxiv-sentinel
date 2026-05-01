import os
import re
import json
import time
import requests
import fitz
from typing import Dict, Optional, List, Tuple
from datetime import datetime

from .sniffer import Paper


class RetryManager:
    def __init__(self, max_retries: int = 3, initial_delay: float = 1.0, backoff_factor: float = 2.0):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.backoff_factor = backoff_factor

    def execute(self, func, *args, **kwargs):
        last_exception = None
        delay = self.initial_delay

        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout) as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    print(f"    重试 {attempt + 1}/{self.max_retries} 后... (等待 {delay}s)")
                    time.sleep(delay)
                    delay *= self.backoff_factor
                else:
                    raise
            except Exception as e:
                raise

        raise last_exception


class PDFExtractor:
    def __init__(self):
        pass

    def extract_text(self, pdf_path: str) -> str:
        doc = fitz.open(pdf_path)
        text_parts = []

        for page_num, page in enumerate(doc):
            page_text = page.get_text()
            if page_text:
                page_text = self._clean_text(page_text)
                text_parts.append(page_text)

        doc.close()
        full_text = "\n\n".join(text_parts)
        return self._normalize_encoding(full_text)

    def _clean_text(self, text: str) -> str:
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'(\n )+', '\n', text)
        return text.strip()

    def _normalize_encoding(self, text: str) -> str:
        text = text.encode('utf-8', errors='ignore').decode('utf-8')
        text = text.replace('\ufffd', '')
        return text

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

    def __init__(self, api_key: str, model: str = "Qwen/Qwen2.5-7B-Instruct", timeout: int = 180, max_retries: int = 3):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self.retry_manager = RetryManager(max_retries=max_retries)

    def chat(
        self,
        prompt: str,
        system_prompt: str = "你是一个专业的学术论文助手。",
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> str:
        def _make_request():
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

            response = requests.post(
                self.BASE_URL,
                headers=self.headers,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()

            result = response.json()
            content = result["choices"][0]["message"]["content"]

            content = content.encode('utf-8', errors='ignore').decode('utf-8')
            content = content.replace('\ufffd', '')

            return content

        return self.retry_manager.execute(_make_request)


class PaperFilter:
    RELEVANT = "relevant"
    IRRELEVANT = "irrelevant"

    def __init__(self, siliconflow_client: SiliconFlowClient):
        self.client = siliconflow_client

    def is_relevant(self, paper: Paper, target_keywords: List[str]) -> Tuple[bool, str]:
        if not paper.summary or len(paper.summary.strip()) < 50:
            print(f"    警告: 论文 {paper.arxiv_id} 摘要过短，跳过筛选")
            return True, "摘要过短，跳过筛选"

        keywords_str = ", ".join(target_keywords)

        system_prompt = """你是一个专业的学术论文筛选助手。你的任务是根据论文的标题和摘要，判断这篇论文是否与给定的关键词相关。

判断标准：
1. 论文主题必须与关键词高度相关
2. 关键词必须出现在论文的核心研究内容中
3. 如果论文只是在背景介绍中提到关键词，但核心研究内容不相关，则判定为不相关
4. 如果论文分类是物理、化学、生物等领域，但关键词是计算机科学（如LLM、transformer、神经网络等），则判定为不相关

请只输出以下格式之一（不要输出其他内容）：
- RELEVANT: 如果论文与关键词相关
- IRRELEVANT: 如果论文与关键词不相关"""

        user_prompt = f"""请判断以下论文是否与关键词 "{keywords_str}" 相关：

论文标题: {paper.title}

论文分类: {', '.join(paper.categories) if paper.categories else '未知'}

论文摘要:
{paper.summary}

请只输出 RELEVANT 或 IRRELEVANT。"""

        try:
            print(f"    筛选论文 {paper.arxiv_id}...")
            result = self.client.chat(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.1,
                max_tokens=20,
            )

            result = result.strip().upper()

            if self.IRRELEVANT in result:
                return False, f"AI判定为不相关 ({result})"
            elif self.RELEVANT in result:
                return True, f"AI判定为相关 ({result})"
            else:
                print(f"    警告: 无法解析AI响应 '{result}'，默认判定为相关")
                return True, f"无法解析响应，默认相关"

        except Exception as e:
            print(f"    筛选过程出错: {e}，默认判定为相关")
            return True, f"筛选出错，默认相关"


class Summarizer:
    def __init__(self, siliconflow_api_key: str, prompt_dir: str = "./markdown"):
        self.pdf_extractor = PDFExtractor()
        self.siliconflow_client = SiliconFlowClient(siliconflow_api_key)
        self.paper_filter = PaperFilter(self.siliconflow_client)
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

    def filter_papers(self, papers: List[Paper], keywords: List[str]) -> Tuple[List[Paper], List[Paper]]:
        if not keywords:
            return papers, []

        relevant_papers = []
        irrelevant_papers = []

        print(f"\n开始筛选论文 (共 {len(papers)} 篇)...")
        print(f"目标关键词: {', '.join(keywords)}")

        for i, paper in enumerate(papers):
            print(f"\n  [{i+1}/{len(papers)}] 检查: {paper.arxiv_id}")
            print(f"      标题: {paper.title[:60]}...")
            print(f"      分类: {', '.join(paper.categories) if paper.categories else '未知'}")

            is_relevant, reason = self.paper_filter.is_relevant(paper, keywords)

            if is_relevant:
                print(f"      ✓ 相关 ({reason})")
                relevant_papers.append(paper)
            else:
                print(f"      ✗ 不相关 ({reason})")
                irrelevant_papers.append(paper)

        print(f"\n筛选完成: 相关 {len(relevant_papers)} 篇，不相关 {len(irrelevant_papers)} 篇")
        return relevant_papers, irrelevant_papers

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
