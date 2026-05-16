# PaperSniffer HTTP API

本文档描述 Cloudflare Worker 入口（`backend/src/worker.ts`）对外提供的 **HTTP 接口**。响应体均为 **JSON**（`Content-Type: application/json; charset=utf-8`），并带有 **CORS** 头（`Access-Control-Allow-Origin: *` 等），便于浏览器或本地脚本调用。

**本地开发**：先把 `OPENAI_API_KEY`、`ADMIN_TOKEN` 等变量传入 shell 环境，再运行 `bash script/deploy.sh local` / `npm run deploy:local`；脚本会从这些变量生成 `script/config/.dev.vars` 并同步到 `backend/.dev.vars`。默认基址为 `http://127.0.0.1:8787`（以终端输出为准）。

**线上**：部署后的 `*.workers.dev` 或自定义域名，路径与本地一致。

---

## 鉴权（除 OPTIONS 外）

下列接口须携带 **`Authorization: Bearer <ADMIN_TOKEN>`**，且令牌须与环境变量 **`ADMIN_TOKEN`** 完全一致，否则 **401**；未配置 **`ADMIN_TOKEN`** 时 **503**。

```http
Authorization: Bearer <ADMIN_TOKEN>
```

本地必须通过 shell 环境变量传入；`bash script/deploy.sh local` 会据此生成 `.dev.vars` 供 wrangler 读取。

```text
ADMIN_TOKEN=local-dev-token
```

线上建议（密钥名与生成的 `.dev.vars` 中一致）：

```powershell
npx.cmd wrangler secret put ADMIN_TOKEN --config backend/wrangler.toml
```

或先设置 shell 环境变量，再使用 `npm run deploy:cloud`（内部为 `bash script/deploy.sh cloud`，会生成 `.dev.vars` 并上传 secrets）。

---

## OPTIONS

任意路径的 **OPTIONS** 请求用于 CORS 预检，返回 `200`，正文为 `{"ok": true}`，**不要求** `ADMIN_TOKEN`。允许的自定义头包括 `content-type`、`authorization`。

---

## 配置来源与 KV

配置相关接口用于读取、校验和保存 PaperSniffer 运行参数。可编辑配置保存到 **`CONFIG_KV`**，默认 key 为 **`paper-sniffer/config`**，可通过环境变量 **`CONFIG_KV_KEY`** 覆盖。

项目不再通过仓库外层的 `config.json` 文件配置。配置来源收敛为：

- 本地开发：`script/config/.dev.vars`（由 `script/deploy.sh` 从 shell 环境变量生成，并同步到 `backend/.dev.vars`）
- 线上密钥：Cloudflare Secrets
- 前端动态配置：`CONFIG_KV`，通过 `GET` / `PUT /api/config` 读写

**`openai_api_key`** 不属于可写入 KV 的前端配置项；保存时会被剥离。运行时仍通过 **`OPENAI_API_KEY`**（`.dev.vars` 或 Cloudflare Secret）注入。

**运行时优先级**：

1. 若 **`CONFIG_KV`** 中已有配置，KV 为可编辑配置的权威来源；环境变量主要继续提供 **`OPENAI_API_KEY`**。
2. 若 KV 中没有配置，使用 env / `.dev.vars` 中的项。
3. 若 env 中也没有可用项，使用内置默认配置兜底。

---

## 配置 JSON 与校验规则

请求体（`PUT /api/config`、`POST /api/config/validate`）是一个 JSON object。推荐字段如下：

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

校验规则沿用后端 **`Config`**：

- `keywords` 至少 1 项
- `domain_rules` 至少 1 项
- `domain_rules[].mode` 只能是 `accept_all` 或 `categories_filter`
- `categories_filter` 模式下 `filter_categories` 至少 1 项
- `relevance_threshold` 只能是 `IRRELEVANT`、`LOW`、`MEDIUM`、`HIGH`
- `max_results_per_category` 范围是 `1-200`
- `max_concurrent_requests` 范围是 `1-50`
- `openai_model` 必填

---

## 接口一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 存活检查 |
| GET | `/config` | 当前生效配置的脱敏快照（单对象） |
| GET | `/api/analysis-results` | 按 `target_date` 读取某日全部 D1 分析结果（必填查询参数） |
| GET | `/api/config` | 读取 KV / env / 默认 来源的配置及合并后的生效配置 |
| PUT | `/api/config` | 校验并写入 `CONFIG_KV` |
| POST | `/api/config/validate` | 仅校验配置，不写 KV |
| POST | `/run` | 手动触发一次分析流水线（异步入队或同步执行） |

未列出的路径返回 **404**，正文含已知路由列表；当前实现下 **404 不要求鉴权**。

---

## GET /health

**用途**：确认 Worker 已部署且可响应；须携带 `Authorization: Bearer <ADMIN_TOKEN>`（例如探活脚本与线上其它接口使用同一请求头）。

**成功 `200`**：

```json
{
  "ok": true,
  "service": "PaperSniffer",
  "runtime": "cloudflare-workers"
}
```

---

## GET /config

**用途**：调试时快速查看**当前合并后**的运行时配置；敏感字段 `openai_api_key` 在 JSON 中为掩码 `***` 或空字符串（与 `Config.toSafeJSON()` 一致）。

**成功 `200`**：返回单个配置对象（结构与 `GET /api/config` 响应中的 `effective_config` 类似，为扁平对象，无外层 `ok` / `key` / `source` 包装）。

---

## GET /api/analysis-results

**用途**：前端或其它客户端通过 Worker **只读**查询持久化在 D1 表 **`analysis_results`** 中、某一运行日的全部分析结果（不直连数据库）。数据由 `Pipeline` 经 `PipelineStorage#saveResults` 写入；本接口在 Worker 内调用 `PipelineStorage#listAnalysisResults`（见 `backend/src/pipeline.ts`）。

**查询参数**（**必填**）：

| 参数 | 说明 |
|------|------|
| `target_date` | **`YYYY-MM-DD`**，仅返回该日期的所有行；**不可省略** |

不支持 `limit`、`offset`；该日期的结果一次性全部返回。

排序：按 `updated_at` 降序。

**成功 `200`**：

```json
{
  "ok": true,
  "results": []
}
```

- **`results`**：行数组，元素类型为 `AnalysisResultRecord`（在 `SerializedAnalysisResult` 基础上含 `id`、`target_date`、`created_at`、`updated_at`）；`authors`、`categories`、`keywords` 已为解析后的字符串数组。

未绑定 **`PAPER_DB`** 时表不可用，返回 **`results`: []**。

**其它**：非 GET 返回 **405**；缺少 `target_date`、或 `target_date` 非法时返回 **400**。

**PowerShell 示例（本地）**：

```powershell
Invoke-WebRequest "http://127.0.0.1:8787/api/analysis-results?target_date=2026-05-12" `
  -Headers @{ Authorization = "Bearer local-dev-token" } `
  -UseBasicParsing
```

---

## GET /api/config

**用途**：读取「可持久化到 KV 的配置」与「实际运行使用的配置」。

**成功 `200`**：

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

- **`key`**：当前使用的 KV key（默认 `paper-sniffer/config`，可由 `CONFIG_KV_KEY` 覆盖）。
- **`source`**：`kv`（KV 中有配置）｜`env`（无 KV 配置但环境变量有项）｜`default`（使用内置默认）。
- **`config`**：不含 `openai_api_key` 的可编辑配置快照。
- **`effective_config`**：合并 Secret 后的生效配置，`openai_api_key` 显示为 `***`。

**PowerShell 示例（本地）**：

```powershell
Invoke-WebRequest "http://127.0.0.1:8787/api/config" `
  -Headers @{ Authorization = "Bearer local-dev-token" } `
  -UseBasicParsing
```

---

## POST /api/config/validate

**用途**：只校验配置，**不写入** KV。适合前端保存前预检。校验时使用环境中的 `OPENAI_API_KEY` 构造临时 `Config`；若未设置，则使用占位值完成结构校验。

**成功 `200`**：

```json
{
  "ok": true,
  "config": {},
  "effective_config": {}
}
```

**其它**：HTTP 方法非 POST 时返回 **405**。

**PowerShell 示例（本地）**：

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

---

## PUT /api/config

**用途**：校验请求体 JSON，通过校验后写入 **`CONFIG_KV`**。请求体不得包含可保存的明文 `openai_api_key`（保存前会被剥离）；运行时密钥仍来自 **`OPENAI_API_KEY`**。

**前置条件**：Worker 必须绑定 **`CONFIG_KV`**，否则 **503**。

**成功 `200`**：与 `GET /api/config` 成功体结构相同（写入后 `source` 为 `kv`）。

**保存行为**：

- 保存前会校验完整配置
- 保存时会删除 `openai_api_key`
- 保存目标是 `CONFIG_KV`
- 未绑定 `CONFIG_KV` 时返回 **503**

**其它**：HTTP 方法非 GET/PUT 时返回 **405**。

**PowerShell 示例（本地）**：（`$body` 与上一节 `POST /api/config/validate` 相同）

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

---

## POST /run

**用途**：管理员**手动**触发一次完整分析流水线。线上常规调度由 **Cron**（`wrangler.toml` 中 `[triggers].crons`）和/或 **Queue** 消费完成，不依赖本接口。

### 查询参数与 JSON 体（均可选）

- **`date`**（查询）或 **`date` / `targetDate`**（JSON 字符串）：目标日期，**必须为 `YYYY-MM-DD`**（UTC 日历日）。不传则由流水线按默认逻辑选日。
- **`sync`**（查询 `sync=true`）或 JSON **`sync`: true**：为真时**在当前 HTTP 请求内同步执行**完整 `Pipeline.run`；否则优先尝试将任务写入 **`PAPER_ANALYSIS_QUEUE`**。

仅当 `Content-Type` 包含 `application/json` 时才会解析 body；否则视为无 JSON 体。

### 异步（默认，且已绑定 Queue）

**202 Accepted**：

```json
{
  "ok": true,
  "queued": true,
  "mode": "manual",
  "targetDate": "2026-05-16"
}
```

`targetDate` 为解析后的日期字符串；未指定日期时可能为表示自动选择的 `"auto"`（见实现中的 `formatDate(targetDate) || 'auto'`）。

### 同步或未绑定 Queue

在当前请求中执行完毕，**200 OK**：

```json
{
  "ok": true,
  "queued": false,
  "mode": "manual",
  "result": {
    "date": "2026-05-16",
    "total_fetched": 0,
    "total_filtered": 0,
    "results": []
  }
}
```

`result` 为 **`PipelineResult`**：`date`、`total_fetched`、`total_filtered`、`results`（`AnalysisResult[]`，含 `paper`、`score`、`reason` 等）。具体字段定义见 `backend/src/models.ts`。

**其它**：非 POST 返回 **405**。

---

## 错误与 HTTP 状态码

| 状态码 | 常见原因 |
|--------|----------|
| **400** | 缺少 `target_date`，或 `target_date` 不是合法 `YYYY-MM-DD` |
| **401** | `ADMIN_TOKEN` 已配置，但请求未携带或令牌不匹配 |
| **404** | 路径不存在 |
| **405** | HTTP 方法不允许（如 `GET /run`） |
| **500** | 未捕获异常，`error` 为错误消息字符串 |
| **503** | 未配置 `ADMIN_TOKEN`；或 `PUT /api/config` 时未绑定 `CONFIG_KV` |

统一错误 JSON 示例：

```json
{
  "ok": false,
  "error": "未授权"
}
```

未配置 `ADMIN_TOKEN`：

```json
{
  "ok": false,
  "error": "ADMIN_TOKEN 未配置，管理接口已禁用"
}
```

配置校验失败时，`error` 可能为多行说明，例如：

```json
{
  "ok": false,
  "error": "配置校验失败:\n  - keywords: 必填，且至少包含 1 项"
}
```

---

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

---

## 非 HTTP 触发（无 ADMIN_TOKEN）

以下由 Cloudflare 平台调用，**不属于**上述 HTTP API：

- **`scheduled`**：Cron 触发，向 Queue 投递或直接执行 `runPipeline`。
- **`queue`**：消费 `PAPER_ANALYSIS_QUEUE` 中的消息并执行 `runPipeline`。

---

## 相关文档

- Worker 绑定、路由与本地调试：[WORKERS_ADAPTATION_NOTES.md](./WORKERS_ADAPTATION_NOTES.md)
- 部署与线上 Secret、示例命令：[deploy-cloudflare.md](./deploy-cloudflare.md)
- 本地/云端部署与自动化测试：`script/deploy.sh`、`script/test.sh`；密钥与 `script/config/.dev.vars`（模板见 `script/config/.dev.vars.example`）变量名一致。
