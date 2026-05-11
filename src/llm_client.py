from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

import openai

logger = logging.getLogger(__name__)

_DEFAULT_MAX_RETRIES = 3
_DEFAULT_RETRY_BASE = 2
_DEFAULT_TEMPERATURE = 0.1


@dataclass
class LlmResponse:
    """LLM 调用结果"""

    model: str
    data: dict | None
    error: str | None


class LlmClient:
    """通用 LLM 客户端，封装 OpenAI 兼容 API 调用与重试逻辑"""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.siliconflow.cn/v1",
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_base: int = _DEFAULT_RETRY_BASE,
    ) -> None:
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.max_retries = max_retries
        self.retry_base = retry_base

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = _DEFAULT_TEMPERATURE,
        json_mode: bool = True,
    ) -> LlmResponse:
        """调用 LLM chat completion，含指数退避重试

        Args:
            messages: 消息列表，每项包含 role 和 content
            temperature: 采样温度
            json_mode: 是否启用 JSON 输出模式

        Returns:
            LlmResponse: data 为解析后的 dict（json_mode 时），error 为错误信息
        """
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        for attempt in range(self.max_retries):
            try:
                response = self.client.chat.completions.create(**kwargs)
                raw = response.choices[0].message.content

                if json_mode:
                    data = json.loads(raw)
                    return LlmResponse(model=self.model, data=data, error=None)

                return LlmResponse(model=self.model, data={"content": raw}, error=None)

            except json.JSONDecodeError as e:
                return LlmResponse(model=self.model, data=None, error=f"JSON 解析失败: {e}")

            except Exception as e:
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_base**attempt)
                else:
                    logger.warning(
                        "LLM 调用失败（已重试 %d 次）: %s", self.max_retries, e
                    )
                    return LlmResponse(
                        model=self.model,
                        data=None,
                        error=f"API 调用失败（重试 {self.max_retries} 次）: {e}",
                    )

        return LlmResponse(model=self.model, data=None, error="未知错误")
