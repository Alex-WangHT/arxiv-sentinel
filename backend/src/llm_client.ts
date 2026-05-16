import { LlmResponse } from './models';

/*
 * LlmClient 负责调用“大模型聊天补全接口”。
 *
 * Worker 适配点：
 * - 旧代码依赖 openai npm SDK；
 * - SDK 在 Worker 环境中可能引入 Node 相关依赖或增加打包复杂度；
 * - 这里改成直接用 fetch 调 OpenAI-compatible API。
 *
 * 只要服务商兼容 /v1/chat/completions，就可以通过 OPENAI_BASE_URL 切换。
 */

const DEFAULT_MAX_RETRIES = 2;
const DEFAULT_RETRY_BASE = 3;
const DEFAULT_RETRY_JITTER = 0.5;
const DEFAULT_TEMPERATURE = 0.1;
const DEFAULT_TIMEOUT = 120;
const DEFAULT_CONNECTIONS = 3;
const DEFAULT_REQUEST_INTERVAL = 0.5;

type ChatMessage = Array<{ role: string; content: string }>;
type BatchProgressCallback = (completed: number, total: number) => void | Promise<void>;

// 发送给 /chat/completions 的请求体。
// 这里只定义项目实际用到的字段，便于在没有 SDK 的情况下保持类型提示。
interface ChatCompletionParams {
  model: string;
  messages: ChatMessage;
  temperature: number;
  response_format?: { type: 'json_object' };
  stream: false;
}

// 大模型返回体的最小结构。
// 不同服务商可能会返回更多字段，但我们只关心 choices[0].message.content。
interface ChatCompletionResponse {
  choices?: Array<{
    message?: {
      content?: string | null;
    };
  }>;
  error?: {
    message?: string;
  };
}

export class LlmClient {
  private apiKey: string;
  private model: string;
  private baseUrl: string;
  private maxRetries: number;
  private retryBase: number;
  private connections: number;
  private timeout: number;

  constructor(
    apiKey: string,
    model: string,
    baseUrl: string = 'https://api.openai.com/v1',
    maxRetries: number = DEFAULT_MAX_RETRIES,
    retryBase: number = DEFAULT_RETRY_BASE,
    timeout: number = DEFAULT_TIMEOUT,
    connections: number = DEFAULT_CONNECTIONS,
  ) {
    this.apiKey = apiKey;
    this.model = model;
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.maxRetries = maxRetries;
    this.retryBase = retryBase;
    this.connections = connections;
    this.timeout = timeout;
  }

  // achat = async chat。这个方法调用一次大模型，并返回统一的 LlmResponse。
  // jsonMode=true 时，会要求模型返回 JSON，并尝试 JSON.parse。
  async achat(
    messages: ChatMessage,
    temperature: number = DEFAULT_TEMPERATURE,
    jsonMode: boolean = true,
    requestId: string = '',
  ): Promise<LlmResponse> {
    const startTime = Date.now();
    const kwargs = this.buildKwargs(messages, temperature, jsonMode);
    const requestLabel = requestId ? `请求 ${requestId}` : '请求';

    // 手写重试循环：遇到限流、超时、5xx 等临时错误时等待后再试。
    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      try {
        const attemptStart = Date.now();
        console.debug(`${requestLabel} 第 ${attempt + 1} 次调用开始`);

        const response = await this.createChatCompletion(kwargs);
        const elapsed = (Date.now() - attemptStart) / 1000;
        console.debug(`${requestLabel} 第 ${attempt + 1} 次调用成功，耗时 ${elapsed.toFixed(2)} 秒`);

        const totalElapsed = (Date.now() - startTime) / 1000;
        const result = this.parseResponse(response, jsonMode);
        result.elapsed = totalElapsed;
        console.debug(`${requestLabel} 完成，总耗时 ${totalElapsed.toFixed(2)} 秒`);
        return result;
      } catch (error) {
        const elapsed = (Date.now() - startTime) / 1000;
        const errorStr = String(error);

        if (attempt < this.maxRetries && this.shouldRetry(errorStr)) {
          const waitTime = this.calculateRetryDelay(attempt);
          console.warn(
            `${requestLabel} 第 ${attempt + 1} 次失败（${elapsed.toFixed(2)} 秒），等待 ${waitTime.toFixed(2)} 秒后重试: ${errorStr.slice(0, 120)}`,
          );
          await this.sleep(waitTime);
        } else {
          console.error(
            `${requestLabel} 失败（已重试 ${attempt} 次，耗时 ${elapsed.toFixed(2)} 秒）: ${errorStr.slice(0, 200)}`,
          );
          return {
            model: this.model,
            data: null,
            error: `API 调用失败（重试 ${attempt} 次，耗时 ${elapsed.toFixed(2)} 秒）: ${errorStr.slice(0, 200)}`,
            elapsed,
          };
        }
      }
    }

    const totalElapsed = (Date.now() - startTime) / 1000;
    return { model: this.model, data: null, error: '未知错误', elapsed: totalElapsed };
  }

  // 批量调用大模型。
  // Cloudflare Workers 会统计单次 invocation 内的所有外部 fetch/D1 等 subrequests。
  // 这里按固定窗口并发处理：每轮最多 5 个请求同时发出，本轮全部完成后才进入下一轮。
  async batchAchat(
    messagesList: ChatMessage[],
    temperature: number = DEFAULT_TEMPERATURE,
    jsonMode: boolean = true,
    requestInterval: number = DEFAULT_REQUEST_INTERVAL,
    _queueInterval: number = 20.0,
    onProgress?: BatchProgressCallback,
  ): Promise<LlmResponse[]> {
    const totalCount = messagesList.length;
    const results = new Array<LlmResponse>(totalCount);
    const concurrency = 5;
    let completedCount = 0;

    console.info(`开始窗口并发处理 ${totalCount} 个请求，并发宽度: ${concurrency}，轮次间隔: ${requestInterval} 秒`);

    for (let start = 0; start < totalCount; start += concurrency) {
      const windowMessages = messagesList.slice(start, start + concurrency);
      const windowNumber = Math.floor(start / concurrency) + 1;
      console.info(`启动第 ${windowNumber} 轮请求，共 ${windowMessages.length} 个`);

      const windowResults = await Promise.all(windowMessages.map(async (messages, offset) => {
        const index = start + offset;
        const requestId = `${index + 1}/${totalCount}`;
        const result = await this.achat(messages, temperature, jsonMode, requestId);
        if (result.error) {
          throw new Error(result.error);
        }
        return { index, result };
      }));

      for (const { index, result } of windowResults) {
        results[index] = result;
        completedCount++;
        const progress = (completedCount / totalCount) * 100;
        console.info(`请求 ${index + 1}/${totalCount} 完成，进度 ${progress.toFixed(1)}% (${completedCount}/${totalCount})`);
        await onProgress?.(completedCount, totalCount);
      }

      if (start + concurrency < totalCount) {
        await this.sleep(requestInterval);
      }
    }

    console.info(`窗口并发批量调用完成，共 ${completedCount}/${totalCount} 个请求完成`);
    return results;
  }

  // 真正发 HTTP 请求的地方。
  // AbortController 用来实现超时控制：超过 timeout 秒就主动取消请求。
  private async createChatCompletion(kwargs: ChatCompletionParams): Promise<ChatCompletionResponse> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort('request timeout'), this.timeout * 1000);

    try {
      const response = await fetch(`${this.baseUrl}/chat/completions`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${this.apiKey}`,
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify(kwargs),
        signal: controller.signal,
      });

      // 先读成 text，再 JSON.parse。
      // 这样如果服务商返回非 JSON 错误文本，也能把原始内容放进报错里。
      const rawText = await response.text();
      const parsed = rawText ? (JSON.parse(rawText) as ChatCompletionResponse) : {};

      if (!response.ok) {
        const message = parsed.error?.message || rawText || response.statusText;
        throw new Error(`HTTP ${response.status}: ${message}`);
      }

      return parsed;
    } catch (error) {
      if ((error as Error).name === 'AbortError') {
        throw new Error('请求超时');
      }
      throw error;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  // 指数退避 + 随机抖动。
  // 作用是：失败后不要所有请求同时重试，减少再次被限流的概率。
  private calculateRetryDelay(attempt: number): number {
    const baseDelay = Math.pow(this.retryBase, attempt);
    const jitter = (Math.random() - 0.5) * 2 * DEFAULT_RETRY_JITTER * baseDelay;
    return Math.max(2.0, baseDelay + jitter);
  }

  // 构造发送给模型服务商的请求体。
  // jsonMode 打开时，额外加 response_format 和一条“请返回 JSON”的系统提示。
  private buildKwargs(
    messages: ChatMessage,
    temperature: number,
    jsonMode: boolean,
  ): ChatCompletionParams {
    const kwargs: ChatCompletionParams = {
      model: this.model,
      messages: [...messages],
      temperature,
      stream: false,
    };

    if (jsonMode) {
      kwargs.response_format = { type: 'json_object' };
      const jsonPrompt = '请以 JSON 格式输出你的回答。';
      const msgList = kwargs.messages as Array<{ role: string; content: string }>;
      if (msgList.length > 0 && msgList[0].role === 'system') {
        msgList[0] = { ...msgList[0], content: `${jsonPrompt}\n${msgList[0].content}` };
      } else {
        msgList.unshift({ role: 'system', content: jsonPrompt });
      }
    }

    return kwargs;
  }

  // 把模型原始响应转换成项目统一的 LlmResponse。
  // 如果模型输出不是合法 JSON，会返回 error，后续 PaperAnalyzer 会把它视为不相关。
  private parseResponse(response: ChatCompletionResponse, jsonMode: boolean): LlmResponse {
    const rawContent = response.choices?.[0]?.message?.content || '';

    if (jsonMode) {
      try {
        const parsedData = JSON.parse(rawContent) as Record<string, unknown>;
        return { model: this.model, data: parsedData, error: null, elapsed: 0 };
      } catch (error) {
        console.warn(`JSON 解析失败: ${(error as Error).message}`);
        return {
          model: this.model,
          data: null,
          error: `JSON 解析失败: ${(error as Error).message}`,
          elapsed: 0,
        };
      }
    }

    return { model: this.model, data: { content: rawContent }, error: null, elapsed: 0 };
  }

  // 判断某个错误是否值得重试。
  // 认证失败、参数错误通常重试也没用；限流/超时/服务端错误则值得重试。
  private shouldRetry(errorStr: string): boolean {
    const retryableErrors = [
      'rate limit',
      'timeout',
      '请求超时',
      'connection',
      '500',
      '502',
      '503',
      '504',
      'server error',
      'service unavailable',
    ];
    const errorLower = errorStr.toLowerCase();
    return retryableErrors.some(error => errorLower.includes(error));
  }

  // Workers 和浏览器一样没有 Python 那种 sleep 函数，所以用 Promise + setTimeout 实现。
  private sleep(seconds: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, seconds * 1000));
  }
}
