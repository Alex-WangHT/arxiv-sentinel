type LogLevel = 'debug' | 'info' | 'warn' | 'error';

type LogScalar = string | number | boolean | null | undefined;
type LogFieldValue = LogScalar | LogFields | LogFieldValue[];
interface LogFields {
  [key: string]: LogFieldValue;
}

const SERVICE_NAME = 'paper-sniffer-backend';
const MAX_STRING_LENGTH = 2000;

let installed = false;

const nativeConsole = {
  debug: console.debug.bind(console),
  info: console.info.bind(console),
  warn: console.warn.bind(console),
  error: console.error.bind(console),
};

function truncate(value: string): string {
  if (value.length <= MAX_STRING_LENGTH) {
    return value;
  }
  return `${value.slice(0, MAX_STRING_LENGTH)}...`;
}

function errorToFields(error: Error): LogFields {
  return {
    name: error.name,
    message: truncate(error.message),
    stack: error.stack ? truncate(error.stack) : undefined,
  };
}

function normalizeValue(value: unknown): LogFieldValue {
  if (value === null || value === undefined) {
    return value;
  }

  if (value instanceof Error) {
    return errorToFields(value);
  }

  if (typeof value === 'string') {
    return truncate(value);
  }

  if (typeof value === 'number' || typeof value === 'boolean') {
    return value;
  }

  if (Array.isArray(value)) {
    return value.map(item => normalizeValue(item));
  }

  if (typeof value === 'object') {
    const result: LogFields = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      result[key] = normalizeValue(item);
    }
    return result;
  }

  return truncate(String(value));
}

function messageFromArgs(args: unknown[]): string {
  const firstString = args.find(arg => typeof arg === 'string') as string | undefined;
  if (firstString) {
    return truncate(firstString);
  }

  const firstError = args.find(arg => arg instanceof Error) as Error | undefined;
  if (firstError) {
    return truncate(firstError.message);
  }

  return 'backend log';
}

function emit(level: LogLevel, args: unknown[]): void {
  const record = {
    timestamp: new Date().toISOString(),
    service: SERVICE_NAME,
    runtime: 'cloudflare-workers',
    event: 'backend.console',
    level,
    message: messageFromArgs(args),
    fields: args.map(arg => normalizeValue(arg)),
  };

  nativeConsole[level](record);
}

export function installStructuredConsoleLogger(): void {
  if (installed) {
    return;
  }
  installed = true;

  console.debug = (...args: unknown[]) => emit('debug', args);
  console.info = (...args: unknown[]) => emit('info', args);
  console.warn = (...args: unknown[]) => emit('warn', args);
  console.error = (...args: unknown[]) => emit('error', args);
  console.log = (...args: unknown[]) => emit('info', args);
}
