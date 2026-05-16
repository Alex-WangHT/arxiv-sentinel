/*
 * 这个文件只放 Cloudflare Workers 的最小类型声明。
 *
 * 正常项目也可以安装 @cloudflare/workers-types 获得完整类型。
 * 这里先手写最小声明，是为了让当前代码在 TypeScript 编译时知道：
 * - KVNamespace 是什么
 * - Queue 是什么
 * - D1Database 是什么
 * - MessageBatch 是什么
 * - ScheduledController 是什么
 *
 * 注意：这些 interface 只是“类型提示”，不会变成运行时代码。
 */

interface KVNamespace {
  get(key: string): Promise<string | null>;
  put(
    key: string,
    value: string,
    options?: {
      expiration?: number;
      expirationTtl?: number;
      metadata?: Record<string, unknown>;
    },
  ): Promise<void>;
}

interface D1Result<T = unknown> {
  results?: T[];
  success: boolean;
  error?: string;
}

interface D1PreparedStatement {
  bind(...values: unknown[]): D1PreparedStatement;
  first<T = unknown>(): Promise<T | null>;
  all<T = unknown>(): Promise<D1Result<T>>;
  run<T = unknown>(): Promise<D1Result<T>>;
}

interface D1Database {
  prepare(query: string): D1PreparedStatement;
  exec(query: string): Promise<D1Result>;
  batch<T = unknown>(statements: D1PreparedStatement[]): Promise<D1Result<T>[]>;
}

interface Queue<T = unknown> {
  send(message: T): Promise<void>;
}

interface Message<T = unknown> {
  body: T;
  ack(): void;
  retry(options?: { delaySeconds?: number }): void;
}

interface MessageBatch<T = unknown> {
  queue: string;
  messages: Message<T>[];
}

interface ExecutionContext {
  waitUntil(promise: Promise<unknown>): void;
  passThroughOnException(): void;
}

interface ScheduledController {
  scheduledTime: number;
  cron: string;
  noRetry(): void;
}
