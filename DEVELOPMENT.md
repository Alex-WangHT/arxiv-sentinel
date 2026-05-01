# arXiv Sentinel 开发指南

本文档为开发者提供 arXiv Sentinel 项目的详细技术说明、架构设计、模块说明和扩展指南。

---

## 📋 目录

- [项目架构](#项目架构)
- [模块说明](#模块说明)
- [核心流程](#核心流程)
- [代码规范](#代码规范)
- [扩展指南](#扩展指南)
- [测试说明](#测试说明)
- [常见问题](#常见问题)

---

## 🏗️ 项目架构

### 整体架构

```
arxiv-sentinel/
├── src/                    # 源代码目录
│   ├── __init__.py
│   ├── config.py          # 配置管理模块
│   ├── sniffer.py         # 论文嗅探模块
│   ├── summarizer.py      # 论文总结模块
│   ├── publisher.py       # MkDocs发布模块
│   ├── main.py            # 主入口模块
│   └── test_arxiv_sentinel.py  # 单元测试
├── markdown/              # Prompt模板目录
│   ├── summary_prompt.txt
│   ├── technical_route_prompt.txt
│   ├── methodology_prompt.txt
│   ├── experiment_prompt.txt
│   ├── introduction_prompt.txt
│   └── paper_template.md
├── config.json.example    # 配置示例文件
├── requirements.txt       # Python依赖
├── README.md              # 用户文档
└── DEVELOPMENT.md         # 开发文档（本文档）
```

### 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                      arXivSentinel (主控制器)                  │
│              整合所有模块，协调工作流程执行                      │
└──────────────────────────┬──────────────────────────────────┘
                           │
           ┌───────────────┼───────────────┬───────────────┐
           ▼               ▼               ▼               ▼
    ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
    │ Config   │     │ Sniffer  │     │Summarizer│     │Publisher │
    │ Manager  │     │          │     │          │     │          │
    └────┬─────┘     └────┬─────┘     └────┬─────┘     └────┬─────┘
         │                │                │                │
         ▼                ▼                ▼                ▼
    ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
    │ 配置加载  │     │ arXiv   │     │ 硅基流动  │     │  Git    │
    │ 配置保存  │     │ API    │     │ API     │     │ 操作   │
    │ 配置验证  │     │ PDF下载 │     │ 多模态   │     │ MkDocs │
    └──────────┘     └──────────┘     └──────────┘     └──────────┘
```

### 数据流

```
1. 配置输入:
   config.json / 环境变量 → ConfigManager → Config

2. 搜索阶段:
   关键词 + 分类 → ArXivSniffer.search() → List[Paper]

3. 筛选阶段 (可选):
   Paper.abstract → PaperFilter.is_relevant() → bool
   结果: List[Paper] (相关) + List[Paper] (不相关)

4. 下载阶段:
   Paper.pdf_url → ArXivSniffer.download_pdfs() → Paper.local_pdf_path

5. 总结阶段:
   Paper → Summarizer.summarize() → Dict[分析维度: 内容]
   结果 → Summarizer.generate_markdown() → .md 文件

6. 发布阶段:
   .md 文件 → MkDocsPublisher → GitHub Pages 网站
```

---

## 📦 模块说明

### 1. config.py - 配置管理模块

**文件位置**: `src/config.py`

**核心类**:

#### 1.1 DeployMode (Enum)

部署模式枚举，定义三种部署方式：

```python
class DeployMode(str, Enum):
    BUILD_ONLY = "build-only"      # 仅本地构建
    PUSH_TO_BRANCH = "push-to-branch"  # 推送到指定分支
    GH_DEPLOY = "gh-deploy"        # 使用mkdocs gh-deploy
```

#### 1.2 SearchStrategy (Enum)

搜索策略枚举，定义三种搜索严格程度：

```python
class SearchStrategy(str, Enum):
    STRICT = "strict"      # 精确短语匹配
    MODERATE = "moderate"  # 普通匹配（默认）
    BROAD = "broad"        # 宽松匹配
```

#### 1.3 Config (@dataclass)

配置数据类，定义所有配置项：

| 属性 | 类型 | 说明 |
|------|------|------|
| `SILICONFLOW_API_KEY` | `str` | 硅基流动API密钥 |
| `SILICONFLOW_MODEL` | `str` | 文本模型名称 |
| `KEYWORDS` | `List[str]` | 搜索关键词列表 |
| `CATEGORIES` | `List[str]` | arXiv分类列表 |
| `MAX_RESULTS_PER_SEARCH` | `int` | 每次搜索最大结果数 |
| `USE_VISION_MODE` | `bool` | 是否使用视觉模式 |
| `ENABLE_LLM_FILTER` | `bool` | 是否启用AI筛选 |
| `MKDOCS_DEPLOY_MODE` | `str` | 部署模式 |

**主要方法**:
- `to_dict()`: 转换为字典
- `from_dict(data)`: 从字典创建实例

#### 1.4 ConfigManager

配置管理器，提供配置的加载、保存、更新和验证功能：

```python
class ConfigManager:
    def __init__(self, config_file: Optional[str] = None)
    def get(self) -> Config                    # 获取配置
    def save(self) -> bool                      # 保存配置
    def update(self, **kwargs) -> Config       # 更新配置
    def validate(self) -> List[str]             # 验证配置
    def get_github_token(self) -> Optional[str] # 获取GitHub Token
```

**配置优先级**:
1. 环境变量 `SILICONFLOW_API_KEY`（最高）
2. `config.json` 文件
3. `Config` 类默认值（最低）

---

### 2. sniffer.py - 论文嗅探模块

**文件位置**: `src/sniffer.py`

**核心类**:

#### 2.1 Paper (@dataclass)

论文数据结构：

```python
@dataclass
class Paper:
    arxiv_id: str              # arXiv ID
    title: str                 # 标题
    authors: List[str]         # 作者列表
    abstract: str              # 摘要
    categories: List[str]      # 分类列表
    published: str             # 发布日期
    updated: str               # 更新日期
    pdf_url: str               # PDF下载URL
    local_pdf_path: str = ""   # 本地PDF路径（下载后填充）
```

#### 2.2 SearchStrategy (Enum)

搜索策略枚举（与config.py中的枚举对应）：

```python
class SearchStrategy(str, Enum):
    STRICT = "strict"      # 精确短语匹配
    MODERATE = "moderate"  # 普通匹配
    BROAD = "broad"        # 宽松匹配
```

#### 2.3 ArXivSniffer

arXiv论文嗅探器，提供论文搜索、PDF下载和缓存管理功能：

```python
class ArXivSniffer:
    def __init__(self, pdf_cache_dir: str = "./pdf_cache")
    
    # 核心方法
    def search(
        self,
        keywords: List[str],
        categories: Optional[List[str]] = None,
        max_results: int = 10,
        start: int = 0,
        search_all_fields: bool = False,
        use_or_for_categories: bool = False,
        search_strategy: str = SearchStrategy.MODERATE.value,
    ) -> List[Paper]
    
    def download_pdfs(self, papers: List[Paper]) -> int
    def download_pdf(self, paper: Paper) -> bool
    def cleanup_all_pdfs(self, papers: List[Paper]) -> int
    def cleanup_pdf(self, paper: Paper) -> bool
    
    # 辅助方法
    def build_query(
        self,
        keywords: List[str],
        categories: Optional[List[str]] = None,
        search_all_fields: bool = False,
        use_or_for_categories: bool = False,
        search_strategy: str = SearchStrategy.MODERATE.value,
    ) -> str
```

**搜索逻辑详解**:

```
默认逻辑 (use_or_for_categories=False):
    query = "(关键词部分) AND (分类部分)"
    
宽松逻辑 (use_or_for_categories=True):
    query = "(关键词部分) OR (分类部分)"

搜索策略对关键词部分的影响:
    - STRICT:     精确短语匹配 → ti:"keyword" OR abs:"keyword"
    - MODERATE:   普通匹配 → ti:keyword OR abs:keyword
    - BROAD:      宽松匹配 → all:keyword

搜索字段影响:
    - search_all_fields=True:  使用 all: 前缀（搜索所有字段）
    - search_all_fields=False: 使用 ti: 和 abs: 前缀（仅标题摘要）
```

**arXiv API 字段前缀**:

| 前缀 | 字段 | 说明 |
|------|------|------|
| `ti` | Title | 标题 |
| `abs` | Abstract | 摘要 |
| `au` | Author | 作者 |
| `cat` | Category | 分类 |
| `all` | All | 所有字段 |

---

### 3. summarizer.py - 论文总结模块

**文件位置**: `src/summarizer.py`

**核心类**:

#### 3.1 RetryManager

指数退避重试管理器，用于处理网络请求失败：

```python
class RetryManager:
    def __init__(
        self,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        backoff_factor: float = 2.0,
    )
    
    def execute(self, func, *args, **kwargs) -> Any
```

**重试策略**:
- 初始延迟: 1秒
- 退避因子: 2（指数增长）
- 重试次数: 3次
- 延迟序列: 1s → 2s → 4s

**捕获的异常类型**:
- `requests.exceptions.Timeout`
- `requests.exceptions.ConnectionError`
- `requests.exceptions.ReadTimeout`
- `requests.exceptions.ChunkedEncodingError`

#### 3.2 ImageConverter

PDF转图像转换器，用于视觉模式：

```python
class ImageConverter:
    def __init__(self, max_pages: int = 10, dpi: int = 150)
    def pdf_to_images(self, pdf_path: str) -> List[bytes]
```

**工作原理**:
1. 使用 PyMuPDF (fitz) 打开PDF文件
2. 逐页渲染为图像（PNG格式）
3. 限制最大页数避免上下文窗口溢出
4. 返回图像二进制数据列表

#### 3.3 SiliconFlowClient

硅基流动API客户端，支持文本模型和多模态视觉模型：

```python
class SiliconFlowClient:
    def __init__(
        self,
        api_key: str,
        text_model: str = "Qwen/Qwen2.5-7B-Instruct",
        vision_model: str = "Qwen/Qwen2-VL-72B-Instruct",
        timeout: int = 180,
        max_retries: int = 3,
    )
    
    # 核心方法
    def chat(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4000,
    ) -> str
    
    def chat_with_images(
        self,
        text_prompt: str,
        images: List[bytes],
        system_prompt: str = "",
    ) -> str
    
    # 辅助方法
    def _normalize_encoding(self, text: str) -> str
    def _clean_response(self, content: str) -> str
```

**API端点**:
- 文本对话: `https://api.siliconflow.cn/v1/chat/completions`
- 视觉对话: 相同端点，但使用不同的消息格式

**视觉消息格式**:
```python
{
    "role": "user",
    "content": [
        {"type": "text", "text": text_prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
    ]
}
```

#### 3.4 PaperFilter

AI论文筛选器，基于标题、分类、摘要判断相关性：

```python
class PaperFilter:
    def __init__(self, client: SiliconFlowClient)
    def is_relevant(
        self,
        paper: Paper,
        target_keywords: List[str]
    ) -> Tuple[bool, str]
```

**筛选Prompt**:
```
你是一位专业的学术论文筛选专家。请根据以下信息判断这篇论文是否与指定的关键词相关。

论文标题: {title}
论文分类: {categories}
论文摘要: {abstract}
目标关键词: {keywords}

请直接输出你的判断结果：
- 如果论文相关，输出 "RELEVANT"
- 如果论文不相关，输出 "IRRELEVANT"
```

**响应解析逻辑**:
1. 移除所有非字母字符
2. 转换为大写
3. 与常量 `RELEVANT` / `IRRELEVANT` 比较
4. 如果无法解析，默认判定为相关（避免遗漏）

#### 3.5 PDFExtractor

PDF文本提取器：

```python
class PDFExtractor:
    def __init__(self)
    def extract_text(self, pdf_path: str) -> str
    def _normalize_encoding(self, text: str) -> str
```

**工作原理**:
1. 使用 PyMuPDF (fitz) 打开PDF
2. 逐页提取文本
3. 规范化编码（解决乱码问题）
4. 返回合并的文本

#### 3.6 Summarizer

论文总结器，核心功能类：

```python
class Summarizer:
    def __init__(
        self,
        siliconflow_api_key: str,
        prompt_dir: str = "./markdown",
        use_vision_mode: bool = False,
        text_model: str = "Qwen/Qwen2.5-7B-Instruct",
        vision_model: str = "Qwen/Qwen2-VL-72B-Instruct",
    )
    
    # 核心方法
    def filter_papers(
        self,
        papers: List[Paper],
        keywords: List[str]
    ) -> Tuple[List[Paper], List[Paper]]
    
    def summarize(self, paper: Paper) -> Dict[str, Any]
    
    def generate_markdown(
        self,
        summary_result: Dict[str, Any],
        output_dir: str
    ) -> str
    
    # 辅助方法
    def _load_prompts(self)
    def _summarize_text_mode(self, paper: Paper) -> Dict[str, Any]
    def _summarize_vision_mode(self, paper: Paper) -> Dict[str, Any]
    def _call_llm_for_section(
        self,
        prompt_name: str,
        context: str,
        paper: Paper
    ) -> str
    def _call_vision_llm_for_section(
        self,
        prompt_name: str,
        images: List[bytes],
        paper: Paper
    ) -> str
```

**分析维度**:

| 维度 | Prompt文件 | 分析内容 |
|------|------------|----------|
| 整体总结 | `summary_prompt.txt` | 论文核心贡献、创新点、价值 |
| 技术路线 | `technical_route_prompt.txt` | 技术框架、数据流、关键模块 |
| 方法论 | `methodology_prompt.txt` | 研究方法、核心算法、损失函数 |
| 实验方案 | `experiment_prompt.txt` | 数据集、评价指标、实验结果 |
| Introduction逻辑 | `introduction_prompt.txt` | 研究背景、问题、动机、假设 |

**Markdown模板**:
使用 `markdown/paper_template.md` 文件作为模板，包含以下占位符：
- `{{arxiv_id}}`
- `{{title}}`
- `{{authors}}`
- `{{categories}}`
- `{{published}}`
- `{{pdf_url}}`
- `{{summary}}`
- `{{technical_route}}`
- `{{methodology}}`
- `{{experiment}}`
- `{{introduction}}`

---

### 4. publisher.py - MkDocs发布模块

**文件位置**: `src/publisher.py`

**核心类**:

#### 4.1 MkDocsPublisher

MkDocs发布管理器，整合Git操作、MkDocs构建和部署：

```python
class MkDocsPublisher:
    def __init__(
        self,
        working_dir: str = "./mkdocs_repo",
        repo_url: str = "",
        repo_branch: str = "gh-pages",
        deploy_mode: str = "build-only",
    )
    
    # Git操作方法
    def prepare_repository(self) -> bool
    def git_add_all(self) -> bool
    def git_commit(
        self,
        message: str,
        author_name: Optional[str] = None,
        author_email: Optional[str] = None
    ) -> bool
    def git_push(self) -> bool
    def has_changes(self) -> bool
    
    # MkDocs操作方法
    def initialize_project(
        self,
        site_name: str = "arXiv Sentinel",
        description: str = "每日arXiv论文总结"
    )
    def copy_markdown_files(
        self,
        markdown_files: List[str],
        subfolder: Optional[str] = None
    ) -> List[str]
    def build(self) -> bool
    def serve(self, port: int = 8000) -> subprocess.Popen
    def deploy_gh_pages(self) -> bool
    def deploy(
        self,
        commit_message: str = "自动更新: 新增论文总结",
        author_name: Optional[str] = None,
        author_email: Optional[str] = None
    ) -> bool
    
    # 导航和内容更新方法
    def update_navigation(self, papers_dir: str = "papers")
    def update_index_page(
        self,
        new_papers_count: int,
        keywords: List[str]
    )
    
    # 内部方法
    def _run_git_command(self, args: List[str], cwd: Optional[str] = None) -> tuple
    def _get_authenticated_url(self) -> str
    def _generate_mkdocs_config(self, site_name: str, description: str) -> str
    def _generate_index_page(self, site_name: str, description: str) -> str
```

**部署模式行为**:

| 模式 | Git操作 | 构建 | 部署 |
|------|---------|------|------|
| `build-only` | ❌ 跳过 | ✅ 执行 | ❌ 跳过 |
| `push-to-branch` | ✅ 完整流程 | ✅ 执行 | ✅ 推送 |
| `gh-deploy` | ✅ 自动处理 | ✅ 自动 | ✅ gh-deploy |

**push-to-branch 流程**:
1. `has_changes()` - 检查是否有更改
2. `git_add_all()` - 添加所有文件到暂存区
3. `git_commit()` - 提交更改
4. `git_push()` - 推送到远程

**Git认证**:
- 从环境变量 `GITHUB_TOKEN` 获取Token
- 自动注入到URL中
- 支持HTTPS和SSH URL格式转换

**导航更新**:
- 扫描 `docs/papers/` 目录
- 按文件名降序排列（最新在前）
- 重写 `mkdocs.yml` 中的 `nav` 部分

---

### 5. main.py - 主入口模块

**文件位置**: `src/main.py`

**核心类**:

#### 5.1 arXivSentinel

主控制器类，整合所有模块功能：

```python
class arXivSentinel:
    def __init__(self, config_file: Optional[str] = None)
    
    # 核心方法
    def run(
        self,
        keywords: Optional[List[str]] = None,
        max_results: Optional[int] = None
    ) -> int
    
    # 内部方法
    def _validate_config(self)
    def _setup_directories(self)
```

**工作流程 (run() 方法)**:

```
[1/7] 搜索arXiv论文
    → sniffer.search() → List[Paper]

[2/7] AI论文筛选（可选）
    → summarizer.filter_papers() → (相关论文, 不相关论文)

[3/7] 下载PDF文件
    → sniffer.download_pdfs()

[4/7] 生成论文总结
    → summarizer.summarize()
    → summarizer.generate_markdown()

[5/7] 清理PDF缓存
    → sniffer.cleanup_all_pdfs()

[6/7] 准备MkDocs仓库
    → publisher.prepare_repository()
    → publisher.initialize_project()

[7/7] 构建和部署
    → publisher.copy_markdown_files()
    → publisher.update_navigation()
    → publisher.update_index_page()
    → publisher.build()
    → publisher.deploy()
```

#### 5.2 main() 函数

命令行入口函数，解析命令行参数并执行相应操作。

**命令行参数**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `--config, -c` | string | 配置文件路径 |
| `--keywords, -k` | string... | 搜索关键词 |
| `--max-results, -n` | int | 最大结果数 |
| `--serve` | flag | 启动本地服务器 |
| `--port, -p` | int | 服务器端口 |
| `--no-filter` | flag | 禁用AI筛选 |
| `--use-vision` | flag | 启用视觉模式 |
| `--no-vision` | flag | 禁用视觉模式 |
| `--search-strict` | flag | 严格搜索策略 |
| `--search-moderate` | flag | 中等搜索策略 |
| `--search-broad` | flag | 宽松搜索策略 |
| `--use-or-categories` | flag | OR逻辑 |
| `--use-and-categories` | flag | AND逻辑 |
| `--search-all-fields` | flag | 搜索所有字段 |
| `--search-title-abstract` | flag | 仅标题摘要 |

---

## 🔄 核心流程

### 完整流程图

```
┌───────────────────────────────────────────────────────────────┐
│                         开始执行                                │
└──────────────────────────┬────────────────────────────────────┘
                           ▼
┌───────────────────────────────────────────────────────────────┐
│  1. 配置初始化                                                   │
│     - 加载 config.json                                          │
│     - 读取环境变量                                               │
│     - 验证配置有效性                                             │
│     - 创建必要目录                                               │
└──────────────────────────┬────────────────────────────────────┘
                           ▼
┌───────────────────────────────────────────────────────────────┐
│  2. 论文搜索                                                     │
│     输入: 关键词、分类、搜索策略                                  │
│     过程:                                                        │
│       - 构建 arXiv API 查询字符串                               │
│       - 调用 arXiv OpenSearch API                              │
│       - 解析 XML 响应                                           │
│     输出: List[Paper]                                           │
└──────────────────────────┬────────────────────────────────────┘
                           ▼
┌───────────────────────────────────────────────────────────────┐
│  3. AI 筛选（可选）                                              │
│     条件: ENABLE_LLM_FILTER = true                              │
│     过程:                                                        │
│       - 对每篇论文调用 LLM                                       │
│       - 基于标题、分类、摘要判断相关性                           │
│       - 解析 LLM 响应（RELEVANT/IRRELEVANT）                   │
│     输出: (相关论文列表, 不相关论文列表)                          │
└──────────────────────────┬────────────────────────────────────┘
                           ▼
┌───────────────────────────────────────────────────────────────┐
│  4. PDF 下载                                                     │
│     输入: 相关论文列表                                           │
│     过程:                                                        │
│       - 对每篇论文下载 PDF                                       │
│       - 保存到 PDF_CACHE_DIR                                    │
│       - 填充 paper.local_pdf_path                               │
│     输出: 下载成功的论文数量                                      │
└──────────────────────────┬────────────────────────────────────┘
                           ▼
┌───────────────────────────────────────────────────────────────┐
│  5. 论文总结                                                     │
│     输入: 论文（含 local_pdf_path）                              │
│     过程:                                                        │
│       A. 文本模式 (USE_VISION_MODE=false):                      │
│          - 从 PDF 提取文本                                       │
│          - 按5个维度调用文本模型                                 │
│       B. 视觉模式 (USE_VISION_MODE=true):                       │
│          - 将 PDF 转为图像                                       │
│          - 按5个维度调用视觉模型                                 │
│     输出:                                                        │
│       - 各维度分析结果（Dict）                                   │
│       - 生成的 Markdown 文件路径                                 │
└──────────────────────────┬────────────────────────────────────┘
                           ▼
┌───────────────────────────────────────────────────────────────┐
│  6. 清理缓存                                                     │
│     - 删除已处理的 PDF 文件                                      │
│     - 释放磁盘空间                                               │
└──────────────────────────┬────────────────────────────────────┘
                           ▼
┌───────────────────────────────────────────────────────────────┐
│  7. 准备发布                                                     │
│     过程:                                                        │
│       - 克隆/拉取 MkDocs 仓库                                   │
│       - 初始化 MkDocs 项目                                      │
│       - 复制 Markdown 文件到 docs/papers/                       │
│       - 更新导航栏                                               │
│       - 更新首页统计                                             │
└──────────────────────────┬────────────────────────────────────┘
                           ▼
┌───────────────────────────────────────────────────────────────┐
│  8. 构建与部署                                                   │
│     过程:                                                        │
│       - 执行 mkdocs build                                        │
│       - 根据部署模式:                                            │
│         * build-only: 跳过部署                                   │
│         * push-to-branch: Git 提交 + 推送                       │
│         * gh-deploy: 执行 mkdocs gh-deploy                      │
└──────────────────────────┬────────────────────────────────────┘
                           ▼
┌───────────────────────────────────────────────────────────────┐
│                         执行结束                                 │
│  输出: 成功处理的论文数量、运行状态报告                           │
└───────────────────────────────────────────────────────────────┘
```

---

## 📝 代码规范

### Python 版本

- 最低支持: Python 3.8
- 推荐使用: Python 3.10+

### 代码风格

遵循 PEP 8 规范，主要约定：

| 类型 | 规范 | 示例 |
|------|------|------|
| 模块名 | 小写下划线 | `config.py`, `sniffer.py` |
| 类名 | 大驼峰 | `ArXivSniffer`, `PaperFilter` |
| 函数名 | 小写下划线 | `search()`, `download_pdfs()` |
| 常量 | 大写下划线 | `RELEVANT`, `API_TIMEOUT` |
| 私有方法 | 单下划线前缀 | `_load_prompts()`, `_run_git_command()` |

### 文档字符串

所有公共类和函数必须包含详细的文档字符串，使用Google风格：

```python
class ExampleClass:
    """
    类的简要说明。
    
    详细描述类的功能、用途、注意事项等。
    
    Attributes:
        attribute1 (type): 属性1的说明
        attribute2 (type): 属性2的说明
    
    Example:
        >>> example = ExampleClass(param1="value")
        >>> result = example.method()
        >>> print(result)
    """
    
    def __init__(self, param1: str):
        """
        初始化方法。
        
        Args:
            param1: 参数1的说明
        """
        self.attribute1 = param1
    
    def method(self, param2: int = 0) -> bool:
        """
        方法的简要说明。
        
        详细描述方法的功能、执行过程、返回值含义等。
        
        Args:
            param2: 参数2的说明，默认值为0
        
        Returns:
            返回值的说明，包括类型和含义
        
        Raises:
            ValueError: 描述可能抛出的异常及条件
        
        Example:
            >>> example = ExampleClass("test")
            >>> example.method(5)
            True
        """
        return param2 > 0
```

### 类型注解

所有函数参数和返回值必须添加类型注解：

```python
from typing import List, Dict, Optional, Tuple, Any

def process_papers(
    papers: List[Paper],
    keywords: Optional[List[str]] = None
) -> Tuple[int, Dict[str, Any]]:
    """处理论文列表。"""
    pass
```

### 异常处理

1. **捕获具体异常**，不要捕获泛型 `Exception`（除非必要）
2. **提供有意义的错误信息**
3. **记录错误日志**（或打印到控制台）

```python
try:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
except requests.exceptions.Timeout:
    print(f"请求超时: {url}")
    return False
except requests.exceptions.HTTPError as e:
    print(f"HTTP错误: {e}")
    return False
except requests.exceptions.RequestException as e:
    print(f"请求错误: {e}")
    return False
```

### 日志和输出

- 使用 `print()` 进行用户可见的输出
- 重要操作需要打印进度信息
- 错误信息需要清晰明确

```python
print("\n[1/7] 搜索arXiv论文...")
print(f"  找到 {len(papers)} 篇论文")

# 错误输出
print(f"  错误: {error_message}")
```

---

## 🔧 扩展指南

### 1. 添加新的分析维度

要添加新的论文分析维度，请遵循以下步骤：

#### 步骤1: 创建Prompt模板

在 `markdown/` 目录下创建新的Prompt文件：

```
markdown/
├── summary_prompt.txt
├── technical_route_prompt.txt
├── methodology_prompt.txt
├── experiment_prompt.txt
├── introduction_prompt.txt
└── NEW_DIMENSION_prompt.txt  # 新添加
```

Prompt内容示例：
```
你是一位专业的学术研究员。请分析以下论文的【新维度】：

论文标题: {title}
论文分类: {categories}
论文内容: {context}

请从以下角度分析：
1. ...
2. ...

请用简洁的语言总结，不超过300字。
```

#### 步骤2: 修改Summarizer类

在 `src/summarizer.py` 中修改以下部分：

1. **添加维度常量**（如果需要）
2. **修改 `_load_prompts()` 方法**
3. **修改 `_summarize_text_mode()` 方法**
4. **修改 `_summarize_vision_mode()` 方法**
5. **修改 `generate_markdown()` 方法**
6. **修改Markdown模板**

#### 步骤3: 更新Markdown模板

编辑 `markdown/paper_template.md`，添加新的占位符：

```markdown
## 新维度分析

{{new_dimension}}
```

### 2. 支持新的LLM提供商

要添加对新的LLM API提供商的支持：

#### 步骤1: 创建新的Client类

在 `src/summarizer.py` 中创建新的客户端类：

```python
class NewProviderClient:
    """新LLM提供商的客户端。"""
    
    def __init__(self, api_key: str, model: str, ...):
        self.api_key = api_key
        self.model = model
        # 初始化配置
    
    def chat(self, prompt: str, ...) -> str:
        """文本对话。"""
        # 实现API调用逻辑
        pass
    
    def chat_with_images(self, text_prompt: str, images: List[bytes], ...) -> str:
        """多模态对话（如果支持）。"""
        # 实现API调用逻辑
        pass
```

#### 步骤2: 修改Summarizer初始化

在 `Summarizer.__init__()` 中添加新的配置项：

```python
def __init__(
    self,
    siliconflow_api_key: str,
    prompt_dir: str = "./markdown",
    use_vision_mode: bool = False,
    text_model: str = "Qwen/Qwen2.5-7B-Instruct",
    vision_model: str = "Qwen/Qwen2-VL-72B-Instruct",
    # 新增
    llm_provider: str = "siliconflow",  # siliconflow / new_provider
    new_provider_api_key: str = "",
):
    # 初始化逻辑
    if llm_provider == "siliconflow":
        self.client = SiliconFlowClient(...)
    elif llm_provider == "new_provider":
        self.client = NewProviderClient(...)
```

#### 步骤3: 更新配置类

在 `src/config.py` 中添加新的配置项：

```python
@dataclass
class Config:
    # 现有配置...
    
    # 新增
    LLM_PROVIDER: str = "siliconflow"
    NEW_PROVIDER_API_KEY: str = ""
    NEW_PROVIDER_MODEL: str = "default-model"
```

### 3. 自定义搜索逻辑

要修改或扩展论文搜索逻辑：

#### 步骤1: 修改 `build_query()` 方法

在 `src/sniffer.py` 的 `ArXivSniffer.build_query()` 方法中添加自定义逻辑：

```python
def build_query(
    self,
    keywords: List[str],
    categories: Optional[List[str]] = None,
    search_all_fields: bool = False,
    use_or_for_categories: bool = False,
    search_strategy: str = SearchStrategy.MODERATE.value,
) -> str:
    # 现有逻辑...
    
    # 添加自定义逻辑
    # 例如: 排除某些分类
    # 例如: 添加日期范围筛选
    
    return query
```

#### 步骤2: arXiv API查询语法参考

```
基础语法:
    ti:keyword          # 标题中包含keyword
    abs:keyword         # 摘要中包含keyword
    all:keyword         # 所有字段包含keyword
    cat:cs.CL           # 属于cs.CL分类

组合逻辑:
    AND                 # 与逻辑
    OR                  # 或逻辑
    ()                  # 分组

精确匹配:
    "large language model"  # 精确短语匹配

示例:
    (ti:LLM OR abs:LLM) AND (cat:cs.CL OR cat:cs.AI)
    all:"retrieval augmented generation"
    (ti:transformer OR ti:attention) AND submittedDate:[20240101 TO *]
```

### 4. 添加新的命令行参数

要添加新的命令行参数：

#### 步骤1: 修改 `main()` 函数

在 `src/main.py` 的 `main()` 函数中添加参数定义：

```python
def main():
    parser = argparse.ArgumentParser(...)
    
    # 现有参数...
    
    # 新增参数
    parser.add_argument(
        "--new-option",
        action="store_true",
        help="新选项的说明"
    )
    parser.add_argument(
        "--new-value",
        type=str,
        default="default",
        help="新值选项的说明"
    )
    
    args = parser.parse_args()
    
    # 处理新参数
    if args.new_option:
        sentinel.config.NEW_OPTION = True
    if args.new_value:
        sentinel.config.NEW_VALUE = args.new_value
```

#### 步骤2: 更新Config类（如果需要）

如果参数对应新的配置项，在 `src/config.py` 中添加：

```python
@dataclass
class Config:
    # 现有配置...
    NEW_OPTION: bool = False
    NEW_VALUE: str = "default"
```

### 5. 扩展部署模式

要添加新的部署模式：

#### 步骤1: 添加DeployMode枚举值

在 `src/config.py` 中：

```python
class DeployMode(str, Enum):
    BUILD_ONLY = "build-only"
    PUSH_TO_BRANCH = "push-to-branch"
    GH_DEPLOY = "gh-deploy"
    NEW_MODE = "new-mode"  # 新增
```

#### 步骤2: 修改 `MkDocsPublisher.deploy()` 方法

在 `src/publisher.py` 中：

```python
def deploy(
    self,
    commit_message: str = "自动更新: 新增论文总结",
    author_name: Optional[str] = None,
    author_email: Optional[str] = None,
) -> bool:
    # 现有模式...
    
    if self.deploy_mode == "new-mode":
        print("  使用新模式部署...")
        # 实现新的部署逻辑
        return True
    
    print(f"  未知的部署模式: {self.deploy_mode}")
    return False
```

---

## 🧪 测试说明

### 测试文件位置

`src/test_arxiv_sentinel.py`

### 运行测试

```bash
# 运行所有测试
python -m pytest src/test_arxiv_sentinel.py -v

# 运行特定测试
python -m pytest src/test_arxiv_sentinel.py::TestConfig -v
```

### 测试结构

```
TestConfig                    # 配置模块测试
├── test_default_config       # 测试默认配置
├── test_from_dict            # 测试从字典加载
├── test_to_dict              # 测试转换为字典
└── test_config_manager       # 测试配置管理器

TestPaper                    # 论文数据类测试
└── test_paper_creation      # 测试Paper创建

TestSearchStrategy           # 搜索策略测试
├── test_strict_strategy     # 测试严格策略
├── test_moderate_strategy   # 测试中等策略
└── test_broad_strategy      # 测试宽松策略

TestBuildQuery               # 查询构建测试
├── test_basic_query         # 测试基础查询
├── test_with_categories     # 测试带分类查询
├── test_and_logic           # 测试AND逻辑
└── test_or_logic            # 测试OR逻辑
```

### 编写新测试

测试文件使用 `pytest` 框架，遵循以下格式：

```python
import pytest
from src.module import ClassOrFunction

class TestFeatureName:
    """功能测试类。"""
    
    def setup_method(self):
        """每个测试前执行。"""
        pass
    
    def teardown_method(self):
        """每个测试后执行。"""
        pass
    
    def test_scenario_1(self):
        """测试场景1。"""
        # 准备测试数据
        input_data = ...
        
        # 执行测试
        result = function_under_test(input_data)
        
        # 验证结果
        assert result == expected_value
    
    def test_scenario_2(self):
        """测试场景2。"""
        # 使用pytest.raises测试异常
        with pytest.raises(ValueError):
            function_that_raises()
```

### 测试最佳实践

1. **测试命名**: 使用 `test_` 前缀，描述测试内容
2. **独立性**: 每个测试应该独立，不依赖其他测试结果
3. **覆盖边界**: 测试正常情况、边界情况和错误情况
4. **清晰断言**: 断言信息应该明确，便于定位问题

---

## ❓ 常见问题

### Q1: 如何调试API调用？

**方法1: 添加调试输出**

在关键位置添加 `print()` 语句：

```python
def chat(self, prompt: str, ...) -> str:
    print(f"[DEBUG] 调用API，模型: {self.model}")
    print(f"[DEBUG] Prompt长度: {len(prompt)}")
    
    response = requests.post(...)
    
    print(f"[DEBUG] 响应状态码: {response.status_code}")
    print(f"[DEBUG] 响应内容: {response.text[:500]}")
```

**方法2: 使用日志模块**

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def chat(self, prompt: str, ...) -> str:
    logger.debug(f"调用API，模型: {self.model}")
    logger.debug(f"Prompt: {prompt[:200]}...")
```

### Q2: 如何处理API速率限制？

**方案1: 添加延迟**

```python
import time

# 在API调用之间添加延迟
for i, paper in enumerate(papers):
    if i > 0:
        time.sleep(1)  # 每秒最多1次调用
    process(paper)
```

**方案2: 捕获429错误并重试**

```python
import requests
from time import sleep

def call_api_with_retry(self, ...):
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = requests.post(...)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:  # Too Many Requests
                wait_time = 2 ** attempt  # 指数退避
                print(f"速率限制，等待 {wait_time} 秒后重试...")
                sleep(wait_time)
                continue
            raise
```

### Q3: 如何自定义MkDocs主题？

**方法1: 修改生成的配置**

编辑 `publisher.py` 中的 `_generate_mkdocs_config()` 方法：

```python
def _generate_mkdocs_config(self, site_name: str, description: str) -> str:
    return f"""site_name: {site_name}
# ... 其他配置 ...

theme:
  name: material
  features:
    - navigation.tabs
    - navigation.sections
  palette:
    - scheme: default
      primary: indigo      # 修改主色调
      accent: purple       # 修改强调色
# ...
"""
```

**方法2: 使用自定义CSS**

在MkDocs项目中添加 `docs/stylesheets/custom.css`，并在配置中引用：

```yaml
extra_css:
  - stylesheets/custom.css
```

### Q4: 如何添加新的arXiv分类？

在 `config.json` 中修改 `CATEGORIES` 配置：

```json
{
  "CATEGORIES": [
    "cs.CL",    # 计算语言学
    "cs.AI",    # 人工智能
    "cs.CV",    # 计算机视觉
    "cs.LG",    # 机器学习
    "cs.RO",    # 机器人学（新增）
    "cs.SE"     # 软件工程（新增）
  ]
}
```

**常用arXiv分类**:

| 分类 | 说明 |
|------|------|
| cs.AI | 人工智能 |
| cs.CL | 计算语言学 |
| cs.CV | 计算机视觉 |
| cs.LG | 机器学习 |
| cs.IR | 信息检索 |
| cs.RO | 机器人学 |
| cs.SE | 软件工程 |
| cs.NE | 神经和进化计算 |
| stat.ML | 统计机器学习 |

### Q5: 如何处理大PDF文件？

**方案1: 增加视觉模式页数限制**

```json
{
  "VISION_MAX_PAGES": 5,  // 从10减少到5
  "VISION_DPI": 100        // 从150降低到100
}
```

**方案2: 使用文本模式**

文本模式只提取文本，不处理图像，速度更快且不受PDF大小限制：

```json
{
  "USE_VISION_MODE": false
}
```

**方案3: 修改Prompt以处理长文本**

在 `markdown/` 目录下的Prompt模板中，添加处理长文本的指示：

```
注意：论文内容可能很长，请关注与关键词最相关的部分，
忽略与主题无关的附录、参考文献等内容。
```

---

## 📚 参考资源

### 官方文档

- **arXiv API**: [https://arxiv.org/help/api](https://arxiv.org/help/api)
- **arXiv OpenSearch**: [https://arxiv.org/help/api/user-manual](https://arxiv.org/help/api/user-manual)
- **硅基流动API**: [https://siliconflow.cn/docs](https://siliconflow.cn/docs)
- **MkDocs**: [https://www.mkdocs.org](https://www.mkdocs.org)
- **Material for MkDocs**: [https://squidfunk.github.io/mkdocs-material](https://squidfunk.github.io/mkdocs-material)

### 第三方库文档

- **requests**: [https://requests.readthedocs.io](https://requests.readthedocs.io)
- **PyMuPDF (fitz)**: [https://pymupdf.readthedocs.io](https://pymupdf.readthedocs.io)
- **pytest**: [https://docs.pytest.org](https://docs.pytest.org)

### arXiv分类参考

完整的arXiv分类列表：[https://arxiv.org/category_taxonomy](https://arxiv.org/category_taxonomy)

---

## 📄 更新日志

### v1.0.0 (当前版本)

- ✅ 基础功能：论文搜索、PDF下载、AI总结、MkDocs发布
- ✅ 多模态支持：文本模式和视觉模式
- ✅ AI筛选：基于摘要的论文相关性判断
- ✅ 灵活配置：丰富的配置项和搜索策略
- ✅ 多种部署模式：build-only、push-to-branch、gh-deploy
- ✅ 完整文档：用户文档和开发文档
- ✅ 单元测试：核心功能测试覆盖

---

**返回 [README.md](./README.md)** → 用户指南和使用说明
