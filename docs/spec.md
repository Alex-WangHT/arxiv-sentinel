# Logic SPEC: arxiv-sentinel

## 1. 项目愿景
全自动 arXiv 论文追踪系统。系统周期性执行“嗅探-筛选-总结-发布”流水线

## 2. 技术栈约束
* **核心语言**: Python 3.10+
* **AI 接口**: OpenAI (需支持结构化输出，使用硅基流动的API：base_url="https://api.siliconflow.cn/v1")
* **发布平台**: GitHub Pages (基于 Markdown)
* **数据持久化**: Markdown YAML (用于前端展示)
* **强制依赖**: PyYAML (处理元数据), PyMuPDF (提取 Intro), pdf2image (转图片)

## 3. Paper Object 与 Metadata 规范
> **AI 指令：生成的每个 Markdown 文件必须包含以下 YAML Front Matter 格式**

每个总结文档的开头必须包含以下元数据块：
```
---
title: "[论文标题]"
date: YYYY-MM-DD
arxiv_id: "2405.XXXXX"
categories: ["cs.AI", "cs.CL"]
keywords: ["LLM", "Agent", "Optimization"] # 来自微信定义的触发关键词
ai_score: 8.5
url: "https://arxiv.org/abs/2405.XXXXX"
authors: ["Author A", "Author B"]
---
```

## 4. 后台自动化流水线逻辑

### Step 1: 初始化 (Config)
1. 从`config.json`中获取初始化的信息，包括：
    - 大模型平台：
        - 访问硅基流动的secret id
    - 本地缓存：
        - arXiv论文总结的缓存文件夹路径
    - 关键词：
        - 论文检索关键词
    - Abstract筛选： 
        - Abstract筛选等级
        - Abstract筛选时调用的默认模型
    - Introduction筛选
        - Introduction筛选等级
        - Introduction筛选时调用的模型
    - 全文总结
        - AI总结时调用的默认多模态模型
    - Github Page总结相关
        - Page部署模式
2. 初始化导入的程序代码文件放在`./src/sniffer.py`中。

### Step 2: 嗅探 (ArxivSniffer)
1. 从 `config.json` 读取 `keywords` 列表。
2. 遍历关键词，调用 arXiv API 获取最新论文。
3. 通过遍历本地 `docs/papers/` 文件夹下的 Markdown 文件名称，过滤掉历史上已经处理过的 arxiv_id。同时合并本次多关键词请求中重复命中的 arxiv_id。
4. 代码文件放在 `./src/sniffer.py` 中。

### Step 3: Abstract的AI筛选 (AbstractFilter)
1. 获取`arxiv_id`对应论文的`title`和`abstract`
2. 将 `keywords`,`title`和`abstract`交给AI，让AI评价相关度
3. 相关度分为`IRRELEVANT`,`LOW`,`MEDIUM`,`HIGH`，AI返回的结果应该是：`{"score": "HIGH", "reason": "..."}`
4. 根据`config.json`提取相关度阈值，将不相关的论文对应的`arxiv_id`筛选掉
5. 将剩下的`arxiv_id`对应的论文PDF下载到缓存文件夹中
6. 这里需要实现`system prompt`，`user prompt`和程序的解耦，prompt单独存放在`./prompts/abstract_filter`中，代码文件放在`./src/abstract_filter.py`中

### Step 4: Introduction的AI筛选 (IntroductionFilter)
1. **PDF 文本提取优化**: 
   - 遍历 PDF 缓存文件夹，使用 `pdfplumber` 库进行文本提取。
   - **双栏裁剪逻辑**: 针对学术论文常见的双栏排版，程序需计算页面宽度并建立左、右两个边界框（Bbox），依次提取左栏和右栏文本，最后进行拼接。
   - **范围控制**: 仅提取前 2-3 页内容，确保覆盖完整的 Introduction 章节。
2. **AI 质量评估**:
   - 将提取出的结构化文本交给 AI 筛选。
   - AI 根据 Introduction 评价论文的创新性、实验严谨度及质量，给出 `LOW`, `MEDIUM`, `HIGH` 评分。
   - **返回格式**: 强制要求结构化 JSON：`{"score": "HIGH", "reason": "..."}`。
3. **阈值过滤**: 
   - 根据 `config.json` 中的质量评分阈值，剔除低分论文，保留高价值 `arxiv_id` 进入下一环节。
4. **解耦设计**: Prompt 单独存放在 `./prompts/introduction_filter` 中，核心逻辑封装在 `./src/introduction_filter.py`。

### Step 5: 全文AI总结与Markdown生成 (PaperSummarizer)
1. 使用 pdf2image 库将 PDF 前 5 页（设定上限以避免 API 超时和 Token 浪费）转为图片，并将图片转换为 Base64 编码列表，按硅基流动多模态 API 的标准格式组装 payload。
2. 设定 System Prompt，要求 AI 必须以 **Markdown 混合 XML 标签** 的结构化格式输出总结内容。要求提取的内容包括：
    - 一句话的 Related Work (相关工作)
    - Introduction (导言) 行文逻辑简短总结
    - Methodology (方法论) 简短总结
    - Technical Route (技术路线) 简短总结及 Mermaid 流程图（必须使用规范的 Mermaid 语法）
    - Experiments (实验方法和结果) 简短总结
3. **AI 输出格式规范**：强制 AI 使用以下自定义 XML 标签包裹对应内容：
    ```markdown
    <relative_work>一句话相关工作总结...</relative_work>
    <intro_summary>导言逻辑简短总结...</intro_summary>
    <methodology>方法论简短总结...</methodology>
    <technical_route>
    <text>技术路线文字说明...</text>
    <mermaid>
    graph TD
      A[数据输入] --> B(特征提取)
      B --> C{分类器}
    </mermaid>
    </technical_route>
    <experiments>实验方法与结果总结...</experiments>
    ```
4. **内容解析与提取**：在 Python 端（`summarizer.py`），使用正则表达式（Regex，例如 `re.search(r'<mermaid>(.*?)</mermaid>', response_text, re.DOTALL)`）精准提取各个标签内部的纯文本数据。
5. **文件命名**: 最终生成文件路径为 `docs/papers/YYYY-MM-DD-[arxiv_id].md`。
6. **内容构造**:
    - **Header**: 填充第 3 节定义的 YAML Front Matter 块。
    - **Body**:
        - `## 原始摘要`：填入第一阶段获取的 Abstract。
        - `## AI 总结`：将正则提取出的各模块内容，注入到设定好的 Jinja2 Markdown 模板 (`templates/paper_template.md`) 中进行标准排版。
7. 这里需要实现 `system prompt`，`user prompt` 和程序的解耦，prompt 单独存放在 `./prompts/summarizer` 中，代码文件放在 `./src/summarizer.py` 中。

### Step 6: 发布 (GithubDeployer)
1. 将生成的 `.md` 文件提交至 GitHub 仓库。
2. 触发 GitHub Actions 自动构建 Pages。

## 5. 系统架构与工程结构 (System Architecture & Project Structure)

### 5.1 系统逻辑流转架构 (Data Flow)
系统采用单向数据流的漏斗式架构（Pipeline），各模块高度解耦，通过 `PipelineOrchestrator` 进行集中调度。

1. **配置注入**: `ConfigLoader` 加载全局配置并贯穿全生命周期。
2. **数据源采集**: `ArxivSniffer` 负责外部数据获取与本地状态（历史记录）校验。
3. **分级漏斗**:
   - 一级过滤: `AbstractFilter` 结合 AI 与摘要判定初筛。
   - 二级过滤: `IntroductionFilter` 提取物理 PDF 文本进行深度质量判定。
4. **内容聚合**: `PaperSummarizer` 调用多模态 API 并结合 Jinja2 模板引擎输出标准 Markdown。
5. **分发部署**: `GithubDeployer` 托管 Git 提交流程，触发远端 GitHub Actions 完成 MkDocs 构建。

### 5.2 全局工程目录结构 (Monorepo Directory Tree)
> **AI 指令：初始化项目时，必须严格按照以下树状结构建立文件夹和空文件。**

```text
arxiv-sentinel/
│
├── config.json                 # 核心业务配置文件
├── requirements.txt            # 项目依赖清单
├── mkdocs.yml                  # MkDocs 站点全局配置文件
├── SPEC.md                     # 本项目技术规格说明书
├── main.py                     # 后台爬虫与分析入口文件
├── .gitignore                  # 忽略规则（必须包含 cache/ 和 site/）
│
├── .github/                    
│   └── workflows/
│       └── deploy.yml          # GitHub Actions CI/CD 配置文件
│
├── docs/                       # MkDocs Markdown 源码目录
│   ├── index.md                # 站点首页
│   └── papers/                 # 自动生成的论文总结页面存放处
│
├── src/                        # 后台核心 Python 业务代码目录
│   ├── __init__.py
│   ├── config_loader.py        # 配置解析器
│   ├── llm_client.py           # 硅基流动大模型通信客户端
│   ├── sniffer.py              # arXiv 接口嗅探与去重
│   ├── abstract_filter.py      # 摘要级初筛
│   ├── introduction_filter.py  # 导言级深筛与 PDF 处理
│   ├── summarizer.py           # 总结生成与 Jinja2 模板渲染
│   ├── deployer.py             # Git 自动化提交与推送
│   ├── pipeline.py             # 主控引擎
│   └── utils.py                # 公共工具函数库
│
├── prompts/                    # 解耦的 Prompt 模板库 (纯文本存储)
│   ├── abstract_filter/
│   │   ├── system.md
│   │   └── user.md
│   ├── introduction_filter/
│   │   ├── system.md
│   │   └── user.md
│   └── summarizer/
│       ├── system.md
│       └── user.md
│
├── templates/                  # 结构化排版模板
│   └── paper_template.md       # Jinja2 Markdown 模板文件
│
└── cache/                      # 运行时本地临时缓存目录
    ├── pdfs/                   # 下载的原始 PDF 存放区
    ├── images/                 # PDF 转图片的缓存区
    └── history.json            # 历史处理记录（唯一的去重状态来源）
```
### 5.3 核心类与职责映射 (Module & Class Responsibilities)
> **AI 指令：`src/` 下的代码必须遵循“单文件单核心类”原则，严禁逻辑越界。**

| 模块文件 | 核心类名 | 主要职责边界 |
| :--- | :--- | :--- |
| `config_loader.py` | `ConfigLoader` | 解析 `config.json`，验证必填字段，提供类型安全的配置读取。 |
| `llm_client.py` | `LLMClient` | 封装所有大模型 API 调用，强制结构化 JSON 输出，包含指数退避重试。 |
| `sniffer.py` | `ArxivSniffer` | 查询 arXiv API，对比 `cache/history.json` 实现精准去重。 |
| `abstract_filter.py` | `AbstractFilter` | 组装摘要层 Prompt 调取 AI 判定，处理高分论文的 PDF 下载。 |
| `introduction_filter.py` | `IntroductionFilter`| 提取 PDF 文本，组装导言层 Prompt 调取 AI 进行深度质量打分。 |
| `summarizer.py` | `PaperSummarizer` | 提取 PDF 图片传至多模态 API，获取 JSON 总结后结合 Jinja2 写入 `docs/papers/`。 |
| `deployer.py` | `GithubDeployer` | 执行 Git 的 add, commit, pull --rebase 和 push 操作。 |
| `pipeline.py` | `PipelineOrchestrator`| 初始化 `ConfigLoader` 与 `LLMClient`，使用依赖注入串联上述所有类。 |


## 6. 全局准则 (Global Guiding Principles)

* **原子性 (Atomicity)**: 只有当 Markdown 文件成功推送到 GitHub 仓库后，才将 `arxiv_id` 标记为“已处理”并更新至 `cache/history.json`。若 Pipeline 中途崩溃，系统须支持断点续爬，避免重复消耗 API Token。
* **格式校验 (Validation)**: 
    * 在写入文件前，必须验证 YAML Front Matter 的合法性。
    * **特殊字符处理**: 论文标题中若包含冒号 (`:`)、单引号 (`'`) 或双引号 (`"`)，必须使用双引号包裹整个字段，并对内部引号进行转义，防止 MkDocs 编译站点时报错。
* **关键词一致性 (Traceability)**: 生成的 Markdown 元数据中的 `keywords` 数组，必须精准记录触发该论文收录的订阅关键词，以便于前端进行分类索引。
* **合规性频率限制 (Rate Limiting)**: 
    * **arXiv API**: 严格遵守官方爬虫协议，连续请求之间的 `time.sleep()` 不得低于 **3秒**。
    * **LLM API**: 针对不同任务配置指数退避重试 (Exponential Backoff)。当接收到 HTTP `429` (Rate Limit Exceeded) 状态码时，应自动按 2s, 4s, 8s... 序列延迟重试。
* **工程强韧性 (Resilience)**:
    * **超时管理**: 纯文本筛选任务超时设为 30s；多模态全文总结任务（涉及 Base64 图片上传）超时设为 **120s**。
    * **多模态降级 (Fallback)**: 若由于 PDF 页面过大或网络波动导致多模态模型总结连续失败，系统应自动降级为“仅文本模式”（仅发送前 2 页文本），确保流程不中断。
* **内存安全 (Memory Safety)**: 
    * `pdf2image` 转换后的 Base64 列表在上传成功后，须显式清空变量并释放内存。
    * `cache/pdfs/` 目录下的原始文件在处理完成后应根据配置决定是否定期清理，防止磁盘溢出。

## 7. 验收标准
1. [ ] 生成的 Markdown 文件顶部包含正确的 `---` 分隔的 YAML 块。
2. [ ] 关键词 (keywords) 在元数据中以数组形式存储。
3. [ ] GitHub Pages 能根据元数据正确渲染文章分类和标签。