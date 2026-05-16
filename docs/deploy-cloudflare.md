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

HTTP 接口的完整说明见 [api.md](./api.md)。

## 1. 一键云端部署

`backend/script/deploy.sh cloud` 已经包含本文档原来的 Cloudflare 部署流程。它不读取现成 `.dev.vars`，必须从 shell 环境变量生成。

PowerShell：

```powershell
$env:OPENAI_API_KEY = "sk-your-real-key"
$env:ADMIN_TOKEN = "your-admin-token"
npm.cmd run deploy:cloud
```

Git Bash：

```bash
OPENAI_API_KEY=sk-your-real-key ADMIN_TOKEN=your-admin-token bash backend/script/deploy.sh cloud
```

## 2. Cloud 分支会执行什么

`deploy.sh cloud` 会按顺序执行：

1. 校验 `OPENAI_API_KEY`、`ADMIN_TOKEN` 必须来自 shell 环境变量。
2. 生成 `backend/script/config/.dev.vars`。
3. 运行 `npm run typecheck` 和 `npm run build`。
4. 检查 Cloudflare 登录状态；未登录时启动 `wrangler login`。
5. 确认 KV namespace `CONFIG_KV`；如果 `wrangler.toml` 里没有有效 `id`，创建并自动更新配置。
6. 确认 Queue `paper-sniffer-analysis`；不存在则创建。
7. 确认 D1 database `paper-sniffer-db`；如果 `wrangler.toml` 里没有有效 `database_id`，创建并自动更新配置。
8. 确认 Cron 配置为 `0 1 * * *`，即北京时间每天 `09:00`。
9. 使用生成的 `.dev.vars` 作为 `--secrets-file` 执行 `wrangler deploy`。
10. 部署成功后尽量从 Wrangler 输出中解析 Worker URL，并运行云端 API smoke test。
11. 查询远端 D1 分析结果摘要；首次运行前表可能还没创建，此步骤失败不会中断部署。

如果使用自定义域名，或 Wrangler 输出中没有解析到 URL，可以显式传入：

```powershell
$env:BASE_URL = "https://your-domain.example.com"
npm.cmd run deploy:cloud
```

## 3. Wrangler 配置要求

[wrangler.toml](../backend/wrangler.toml) 中应保留这些绑定名：

```toml
[[kv_namespaces]]
binding = "CONFIG_KV"

[[d1_databases]]
binding = "PAPER_DB"
database_name = "paper-sniffer-db"

[[queues.producers]]
binding = "PAPER_ANALYSIS_QUEUE"
queue = "paper-sniffer-analysis"

[[queues.consumers]]
queue = "paper-sniffer-analysis"
max_batch_size = 1
max_batch_timeout = 30

[triggers]
crons = ["0 1 * * *"]
```

如果 KV 的 `id` 或 D1 的 `database_id` 为空/占位，`deploy.sh cloud` 会调用 Wrangler 创建资源并使用 `--update-config` 写回配置。

## 4. 部署后验证

部署脚本会自动运行 `backend/script/test.sh cloud`。它测试健康检查、鉴权、配置读取/校验、分析结果查询等轻量接口，不会触发 `/run`，也不会发起真实论文分析。

查看线上日志：

```powershell
npm.cmd run tail
```

日志中应该能看到：

```text
Scheduled run triggered by cron: 0 1 * * *
Scheduled run enqueued
```

任务完成后，也可以手动查 D1：

```powershell
npx.cmd wrangler d1 execute paper-sniffer-db `
  --remote `
  --config backend/wrangler.toml `
  --command "SELECT target_date, COUNT(*) AS count FROM analysis_results GROUP BY target_date ORDER BY target_date DESC LIMIT 5;"
```

## 5. 管理员手动调试

这个接口不是正式启动方式，只用于临时验证 Pipeline：

```powershell
$BASE = "https://paper-sniffer-backend.<你的账号>.workers.dev"
$TOKEN = "你的_ADMIN_TOKEN"

Invoke-WebRequest "$BASE/run?sync=true&date=2026-05-12" `
  -Method POST `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -UseBasicParsing
```

不带 `ADMIN_TOKEN` 会返回 `401`。普通 `GET /run` 不会启动任务。

## 6. 常见错误

`Queue "paper-sniffer-analysis" does not exist`:

重新运行：

```powershell
npm.cmd run deploy:cloud
```

`未绑定 PAPER_DB D1，分析结果不会持久化`:

检查 [wrangler.toml](../backend/wrangler.toml) 是否已经配置 `[[d1_databases]]`，并且 `binding = "PAPER_DB"`。

`CONFIG_KV 中没有找到配置`:

这是正常兜底行为。第一次部署后，Worker 会使用内置默认配置；需要修改运行参数时，通过 `PUT /api/config` 保存到 KV。
