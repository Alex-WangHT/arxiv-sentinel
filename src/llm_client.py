"""LLM 客户端模块 - 异步版本

提供高性能的异步 LLM API 调用封装，支持：
- 异步调用模式
- 流式响应
- 指数退避+抖动重试
- 批量异步调用
- 连接池优化

当前实现基于 OpenAI 兼容 API，通过配置 base_url 可适配各类服务。
"""

import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

import openai
from httpx import Timeout, AsyncClient, Limits

# 模块级日志记录器
logger = logging.getLogger(__name__)

# 默认配置常量
_DEFAULT_MAX_RETRIES = 2     # 最大重试次数
_DEFAULT_RETRY_BASE = 3      # 指数退避基数（秒）
_DEFAULT_RETRY_JITTER = 0.5  # 抖动系数
_DEFAULT_TEMPERATURE = 0.1   # 默认采样温度
_DEFAULT_TIMEOUT = 120       # 超时时间（秒）
_DEFAULT_CONNECTIONS = 5     # 连接池大小


@dataclass
class LlmResponse:
    """LLM API 调用结果封装类"""
    model: str
    data: Optional[Dict[str, Any]]
    error: Optional[str]


class LlmClient:
    """异步 LLM 客户端类"""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_base: int = _DEFAULT_RETRY_BASE,
        timeout: int = _DEFAULT_TIMEOUT,
        connections: int = _DEFAULT_CONNECTIONS,
    ) -> None:
        limits = Limits(
            max_connections=connections,
            max_keepalive_connections=connections
        )

        # 异步客户端 - 禁用内置重试，由我们自己的逻辑处理
        self.async_client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=Timeout(timeout, read=timeout),
            http_client=AsyncClient(limits=limits),
            max_retries=0,
        )

        self.model = model
        self.max_retries = max_retries
        self.retry_base = retry_base
        self.timeout = timeout

    def _calculate_retry_delay(self, attempt: int) -> float:
        """计算重试延迟（带抖动）"""
        base_delay = self.retry_base ** attempt
        jitter = random.uniform(-_DEFAULT_RETRY_JITTER, _DEFAULT_RETRY_JITTER) * base_delay
        return max(0.5, base_delay + jitter)

    def _build_kwargs(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        json_mode: bool,
        stream: bool = False,
    ) -> Dict[str, Any]:
        """构建 API 调用参数"""
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        return kwargs

    def _parse_response(self, response, json_mode: bool) -> LlmResponse:
        """解析 API 响应"""
        raw_content = response.choices[0].message.content
        if json_mode:
            try:
                parsed_data = json.loads(raw_content)
                return LlmResponse(model=self.model, data=parsed_data, error=None)
            except json.JSONDecodeError as e:
                logger.warning(f"JSON 解析失败: {str(e)}")
                return LlmResponse(model=self.model, data=None, error=f"JSON 解析失败: {str(e)}")
        return LlmResponse(model=self.model, data={"content": raw_content}, error=None)

    def _should_retry(self, error_str: str) -> bool:
        """判断错误是否值得重试"""
        retryable_errors = [
            "rate limit",
            "timeout",
            "connection",
            "500",
            "502",
            "503",
            "504",
            "server error",
            "service unavailable",
        ]
        error_lower = error_str.lower()
        return any(error in error_lower for error in retryable_errors)

    async def achat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = _DEFAULT_TEMPERATURE,
        json_mode: bool = True,
    ) -> LlmResponse:
        """异步调用 LLM 进行对话补全"""
        start_time = time.time()
        kwargs = self._build_kwargs(messages, temperature, json_mode)

        for attempt in range(self.max_retries + 1):
            try:
                attempt_start = time.time()
                logger.debug(f"LLM 调用第 {attempt + 1} 次开始")

                response = await self.async_client.chat.completions.create(**kwargs)

                elapsed = time.time() - attempt_start
                logger.debug(f"LLM 调用第 {attempt + 1} 次成功，耗时 {elapsed:.2f} 秒")

                total_elapsed = time.time() - start_time
                logger.debug(f"LLM 调用完成，总耗时 {total_elapsed:.2f} 秒")
                return self._parse_response(response, json_mode)

            except Exception as e:
                elapsed = time.time() - start_time
                error_str = str(e)
                
                if attempt < self.max_retries and self._should_retry(error_str):
                    wait_time = self._calculate_retry_delay(attempt)
                    logger.warning(
                        "LLM 调用第 %d 次失败（已耗时 %.2f 秒），等待 %.2f 秒后重试",
                        attempt + 1, elapsed, wait_time
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(
                        "LLM 调用失败（已重试 %d 次，总耗时 %.2f 秒）: %s",
                        attempt, elapsed, error_str[:100]
                    )
                    return LlmResponse(
                        model=self.model,
                        data=None,
                        error=f"API 调用失败（重试 {attempt} 次，耗时 {elapsed:.2f} 秒）: {error_str[:100]}"
                    )

        return LlmResponse(model=self.model, data=None, error="未知错误")

    async def achat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = _DEFAULT_TEMPERATURE,
    ) -> str:
        """异步流式调用 LLM，边接收边处理"""
        kwargs = self._build_kwargs(messages, temperature, json_mode=False, stream=True)

        async with self.async_client.chat.completions.create(**kwargs) as stream:
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

    async def batch_achat(
        self,
        messages_list: List[List[Dict[str, str]]],
        temperature: float = _DEFAULT_TEMPERATURE,
        json_mode: bool = True,
        max_concurrent: int = 3,
    ) -> List[LlmResponse]:
        """批量异步调用 LLM，限制并发数"""
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _limited_call(messages: List[Dict[str, str]]) -> LlmResponse:
            async with semaphore:
                return await self.achat(messages, temperature, json_mode)

        tasks = [_limited_call(messages) for messages in messages_list]
        return await asyncio.gather(*tasks)


if __name__ == "__main__":
    """模块自测试入口"""
    from config import Config

    cfg = Config.from_file()
    llm = LlmClient(
        api_key=cfg.openai_api_key,
        model=cfg.openai_model,
        base_url=cfg.openai_base_url,
    )

    async def run_tests():
        test_messages = [{
            "role": "user",
            "content": '{"task": "介绍一下你自己", "language": "Chinese"}'
        }]
        
        # 单条异步调用
        result = await llm.achat(messages=test_messages)
        print(f"模型: {result.model}")
        print(f"数据: {result.data}")
        print(f"错误: {result.error}")

        # 批量异步调用
        batch_messages = [
            [{"role": "user", "content": f'{{"task": "用一句话描述问题{i}", "language": "Chinese"}}'}]
            for i in range(2)
        ]
        results = await llm.batch_achat(batch_messages, max_concurrent=2)
        print(f"批量调用结果: {[r.data for r in results]}")

    asyncio.run(run_tests())