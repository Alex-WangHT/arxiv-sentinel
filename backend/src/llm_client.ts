import OpenAI from 'openai';
import { LlmResponse } from './models';

const DEFAULT_MAX_RETRIES = 2;
const DEFAULT_RETRY_BASE = 3;
const DEFAULT_RETRY_JITTER = 0.5;
const DEFAULT_TEMPERATURE = 0.1;
const DEFAULT_TIMEOUT = 120;
const DEFAULT_CONNECTIONS = 3;
const DEFAULT_REQUEST_INTERVAL = 0.5;

export class LlmClient {
  private client: OpenAI.AsyncOpenAI;
  private model: string;
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
    this.client = new OpenAI({
      apiKey,
      baseURL: baseUrl,
      timeout: timeout * 1000,
      maxRetries: 0,
    });

    this.model = model;
    this.maxRetries = maxRetries;
    this.retryBase = retryBase;
    this.connections = connections;
    this.timeout = timeout;
  }

  private calculateRetryDelay(attempt: number): number {
    const baseDelay = Math.pow(this.retryBase, attempt);
    const jitter = (Math.random() - 0.5) * 2 * DEFAULT_RETRY_JITTER * baseDelay;
    return Math.max(2.0, baseDelay + jitter);
  }

  private buildKwargs(
    messages: Array<{ role: string; content: string }>,
    temperature: number,
    jsonMode: boolean,
  ): Record<string, unknown> {
    const kwargs: Record<string, unknown> = {
      model: this.model,
      messages: [...messages],
      temperature,
    };

    if (jsonMode) {
      kwargs.response_format = { type: 'json_object' };
      const jsonPrompt = '请以JSON格式输出你的回答。';
      if (kwargs.messages.length > 0 && kwargs.messages[0].role === 'system') {
        kwargs.messages[0].content = jsonPrompt + kwargs.messages[0].content;
      } else {
        kwargs.messages.unshift({ role: 'system', content: jsonPrompt });
      }
    }

    return kwargs;
  }

  private parseResponse(response: OpenAI.Chat.Completions.ChatCompletion, jsonMode: boolean): LlmResponse {
    const rawContent = response.choices[0]?.message.content || '';

    if (jsonMode) {
      try {
        const parsedData = JSON.parse(rawContent);
        return { model: this.model, data: parsedData, error: null, elapsed: 0 };
      } catch (e) {
        console.warn(`JSON 解析失败: ${(e as Error).message}`);
        return { model: this.model, data: null, error: `JSON 解析失败: ${(e as Error).message}`, elapsed: 0 };
      }
    }

    return { model: this.model, data: { content: rawContent }, error: null, elapsed: 0 };
  }

  private shouldRetry(errorStr: string): boolean {
    const retryableErrors = [
      'rate limit',
      'timeout',
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

  async achat(
    messages: Array<{ role: string; content: string }>,
    temperature: number = DEFAULT_TEMPERATURE,
    jsonMode: boolean = true,
    requestId: string = '',
  ): Promise<LlmResponse> {
    const startTime = Date.now();
    const kwargs = this.buildKwargs(messages, temperature, jsonMode);
    const requestLabel = requestId ? `请求${requestId}` : '请求';

    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      try {
        const attemptStart = Date.now();
        console.debug(`${requestLabel} 第 ${attempt + 1} 次调用开始`);

        const response = await Promise.race([
          this.client.chat.completions.create(kwargs),
          new Promise<never>((_, reject) =>
            setTimeout(() => reject(new Error('请求超时')), this.timeout * 1000),
          ),
        ]);

        const elapsed = (Date.now() - attemptStart) / 1000;
        console.debug(`${requestLabel} 第 ${attempt + 1} 次调用成功，耗时 ${elapsed.toFixed(2)} 秒`);

        const totalElapsed = (Date.now() - startTime) / 1000;
        const result = this.parseResponse(response, jsonMode);
        result.elapsed = totalElapsed;
        console.debug(`${requestLabel} 完成，总耗时 ${totalElapsed.toFixed(2)} 秒`);
        return result;

      } catch (e) {
        const elapsed = (Date.now() - startTime) / 1000;
        const errorStr = String(e);

        if (attempt < this.maxRetries && this.shouldRetry(errorStr)) {
          const waitTime = this.calculateRetryDelay(attempt);
          console.warn(`${requestLabel} 第 ${attempt + 1} 次失败（${elapsed.toFixed(2)}秒），等待 ${waitTime.toFixed(2)} 秒后重试: ${errorStr.slice(0, 50)}`);
          await new Promise(resolve => setTimeout(resolve, waitTime * 1000));
        } else {
          console.error(`${requestLabel} 失败（已重试 ${attempt} 次，耗时 ${elapsed.toFixed(2)} 秒）: ${errorStr.slice(0, 100)}`);
          return {
            model: this.model,
            data: null,
            error: `API 调用失败（重试 ${attempt} 次，耗时 ${elapsed.toFixed(2)} 秒）: ${errorStr.slice(0, 100)}`,
            elapsed,
          };
        }
      }
    }

    const totalElapsed = (Date.now() - startTime) / 1000;
    return { model: this.model, data: null, error: '未知错误', elapsed: totalElapsed };
  }

  async batchAchat(
    messagesList: Array<Array<{ role: string; content: string }>>,
    temperature: number = DEFAULT_TEMPERATURE,
    jsonMode: boolean = true,
    requestInterval: number = DEFAULT_REQUEST_INTERVAL,
    queueInterval: number = 20.0,
  ): Promise<LlmResponse[]> {
    const totalCount = messagesList.length;
    const queueSize = this.connections >= 1 ? this.connections : 3;

    const queues: Array<{ index: number; messages: Array<Array<{ role: string; content: string }>> }> = [];
    for (let i = 0; i < queueSize; i++) {
      const queue = messagesList.filter((_, idx) => idx % queueSize === i);
      if (queue.length > 0) {
        queues.push({ index: i, messages: queue });
      }
    }

    console.info(`开始多队列并行处理 ${totalCount} 个请求`);
    console.info(`队列数: ${queues.length}, 队列大小: ${queueSize}, 队列间隔: ${queueInterval}秒, 请求间隔: ${requestInterval}秒`);

    const results = new Array<LlmResponse>(totalCount);
    let completedCount = 0;

    const processQueue = async (queueIndex: number, queueMessages: Array<Array<{ role: string; content: string }>>) => {
      const queueTotal = queueMessages.length;

      for (let j = 0; j < queueTotal; j++) {
        const originalIndex = queueIndex + j * queueSize;
        const messages = queueMessages[j];
        const requestId = `Q${queueIndex + 1}-${j + 1}/${queueTotal}`;

        try {
          const result = await this.achat(messages, temperature, jsonMode, requestId);
          results[originalIndex] = result;

          completedCount++;
          const progress = (completedCount / totalCount) * 100;
          console.info(`请求${requestId} 完成，进度: ${progress.toFixed(1)}% (${completedCount}/${totalCount})`);

        } catch (e) {
          console.error(`请求${requestId} 异常: ${(e as Error).message}`);
          results[originalIndex] = {
            model: this.model,
            data: null,
            error: `请求异常: ${(e as Error).message}`,
            elapsed: 0,
          };
        }

        if (j < queueTotal - 1) {
          await new Promise(resolve => setTimeout(resolve, requestInterval * 1000));
        }
      }
    };

    const queueTasks: Promise<void>[] = [];
    for (let i = 0; i < queues.length; i++) {
      const { index, messages } = queues[i];
      console.info(`启动队列 #${i + 1}/${queues.length}`);
      queueTasks.push(processQueue(index, messages));

      if (i < queues.length - 1) {
        await new Promise(resolve => setTimeout(resolve, queueInterval * 1000));
      }
    }

    await Promise.all(queueTasks);
    console.info(`批量调用完成，共 ${completedCount}/${totalCount} 个请求成功`);
    return results;
  }
}

if (require.main === module) {
  const runTests = async () => {
    const cfg = require('./config').Config.fromFile();
    const llm = new LlmClient(
      cfg.openai_api_key,
      cfg.openai_model,
      cfg.openai_base_url,
    );

    const testMessages = [{
      role: 'user',
      content: '{"task": "介绍一下你自己", "language": "Chinese"}',
    }];

    const result = await llm.achat({ messages: testMessages });
    console.log(`模型: ${result.model}`);
    console.log(`数据: ${JSON.stringify(result.data)}`);
    console.log(`错误: ${result.error}`);
    console.log(`耗时: ${result.elapsed.toFixed(2)}秒`);

    const batchMessages = Array.from({ length: 3 }, (_, i) => [{
      role: 'user',
      content: `{"task": "用一句话描述问题${i}", "language": "Chinese"}`,
    }]);

    console.log('\n=== 队列模式 ===');
    const results = await llm.batchAchat(batchMessages, 0.5);
    for (let i = 0; i < results.length; i++) {
      console.log(`请求${i + 1}: 耗时=${results[i].elapsed.toFixed(2)}s, 数据=${JSON.stringify(results[i].data)}`);
    }
  };

  runTests().catch(console.error);
}