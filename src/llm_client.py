"""LLM 客户端模块 - 异步版本

提供高性能的异步 LLM API 调用封装，支持：
- 异步调用模式
- 指数退避+抖动重试
- 批量异步调用（队列模式）
- 连接池优化
- 请求超时取消机制
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
_DEFAULT_TIMEOUT = 120       # 超时时间（秒）- 缩短到2分钟，配合重试机制
_DEFAULT_CONNECTIONS = 3     # 连接池大小
_DEFAULT_REQUEST_INTERVAL = 0.5  # 请求间隔（秒）


@dataclass
class LlmResponse:
    """LLM API 调用结果封装类"""
    model: str
    data: Optional[Dict[str, Any]]
    error: Optional[str]
    elapsed: float = 0.0  # 请求耗时（秒）


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
        self.connections = connections  # 保存连接池大小供后续使用
        self.timeout = timeout

    def _calculate_retry_delay(self, attempt: int) -> float:
        """计算重试延迟（带抖动）"""
        base_delay = self.retry_base ** attempt
        jitter = random.uniform(-_DEFAULT_RETRY_JITTER, _DEFAULT_RETRY_JITTER) * base_delay
        return max(2.0, base_delay + jitter)  # 最小延迟增加到2秒

    def _build_kwargs(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        json_mode: bool,
    ) -> Dict[str, Any]:
        """构建 API 调用参数"""
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages.copy(),
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
            json_prompt = "请以JSON格式输出你的回答。"
            if kwargs["messages"] and kwargs["messages"][0]["role"] == "system":
                kwargs["messages"][0]["content"] = json_prompt + kwargs["messages"][0]["content"]
            else:
                kwargs["messages"].insert(0, {"role": "system", "content": json_prompt})
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
        request_id: str = "",
    ) -> LlmResponse:
        """异步调用 LLM 进行对话补全（带超时取消机制）"""
        start_time = time.time()
        kwargs = self._build_kwargs(messages, temperature, json_mode)
        request_label = f"请求{request_id}" if request_id else "请求"

        for attempt in range(self.max_retries + 1):
            try:
                attempt_start = time.time()
                logger.debug(f"{request_label} 第 {attempt + 1} 次调用开始")

                # 使用 asyncio.wait_for 添加超时保护
                response = await asyncio.wait_for(
                    self.async_client.chat.completions.create(**kwargs),
                    timeout=self.timeout
                )

                elapsed = time.time() - attempt_start
                logger.debug(f"{request_label} 第 {attempt + 1} 次调用成功，耗时 {elapsed:.2f} 秒")

                total_elapsed = time.time() - start_time
                result = self._parse_response(response, json_mode)
                result.elapsed = total_elapsed
                logger.debug(f"{request_label} 完成，总耗时 {total_elapsed:.2f} 秒")
                return result

            except asyncio.TimeoutError:
                elapsed = time.time() - start_time
                logger.warning(f"{request_label} 第 {attempt + 1} 次调用超时（已耗时 {elapsed:.2f} 秒）")
                
                if attempt < self.max_retries:
                    wait_time = self._calculate_retry_delay(attempt)
                    logger.warning(f"{request_label} 等待 {wait_time:.2f} 秒后重试")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"{request_label} 超时失败（已重试 {attempt} 次，总耗时 {elapsed:.2f} 秒）")
                    return LlmResponse(
                        model=self.model,
                        data=None,
                        error=f"请求超时（重试 {attempt} 次，耗时 {elapsed:.2f} 秒）",
                        elapsed=elapsed
                    )

            except Exception as e:
                elapsed = time.time() - start_time
                error_str = str(e)

                if attempt < self.max_retries and self._should_retry(error_str):
                    wait_time = self._calculate_retry_delay(attempt)
                    logger.warning(
                        f"{request_label} 第 {attempt + 1} 次失败（{elapsed:.2f}秒），等待 {wait_time:.2f} 秒后重试: {error_str[:50]}"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(
                        f"{request_label} 失败（已重试 {attempt} 次，耗时 {elapsed:.2f} 秒）: {error_str[:100]}"
                    )
                    return LlmResponse(
                        model=self.model,
                        data=None,
                        error=f"API 调用失败（重试 {attempt} 次，耗时 {elapsed:.2f} 秒）: {error_str[:100]}",
                        elapsed=elapsed
                    )

        return LlmResponse(model=self.model, data=None, error="未知错误", elapsed=time.time() - start_time)

    async def batch_achat(
        self,
        messages_list: List[List[Dict[str, str]]],
        temperature: float = _DEFAULT_TEMPERATURE,
        json_mode: bool = True,
        request_interval: float = _DEFAULT_REQUEST_INTERVAL,
        queue_interval: float = 20.0,  # 队列间隔时间（秒）
    ) -> List[LlmResponse]:
        """批量异步调用 LLM - 多队列并行模式

        采用队列内串行+多队列并行的方式处理请求：
        - 将请求按连接池大小分成多个队列
        - 每个队列内部按固定间隔串行发送请求
        - 队列之间间隔指定时间启动（默认20秒）

        Args:
            messages_list: 消息列表的列表
            temperature: 采样温度
            json_mode: 是否要求 JSON 格式输出
            request_interval: 队列内请求间隔时间（秒），默认0.5秒
            queue_interval: 队列之间的启动间隔时间（秒），默认20秒

        Returns:
            List[LlmResponse]: 响应列表，顺序与输入一致
        """
        total_count = len(messages_list)
        # 使用初始化时保存的连接池大小作为队列大小
        queue_size = self.connections if self.connections and self.connections >= 1 else 3
        
        # 将请求分成多个队列
        queues = []
        for i in range(queue_size):
            queue = messages_list[i::queue_size]
            if queue:
                queues.append((i, queue))
        
        logger.info(f"开始多队列并行处理 {total_count} 个请求")
        logger.info(f"队列数: {len(queues)}, 队列大小: {queue_size}, 队列间隔: {queue_interval}秒, 请求间隔: {request_interval}秒")
        
        results = [None] * total_count
        completed_count = 0
        
        async def _process_queue(queue_index: int, queue_messages: List[List[Dict[str, str]]]):
            """处理单个队列，队列内串行发送请求"""
            nonlocal completed_count
            queue_total = len(queue_messages)
            
            for j, messages in enumerate(queue_messages):
                # 计算原始索引位置
                original_index = queue_index + j * queue_size
                request_id = f"Q{queue_index + 1}-{j + 1}/{queue_total}"
                
                try:
                    result = await self.achat(messages, temperature, json_mode, request_id)
                    results[original_index] = result
                    
                    completed_count += 1
                    progress = (completed_count / total_count) * 100
                    logger.info(f"请求{request_id} 完成，进度: {progress:.1f}% ({completed_count}/{total_count})")
                    
                except Exception as e:
                    logger.error(f"请求{request_id} 异常: {str(e)}")
                    results[original_index] = LlmResponse(
                        model=self.model,
                        data=None,
                        error=f"请求异常: {str(e)}",
                        elapsed=0.0
                    )
                
                # 队列内请求间隔（最后一个请求不需要等待）
                if j < queue_total - 1:
                    await asyncio.sleep(request_interval)
        
        # 启动多个队列，队列之间间隔指定时间
        queue_tasks = []
        for queue_index, (orig_index, queue_messages) in enumerate(queues):
            logger.info(f"启动队列 #{queue_index + 1}/{len(queues)}")
            task = asyncio.create_task(_process_queue(orig_index, queue_messages))
            queue_tasks.append(task)
            
            # 队列之间间隔（最后一个队列不需要等待）
            if queue_index < len(queues) - 1:
                await asyncio.sleep(queue_interval)
        
        await asyncio.gather(*queue_tasks)
        logger.info(f"批量调用完成，共 {completed_count}/{total_count} 个请求成功")
        return results


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

        result = await llm.achat(messages=test_messages)
        print(f"模型: {result.model}")
        print(f"数据: {result.data}")
        print(f"错误: {result.error}")
        print(f"耗时: {result.elapsed:.2f}秒")

        batch_messages = [
            [{"role": "user", "content": f'{{"task": "用一句话描述问题{i}", "language": "Chinese"}}'}]
            for i in range(3)
        ]
        print("\n=== 队列模式 ===")
        results = await llm.batch_achat(batch_messages, request_interval=0.5)
        for i, r in enumerate(results):
            print(f"请求{i+1}: 耗时={r.elapsed:.2f}s, 数据={r.data}")

    asyncio.run(run_tests())