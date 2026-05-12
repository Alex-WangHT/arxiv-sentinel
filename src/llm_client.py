"""LLM 客户端模块

提供与 OpenAI 兼容的 LLM API 调用封装，支持指数退避重试机制。
主要功能包括：
- 统一的 LLM 响应数据结构
- 自动重试与错误处理
- JSON 输出模式支持
- 可配置的重试策略

当前实现基于 SiliconFlow API，但通过配置 base_url 可适配其他 OpenAI 兼容服务。
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

import openai

# 模块级日志记录器
logger = logging.getLogger(__name__)

# 默认配置常量
_DEFAULT_MAX_RETRIES = 3  # 默认最大重试次数
_DEFAULT_RETRY_BASE = 2    # 指数退避基数（秒）
_DEFAULT_TEMPERATURE = 0.1 # 默认采样温度，较低值使输出更确定


@dataclass
class LlmResponse:
    """LLM API 调用结果封装类

    Attributes:
        model: 调用的模型名称
        data: 解析后的响应数据（JSON 模式下为 dict，普通模式下为含 content 的 dict）
        error: 错误信息，成功时为 None
    """

    model: str
    data: Optional[Dict[str, Any]]
    error: Optional[str]


class LlmClient:
    """通用 LLM 客户端类

    封装 OpenAI 兼容 API 的调用逻辑，提供统一的接口和错误处理。
    支持指数退避重试策略，确保在网络波动或服务限流时的稳定性。

    Args:
        api_key: API 密钥
        model: 模型名称（如 'deepseek-ai/DeepSeek-V4-Flash'）
        base_url: API 基础地址，默认为 SiliconFlow
        max_retries: 最大重试次数
        retry_base: 指数退避基数，每次重试间隔为 base^attempt 秒
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.siliconflow.cn/v1",
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_base: int = _DEFAULT_RETRY_BASE,
    ) -> None:
        # 初始化 OpenAI 客户端
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.max_retries = max_retries
        self.retry_base = retry_base

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = _DEFAULT_TEMPERATURE,
        json_mode: bool = True,
    ) -> LlmResponse:
        """调用 LLM 进行对话补全

        Args:
            messages: 消息列表，每项必须包含 'role'（'system'/'user'/'assistant'）和 'content' 字段
            temperature: 采样温度，范围 0-2，越高越随机
            json_mode: 是否要求模型返回 JSON 格式输出

        Returns:
            LlmResponse: 包含模型名、解析后的数据和错误信息

        Raises:
            不抛出异常，所有错误都封装在返回对象的 error 字段中
        """
        # 构建 API 调用参数
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        
        # JSON 模式下添加响应格式要求
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        # 执行带重试的 API 调用
        for attempt in range(self.max_retries):
            try:
                # 调用 OpenAI API
                response = self.client.chat.completions.create(**kwargs)
                
                # 提取响应内容
                raw_content = response.choices[0].message.content

                # JSON 模式下解析响应
                if json_mode:
                    try:
                        parsed_data = json.loads(raw_content)
                        return LlmResponse(
                            model=self.model,
                            data=parsed_data,
                            error=None
                        )
                    except json.JSONDecodeError as e:
                        # JSON 解析失败，直接返回错误
                        return LlmResponse(
                            model=self.model,
                            data=None,
                            error=f"JSON 解析失败: {str(e)}"
                        )

                # 非 JSON 模式，直接包装返回
                return LlmResponse(
                    model=self.model,
                    data={"content": raw_content},
                    error=None
                )

            except Exception as e:
                # 处理其他异常（网络错误、API 错误等）
                if attempt < self.max_retries - 1:
                    # 非最后一次尝试，等待后重试
                    wait_time = self.retry_base ** attempt
                    logger.debug(
                        "LLM 调用第 %d 次失败，等待 %d 秒后重试: %s",
                        attempt + 1, wait_time, str(e)
                    )
                    time.sleep(wait_time)
                else:
                    # 最后一次尝试失败，记录警告并返回错误
                    logger.warning(
                        "LLM 调用失败（已重试 %d 次）: %s",
                        self.max_retries, str(e)
                    )
                    return LlmResponse(
                        model=self.model,
                        data=None,
                        error=f"API 调用失败（重试 {self.max_retries} 次）: {str(e)}"
                    )

        # 理论上不会到达这里，因为循环会在 max_retries 次后返回
        return LlmResponse(
            model=self.model,
            data=None,
            error="未知错误"
        )


if __name__ == "__main__":
    """模块自测试入口"""
    from config import Config
    
    # 加载配置
    cfg = Config.from_file()
    
    # 创建客户端实例
    llm = LlmClient(
        api_key=cfg.siliconflow_api_key,
        model=cfg.siliconflow_model,
    )
    
    # 测试调用（使用 JSON 模式）
    test_messages = [{
        "role": "user",
        "content": '{"task": "现在你需要介绍一下你自己", "language": "Chinese"}'
    }]
    
    # 执行测试
    result = llm.chat(messages=test_messages)
    
    # 输出结果
    print("测试结果:")
    print(f"  模型: {result.model}")
    print(f"  数据: {result.data}")
    print(f"  错误: {result.error}")