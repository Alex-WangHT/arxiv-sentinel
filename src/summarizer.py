"""
arXiv Sentinel - 论文总结模块
================================
本模块提供论文PDF处理、AI总结和筛选功能。

主要类：
- RetryManager: 带指数退避的重试管理器
- ImageConverter: PDF转图像转换器（用于多模态模型）
- SiliconFlowClient: 硅基流动API客户端
- PaperFilter: AI论文筛选器（基于Abstract判断相关性）
- PDFExtractor: PDF文本提取器
- Summarizer: 论文总结器（整合所有功能）

使用示例：
    from src.summarizer import Summarizer, PaperFilter, SiliconFlowClient
    
    # 创建总结器
    summarizer = Summarizer(
        siliconflow_api_key="your-api-key",
        use_vision_mode=False
    )
    
    # 筛选论文（下载PDF前）
    relevant, irrelevant = summarizer.filter_papers(papers, ["LLM", "transformer"])
    
    # 下载并总结论文
    for paper in relevant:
        summary = summarizer.summarize(paper)
        md_path = summarizer.generate_markdown(summary, "./output")
"""

import os
import re
import base64
import time
import requests
import fitz
from typing import Dict, Optional, List, Tuple, Union
from datetime import datetime

from .sniffer import Paper


class RetryManager:
    """
    带指数退避的重试管理器。
    
    该类提供了一个可重用的重试机制，用于处理网络请求等可能失败的操作。
    支持最大重试次数配置和指数退避延迟策略。
    
    Attributes:
        max_retries (int): 最大重试次数
        initial_delay (float): 初始延迟时间（秒）
        backoff_factor (float): 退避因子，每次重试延迟乘以该因子
    
    Example:
        retrier = RetryManager(max_retries=3, initial_delay=1.0, backoff_factor=2.0)
        
        def risky_operation():
            # 可能失败的操作
            pass
        
        result = retrier.execute(risky_operation)
    """
    
    def __init__(self, max_retries: int = 3, initial_delay: float = 1.0, backoff_factor: float = 2.0):
        """
        初始化重试管理器。
        
        Args:
            max_retries: 最大重试次数，默认为3
            initial_delay: 初始延迟时间（秒），默认为1.0
            backoff_factor: 退避因子，默认为2.0（每次延迟翻倍）
        
        Example:
            # 默认配置：最多重试3次，延迟1s -> 2s -> 4s
            retrier = RetryManager()
            
            # 自定义配置：最多重试5次，延迟0.5s -> 1s -> 2s -> 4s -> 8s
            retrier = RetryManager(max_retries=5, initial_delay=0.5, backoff_factor=2.0)
        """
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.backoff_factor = backoff_factor

    def execute(self, func, *args, **kwargs):
        """
        执行函数，必要时进行重试。
        
        该方法会捕获特定的异常并进行重试。捕获的异常类型包括：
        - requests.exceptions.Timeout
        - requests.exceptions.ConnectionError
        - requests.exceptions.ReadTimeout
        - requests.exceptions.ChunkedEncodingError
        
        其他异常会立即抛出，不会重试。
        
        Args:
            func: 要执行的函数
            *args: 传递给函数的位置参数
            **kwargs: 传递给函数的关键字参数
        
        Returns:
            函数执行成功的返回值
        
        Raises:
            最后一次重试失败时抛出的异常
        
        Example:
            def fetch_data(url):
                response = requests.get(url, timeout=10)
                return response.json()
            
            try:
                data = retrier.execute(fetch_data, "https://api.example.com/data")
            except Exception as e:
                print(f"所有重试都失败了: {e}")
        """
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
    """
    PDF转图像转换器。
    
    该类提供将PDF文件转换为PNG图像的功能，用于多模态视觉模型处理。
    支持配置转换页数、分辨率等参数。
    
    Attributes:
        max_pages (int): 最大转换页数，超出部分会被截断
        dpi (int): 图像分辨率（DPI），影响图像质量和文件大小
    
    Example:
        converter = ImageConverter(max_pages=10, dpi=150)
        
        # 转换为图像字节
        images = converter.pdf_to_images("paper.pdf")
        
        # 转换为Base64编码（用于API上传）
        base64_images = converter.pdf_to_base64_images("paper.pdf")
    """
    
    def __init__(self, max_pages: int = 10, dpi: int = 150):
        """
        初始化图像转换器。
        
        Args:
            max_pages: 最大转换页数，默认为10
            dpi: 图像分辨率，默认为150。建议值：
                - 72 DPI: 低质量，文件小
                - 150 DPI: 平衡质量和大小（推荐）
                - 300 DPI: 高质量，文件大
        
        Example:
            # 只转换前5页，高分辨率
            converter = ImageConverter(max_pages=5, dpi=300)
        """
        self.max_pages = max_pages
        self.dpi = dpi

    def pdf_to_images(self, pdf_path: str) -> List[bytes]:
        """
        将PDF文件转换为PNG图像字节列表。
        
        使用PyMuPDF（fitz）库渲染PDF页面为光栅图像。
        
        Args:
            pdf_path: PDF文件的完整路径
        
        Returns:
            PNG图像字节列表，按页码顺序排列
        
        Raises:
            fitz.FileDataError: 当PDF文件损坏或无法打开时
        
        Example:
            images = converter.pdf_to_images("arxiv_paper.pdf")
            print(f"转换了 {len(images)} 页")
            
            # 保存到文件
            for i, img_data in enumerate(images):
                with open(f"page_{i+1}.png", "wb") as f:
                    f.write(img_data)
        """
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
        """
        将图像字节转换为Base64编码字符串。
        
        Base64编码常用于将二进制数据通过文本协议（如HTTP JSON）传输。
        
        Args:
            img_data: PNG图像字节数据
        
        Returns:
            Base64编码的字符串
        
        Example:
            img_data = open("image.png", "rb").read()
            base64_str = converter.image_to_base64(img_data)
            
            # 构建data URL
            data_url = f"data:image/png;base64,{base64_str}"
        """
        return base64.b64encode(img_data).decode("utf-8")

    def pdf_to_base64_images(self, pdf_path: str) -> List[str]:
        """
        将PDF转换为Base64编码的图像列表。
        
        这是一个便捷方法，等价于先调用 pdf_to_images() 再对每个结果调用 image_to_base64()。
        
        Args:
            pdf_path: PDF文件路径
        
        Returns:
            Base64编码字符串列表
        
        Example:
            base64_images = converter.pdf_to_base64_images("paper.pdf")
            
            # 直接用于多模态API
            for b64_img in base64_images:
                api_call(image=f"data:image/png;base64,{b64_img}")
        """
        images = self.pdf_to_images(pdf_path)
        return [self.image_to_base64(img) for img in images]


class SiliconFlowClient:
    """
    硅基流动（SiliconFlow）API客户端。
    
    该类封装了与硅基流动大模型API的交互，支持：
    - 纯文本对话（文本模型）
    - 多模态对话（视觉模型，支持图像输入）
    - 自动重试机制
    - 响应编码清理
    
    Attributes:
        BASE_URL (str): API基础URL
        api_key (str): 硅基流动API密钥
        text_model (str): 文本模型名称
        vision_model (str): 视觉模型名称
        timeout (int): 请求超时时间（秒）
        max_retries (int): 最大重试次数
        headers (dict): HTTP请求头
        retry_manager (RetryManager): 重试管理器实例
    
    Example:
        client = SiliconFlowClient(
            api_key="your-api-key",
            text_model="Qwen/Qwen2.5-7B-Instruct",
            vision_model="Qwen/Qwen2-VL-72B-Instruct"
        )
        
        # 纯文本对话
        response = client.chat(
            prompt="请解释什么是Transformer架构？",
            system_prompt="你是一个专业的AI助手。"
        )
        
        # 多模态对话
        response = client.chat_with_images(
            text_prompt="请描述这张图片的内容",
            images=[png_bytes]
        )
    """
    
    BASE_URL = "https://api.siliconflow.cn/v1/chat/completions"

    def __init__(
        self,
        api_key: str,
        text_model: str = "Qwen/Qwen2.5-7B-Instruct",
        vision_model: str = "Qwen/Qwen2-VL-72B-Instruct",
        timeout: int = 180,
        max_retries: int = 3,
    ):
        """
        初始化硅基流动API客户端。
        
        Args:
            api_key: 硅基流动API密钥。可以在 https://siliconflow.cn 获取
            text_model: 文本模型名称，默认为 "Qwen/Qwen2.5-7B-Instruct"
            vision_model: 视觉模型名称，默认为 "Qwen/Qwen2-VL-72B-Instruct"
            timeout: 请求超时时间（秒），默认为180
            max_retries: 最大重试次数，默认为3
        
        可用的模型（2024年）：
        文本模型：
            - Qwen/Qwen2.5-7B-Instruct（免费）
            - Qwen/Qwen2.5-14B-Instruct
            - deepseek-ai/deepseek-v3
            - THUDM/glm-4-9b-chat
        
        视觉模型：
            - Qwen/Qwen2-VL-72B-Instruct
            - Qwen/Qwen3-VL
            - deepseek-ai/deepseek-vl2
        
        Example:
            # 使用免费模型
            client = SiliconFlowClient(
                api_key=os.environ.get("SILICONFLOW_API_KEY")
            )
            
            # 使用自定义模型
            client = SiliconFlowClient(
                api_key="your-key",
                text_model="deepseek-ai/deepseek-v3",
                vision_model="Qwen/Qwen2-VL-72B-Instruct",
                timeout=300,
                max_retries=5
            )
        """
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
        """
        执行纯文本对话。
        
        使用OpenAI兼容的聊天格式调用硅基流动API。
        
        Args:
            prompt: 用户输入的提示词
            system_prompt: 系统提示词，用于设定模型角色
            temperature: 采样温度，0.0-2.0。越低越确定，越高越随机
            max_tokens: 最大生成token数
            use_vision_model: 是否使用视觉模型。False使用文本模型
        
        Returns:
            模型生成的响应文本
        
        Raises:
            requests.exceptions.HTTPError: API调用失败时
            requests.exceptions.Timeout: 请求超时时
        
        Example:
            # 简单问答
            response = client.chat(
                prompt="什么是注意力机制？",
                system_prompt="你是一个机器学习专家。",
                temperature=0.5
            )
            
            # 使用视觉模型进行文本任务
            response = client.chat(
                prompt="分析这段文本的情感倾向",
                use_vision_model=True
            )
        """
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
        """
        执行多模态对话（文本+图像）。
        
        使用GPT-4V风格的多模态API格式，支持将图像作为输入。
        图像可以是原始字节或Base64编码字符串。
        
        Args:
            text_prompt: 文本提示词，描述要对图像做什么
            images: 图像列表，支持两种格式：
                - bytes: PNG图像原始字节
                - str: Base64编码字符串或data URL
            system_prompt: 系统提示词
            temperature: 采样温度
            max_tokens: 最大生成token数
            detail: 图像细节级别，可选 "auto"、"low"、"high"
        
        Returns:
            模型生成的响应文本
        
        Example:
            # 使用图像字节
            with open("diagram.png", "rb") as f:
                img_bytes = f.read()
            
            response = client.chat_with_images(
                text_prompt="请解释这个技术架构图",
                images=[img_bytes],
                system_prompt="你是一个技术文档专家。",
                detail="high"
            )
            
            # 使用PDF转换后的图像
            images = converter.pdf_to_images("paper.pdf")
            response = client.chat_with_images(
                text_prompt="请总结这篇论文的主要内容",
                images=images[:5]  # 只使用前5页
            )
        """
        def _make_request():
            content_parts = []

            for img in images:
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
        """
        便捷方法：直接处理PDF文件。
        
        该方法会自动将PDF转换为图像，然后调用多模态API。
        
        Args:
            pdf_path: PDF文件路径
            text_prompt: 文本提示词
            system_prompt: 系统提示词
            temperature: 采样温度
            max_tokens: 最大生成token数
            max_pages: 最大转换页数
        
        Returns:
            模型生成的响应文本
        
        Example:
            response = client.chat_with_pdf(
                pdf_path="arxiv_2401.12345.pdf",
                text_prompt="请总结这篇论文的核心贡献",
                max_pages=8
            )
        """
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
        """
        清理模型响应内容。
        
        内部方法，用于：
        1. 修复UTF-8编码问题
        2. 移除Unicode替换字符（\ufffd）
        3. 规范化多余的换行符
        
        Args:
            content: 原始响应内容
        
        Returns:
            清理后的内容
        """
        content = content.encode('utf-8', errors='ignore').decode('utf-8')
        content = content.replace('\ufffd', '')
        content = re.sub(r'\n{3,}', '\n\n', content)
        return content.strip()


class RelevanceLevel:
    """
    论文相关度分级常量。

    定义四个相关度等级，用于对论文与关键词的匹配程度进行分类。

    Attributes:
        HIGH (str): 高度相关 - 论文核心贡献与关键词直接相关
        MEDIUM (str): 中度相关 - 论文与关键词有明确联系但非核心
        LOW (str): 低度相关 - 论文仅在周边/应用层面涉及关键词
        IRRELEVANT (str): 不相关 - 论文与关键词无实质关联
        ORDER (list): 从高到低的相关度排序（用于阈值比较）
    """

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    IRRELEVANT = "IRRELEVANT"

    ORDER = ["HIGH", "MEDIUM", "LOW", "IRRELEVANT"]

    @classmethod
    def is_above_threshold(cls, level: str, min_level: str) -> bool:
        """
        判断 level 是否达到或超过 min_level 的相关度要求。

        Args:
            level: 当前论文的相关度等级
            min_level: 最低要求的相关度等级

        Returns:
            True 表示达到要求（应保留），False 表示未达到（应过滤）
        """
        try:
            return cls.ORDER.index(level) <= cls.ORDER.index(min_level)
        except ValueError:
            return True  # 无法解析时默认保留


class PaperFilter:
    """
    AI论文筛选器。

    两阶段筛选流程：
    1. 关键词快速预筛（规则，无LLM调用）：检查标题+摘要中是否含有关键词，
       未命中任何关键词的论文直接标记为 IRRELEVANT，跳过后续LLM调用。
    2. LLM相关度分级：对通过预筛的论文，调用LLM将相关度分为
       HIGH / MEDIUM / LOW / IRRELEVANT 四级。

    Attributes:
        RELEVANT (str): 向后兼容标记（任何非IRRELEVANT等级）
        IRRELEVANT (str): 不相关标记
        client (SiliconFlowClient): 硅基流动API客户端实例

    Example:
        client = SiliconFlowClient(api_key="your-key")
        paper_filter = PaperFilter(client)

        # 两阶段筛选
        if paper_filter.keyword_prefilter(paper, keywords):
            level, reason = paper_filter.classify_relevance(paper, keywords)
        else:
            level, reason = RelevanceLevel.IRRELEVANT, "关键词预筛未通过"
    """

    RELEVANT = "RELEVANT"
    IRRELEVANT = "IRRELEVANT"

    def __init__(self, siliconflow_client: SiliconFlowClient, prompt_dir: str = "./prompts"):
        """
        初始化论文筛选器。

        Args:
            siliconflow_client: 硅基流动API客户端实例
            prompt_dir: Prompt模板文件目录，默认为 "./prompts"

        Example:
            client = SiliconFlowClient(api_key="your-key")
            paper_filter = PaperFilter(client)
        """
        self.client = siliconflow_client
        self._system_prompt_template = self._load_system_prompt(prompt_dir)
        self._user_prompt_template = self._load_user_prompt(prompt_dir)

    def _load_system_prompt(self, prompt_dir: str) -> str:
        """从文件加载预筛选 system prompt，路径：prefilter/system/system_prompt.md。"""
        filepath = os.path.join(prompt_dir, "prefilter", "system", "system_prompt.md")
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read().strip()
        return (
            "你是一个严格的学术论文相关度分级助手。你的任务是根据论文的标题、分类和摘要，"
            "将论文与给定关键词的相关程度分为四个等级：HIGH、MEDIUM、LOW 或 IRRELEVANT。\n\n"
            "判断规则：\n"
            "1. 只输出四个词之一：HIGH、MEDIUM、LOW 或 IRRELEVANT\n"
            "2. 不要输出任何其他解释、标点或说明文字\n"
            "3. 如果论文明确属于物理、化学、生物、医学、机械等非计算机科学领域，"
            "且关键词是计算机科学相关（如LLM、transformer、神经网络、深度学习等），"
            "则判定为 IRRELEVANT\n"
            "4. 如果论文分类是 cs.RO（机器人）但核心内容是计算机视觉/深度学习，"
            "则判定为 MEDIUM 或以上\n"
            "5. 如果只是在背景介绍中提到关键词，但核心研究内容不相关，"
            "则判定为 LOW 或 IRRELEVANT\n"
            "6. 如果论文标题和摘要都显示与关键词高度相关，则判定为 HIGH\n\n"
            "注意：必须严格只输出 HIGH、MEDIUM、LOW 或 IRRELEVANT，不要添加任何其他内容！"
        )

    def _load_user_prompt(self, prompt_dir: str) -> str:
        """从文件加载预筛选 user prompt，路径：prefilter/user/user_prompt.md。

        模板占位符：{keywords}、{title}、{categories}、{abstract}
        """
        filepath = os.path.join(prompt_dir, "prefilter", "user", "user_prompt.md")
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read().strip()
        return (
            "请根据以下目标关键词，对论文的标题和摘要进行相关度分级。\n\n"
            "目标关键词: {keywords}\n\n"
            "论文标题: {title}\n\n"
            "论文分类: {categories}\n\n"
            "论文摘要:\n{abstract}\n\n"
            "只输出四个等级之一：HIGH、MEDIUM、LOW 或 IRRELEVANT，不要输出其他任何内容！"
        )

    def classify_relevance(self, paper: Paper, target_keywords: List[str]) -> Tuple[str, str]:
        """
        使用LLM将论文相关度分为四个等级。

        将关键词、标题、分类、摘要一并送入LLM，输出 HIGH / MEDIUM / LOW / IRRELEVANT 之一。
        提示词模板从 prompts/prefilter_prompt.md 加载（含 {keywords}、{title}、
        {categories}、{abstract} 占位符），文件不存在时使用内置默认值。

        Args:
            paper: Paper对象，需要有 title、categories、summary 属性
            target_keywords: 目标关键词列表

        Returns:
            元组 (level, reason):
            - level: RelevanceLevel 常量之一
            - reason: 判定原因描述

        Example:
            level, reason = paper_filter.classify_relevance(paper, ["LLM", "transformer"])
            if RelevanceLevel.is_above_threshold(level, "MEDIUM"):
                print(f"保留: {paper.title} [{level}]")
        """
        if not paper.summary or len(paper.summary.strip()) < 30:
            print(f"    警告: 论文 {paper.arxiv_id} 摘要过短，跳过LLM分级")
            return RelevanceLevel.LOW, "摘要过短，跳过LLM分级"

        user_prompt = self._user_prompt_template.format(
            keywords=", ".join(target_keywords),
            title=paper.title,
            categories=", ".join(paper.categories) if paper.categories else "未知",
            abstract=paper.summary,
        )

        try:
            print(f"    分级论文 {paper.arxiv_id}...")
            result = self.client.chat(
                prompt=user_prompt,
                system_prompt=self._system_prompt_template,
                temperature=0.1,
                max_tokens=20,
                use_vision_model=False,
            )

            result = result.strip().upper()
            result = re.sub(r'[^A-Z_]', '', result)

            print(f"    AI响应: '{result}'")

            for level in [RelevanceLevel.HIGH, RelevanceLevel.MEDIUM, RelevanceLevel.LOW, RelevanceLevel.IRRELEVANT]:
                if level in result:
                    return level, f"AI分级: {level}"

            print(f"    警告: 无法解析AI响应，默认判定为 LOW")
            return RelevanceLevel.LOW, "无法解析响应，默认 LOW"

        except Exception as e:
            print(f"    分级过程出错: {e}，默认判定为 LOW")
            return RelevanceLevel.LOW, "分级出错，默认 LOW"

    def is_relevant(self, paper: Paper, target_keywords: List[str]) -> Tuple[bool, str]:
        """
        向后兼容接口：判断论文是否相关。

        内部调用 classify_relevance，将非 IRRELEVANT 的等级视为相关。

        Args:
            paper: Paper对象
            target_keywords: 目标关键词列表

        Returns:
            元组 (is_relevant, reason)
        """
        level, reason = self.classify_relevance(paper, target_keywords)
        return level != RelevanceLevel.IRRELEVANT, reason


class PDFExtractor:
    """
    PDF文本提取器。
    
    该类使用PyMuPDF（fitz）库从PDF文件中提取文本内容。
    支持提取全文、提取特定章节、编码规范化等功能。
    
    注意：该类用于文本模式。视觉模式使用 ImageConverter 类。
    
    Attributes:
        无（无状态类）
    
    Example:
        extractor = PDFExtractor()
        
        # 提取全文
        text = extractor.extract_text("paper.pdf")
        
        # 提取特定章节
        intro = extractor.extract_section("paper.pdf", "Introduction")
        methods = extractor.extract_section("paper.pdf", "Method")
    """
    
    def __init__(self):
        """
        初始化PDF文本提取器。
        
        这是一个无状态类，可以多次调用其方法。
        """
        pass

    def extract_text(self, pdf_path: str) -> str:
        """
        从PDF文件中提取所有文本内容。
        
        逐页提取文本，然后合并为单个字符串。自动处理编码问题和多余空白。
        
        Args:
            pdf_path: PDF文件路径
        
        Returns:
            提取的文本内容，已规范化编码
        
        Example:
            text = extractor.extract_text("paper.pdf")
            print(f"提取了 {len(text)} 字符")
            
            # 由于模型上下文限制，可能需要截断
            if len(text) > 12000:
                text = text[:12000] + "\n...（内容已截断）"
        """
        doc = fitz.open(pdf_path)
        text_parts = []

        for page in doc:
            page_text = page.get_text()
            if page_text:
                page_text = self._clean_text(page_text)
                text_parts.append(page_text)

        doc.close()
        full_text = "\n\n".join(text_parts)
        return self._normalize_encoding(full_text)

    def _clean_text(self, text: str) -> str:
        """
        清理提取的文本。
        
        内部方法，用于：
        1. 将多个连续换行符（3个或更多）缩减为2个
        2. 将多个连续空格或制表符缩减为1个
        3. 移除行首的多余空格
        
        Args:
            text: 原始提取文本
        
        Returns:
            清理后的文本
        """
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'(\n )+', '\n', text)
        return text.strip()

    def _normalize_encoding(self, text: str) -> str:
        """
        规范化文本编码。
        
        内部方法，用于修复UTF-8编码问题，移除Unicode替换字符。
        
        Args:
            text: 原始文本
        
        Returns:
            编码规范化后的文本
        """
        text = text.encode('utf-8', errors='ignore').decode('utf-8')
        text = text.replace('\ufffd', '')
        return text

    def extract_section(self, pdf_path: str, section_name: str) -> Optional[str]:
        """
        尝试提取PDF中的特定章节。
        
        该方法使用正则表达式匹配章节标题，然后提取该标题到下一个章节标题之间的内容。
        
        注意：由于学术论文的格式多样性，该方法可能无法100%准确匹配所有论文。
        
        Args:
            pdf_path: PDF文件路径
            section_name: 章节名称，如 "Introduction"、"Method"、"Conclusion"
        
        Returns:
            章节内容字符串，如果找不到则返回None
        
        匹配的章节标题模式：
        - "1. Introduction"
        - "I. INTRODUCTION"
        - "INTRODUCTION"（单独一行）
        - "Introduction:"
        
        Example:
            # 提取引言部分
            intro = extractor.extract_section("paper.pdf", "Introduction")
            if intro:
                print("找到引言:", intro[:200])
            
            # 提取方法部分（可能匹配多个变体）
            methods = extractor.extract_section("paper.pdf", "Method")
            # 可能匹配 "Method", "Methods", "Methodology" 等
        """
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
    """
    论文总结器。
    
    该类是总结模块的核心，整合了以下功能：
    1. AI论文筛选（下载PDF前）
    2. PDF内容提取（文本模式或视觉模式）
    3. 调用LLM进行多维度总结
    4. 生成Markdown输出
    
    两种工作模式：
    - 文本模式：使用PDFExtractor提取文本，调用文本模型
    - 视觉模式：使用ImageConverter转换为图像，调用视觉模型
    
    Attributes:
        use_vision_mode (bool): 是否使用视觉模式
        pdf_extractor (PDFExtractor): PDF文本提取器实例
        image_converter (ImageConverter): 图像转换器实例
        siliconflow_client (SiliconFlowClient): API客户端实例
        paper_filter (PaperFilter): 论文筛选器实例
        prompt_dir (str): Prompt文件目录
        prompts (dict): 加载的Prompt模板字典
    
    Example:
        # 使用文本模式（默认，更快、更便宜）
        summarizer = Summarizer(
            siliconflow_api_key="your-key",
            use_vision_mode=False
        )
        
        # 使用视觉模式（可以理解图表、公式）
        summarizer = Summarizer(
            siliconflow_api_key="your-key",
            use_vision_mode=True,
            vision_model="Qwen/Qwen2-VL-72B-Instruct"
        )
        
        # 完整流程
        papers = sniffer.search(keywords=["LLM"], max_results=5)
        
        # 筛选（下载前）
        relevant, irrelevant = summarizer.filter_papers(papers, ["LLM"])
        
        # 下载和总结
        for paper in relevant:
            sniffer.download_pdf(paper)
            summary = summarizer.summarize(paper)
            md_path = summarizer.generate_markdown(summary, "./output")
            sniffer.cleanup_pdf(paper)
    """
    
    def __init__(
        self,
        siliconflow_api_key: str,
        prompt_dir: str = "./prompts",
        use_vision_mode: bool = False,
        text_model: str = "Qwen/Qwen2.5-7B-Instruct",
        vision_model: str = "Qwen/Qwen2-VL-72B-Instruct",
        filter_model: str = "Qwen/Qwen2.5-7B-Instruct",
    ):
        """
        初始化论文总结器。

        Args:
            siliconflow_api_key: 硅基流动API密钥
            prompt_dir: Prompt模板文件目录，默认为 "./prompts"
            use_vision_mode: 是否使用视觉模式，默认为False
            text_model: 论文总结使用的文本模型名称
            vision_model: 论文总结使用的视觉模型名称
            filter_model: Abstract筛选使用的模型名称，可独立于总结模型配置

        说明：
            筛选模型（filter_model）用于下载PDF前根据摘要判断相关性，
            总结模型（text_model/vision_model）用于下载PDF后的深度分析。
            两者独立配置，筛选可使用更小更快的模型以节省成本。

        Prompt文件结构（均为Markdown格式）：
            prompt_dir/
            ├── system_prompt_text.md           # 文本模式system prompt
            ├── system_prompt_vision.md         # 视觉模式system prompt
            ├── system_prompt_filter.md         # 摘要筛选system prompt
            ├── system_prompt_fulltext_filter.md # 全文筛选system prompt
            ├── fulltext_filter_prompt.md       # 全文筛选提示（含{keywords},{content}占位符）
            ├── related_work_prompt.md          # 相关工作一句话提示（含{content}占位符）
            ├── technical_route_prompt.md       # 技术路线分析提示（含{content}占位符）
            ├── methodology_prompt.md           # 方法论分析提示（含{content}占位符）
            ├── experiment_prompt.md            # 实验方案分析提示（含{content}占位符）
            ├── introduction_prompt.md          # Introduction逻辑分析提示（含{content}占位符）
            └── paper_template.md               # 输出Markdown模板

        Example:
            # 文本模式，筛选和总结用不同模型
            summarizer = Summarizer(
                siliconflow_api_key=os.environ["SILICONFLOW_API_KEY"],
                filter_model="Qwen/Qwen2.5-7B-Instruct",   # 小模型筛选
                text_model="deepseek-ai/deepseek-v3",       # 大模型总结
            )

            # 视觉模式（包含大量图表、公式的论文）
            summarizer = Summarizer(
                siliconflow_api_key="your-key",
                use_vision_mode=True,
                vision_model="Qwen/Qwen2-VL-72B-Instruct"
            )
        """
        self.use_vision_mode = use_vision_mode
        self.pdf_extractor = PDFExtractor()
        self.image_converter = ImageConverter(max_pages=10)

        # 论文总结客户端（text_model 用于文本模式，vision_model 用于视觉模式）
        self.siliconflow_client = SiliconFlowClient(
            api_key=siliconflow_api_key,
            text_model=text_model,
            vision_model=vision_model,
        )

        # Abstract筛选客户端（独立模型，可配置为更轻量的模型）
        self.filter_client = SiliconFlowClient(
            api_key=siliconflow_api_key,
            text_model=filter_model,
            vision_model=vision_model,
        )

        self.paper_filter = PaperFilter(self.filter_client, prompt_dir=prompt_dir)
        self.prompt_dir = prompt_dir
        self._load_prompts()

    def _load_prompts(self):
        """
        加载Prompt模板文件。

        内部方法，从prompt_dir目录加载以下文件：

        System prompts（系统角色提示）：
        - system_prompt_text.md   # 文本模式system prompt
        - system_prompt_vision.md # 视觉模式system prompt

        User prompts（任务指令）：
        - fulltext_filter_prompt.md  （含 {keywords}, {content} 占位符）
        - related_work_prompt.md     （含 {content} 占位符）
        - technical_route_prompt.md  （含 {content} 占位符）
        - methodology_prompt.md      （含 {content} 占位符）
        - experiment_prompt.md       （含 {content} 占位符）
        - introduction_prompt.md     （含 {content} 占位符）

        如果文件不存在，会使用内置的默认模板。
        """
        self.prompts = {}
        prompts_config = [
            ("summary_system_text",   "summary/system/system_prompt_text.md"),
            ("summary_system_vision", "summary/system/system_prompt_vision.md"),
            ("postfilter_system",     "postfilter/system/system_prompt.md"),
            ("postfilter_user",       "postfilter/user/user_prompt.md"),
            ("related_work",          "summary/user/related_work_prompt.md"),
            ("technical_route",       "summary/user/technical_route_prompt.md"),
            ("methodology",           "summary/user/methodology_prompt.md"),
            ("experiment",            "summary/user/experiment_prompt.md"),
            ("introduction",          "summary/user/introduction_prompt.md"),
        ]

        for key, rel_path in prompts_config:
            filepath = os.path.join(self.prompt_dir, rel_path)
            if os.path.exists(filepath):
                with open(filepath, "r", encoding="utf-8") as f:
                    self.prompts[key] = f.read().strip()
            else:
                self.prompts[key] = self._get_default_prompt(key)

    def _get_default_prompt(self, key: str) -> str:
        """
        获取默认Prompt模板。

        内部方法，当文件不存在时提供内置的默认模板。

        Args:
            key: Prompt键名（与 prompts_config 中的 key 对应）

        Returns:
            默认Prompt字符串
        """
        defaults = {
            "summary_system_text": (
                "你是一个专业的学术论文助手，擅长总结和分析学术论文。"
                "请用中文回答，确保回答准确、清晰、有条理。"
            ),
            "summary_system_vision": (
                "你是一个专业的学术论文助手，擅长通过阅读论文图像来总结和分析学术论文。"
                "请用中文回答，确保回答准确、清晰、有条理。"
            ),
            "postfilter_system": (
                "你是一个严格的学术论文全文筛选助手。根据论文完整内容深度判断相关性。\n"
                "判断规则：\n"
                "1. 只输出两个词之一：RELEVANT 或 IRRELEVANT\n"
                "2. 不要输出任何其他解释、标点或说明文字\n"
                "3. 核心方法、贡献或应用与关键词直接相关 → RELEVANT\n"
                "4. 仅在引言或相关工作中提到关键词，核心内容不相关 → IRRELEVANT\n"
                "注意：必须严格只输出 RELEVANT 或 IRRELEVANT！"
            ),
            "postfilter_user": (
                "请根据以下论文总结内容，判断该论文是否与关键词 \"{keywords}\" 高度相关。\n\n"
                "重点考察论文的核心方法和技术贡献是否与关键词直接相关。\n\n"
                "只输出 RELEVANT 或 IRRELEVANT，不要输出其他任何内容！\n\n"
                "论文总结内容：\n{content}"
            ),
            "related_work": (
                "请用一句话（不超过60字）简明扼要地总结该论文相对于已有工作的核心创新点。\n"
                "格式建议：与[已有方法/工作]相比，本文[核心创新/关键区别]。\n"
                "要求：用中文，严格一句话，不超过60字。\n\n"
                "论文内容：\n{content}"
            ),
            "technical_route": (
                "请用 Mermaid flowchart 格式描述该论文的技术路线。\n\n"
                "要求：\n"
                "1. 输出 ```mermaid 代码块，使用 flowchart TD 方向\n"
                "2. 节点文字用中文，每个节点不超过10个字\n"
                "3. 只展示核心步骤，节点总数不超过8个\n"
                "4. 不要输出任何代码块以外的额外说明\n\n"
                "论文内容：\n{content}"
            ),
            "methodology": (
                "请用简短要点列出该论文的核心方法，每点不超过20字。\n\n"
                "要求：\n"
                "1. 用中文\n"
                "2. 每个要点以 • 开头\n"
                "3. 不超过5个要点\n"
                "4. 聚焦最核心的技术手段，不要解释背景\n\n"
                "论文内容：\n{content}"
            ),
            "experiment": (
                "请用2-3句话概述该论文的实验方案。\n\n"
                "要求：\n"
                "1. 用中文\n"
                "2. 依次涵盖：数据集与基线、核心指标、主要结论\n"
                "3. 严格控制在3句话以内，不要展开\n\n"
                "论文内容：\n{content}"
            ),
            "introduction": (
                "请用2-3句话概述该论文 Introduction 的核心逻辑。\n\n"
                "要求：\n"
                "1. 用中文\n"
                "2. 依次涵盖：问题背景、研究动机、主要贡献\n"
                "3. 严格控制在3句话以内，不要展开\n\n"
                "论文内容：\n{content}"
            ),
        }
        return defaults.get(key, "")

    def filter_papers(self, papers: List[Paper], keywords: List[str], min_relevance: str = RelevanceLevel.LOW) -> Tuple[List[Paper], List[Paper]]:
        """
        批量筛选论文（LLM单阶段相关度分级）。

        对每篇论文将关键词、标题、分类、摘要一并送入LLM，分级为
        HIGH / MEDIUM / LOW / IRRELEVANT，保留达到 min_relevance 阈值的论文。

        Args:
            papers: Paper对象列表
            keywords: 目标关键词列表
            min_relevance: 最低保留相关度，默认 RelevanceLevel.LOW
                - "HIGH": 只保留高度相关
                - "MEDIUM": 保留中度及以上
                - "LOW": 保留低度及以上（默认，宽松）

        Returns:
            元组 (relevant_papers, irrelevant_papers)

        Example:
            papers = sniffer.search(keywords=["LLM"], max_results=10)
            relevant, irrelevant = summarizer.filter_papers(papers, ["LLM"], min_relevance="MEDIUM")
            print(f"保留: {len(relevant)} 篇，过滤: {len(irrelevant)} 篇")
        """
        if not keywords:
            return papers, []

        relevant_papers = []
        irrelevant_papers = []

        print(f"\n开始筛选论文 (共 {len(papers)} 篇)...")
        print(f"目标关键词: {', '.join(keywords)}")
        print(f"最低相关度阈值: {min_relevance}")

        for i, paper in enumerate(papers):
            print(f"\n  [{i+1}/{len(papers)}] 检查: {paper.arxiv_id}")
            print(f"      标题: {paper.title[:60]}{'...' if len(paper.title) > 60 else ''}")
            print(f"      分类: {', '.join(paper.categories) if paper.categories else '未知'}")

            level, reason = self.paper_filter.classify_relevance(paper, keywords)

            if RelevanceLevel.is_above_threshold(level, min_relevance):
                print(f"      ✓ 保留 [{level}] ({reason})")
                relevant_papers.append(paper)
            else:
                print(f"      ✗ 过滤 [{level}] ({reason})")
                irrelevant_papers.append(paper)

        print(f"\n筛选完成: 保留 {len(relevant_papers)} 篇，过滤 {len(irrelevant_papers)} 篇")
        return relevant_papers, irrelevant_papers

    def _filter_by_summary(self, paper: Paper, summary_text: str, keywords: List[str]) -> Tuple[bool, str]:
        """
        基于论文总结内容进行相关性筛选。

        在所有总结步骤完成后调用，用生成的总结内容（比原始全文更精炼）判断是否相关。
        如不相关则调用方丢弃 summary_result，不生成 Markdown 文件。

        Args:
            paper: Paper对象（用于日志输出）
            summary_text: 各维度总结拼接后的文本
            keywords: 目标关键词列表

        Returns:
            元组 (is_relevant, reason):
            - is_relevant: 是否相关，布尔值
            - reason: 判定原因描述
        """
        keywords_str = ", ".join(keywords) if keywords else "未指定"
        system_prompt = self.prompts["system_prompt_fulltext_filter.md"]
        user_prompt = self.prompts["fulltext_filter_prompt.md"].format(
            keywords=keywords_str,
            content=summary_text,
        )

        try:
            print(f"    [总结筛选] 正在判断 {paper.arxiv_id} 的相关性...")
            result = self.siliconflow_client.chat(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.1,
                max_tokens=20,
                use_vision_model=False,
            )

            result_clean = result.strip().upper()
            result_clean = re.sub(r'[^A-Z_]', '', result_clean)
            print(f"    [总结筛选] AI响应: '{result_clean}'")

            if "IRRELEVANT" in result_clean:
                return False, "总结筛选：AI判定不相关"
            elif "RELEVANT" in result_clean:
                return True, "总结筛选：AI判定相关"
            else:
                print(f"    [总结筛选] 无法解析响应，默认判定为相关")
                return True, "总结筛选：无法解析响应，默认相关"

        except Exception as e:
            print(f"    [总结筛选] 出错: {e}，默认判定为相关")
            return True, "总结筛选：出错，默认相关"

    def summarize(self, paper: Paper, keywords: Optional[List[str]] = None) -> Optional[Dict]:
        """
        总结论文。

        根据配置的模式（文本或视觉），调用相应的总结方法。

        完整流程：
        1. 提取论文内容（文本提取或图像转换）
        2. 相关工作一句话总结（related_work_prompt.md）
        3. Mermaid 技术路线（technical_route_prompt.md）
        4. 方法论要点（methodology_prompt.md）
        5. 实验概述（experiment_prompt.md）
        6. Introduction 简述（introduction_prompt.md）
        7. 基于总结内容进行相关性筛选 → 如不相关则返回 None

        Args:
            paper: Paper对象，必须有local_pdf_path属性
            keywords: 目标关键词列表，用于总结后的相关性筛选

        Returns:
            包含多维度分析结果的字典，或 None（总结筛选未通过时）：
            {
                "arxiv_id": "2401.12345",
                "title": "论文标题",
                "authors": ["作者1", "作者2"],
                "arxiv_url": "https://arxiv.org/abs/...",
                "categories": ["cs.CL", "cs.AI"],
                "original_abstract": "原摘要",
                "related_work": "相关工作一句话",
                "technical_route": "技术路线分析",
                "methodology": "方法论分析",
                "experiment": "实验方案分析",
                "introduction_analysis": "Introduction逻辑分析"
            }

        Raises:
            ValueError: 当paper.local_pdf_path为None时

        Example:
            paper = papers[0]
            sniffer.download_pdf(paper)  # 确保已下载

            try:
                result = summarizer.summarize(paper, keywords=["LLM"])
                if result is None:
                    print("总结筛选未通过，跳过")
                else:
                    print(f"相关工作: {result['related_work']}")
                    print(f"技术路线: {result['technical_route'][:200]}...")
            finally:
                sniffer.cleanup_pdf(paper)
        """
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
            return self._summarize_with_vision(paper, summary_result, keywords or [])
        else:
            return self._summarize_with_text(paper, summary_result, keywords or [])

    def _summarize_with_text(self, paper: Paper, summary_result: Dict, keywords: List[str]) -> Optional[Dict]:
        """
        使用文本模式总结论文。

        内部方法，执行以下步骤：
        1. 提取全文文本
        2. 相关工作一句话（related_work_prompt.md）
        3. Mermaid 技术路线（technical_route_prompt.md）
        4. 方法论要点（methodology_prompt.md）
        5. 实验概述（experiment_prompt.md）
        6. Introduction 简述（introduction_prompt.md）
        7. 基于总结内容进行相关性筛选 → 不相关则返回 None

        Args:
            paper: Paper对象
            summary_result: 待填充的结果字典
            keywords: 目标关键词列表，用于总结后筛选

        Returns:
            填充完成的结果字典，或 None（总结筛选未通过时）
        """
        full_text = self.pdf_extractor.extract_text(paper.local_pdf_path)

        if len(full_text) > 12000:
            full_text = full_text[:12000] + "\n...（内容已截断）"

        print("    使用文本模式总结...")

        system_prompt = self.prompts["system_prompt_text.md"]

        # Step 1: 相关工作一句话
        related_work = self.siliconflow_client.chat(
            prompt=self.prompts["related_work_prompt.md"].format(content=full_text),
            system_prompt=system_prompt,
            max_tokens=100,
            use_vision_model=False,
        )
        summary_result["related_work"] = related_work
        print("      ✓ 相关工作总结完成")

        # Step 2: Mermaid 技术路线
        technical_route = self.siliconflow_client.chat(
            prompt=self.prompts["technical_route_prompt.md"].format(content=full_text),
            system_prompt=system_prompt,
            max_tokens=600,
            use_vision_model=False,
        )
        summary_result["technical_route"] = technical_route
        print("      ✓ 技术路线（Mermaid）完成")

        # Step 3: 方法论要点
        methodology = self.siliconflow_client.chat(
            prompt=self.prompts["methodology_prompt.md"].format(content=full_text),
            system_prompt=system_prompt,
            max_tokens=200,
            use_vision_model=False,
        )
        summary_result["methodology"] = methodology
        print("      ✓ 方法论要点完成")

        # Step 4: 实验概述
        experiment = self.siliconflow_client.chat(
            prompt=self.prompts["experiment_prompt.md"].format(content=full_text),
            system_prompt=system_prompt,
            max_tokens=200,
            use_vision_model=False,
        )
        summary_result["experiment"] = experiment
        print("      ✓ 实验概述完成")

        # Step 5: Introduction 简述
        intro_analysis = self.siliconflow_client.chat(
            prompt=self.prompts["introduction_prompt.md"].format(content=full_text),
            system_prompt=system_prompt,
            max_tokens=200,
            use_vision_model=False,
        )
        summary_result["introduction_analysis"] = intro_analysis
        print("      ✓ Introduction 简述完成")

        # Step 6: 基于总结内容进行相关性筛选
        if keywords:
            combined = "\n\n".join([
                f"相关工作：{related_work}",
                f"技术路线：{technical_route}",
                f"方法论：{methodology}",
                f"实验：{experiment}",
                f"Introduction：{intro_analysis}",
            ])
            is_relevant, reason = self._filter_by_summary(paper, combined, keywords)
            if not is_relevant:
                print(f"      ✗ 总结筛选未通过: {reason}")
                return None
            print(f"      ✓ 总结筛选通过")

        return summary_result

    def _summarize_with_vision(self, paper: Paper, summary_result: Dict, keywords: List[str]) -> Optional[Dict]:
        """
        使用视觉模式总结论文。

        内部方法，将PDF转换为图像后调用视觉模型。
        可以理解论文中的图表、公式和布局。

        筛选在所有总结步骤完成后进行（基于生成的总结文本），
        避免额外的视觉API调用。

        Args:
            paper: Paper对象
            summary_result: 待填充的结果字典
            keywords: 目标关键词列表，用于总结后筛选

        Returns:
            填充完成的结果字典，或 None（总结筛选未通过时）
        """
        print("    使用视觉模式（多模态）总结...")

        # Step 1: 先将PDF转换为图像
        print("    正在将PDF转换为图像...")
        images = self.image_converter.pdf_to_images(paper.local_pdf_path)
        print(f"    已转换 {len(images)} 页为图像")

        system_prompt = self.prompts["system_prompt_vision.md"]

        # 视觉模式下论文内容已通过图像传入，user prompt不需要注入文本内容
        # Step 2: 相关工作一句话
        related_work = self.siliconflow_client.chat_with_images(
            text_prompt=self.prompts["related_work_prompt.md"].format(content="（见图像）"),
            images=images,
            system_prompt=system_prompt,
            max_tokens=100,
        )
        summary_result["related_work"] = related_work
        print("      ✓ 相关工作总结完成")

        # Step 3: Mermaid 技术路线
        technical_route = self.siliconflow_client.chat_with_images(
            text_prompt=self.prompts["technical_route_prompt.md"].format(content="（见图像）"),
            images=images,
            system_prompt=system_prompt,
            max_tokens=600,
        )
        summary_result["technical_route"] = technical_route
        print("      ✓ 技术路线（Mermaid）完成")

        # Step 4: 方法论要点
        methodology = self.siliconflow_client.chat_with_images(
            text_prompt=self.prompts["methodology_prompt.md"].format(content="（见图像）"),
            images=images,
            system_prompt=system_prompt,
            max_tokens=200,
        )
        summary_result["methodology"] = methodology
        print("      ✓ 方法论要点完成")

        # Step 5: 实验概述
        experiment = self.siliconflow_client.chat_with_images(
            text_prompt=self.prompts["experiment_prompt.md"].format(content="（见图像）"),
            images=images,
            system_prompt=system_prompt,
            max_tokens=200,
        )
        summary_result["experiment"] = experiment
        print("      ✓ 实验概述完成")

        # Step 6: Introduction 简述
        intro_analysis = self.siliconflow_client.chat_with_images(
            text_prompt=self.prompts["introduction_prompt.md"].format(content="（见图像）"),
            images=images,
            system_prompt=system_prompt,
            max_tokens=200,
        )
        summary_result["introduction_analysis"] = intro_analysis
        print("      ✓ Introduction 简述完成")

        # Step 7: 基于总结内容进行相关性筛选
        if keywords:
            combined = "\n\n".join([
                f"相关工作：{related_work}",
                f"技术路线：{technical_route}",
                f"方法论：{methodology}",
                f"实验：{experiment}",
                f"Introduction：{intro_analysis}",
            ])
            is_relevant, reason = self._filter_by_summary(paper, combined, keywords)
            if not is_relevant:
                print(f"      ✗ 总结筛选未通过: {reason}")
                return None
            print(f"      ✓ 总结筛选通过")

        return summary_result

    def generate_markdown(self, summary_result: Dict, output_dir: str) -> str:
        """
        生成Markdown格式的总结文档。
        
        使用模板文件（paper_template.md）或默认模板，将总结结果填充为Markdown文档。
        
        模板变量：
        - {title}: 论文标题
        - {arxiv_id}: arXiv ID
        - {arxiv_url}: arXiv链接
        - {authors}: 作者列表
        - {published}: 发布时间
        - {categories}: 分类列表
        - {original_abstract}: 原摘要
        - {related_work}: 相关工作一句话总结
        - {technical_route}: 技术路线分析
        - {methodology}: 方法论分析
        - {experiment}: 实验方案分析
        - {introduction_analysis}: Introduction分析
        - {generated_at}: 生成时间
        
        Args:
            summary_result: summarize()方法返回的结果字典
            output_dir: 输出目录路径
        
        Returns:
            生成的Markdown文件的完整路径
        
        Example:
            result = summarizer.summarize(paper)
            
            # 生成Markdown
            md_path = summarizer.generate_markdown(result, "./output")
            print(f"Markdown已保存到: {md_path}")
            
            # 查看内容
            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read()
                print(content)
        """
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
            related_work=summary_result["related_work"],
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
        """
        获取默认Markdown模板。
        
        内部方法，当paper_template.md不存在时提供默认模板。
        
        Returns:
            默认模板字符串
        """
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

## 相关工作（一句话）

{related_work}

---

## 技术路线（Mermaid）

{technical_route}

---

## 方法论要点

{methodology}

---

## 实验概述

{experiment}

---

## Introduction 简述

{introduction_analysis}

---

*本文由 arXiv Sentinel 自动生成于 {generated_at}*
"""
