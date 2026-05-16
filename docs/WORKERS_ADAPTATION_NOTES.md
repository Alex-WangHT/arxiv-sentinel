# PaperSniffer Workers 改造说明

这份文档记录当前 Cloudflare Workers 版本的运行方式。现在的线上资源只依赖 **D1、KV、Queue**，不使用 R2。

正式后台任务由 Cloudflare Cron Trigger 自动启动，不依赖前端请求或 HTTP 请求。

## 1. 整体运行流程

当前主流程是：

1. Cloudflare 按 `wrangler.toml` 里的 Cron 调用 `scheduled()`。
2. `scheduled()` 把一次运行任务投递到 `PAPER_ANALYSIS_QUEUE`。
3. Queue 消费者调用 `queue()`。
4. [worker.ts](../backend/src/worker.ts) 从 `CONFIG_KV` 读取配置 JSON；如果 KV 没有配置，则回退到 env / 内置默认配置。
5. [config.ts](../backend/src/config.ts) 校验配置并生成 `Config` 对象。
6. [pipeline.ts](../backend/src/pipeline.ts) 串起完整业务流程。
7. [arxiv_sniffer.ts](../backend/src/arxiv_sniffer.ts) 请求 arXiv API，抓取论文列表。
8. [paper_analyzer.ts](../backend/src/paper_analyzer.ts) 构造 prompt。
9. [llm_client.ts](../backend/src/llm_client.ts) 通过 `fetch` 调用 OpenAI-compatible 接口。
10. `WorkerD1Storage` 把分析结果和已处理论文历史保存到 Cloudflare D1。

```text
Cron Trigger
  -> scheduled()
  -> Queue
  -> queue()
  -> Pipeline
  -> arXiv 抓取
  -> LLM 分析
  -> D1 保存结果和历史
```

HTTP 路由只用于健康检查、配置管理、**分析结果只读查询**和管理员手动调试，不是正式任务启动方式。

## 2. 配置来源

项目不再通过仓库外层的 `config.json` 文件配置。当前配置来源收敛为：

- 本地开发密钥：`script/config/.dev.vars`（由 `script/deploy.sh` 从 shell 环境变量生成，并同步到 `backend/.dev.vars`）
- 线上密钥：Cloudflare Secrets
- 前端可编辑配置：`CONFIG_KV`，默认 key 是 `paper-sniffer/config`
- KV 未配置时的兜底：Worker 内置默认配置，可被 env 覆盖

`OPENAI_API_KEY` 不保存到 KV，仍然通过 `.dev.vars` 或 Cloudflare Secret 注入。

HTTP API 说明见 [api.md](api.md)。

## 3. 为什么使用 D1 保存结果

论文分析结果是结构化数据，包含日期、arXiv ID、标题、作者、分类、评分、理由、方法和关键词等字段。D1 更适合后续按日期、评分、分类等条件查询。

Worker 里的 `WorkerD1Storage` 实现了 `PipelineStorage`：

```ts
export interface PipelineStorage {
  loadHistory(...): Promise<string[]>;
  saveResults(...): Promise<string>;
  saveHistory(...): Promise<void>;
  listAnalysisResults(query: AnalysisResultsQuery): Promise<AnalysisResultRecord[]>;
}
```

（完整类型见 `backend/src/pipeline.ts`。）

D1 中会自动创建两张表：

- `analysis_results`: 保存每天的结构化分析结果。
- `processed_papers`: 保存已处理过的 arXiv ID，避免重复分析。

如果没有绑定 `PAPER_DB`，Worker 仍能运行，但历史和结果不会持久化。因此线上部署必须绑定 D1。

## 4. KV、D1、Queue 的职责

`CONFIG_KV` 只负责配置：

- `paper-sniffer/config`: 前端保存的可编辑配置。
- 不保存 `OPENAI_API_KEY`。
- 不保存分析结果。

`PAPER_DB` 负责持久化数据：

- 已处理论文历史。
- 分析结果。
- 前端或其它客户端通过 **`GET /api/analysis-results`**（Worker HTTP，见 [api.md](api.md)）只读查询 `analysis_results`，不直连 D1。

`PAPER_ANALYSIS_QUEUE` 负责异步任务：

- Cron 定时任务把运行请求投递进 Queue。
- Queue 消费者在后台执行抓取和分析。
- 失败时可以 retry。

## 5. Worker 入口

`worker.ts` 暴露三个 Cloudflare Workers 入口：

```ts
fetch()
scheduled()
queue()
```

常规后台任务入口是 `scheduled()`。它由 Cloudflare Cron 自动调用。

当前 HTTP 路由：

```text
GET  /health
GET  /config
GET  /api/analysis-results
GET  /api/config
PUT  /api/config
POST /api/config/validate
POST /run
POST /run?sync=true
```

`POST /run` 是管理员手动调试入口；所有需鉴权的 HTTP 路由统一使用请求头 `Authorization: Bearer <ADMIN_TOKEN>`。普通请求不会启动任务。

## 6. 本地调试命令

安装依赖：

```powershell
npm.cmd install
```

准备本地密钥变量。`deploy.sh` 不读取现成 `.dev.vars`，必须从 shell 环境变量生成：

```powershell
$env:OPENAI_API_KEY = "sk-your-real-key"
$env:ADMIN_TOKEN = "local-dev-token"
```

等价的 Git Bash 写法：

```bash
export OPENAI_API_KEY=sk-your-real-key
export ADMIN_TOKEN=local-dev-token
```

检查类型并编译：

```powershell
npm.cmd run typecheck
npm.cmd run build
```

启动本地 Worker（任选其一）：

- 已用 `script/deploy.sh` / `npm run deploy:local` 同步过 `backend/.dev.vars` 时：

```powershell
npm.cmd run dev
```

- 或一条命令完成「从 shell 变量生成 `.dev.vars` + typecheck + build + wrangler dev」（需已安装 Git Bash 或 WSL 的 `bash`）：

```powershell
npm.cmd run deploy:local
```

本地 Worker 启动后，可以运行本地 API smoke test（需 `bash`）：

```powershell
npm.cmd run test:local
```

云端 API smoke test 需要传入 Worker URL：

```powershell
npm.cmd run test:cloud -- https://paper-sniffer-backend.<your-subdomain>.workers.dev
```

模拟 Cron：

```powershell
npm.cmd run dev:scheduled
```

然后访问：

```text
http://127.0.0.1:8787/__scheduled
```

管理员手动同步调试：

```powershell
Invoke-WebRequest "http://127.0.0.1:8787/run?sync=true&date=2026-05-12" `
  -Method POST `
  -Headers @{ Authorization = "Bearer local-dev-token" } `
  -UseBasicParsing
```

## 7. 建议阅读源码顺序

1. [models.ts](../backend/src/models.ts): 数据结构。
2. [config.ts](../backend/src/config.ts): 配置来源和校验。
3. [worker.ts](../backend/src/worker.ts): Worker 入口、路由、Cron、Queue、D1。
4. [pipeline.ts](../backend/src/pipeline.ts): 主业务流水线。
5. [arxiv_sniffer.ts](../backend/src/arxiv_sniffer.ts): arXiv 抓取。
6. [paper_analyzer.ts](../backend/src/paper_analyzer.ts): prompt 和分析结果。
7. [llm_client.ts](../backend/src/llm_client.ts): 大模型接口。
