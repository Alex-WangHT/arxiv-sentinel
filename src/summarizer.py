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
import io
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


class PaperFilter:
    """
    AI论文筛选器。
    
    该类使用大模型根据论文的标题、分类和摘要判断论文是否与目标关键词相关。
    在下载PDF之前进行筛选，可以节省时间和API成本。
    
    Attributes:
        RELEVANT (str): 相关标记
        IRRELEVANT (str): 不相关标记
        client (SiliconFlowClient): 硅基流动API客户端实例
    
    筛选逻辑：
    1. 检查摘要长度，过短则跳过筛选
    2. 调用LLM判断相关性
    3. 解析LLM响应
    4. 出错时默认判定为相关（避免漏检）
    
    Example:
        from src.summarizer import PaperFilter, SiliconFlowClient
        
        client = SiliconFlowClient(api_key="your-key")
        filter = PaperFilter(client)
        
        # 判断单篇论文
        is_relevant, reason = filter.is_relevant(paper, ["LLM", "transformer"])
        
        # 批量筛选
        relevant = []
        for paper in papers:
            is_rel, reason = filter.is_relevant(paper, keywords)
            if is_rel:
                relevant.append(paper)
    """
    
    RELEVANT = "RELEVANT"
    IRRELEVANT = "IRRELEVANT"

    def __init__(self, siliconflow_client: SiliconFlowClient):
        """
        初始化论文筛选器。
        
        Args:
            siliconflow_client: 硅基流动API客户端实例
        
        Example:
            client = SiliconFlowClient(api_key="your-key")
            paper_filter = PaperFilter(client)
        """
        self.client = siliconflow_client

    def is_relevant(self, paper: Paper, target_keywords: List[str]) -> Tuple[bool, str]:
        """
        判断论文是否与目标关键词相关。
        
        该方法会：
        1. 检查论文摘要是否足够长（至少30字符）
        2. 构建提示词，包含论文标题、分类、摘要
        3. 调用LLM进行相关性判断
        4. 解析LLM响应
        
        判断规则（通过提示词传递给LLM）：
        - 非CS领域（物理、化学、生物等）+ CS关键词 = 不相关
        - cs.RO（机器人）但核心是计算机视觉/深度学习 = 相关
        - 仅背景介绍提到关键词，核心内容不相关 = 不相关
        - 标题和摘要都显示高度相关 = 相关
        
        Args:
            paper: Paper对象，需要有title、categories、summary属性
            target_keywords: 目标关键词列表
        
        Returns:
            元组 (is_relevant, reason):
            - is_relevant: 是否相关，布尔值
            - reason: 判定原因的描述字符串
        
        Example:
            # 基本用法
            is_relevant, reason = filter.is_relevant(paper, ["LLM", "transformer"])
            if is_relevant:
                print(f"相关论文: {paper.title}")
            else:
                print(f"跳过不相关论文: {reason}")
            
            # 处理摘要过短的情况
            if paper.summary and len(paper.summary) > 100:
                is_relevant, reason = filter.is_relevant(paper, keywords)
            else:
                # 摘要太短，自行判断
                is_relevant = any(kw.lower() in paper.title.lower() for kw in keywords)
        """
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

        for page_num, page in enumerate(doc):
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
        prompt_dir: str = "./markdown",
        use_vision_mode: bool = False,
        text_model: str = "Qwen/Qwen2.5-7B-Instruct",
        vision_model: str = "Qwen/Qwen2-VL-72B-Instruct",
    ):
        """
        初始化论文总结器。
        
        Args:
            siliconflow_api_key: 硅基流动API密钥
            prompt_dir: Prompt模板文件目录，默认为 "./markdown"
            use_vision_mode: 是否使用视觉模式，默认为False
            text_model: 文本模型名称
            vision_model: 视觉模型名称
        
        Prompt文件结构：
            prompt_dir/
            ├── summary_prompt.txt          # 摘要总结提示
            ├── technical_route_prompt.txt  # 技术路线分析提示
            ├── methodology_prompt.txt      # 方法论分析提示
            ├── experiment_prompt.txt       # 实验方案分析提示
            ├── introduction_prompt.txt     # Introduction逻辑分析提示
            └── paper_template.md           # 输出Markdown模板
        
        Example:
            # 文本模式（推荐大多数场景）
            summarizer = Summarizer(
                siliconflow_api_key=os.environ["SILICONFLOW_API_KEY"],
                prompt_dir="./my_prompts",
                use_vision_mode=False
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
        self.siliconflow_client = SiliconFlowClient(
            api_key=siliconflow_api_key,
            text_model=text_model,
            vision_model=vision_model,
        )
        self.paper_filter = PaperFilter(self.siliconflow_client)
        self.prompt_dir = prompt_dir
        self._load_prompts()

    def _load_prompts(self):
        """
        加载Prompt模板文件。
        
        内部方法，从prompt_dir目录加载以下文件：
        - summary_prompt.txt
        - technical_route_prompt.txt
        - methodology_prompt.txt
        - experiment_prompt.txt
        - introduction_prompt.txt
        
        如果文件不存在，会使用内置的默认模板。
        """
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
        """
        获取默认Prompt模板。
        
        内部方法，当文件不存在时提供内置的默认模板。
        
        Args:
            prompt_type: Prompt类型（文件名）
        
        Returns:
            默认Prompt字符串
        """
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
        """
        批量筛选论文。
        
        对论文列表中的每篇论文调用PaperFilter.is_relevant()进行筛选，
        并将结果分为相关和不相关两组。
        
        Args:
            papers: Paper对象列表
            keywords: 目标关键词列表
        
        Returns:
            元组 (relevant_papers, irrelevant_papers):
            - relevant_papers: 被判定为相关的论文列表
            - irrelevant_papers: 被判定为不相关的论文列表
        
        Example:
            papers = sniffer.search(keywords=["LLM"], max_results=10)
            
            # 筛选
            relevant, irrelevant = summarizer.filter_papers(papers, ["LLM"])
            
            print(f"相关: {len(relevant)} 篇")
            print(f"不相关: {len(irrelevant)} 篇")
            
            # 只处理相关论文
            for paper in relevant:
                sniffer.download_pdf(paper)
                summary = summarizer.summarize(paper)
                # ...
        """
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
        """
        总结论文。
        
        根据配置的模式（文本或视觉），调用相应的总结方法。
        
        文本模式流程：
        1. 使用PDFExtractor提取文本
        2. 截断超长文本（>12000字符）
        3. 调用文本模型进行5个维度的分析
        
        视觉模式流程：
        1. 使用ImageConverter转换为图像
        2. 调用视觉模型进行5个维度的分析
        
        Args:
            paper: Paper对象，必须有local_pdf_path属性
        
        Returns:
            包含多维度分析结果的字典：
            {
                "arxiv_id": "2401.12345",
                "title": "论文标题",
                "authors": ["作者1", "作者2"],
                "arxiv_url": "https://arxiv.org/abs/...",
                "categories": ["cs.CL", "cs.AI"],
                "original_abstract": "原摘要",
                "summary": "AI生成的摘要",
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
                result = summarizer.summarize(paper)
                print(f"摘要: {result['summary'][:200]}...")
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
            return self._summarize_with_vision(paper, summary_result)
        else:
            return self._summarize_with_text(paper, summary_result)

    def _summarize_with_text(self, paper: Paper, summary_result: Dict) -> Dict:
        """
        使用文本模式总结论文。
        
        内部方法，执行以下5个维度的分析：
        1. 论文摘要（summary_prompt.txt）
        2. 技术路线分析（technical_route_prompt.txt）
        3. 方法论分析（methodology_prompt.txt）
        4. 实验方案分析（experiment_prompt.txt）
        5. Introduction行文逻辑分析（introduction_prompt.txt）
        
        Args:
            paper: Paper对象
            summary_result: 待填充的结果字典
        
        Returns:
            填充完成的结果字典
        """
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
        """
        使用视觉模式总结论文。
        
        内部方法，将PDF转换为图像后调用视觉模型。
        可以理解论文中的图表、公式和布局。
        
        Args:
            paper: Paper对象
            summary_result: 待填充的结果字典
        
        Returns:
            填充完成的结果字典
        """
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
        - {summary}: AI生成摘要
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
