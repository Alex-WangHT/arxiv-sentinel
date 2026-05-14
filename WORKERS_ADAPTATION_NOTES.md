# PaperSniffer Workers 改造说明

这份文档写给 TypeScript 和 Cloudflare Workers 还不太熟的读者。你可以先看这里，再去看源码里的注释。

## 1. 整体运行流程

现在后端的主流程是：

1. HTTP、Cron 或 Queue 触发 Worker。
2. [worker.ts](src/worker.ts) 接收请求，并决定“立即执行”还是“放入队列”。
3. [worker.ts](src/worker.ts) 从 `CONFIG_KV` 读取配置 JSON，再交给 [config.ts](src/config.ts) 生成 `Config` 对象。
4. [pipeline.ts](src/pipeline.ts) 串起完整业务流程。
5. [arxiv_sniffer.ts](src/arxiv_sniffer.ts) 用 `fetch` 请求 arXiv API，拿到论文列表。
6. [paper_analyzer.ts](src/paper_analyzer.ts) 把论文标题和摘要变成 prompt。
7. [llm_client.ts](src/llm_client.ts) 用 `fetch` 调用 OpenAI-compatible 大模型接口。
8. `PipelineStorage` 把结果和历史记录保存到 Cloudflare R2。

你可以把它想成一条流水线：

```text
请求 / 定时任务
  -> Worker 入口
  -> Queue 可选排队
  -> Pipeline
  -> arXiv 抓取
  -> LLM 分析
  -> R2 保存结果和历史
```

## 2. 为什么要改 config.ts

原来的后端更像传统 Node.js 程序，会从本地 `config.json` 读取配置。

Cloudflare Workers 不适合依赖本地文件系统，所以现在改成两层读取：

- 普通配置放在 `CONFIG_KV`，默认 key 是 `paper-sniffer/config.json`
- 本地密钥放在 `backend/.dev.vars`
- 线上密钥用 `wrangler secret put OPENAI_API_KEY`

`CONFIG_KV` 中保存的内容可以参考 [config.example.json](config.example.json)。

`Config.fromEnv(env)` 做了三件事：

1. 合并 `CONFIG_KV` 读出来的 JSON 和必要的 env/secret。
2. 把字符串配置转换成真正的数组或数字。
3. 校验配置是否完整，比如 API Key、模型名、arXiv 分类规则是否存在。

注意：`OPENAI_API_KEY` 仍然建议用 secret 管理，不要明文放入 KV。

## 3. 为什么要改 arxiv_sniffer.ts

Cloudflare Workers 没有 Node.js 的 `https` 模块，但有标准 `fetch`。

所以 `ArxivSniffer` 现在用：

```ts
await fetch(url.toString())
```

来请求 arXiv API。

这个文件的职责很单纯：

- 根据 `domain_rules` 抓取 arXiv 分类
- 解析 arXiv 返回的 XML
- 转成项目内部的 `Paper` 对象
- 去掉重复论文
- 跳过历史上已经处理过的论文

它不调用大模型，也不保存结果。

## 4. 为什么要改 llm_client.ts

旧代码使用 OpenAI SDK。SDK 对普通 Node.js 很方便，但在 Workers 里会增加运行时兼容和打包复杂度。

现在的 `LlmClient` 直接用 HTTP 调用：

```text
POST {OPENAI_BASE_URL}/chat/completions
```

这样有几个好处：

- 更贴近 Workers 的原生能力
- 可以兼容 OpenAI、DeepSeek、SiliconFlow 等 OpenAI-compatible 服务
- 不需要依赖 Node.js API

`LlmClient` 还负责：

- 超时控制
- 重试
- 并发队列
- JSON mode
- 把模型返回结果转换成统一的 `LlmResponse`

## 5. 为什么要改 pipeline.ts

原来的流水线会直接写本地文件，例如 `output/history.json`。

Workers 没有传统意义上的持久本地磁盘，所以现在把存储抽象成接口：

```ts
export interface PipelineStorage {
  loadHistory(...): Promise<string[]>;
  saveResults(...): Promise<string>;
  saveHistory(...): Promise<void>;
}
```

这意味着 `Pipeline` 不关心结果保存在哪里。

现在 Worker 使用 R2 实现这个接口：

- 历史记录保存到 `PAPER_RESULTS` R2 bucket 的 `history.json`
- 分析结果保存到 `PAPER_RESULTS` R2 bucket 的 `output/analysis_results_YYYY-MM-DD.json`

以后如果你想换成 D1 或数据库，只需要新增一个 Storage 实现，不必重写整个流水线。

## 6. worker.ts 是做什么的

`worker.ts` 是 Cloudflare Workers 的入口。

它暴露三个入口函数：

```ts
fetch()
scheduled()
queue()
```

含义分别是：

- `fetch`: 用户访问 HTTP 接口时执行
- `scheduled`: Cron 定时任务触发时执行
- `queue`: Cloudflare Queue 有消息要消费时执行

现在支持的 HTTP 路由：

```text
GET  /health
GET  /config
POST /run
POST /run?sync=true
```

默认 `POST /run` 会把任务放进 Queue。

本地调试时建议用：

```text
POST /run?sync=true
```

这样请求会等待任务跑完，并直接返回结果。

## 7. Queue 在这里的作用

论文抓取和大模型分析可能比较慢。

如果直接在 HTTP 请求里做全部工作，用户请求可能等待很久，也更容易超时。

Queue 的作用是：

1. HTTP 请求只负责提交任务。
2. Worker 把任务放入 Queue。
3. Queue 消费者在后台慢慢处理任务。
4. 失败时可以 retry。

这更适合自动化任务和定时任务。

## 8. KV 和 R2 在这里的作用

KV 是 Cloudflare 提供的键值存储。

这里按你的设计只让 KV 保存配置（包括 prompt）：

1. `CONFIG_KV` 保存 `paper-sniffer/config.json`
2. 配置里放关键词、arXiv 分类规则、模型名、阈值、以及 `prompt_system` / `prompt_user_template`
3. API Key 不建议放 KV，仍然用 secret/env

R2 是 Cloudflare 的对象存储，更适合保存结果文件：

1. `history.json`: 已经处理过的 arXiv ID，避免重复分析。
2. `output/analysis_results_YYYY-MM-DD.json`: 每天的分析结果。

这样 KV 的职责很单纯：只管配置；R2 的职责也很清楚：持久化输出。

## 9. 本地调试命令

先安装依赖：

```powershell
npm.cmd install
```

准备本地密钥：

```powershell
Copy-Item backend/.dev.vars.example backend/.dev.vars
notepad backend/.dev.vars
```

在 `.dev.vars` 里填写：

```text
OPENAI_API_KEY=sk-your-real-key
```

准备配置。线上建议把 [config.example.json](config.example.json) 的内容写入 `CONFIG_KV` 的 `paper-sniffer/config.json`。

本地开发时，如果你还没有配置本地 KV，也可以临时在 `.dev.vars` 加一个 `CONFIG_JSON` 做兜底；等 KV 调通后再删掉。

检查类型：

```powershell
npm.cmd run typecheck
```

编译：

```powershell
npm.cmd run build
```

启动本地 Worker：

```powershell
npm.cmd run dev
```

测试健康检查：

```powershell
Invoke-WebRequest http://127.0.0.1:8787/health -UseBasicParsing
```

同步跑一次任务：

```powershell
Invoke-WebRequest "http://127.0.0.1:8787/run?sync=true&date=2026-05-12" -UseBasicParsing
```

## 10. 建议阅读源码顺序

如果你 TypeScript 还不熟，建议按这个顺序看：

1. [models.ts](src/models.ts)：先看数据结构。
2. [config.ts](src/config.ts)：理解配置从哪里来。
3. [worker.ts](src/worker.ts)：理解请求怎么进入系统。
4. [pipeline.ts](src/pipeline.ts)：理解主业务流程。
5. [arxiv_sniffer.ts](src/arxiv_sniffer.ts)：理解论文怎么抓。
6. [paper_analyzer.ts](src/paper_analyzer.ts)：理解 prompt 怎么构造。
7. [llm_client.ts](src/llm_client.ts)：理解大模型接口怎么调。
