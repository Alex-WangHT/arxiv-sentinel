# 配置管理 API

这些接口用于未来前端读取、校验和保存 PaperSniffer 配置。配置保存到 `CONFIG_KV`，默认 key 为 `paper-sniffer/config`，可通过 `CONFIG_KV_KEY` 覆盖。

项目不再通过仓库外层的 `config.json` 文件配置。配置来源收敛为：

- 本地开发：`backend/.dev.vars`
- 线上密钥：Cloudflare Secrets
- 前端动态配置：`CONFIG_KV`，通过本 API 读写

`openai_api_key` 不属于前端配置项，接口会拒绝把它保存到 KV。API Key 仍通过 `.dev.vars` 或 Cloudflare Secret 注入。

运行时优先级：

- 如果 `CONFIG_KV` 中存在配置，KV 是前端配置的权威来源，环境变量只继续注入 `OPENAI_API_KEY`
- 如果 KV 中没有配置，后端使用 env / `.dev.vars` 中的配置
- 如果 env 中也没有配置，后端使用内置默认配置兜底

## 鉴权

配置管理接口需要 `ADMIN_TOKEN`。

请求头二选一：

```http
Authorization: Bearer <ADMIN_TOKEN>
```

```http
X-Admin-Token: <ADMIN_TOKEN>
```

本地开发可在 `backend/.dev.vars` 中配置：

```text
ADMIN_TOKEN=local-dev-token
```

线上使用：

```powershell
npx.cmd wrangler secret put ADMIN_TOKEN --config backend/wrangler.toml
```

## 配置对象

请求体是一个 JSON object。推荐字段如下：

```json
{
  "keywords": ["large language model", "agent", "reasoning"],
  "domain_rules": [
    {
      "category": "cs.RO",
      "mode": "accept_all",
      "filter_categories": []
    },
    {
      "category": "cs.CV",
      "mode": "categories_filter",
      "filter_categories": ["cs.AI", "cs.CL", "cs.RO", "cs.LG"]
    }
  ],
  "relevance_threshold": "MEDIUM",
  "openai_model": "deepseek-v4-flash",
  "openai_base_url": "https://api.deepseek.com/v1",
  "max_results_per_category": 5,
  "max_concurrent_requests": 3,
  "output_dir": "output",
  "prompts_dir": "prompts",
  "log_level": "INFO",
  "history_file": "history.json",
  "prompt_system": "可选",
  "prompt_user_template": "可选"
}
```

校验规则沿用后端 `Config`：

- `keywords` 至少 1 项
- `domain_rules` 至少 1 项
- `domain_rules[].mode` 只能是 `accept_all` 或 `categories_filter`
- `categories_filter` 模式下 `filter_categories` 至少 1 项
- `relevance_threshold` 只能是 `IRRELEVANT`、`LOW`、`MEDIUM`、`HIGH`
- `max_results_per_category` 范围是 `1-200`
- `max_concurrent_requests` 范围是 `1-50`
- `openai_model` 必填

## GET /api/config

读取当前前端可编辑配置，并返回后端最终生效配置。

```powershell
Invoke-WebRequest "http://127.0.0.1:8787/api/config" `
  -Headers @{ Authorization = "Bearer local-dev-token" } `
  -UseBasicParsing
```

响应：

```json
{
  "ok": true,
  "key": "paper-sniffer/config",
  "source": "kv",
  "config": {},
  "effective_config": {}
}
```

字段说明：

- `key`: 当前使用的 KV key
- `source`: 配置来源，可能是 `kv`、`env`、`default`
- `config`: 前端可编辑并可保存的配置，不包含 `openai_api_key`
- `effective_config`: 后端合并 secret 后实际使用的配置，`openai_api_key` 会显示为 `***`

## POST /api/config/validate

只校验配置，不保存。适合前端保存前做预检。

```powershell
$body = @{
  keywords = @("large language model", "agent", "reasoning")
  domain_rules = @(
    @{
      category = "cs.RO"
      mode = "accept_all"
      filter_categories = @()
    }
  )
  relevance_threshold = "MEDIUM"
  openai_model = "deepseek-v4-flash"
  openai_base_url = "https://api.deepseek.com/v1"
  max_results_per_category = 5
  max_concurrent_requests = 3
  output_dir = "output"
  prompts_dir = "prompts"
  log_level = "INFO"
  history_file = "history.json"
} | ConvertTo-Json -Depth 20

Invoke-WebRequest "http://127.0.0.1:8787/api/config/validate" `
  -Method POST `
  -Headers @{
    Authorization = "Bearer local-dev-token"
    "Content-Type" = "application/json"
  } `
  -Body $body `
  -UseBasicParsing
```

成功响应：

```json
{
  "ok": true,
  "config": {},
  "effective_config": {}
}
```

## PUT /api/config

校验并保存配置到 `CONFIG_KV`。

```powershell
Invoke-WebRequest "http://127.0.0.1:8787/api/config" `
  -Method PUT `
  -Headers @{
    Authorization = "Bearer local-dev-token"
    "Content-Type" = "application/json"
  } `
  -Body $body `
  -UseBasicParsing
```

成功响应：

```json
{
  "ok": true,
  "key": "paper-sniffer/config",
  "source": "kv",
  "config": {},
  "effective_config": {}
}
```

保存行为：

- 保存前会校验完整配置
- 保存时会删除 `openai_api_key`
- 保存目标是 `CONFIG_KV`
- 如果未绑定 `CONFIG_KV`，返回 `503`

## 错误响应

未配置 `ADMIN_TOKEN`：

```json
{
  "ok": false,
  "error": "ADMIN_TOKEN 未配置，管理接口已禁用"
}
```

Token 错误：

```json
{
  "ok": false,
  "error": "未授权"
}
```

配置校验失败：

```json
{
  "ok": false,
  "error": "配置校验失败:\n  - keywords: 必填，且至少包含 1 项"
}
```

## 前端调用示例

```ts
async function loadConfig(token: string) {
  const response = await fetch('/api/config', {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
  if (!response.ok) {
    throw new Error((await response.json()).error);
  }
  return response.json();
}

async function saveConfig(token: string, config: unknown) {
  const response = await fetch('/api/config', {
    method: 'PUT',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(config),
  });
  if (!response.ok) {
    throw new Error((await response.json()).error);
  }
  return response.json();
}
```
