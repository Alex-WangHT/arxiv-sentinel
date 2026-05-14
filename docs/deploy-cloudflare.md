# Cloudflare 部署和线上测试

当前 PaperSniffer 线上只需要 **D1、KV、Queue** 三类 Cloudflare 资源，不需要 R2。

正式运行方式是：

```text
Cloudflare Cron Trigger
  -> scheduled()
  -> PAPER_ANALYSIS_QUEUE
  -> queue()
  -> Pipeline
  -> D1
```

也就是说，后台任务会按 `wrangler.toml` 里的 Cron 自动启动，不需要前端或 HTTP 请求启动。`POST /run` 只保留为管理员手动调试入口。

## 1. 登录 Cloudflare

```powershell
npx.cmd wrangler login
```

确认账号：

```powershell
npx.cmd wrangler whoami
```

## 2. 创建或确认 KV

如果还没有 KV namespace：

```powershell
npx.cmd wrangler kv namespace create CONFIG_KV --config backend/wrangler.toml
```

把输出里的 `id` 填到 [wrangler.toml](../backend/wrangler.toml)：

```toml
[[kv_namespaces]]
binding = "CONFIG_KV"
id = "你的_KV_ID"
```

## 3. 创建或确认 Queue

```powershell
npx.cmd wrangler queues create paper-sniffer-analysis --config backend/wrangler.toml
```

[wrangler.toml](../backend/wrangler.toml) 中应保留：

```toml
[[queues.producers]]
binding = "PAPER_ANALYSIS_QUEUE"
queue = "paper-sniffer-analysis"

[[queues.consumers]]
queue = "paper-sniffer-analysis"
max_batch_size = 1
max_batch_timeout = 30
```

## 4. 创建或确认 D1

如果还没有 D1 database：

```powershell
npx.cmd wrangler d1 create paper-sniffer-db --config backend/wrangler.toml
```

把输出里的 `database_id` 填到 [wrangler.toml](../backend/wrangler.toml)，绑定名必须是 `PAPER_DB`：

```toml
[[d1_databases]]
binding = "PAPER_DB"
database_name = "paper-sniffer-db"
database_id = "你的_D1_DATABASE_ID"
```

D1 表结构由 Worker 首次运行时自动创建，不需要单独执行 SQL migration。

## 5. 确认 Cron

[wrangler.toml](../backend/wrangler.toml) 里已经配置：

```toml
[triggers]
crons = ["0 1 * * *"]
```

Cloudflare Cron 使用 UTC 时间。这个配置表示每天 `01:00 UTC` 自动触发，也就是北京时间每天 `09:00`。

## 6. 配置线上 Secret

```powershell
npx.cmd wrangler secret put OPENAI_API_KEY --config backend/wrangler.toml
npx.cmd wrangler secret put ADMIN_TOKEN --config backend/wrangler.toml
```

`OPENAI_API_KEY` 不要写入 KV。`ADMIN_TOKEN` 用于保护配置管理接口和手动调试入口。

## 7. 本地检查

```powershell
npm.cmd run typecheck
npm.cmd run build
```

本地模拟 Cron：

```powershell
npm.cmd run dev:scheduled
```

然后访问：

```text
http://127.0.0.1:8787/__scheduled
```

这会触发 `scheduled()`，用于验证自动任务路径。它是本地模拟，不是线上启动方式。

## 8. 部署

```powershell
npm.cmd run deploy
```

部署成功后，Wrangler 会输出 Worker 地址，通常类似：

```text
https://paper-sniffer-backend.<你的账号>.workers.dev
```

下面示例用 `$BASE` 保存这个地址：

```powershell
$BASE = "https://paper-sniffer-backend.<你的账号>.workers.dev"
$TOKEN = "你的_ADMIN_TOKEN"
```

## 9. 线上配置测试

健康检查只验证 Worker 可访问，不会启动后台任务：

```powershell
Invoke-WebRequest "$BASE/health" -UseBasicParsing
```

读取当前配置：

```powershell
Invoke-WebRequest "$BASE/api/config" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -UseBasicParsing
```

校验配置：

```powershell
$body = @{
  keywords = @("large language model", "agent", "reasoning")
  domain_rules = @(
    @{
      category = "cs.RO"
      mode = "accept_all"
      filter_categories = @()
    },
    @{
      category = "cs.CV"
      mode = "categories_filter"
      filter_categories = @("cs.AI", "cs.CL", "cs.RO", "cs.LG")
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

Invoke-WebRequest "$BASE/api/config/validate" `
  -Method POST `
  -Headers @{
    Authorization = "Bearer $TOKEN"
    "Content-Type" = "application/json"
  } `
  -Body $body `
  -UseBasicParsing
```

保存配置到 KV：

```powershell
Invoke-WebRequest "$BASE/api/config" `
  -Method PUT `
  -Headers @{
    Authorization = "Bearer $TOKEN"
    "Content-Type" = "application/json"
  } `
  -Body $body `
  -UseBasicParsing
```

## 10. 线上自动任务验证

部署后，等待下一个 Cron 时间点。当前配置会在北京时间每天 `09:00` 自动触发。

查看线上日志：

```powershell
npm.cmd run tail
```

日志中应该能看到：

```text
Scheduled run triggered by cron: 0 1 * * *
Scheduled run enqueued
```

任务完成后，可以查 D1：

```powershell
npx.cmd wrangler d1 execute paper-sniffer-db `
  --remote `
  --config backend/wrangler.toml `
  --command "SELECT target_date, COUNT(*) AS count FROM analysis_results GROUP BY target_date ORDER BY target_date DESC LIMIT 5;"
```

如果 Queue 没有绑定，日志会显示 `PAPER_ANALYSIS_QUEUE 未绑定`，然后 Worker 会直接在 `scheduled()` 里执行 Pipeline。线上建议绑定 Queue。

## 11. 管理员手动调试

这个接口不是正式启动方式，只用于你临时验证 Pipeline：

```powershell
Invoke-WebRequest "$BASE/run?sync=true&date=2026-05-12" `
  -Method POST `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -UseBasicParsing
```

不带 `ADMIN_TOKEN` 会返回 `401`。普通 `GET /run` 不会启动任务。

## 12. 常见错误

`Queue "paper-sniffer-analysis" does not exist`:

```powershell
npx.cmd wrangler queues create paper-sniffer-analysis --config backend/wrangler.toml
```

`未绑定 PAPER_DB D1，分析结果不会持久化`:

检查 [wrangler.toml](../backend/wrangler.toml) 是否已经配置 `[[d1_databases]]`，并且 `binding = "PAPER_DB"`。

`CONFIG_KV 中没有找到配置`:

这是正常兜底行为。第一次部署后，通过 `PUT /api/config` 保存配置即可。
