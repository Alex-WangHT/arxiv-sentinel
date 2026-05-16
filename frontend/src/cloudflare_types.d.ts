/*
 * Minimal Cloudflare Workers declarations used by the frontend Worker.
 * They keep the project dependency-free while still giving TypeScript the
 * runtime shapes that are not part of the standard WebWorker lib.
 */

interface ExecutionContext {
  waitUntil(promise: Promise<unknown>): void;
  passThroughOnException(): void;
}
