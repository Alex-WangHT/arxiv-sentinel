"""LLMClient — 硅基流动通信封装，强制结构化 JSON 输出（SPEC §5.3 / §6）。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class LLMMessage:
    role: str
    content: str | list[dict[str, Any]]


class LLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        text_timeout: int = 30,
        multimodal_timeout: int = 120,
        retry_max_attempts: int = 5,
        retry_initial_backoff: int = 2,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.text_timeout = text_timeout
        self.multimodal_timeout = multimodal_timeout
        self.retry_max_attempts = retry_max_attempts
        self.retry_initial_backoff = retry_initial_backoff
        self._client = self._build_client()

    def _build_client(self) -> Any:
        raise NotImplementedError("instantiate openai.OpenAI(base_url=..., api_key=...)")

    def chat_json(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        schema_hint: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """纯文本任务，返回结构化 JSON（response_format=json_object）。超时 = text_timeout。"""
        raise NotImplementedError

    def chat_multimodal(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        image_b64_list: list[str],
    ) -> str:
        """多模态全文总结，返回原始 Markdown+XML 字符串。超时 = multimodal_timeout。"""
        raise NotImplementedError

    def _retry_with_backoff(self, fn, *args, **kwargs):
        """指数退避重试：HTTP 429 时 2s, 4s, 8s... 序列延迟。"""
        raise NotImplementedError
