import {
  AnalysisResultsResponse,
  BackendApiError,
  ConfigResponse,
  EditableConfig,
  HealthResponse,
  RunResponse,
} from './models';

export interface BackendClientEnv {
  BACKEND_BASE_URL?: string;
  BACKEND_ADMIN_TOKEN?: string;
  ADMIN_TOKEN?: string;
}

function backendBaseUrl(env: BackendClientEnv): string {
  const baseUrl = env.BACKEND_BASE_URL?.trim();
  if (!baseUrl) {
    throw new Error('未配置后端地址 BACKEND_BASE_URL');
  }
  return baseUrl.endsWith('/') ? baseUrl : `${baseUrl}/`;
}

function backendAdminToken(env: BackendClientEnv): string {
  const token = env.BACKEND_ADMIN_TOKEN?.trim() || env.ADMIN_TOKEN?.trim();
  if (!token) {
    throw new Error('未配置后端访问令牌 BACKEND_ADMIN_TOKEN');
  }
  return token;
}

async function parseJsonBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) {
    return null;
  }

  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

function errorMessageFromBody(body: unknown, fallback: string): string {
  if (body && typeof body === 'object' && 'error' in body) {
    const error = (body as { error?: unknown }).error;
    if (typeof error === 'string' && error.trim()) {
      return error;
    }
  }

  if (body && typeof body === 'object' && 'message' in body) {
    const message = (body as { message?: unknown }).message;
    if (typeof message === 'string' && message.trim()) {
      return message;
    }
  }

  return fallback;
}

export class BackendClient {
  constructor(private readonly env: BackendClientEnv) {}

  async health(): Promise<HealthResponse> {
    return this.request<HealthResponse>('/health');
  }

  async config(): Promise<ConfigResponse> {
    return this.request<ConfigResponse>('/api/config');
  }

  async validateConfig(config: EditableConfig): Promise<ConfigResponse> {
    return this.request<ConfigResponse>('/api/config/validate', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
      },
      body: JSON.stringify(config),
    });
  }

  async saveConfig(config: EditableConfig): Promise<ConfigResponse> {
    return this.request<ConfigResponse>('/api/config', {
      method: 'PUT',
      headers: {
        'content-type': 'application/json',
      },
      body: JSON.stringify(config),
    });
  }

  async analysisResults(targetDate: string): Promise<AnalysisResultsResponse> {
    return this.request<AnalysisResultsResponse>(
      `/api/analysis-results?target_date=${encodeURIComponent(targetDate)}`,
    );
  }

  async run(options: { date?: string; sync?: boolean }): Promise<RunResponse> {
    const searchParams = new URLSearchParams();
    if (options.date) {
      searchParams.set('date', options.date);
    }
    if (options.sync) {
      searchParams.set('sync', 'true');
    }

    const query = searchParams.toString();
    return this.request<RunResponse>(`/run${query ? `?${query}` : ''}`, {
      method: 'POST',
    });
  }

  async proxy(request: Request, mappedPath: string): Promise<Response> {
    const backendUrl = new URL(mappedPath, backendBaseUrl(this.env));
    const incomingUrl = new URL(request.url);
    backendUrl.search = incomingUrl.search;

    const headers = new Headers(request.headers);
    headers.delete('cookie');
    headers.delete('host');
    headers.delete('cf-connecting-ip');
    headers.delete('cf-ipcountry');
    headers.delete('cf-ray');
    headers.set('authorization', `Bearer ${backendAdminToken(this.env)}`);

    const init: RequestInit = {
      method: request.method,
      headers,
      redirect: 'manual',
    };

    if (request.method !== 'GET' && request.method !== 'HEAD') {
      init.body = request.body;
    }

    return fetch(backendUrl, init);
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const url = new URL(path, backendBaseUrl(this.env));
    const headers = new Headers(init.headers);
    headers.set('authorization', `Bearer ${backendAdminToken(this.env)}`);

    const response = await fetch(url, {
      ...init,
      headers,
    });

    const body = await parseJsonBody(response);
    if (!response.ok) {
      throw new BackendApiError(
        errorMessageFromBody(body, `后端请求失败，HTTP 状态码 ${response.status}`),
        response.status,
        body,
      );
    }

    return body as T;
  }
}
