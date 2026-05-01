import os
import re
import io
import base64
import time
import requests
import fitz
from typing import Dict, Optional, List, Tuple, Union
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
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, 
                    requests.exceptions.ReadTimeout, requests.exceptions.ChunkedEncodingError) as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    print(f"    重试 {attempt + 1}/{self.max_retries}... (等待 {delay}s)")
                    time.sleep(delay)
                    delay *= self.backoff_factor
                else:
                    raise
            except Exception as e:
                raise

        raise last_exception


class ImageConverter:
    def __init__(self, max_pages: int = 10, dpi: int = 150):
        self.max_pages = max_pages
        self.dpi = dpi

    def pdf_to_images(self, pdf_path: str) -> List[bytes]:
        doc = fitz.open(pdf_path)
        images = []

        total_pages = min(len(doc), self.max_pages)
        print(f"    转换PDF前 {total_pages} 页为图像...")

        for page_num in range(total_pages):
            page = doc[page_num]
            mat = fitz.Matrix(self.dpi / 72, self.dpi / 72)
            pix = page.get_pixmap(matrix=mat)
            
            img_data = pix.tobytes("png")
            images.append(img_data)

        doc.close()
        return images

    def image_to_base64(self, img_data: bytes) -> str:
        return base64.b64encode(img_data).decode("utf-8")

    def pdf_to_base64_images(self, pdf_path: str) -> List[str]:
        images = self.pdf_to_images(pdf_path)
        return [self.image_to_base64(img) for img in images]


class SiliconFlowClient:
    BASE_URL = "https://api.siliconflow.cn/v1/chat/completions"

    def __init__(
        self,
        api_key: str,
        text_model: str = "Qwen/Qwen2.5-7B-Instruct",
        vision_model: str = "Qwen/Qwen2-VL-72B-Instruct",
        timeout: int = 180,
        max_retries: int = 3,
    ):
        self.api_key = api_key
        self.text_model = text_model
        self.vision_model = vision_model
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
        use_vision_model: bool = False,
    ) -> str:
        model = self.vision_model if use_vision_model else self.text_model

        def _make_request():
            payload = {
                "model": model,
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
            return self._clean_response(content)

        return self.retry_manager.execute(_make_request)

    def chat_with_images(
        self,
        text_prompt: str,
        images: List[Union[str, bytes]],
        system_prompt: str = "你是一个专业的学术论文助手。",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        detail: str = "high",
    ) -> str:
        def _make_request():
            content_parts = []

            for i, img in enumerate(images):
                if isinstance(img, bytes):
                    base64_img = base64.b64encode(img).decode("utf-8")
                    img_url = f"data:image/png;base64,{base64_img}"
                elif img.startswith("data:"):
                    img_url = img
                else:
                    base64_img = img
                    img_url = f"data:image/png;base64,{base64_img}"

                content_parts.append({
                    "type": "image_url",
                    "image_url": {
                        "url": img_url,
                        "detail": detail,
                    }
                })

            content_parts.append({
                "type": "text",
                "text": text_prompt,
            })

            payload = {
                "model": self.vision_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content_parts},
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
            return self._clean_response(content)

        return self.retry_manager.execute(_make_request)

    def chat_with_pdf(
        self,
        pdf_path: str,
        text_prompt: str,
        system_prompt: str = "你是一个专业的学术论文助手。",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        max_pages: int = 10,
    ) -> str:
        converter = ImageConverter(max_pages=max_pages)
        images = converter.pdf_to_images(pdf_path)

        if not images:
            raise ValueError(f"无法从PDF提取图像: {pdf_path}")

        return self.chat_with_images(
            text_prompt=text_prompt,
            images=images,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def _clean_response(self, content: str) -> str:
        content = content.encode('utf-8', errors='ignore').decode('utf-8')
        content = content.replace('\ufffd', '')
        content = re.sub(r'\n{3,}', '\n\n', content)
        return content.strip()


class PaperFilter:
    RELEVANT = "RELEVANT"
    IRRELEVANT = "IRRELEVANT"

    def __init__(self, siliconflow_client: SiliconFlowClient):
        self.client = siliconflow_client

    def is_relevant(self, paper: Paper, target_keywords: List[str]) -> Tuple[bool, str]:
        if not paper.summary or len(paper.summary.strip()) < 30:
            print(f"    警告: 论文 {paper.arxiv_id} 摘要过短，跳过筛选")
            return True, "摘要过短，跳过筛选"

        keywords_str = ", ".join(target_keywords)
        categories_str = ", ".join(paper.categories) if paper.categories else "未知"

        system_prompt = f"""你是一个严格的学术论文筛选助手。你的任务是根据论文的标题、分类和摘要，判断这篇论文是否与给定的关键词高度相关。

判断规则：
1. 只输出两个词之一：{self.RELEVANT} 或 {self.IRRELEVANT}
2. 不要输出任何其他解释、标点或说明文字
3. 如果论文明确属于物理、化学、生物、医学、机械等非计算机科学领域，且关键词是计算机科学相关（如LLM、transformer、神经网络、深度学习等），则判定为 {self.IRRELEVANT}
4. 如果论文分类是 cs.RO（机器人）但核心内容是计算机视觉/深度学习，则判定为 {self.RELEVANT}
5. 如果只是在背景介绍中提到关键词，但核心研究内容不相关，则判定为 {self.IRRELEVANT}
6. 如果论文标题和摘要都显示与关键词高度相关，则判定为 {self.RELEVANT}

注意：必须严格只输出 {self.RELEVANT} 或 {self.IRRELEVANT}，不要添加任何其他内容！"""

        user_prompt = f"""请判断以下论文是否与关键词 "{keywords_str}" 高度相关：

论文标题: {paper.title}

论文分类: {categories_str}

论文摘要:
{paper.summary}

只输出 {self.RELEVANT} 或 {self.IRRELEVANT}，不要输出其他任何内容！"""

        try:
            print(f"    筛选论文 {paper.arxiv_id}...")
            result = self.client.chat(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.1,
                max_tokens=20,
                use_vision_model=False,
            )

            result = result.strip().upper()
            result = re.sub(r'[^A-Z_]', '', result)

            print(f"    AI响应: '{result}'")

            if self.IRRELEVANT == result or self.IRRELEVANT in result:
                return False, f"AI判定为不相关"
            elif self.RELEVANT == result or self.RELEVANT in result:
                return True, f"AI判定为相关"
            else:
                print(f"    警告: 无法解析AI响应，默认判定为相关")
                return True, f"无法解析响应，默认相关"

        except Exception as e:
            print(f"    筛选过程出错: {e}，默认判定为相关")
            import traceback
            traceback.print_exc()
            return True, f"筛选出错，默认相关"


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


class Summarizer:
    def __init__(
        self,
        siliconflow_api_key: str,
        prompt_dir: str = "./markdown",
        use_vision_mode: bool = False,
        text_model: str = "Qwen/Qwen2.5-7B-Instruct",
        vision_model: str = "Qwen/Qwen2-VL-72B-Instruct",
    ):
        self.use_vision_mode = use_vision_mode
        self.pdf_extractor = PDFExtractor()
        self.image_converter = ImageConverter(max_pages=10)
        self.siliconflow_client = SiliconFlowClient(
            api_key=siliconflow_api_key,
            text_model=text_model,
            vision_model=vision_model,
        )
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
            "summary_prompt.txt": """请为以下学术论文提供一个简洁的摘要总结。要求：
1. 用中文回答
2. 突出论文的核心贡献和创新点
3. 总结要准确、全面，不要遗漏关键信息
4. 字数控制在300-500字之间

请用清晰的段落组织你的回答。""",

            "technical_route_prompt.txt": """请分析以下论文的技术路线。要求：
1. 用中文回答
2. 分点列出技术路线的关键步骤（使用1. 2. 3. 格式）
3. 说明各步骤之间的逻辑关系和数据流
4. 指出技术路线的创新性和与现有方法的区别
5. 如果有架构图或流程图，请描述图中的关键组件和连接

请清晰、有条理地组织你的回答。""",

            "methodology_prompt.txt": """请分析以下论文的方法论。要求：
1. 用中文回答
2. 详细描述论文采用的核心方法和技术
3. 说明方法的理论基础和数学原理（如有）
4. 分析方法的优势、局限性和适用场景
5. 描述方法的实现细节和关键算法步骤

请清晰、有条理地组织你的回答。""",

            "experiment_prompt.txt": """请分析以下论文的实验方案。要求：
1. 用中文回答
2. 列出实验设置：
   - 数据集（名称、规模、来源）
   - 评价指标
   - 基线方法（Baselines）
   - 实现细节（硬件、框架、超参数等）
3. 总结主要实验结果和关键发现
4. 分析实验的有效性、可靠性和局限性
5. 如果有消融实验（Ablation Study），请分析其结果

请清晰、有条理地组织你的回答。""",

            "introduction_prompt.txt": """请分析以下论文的Introduction（引言）部分的行文逻辑。要求：
1. 用中文回答
2. 梳理作者如何提出研究背景和问题
3. 分析作者如何引出研究动机和挑战
4. 说明论文贡献的组织方式和阐述顺序
5. 分析作者如何定位自己的工作与现有研究的关系

请清晰、有条理地组织你的回答。""",
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

        summary_result = {}
        summary_result["arxiv_id"] = paper.arxiv_id
        summary_result["title"] = paper.title
        summary_result["authors"] = paper.authors
        summary_result["arxiv_url"] = f"https://arxiv.org/abs/{paper.arxiv_id}"
        summary_result["pdf_url"] = paper.pdf_url
        summary_result["published"] = paper.published
        summary_result["categories"] = paper.categories
        summary_result["original_abstract"] = paper.summary

        print(f"  总结论文: {paper.arxiv_id}")

        if self.use_vision_mode:
            return self._summarize_with_vision(paper, summary_result)
        else:
            return self._summarize_with_text(paper, summary_result)

    def _summarize_with_text(self, paper: Paper, summary_result: Dict) -> Dict:
        full_text = self.pdf_extractor.extract_text(paper.local_pdf_path)

        if len(full_text) > 12000:
            full_text = full_text[:12000] + "\n...（内容已截断）"

        print("    使用文本模式总结...")

        system_prompt = "你是一个专业的学术论文助手，擅长总结和分析学术论文。请用中文回答，确保回答准确、清晰、有条理。"

        summary = self.siliconflow_client.chat(
            prompt=self.prompts["summary_prompt.txt"] + "\n\n论文内容：\n" + full_text,
            system_prompt=system_prompt,
            use_vision_model=False,
        )
        summary_result["summary"] = summary
        print("      ✓ 摘要总结完成")

        technical_route = self.siliconflow_client.chat(
            prompt=self.prompts["technical_route_prompt.txt"] + "\n\n论文内容：\n" + full_text,
            system_prompt=system_prompt,
            use_vision_model=False,
        )
        summary_result["technical_route"] = technical_route
        print("      ✓ 技术路线分析完成")

        methodology = self.siliconflow_client.chat(
            prompt=self.prompts["methodology_prompt.txt"] + "\n\n论文内容：\n" + full_text,
            system_prompt=system_prompt,
            use_vision_model=False,
        )
        summary_result["methodology"] = methodology
        print("      ✓ 方法论分析完成")

        experiment = self.siliconflow_client.chat(
            prompt=self.prompts["experiment_prompt.txt"] + "\n\n论文内容：\n" + full_text,
            system_prompt=system_prompt,
            use_vision_model=False,
        )
        summary_result["experiment"] = experiment
        print("      ✓ 实验方案分析完成")

        intro_analysis = self.siliconflow_client.chat(
            prompt=self.prompts["introduction_prompt.txt"] + "\n\n论文内容：\n" + full_text,
            system_prompt=system_prompt,
            use_vision_model=False,
        )
        summary_result["introduction_analysis"] = intro_analysis
        print("      ✓ Introduction分析完成")

        return summary_result

    def _summarize_with_vision(self, paper: Paper, summary_result: Dict) -> Dict:
        print("    使用视觉模式（多模态）总结...")
        print("    正在将PDF转换为图像...")

        images = self.image_converter.pdf_to_images(paper.local_pdf_path)
        print(f"    已转换 {len(images)} 页为图像")

        system_prompt = "你是一个专业的学术论文助手，擅长通过阅读论文图像来总结和分析学术论文。请用中文回答，确保回答准确、清晰、有条理。"

        summary = self.siliconflow_client.chat_with_images(
            text_prompt=self.prompts["summary_prompt.txt"],
            images=images,
            system_prompt=system_prompt,
        )
        summary_result["summary"] = summary
        print("      ✓ 摘要总结完成")

        technical_route = self.siliconflow_client.chat_with_images(
            text_prompt=self.prompts["technical_route_prompt.txt"],
            images=images,
            system_prompt=system_prompt,
        )
        summary_result["technical_route"] = technical_route
        print("      ✓ 技术路线分析完成")

        methodology = self.siliconflow_client.chat_with_images(
            text_prompt=self.prompts["methodology_prompt.txt"],
            images=images,
            system_prompt=system_prompt,
        )
        summary_result["methodology"] = methodology
        print("      ✓ 方法论分析完成")

        experiment = self.siliconflow_client.chat_with_images(
            text_prompt=self.prompts["experiment_prompt.txt"],
            images=images,
            system_prompt=system_prompt,
        )
        summary_result["experiment"] = experiment
        print("      ✓ 实验方案分析完成")

        intro_analysis = self.siliconflow_client.chat_with_images(
            text_prompt=self.prompts["introduction_prompt.txt"],
            images=images,
            system_prompt=system_prompt,
        )
        summary_result["introduction_analysis"] = intro_analysis
        print("      ✓ Introduction分析完成")

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
