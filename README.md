# arXiv Sentinel

🚀 自动化 arXiv 论文嗅探、智能总结与发布系统。通过 GitHub Actions 定时执行，让你始终站在研究领域的前沿。

## ✨ 功能特性

- **智能嗅探**: 基于关键词和分类自动搜索 arXiv 最新论文
- **AI 筛选**: 使用大语言模型基于摘要判断论文相关性
- **多维度总结**: 从摘要、技术路线、方法论、实验方案、研究逻辑等角度全面分析
- **多模态支持**: 支持文本模式和视觉模式（将 PDF 转为图像后使用视觉模型分析）
- **自动发布**: 自动生成 MkDocs 网站并部署到 GitHub Pages
- **灵活配置**: 丰富的配置项，满足不同使用场景
- **本地预览**: 支持启动本地服务器预览网站效果

## 📋 目录

- [快速开始](#快速开始)
- [安装依赖](#安装依赖)
- [配置说明](#配置说明)
- [命令行使用](#命令行使用)
- [GitHub Actions 部署](#github-actions-部署)
- [搜索策略](#搜索策略)
- [部署模式](#部署模式)
- [常见问题](#常见问题)
- [开发指南](./docs/DEVELOPMENT.md)

---

## 🚀 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/your-username/arxiv-sentinel.git
cd arxiv-sentinel
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置 API 密钥

复制配置示例文件并编辑：

```bash
cp config.json.example config.json
```

编辑 `config.json`，填入你的 API 密钥：

```json
{
  "SILICONFLOW_API_KEY": "your_siliconflow_api_key_here",
  ...
}
```

或者通过环境变量设置（推荐用于 GitHub Actions）：

```bash
export SILICONFLOW_API_KEY="your_api_key"
```

### 4. 运行程序

```bash
# 基本运行（使用默认配置）
python -m src.main

# 自定义关键词
python -m src.main -k LLM "large language model" RAG -n 15

# 使用视觉模式（多模态模型）
python -m src.main --use-vision

# 本地预览
python -m src.main --serve --port 8000
```

---

## 📦 安装依赖

### Python 版本要求

- Python 3.8+

### 依赖列表

```txt
requests>=2.28.0
PyMuPDF>=1.23.0
mkdocs>=1.5.0
mkdocs-material>=9.0.0
pymdown-extensions>=10.0
```

### 安装命令

```bash
pip install -r requirements.txt
```

---

## ⚙️ 配置说明

配置文件 `config.json` 包含所有可配置项。以下是详细说明：

### API 配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `SILICONFLOW_API_KEY` | string | `""` | **必需** 硅基流动 API 密钥 |
| `SILICONFLOW_MODEL` | string | `"Qwen/Qwen2.5-7B-Instruct"` | 文本模型名称 |

### 搜索配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `KEYWORDS` | list[string] | `["LLM", "large language model", "transformer"]` | 搜索关键词列表 |
| `CATEGORIES` | list[string] | `["cs.CL", "cs.AI", "cs.CV", "cs.LG"]` | arXiv 分类列表 |
| `MAX_RESULTS_PER_SEARCH` | int | `10` | 每次搜索的最大结果数 |
| `SEARCH_STRATEGY` | string | `"moderate"` | 搜索策略：`strict`/`moderate`/`broad` |
| `SEARCH_ALL_FIELDS` | bool | `false` | 是否搜索所有字段 |
| `USE_OR_FOR_CATEGORIES` | bool | `false` | 关键词和分类的逻辑关系 |

### 模型配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `ENABLE_LLM_FILTER` | bool | `true` | 是否启用 AI 论文筛选 |
| `USE_VISION_MODE` | bool | `false` | 是否使用视觉模式 |
| `VISION_MODEL` | string | `"Qwen/Qwen2-VL-72B-Instruct"` | 视觉模型名称 |
| `VISION_MAX_PAGES` | int | `10` | 视觉模式最大转换页数 |
| `VISION_DPI` | int | `150` | 视觉模式图像分辨率 |
| `API_TIMEOUT` | int | `180` | API 请求超时时间（秒） |
| `API_MAX_RETRIES` | int | `3` | API 最大重试次数 |

### MkDocs 配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `SITE_NAME` | string | `"arXiv Sentinel"` | 网站名称 |
| `SITE_DESCRIPTION` | string | `"每日arXiv论文总结"` | 网站描述 |
| `MKDOCS_REPO_URL` | string | `""` | MkDocs 仓库 URL（部署时必需） |
| `MKDOCS_REPO_BRANCH` | string | `"gh-pages"` | 目标分支名称 |
| `MKDOCS_WORKING_DIR` | string | `"./mkdocs_repo"` | 工作目录 |
| `MKDOCS_DEPLOY_MODE` | string | `"build-only"` | 部署模式 |

### Git 配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `GIT_COMMIT_MESSAGE` | string | `"自动更新: 新增{count}篇论文总结"` | 提交消息模板 |
| `GIT_AUTHOR_NAME` | string | `"arXiv Sentinel Bot"` | 提交者名称 |
| `GIT_AUTHOR_EMAIL` | string | `"bot@arxiv-sentinel.local"` | 提交者邮箱 |

### 路径配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `PDF_CACHE_DIR` | string | `"./pdf_cache"` | PDF 缓存目录 |
| `MARKDOWN_OUTPUT_DIR` | string | `"./output/markdown"` | Markdown 输出目录 |
| `PROMPT_DIR` | string | `"./markdown"` | Prompt 模板目录 |

---

## 🖥️ 命令行使用

### 基本命令

```bash
python -m src.main [OPTIONS]
```

### 可用参数

#### 配置相关

| 参数 | 缩写 | 类型 | 说明 |
|------|------|------|------|
| `--config` | `-c` | string | 配置文件路径（默认：`./config.json`） |
| `--keywords` | `-k` | string... | 搜索关键词（覆盖配置文件） |
| `--max-results` | `-n` | int | 最大搜索结果数（覆盖配置文件） |

#### 模式控制

| 参数 | 说明 |
|------|------|
| `--no-filter` | 禁用 AI 论文筛选 |
| `--use-vision` | 启用视觉模式（多模态模型处理 PDF 图像） |
| `--no-vision` | 禁用视觉模式（使用文本提取） |

#### 搜索策略

| 参数 | 说明 |
|------|------|
| `--search-strict` | 使用严格搜索策略（精确短语匹配） |
| `--search-moderate` | 使用中等搜索策略（默认） |
| `--search-broad` | 使用宽松搜索策略 |
| `--use-or-categories` | 使用 OR 连接关键词和分类（更宽松） |
| `--use-and-categories` | 使用 AND 连接关键词和分类（更严格，默认） |
| `--search-all-fields` | 搜索所有字段（更宽松） |
| `--search-title-abstract` | 仅搜索标题和摘要（更严格，默认） |

#### 服务器预览

| 参数 | 缩写 | 类型 | 说明 |
|------|------|------|------|
| `--serve` | - | flag | 启动 MkDocs 本地服务器预览 |
| `--port` | `-p` | int | 本地服务器端口（默认：`8000`） |

### 使用示例

#### 基本运行

```bash
# 使用默认配置运行
python -m src.main

# 指定配置文件
python -m src.main --config ./my-config.json
```

#### 自定义搜索

```bash
# 自定义关键词
python -m src.main -k LLM "large language model" RAG "retrieval augmented"

# 自定义最大结果数
python -m src.main -n 20

# 组合使用
python -m src.main -k LLM RAG -n 15
```

#### 搜索策略

```bash
# 严格搜索（精确短语匹配）
python -m src.main --search-strict

# 宽松搜索
python -m src.main --search-broad

# 使用 OR 逻辑（更宽松）
python -m src.main --use-or-categories

# 搜索所有字段
python -m src.main --search-all-fields

# 组合策略（最宽松）
python -m src.main --search-broad --use-or-categories --search-all-fields

# 组合策略（最严格）
python -m src.main --search-strict --use-and-categories --search-title-abstract
```

#### 模型模式

```bash
# 启用视觉模式（使用多模态模型）
python -m src.main --use-vision

# 禁用视觉模式（使用文本提取）
python -m src.main --no-vision

# 禁用 AI 筛选
python -m src.main --no-filter
```

#### 本地预览

```bash
# 启动本地服务器（默认端口 8000）
python -m src.main --serve

# 指定端口
python -m src.main --serve --port 8080

# 访问 http://localhost:8000 预览
```

#### 完整示例

```bash
# 完整配置示例
python -m src.main \
  --config ./config.json \
  -k LLM "large language model" RAG "multi-agent" \
  -n 20 \
  --search-moderate \
  --use-and-categories \
  --search-title-abstract \
  --use-vision \
  --no-filter
```

---

## 🔄 GitHub Actions 部署

### 1. 准备工作

1. 创建一个 GitHub 仓库用于存放 MkDocs 网站
2. 获取硅基流动 API 密钥
3. 获取 GitHub Personal Access Token（用于推送）

### 2. 设置 Secrets

在你的 arXiv Sentinel 仓库中设置以下 Secrets：

| Secret 名称 | 说明 |
|-------------|------|
| `SILICONFLOW_API_KEY` | 硅基流动 API 密钥 |
| `MKDOCS_REPO_URL` | MkDocs 仓库的 HTTPS URL（如 `https://github.com/username/repo.git`） |
| `PERSONAL_ACCESS_TOKEN` | GitHub Personal Access Token（需要 repo 权限） |

### 3. 创建 Workflow 文件

在 `.github/workflows/` 目录下创建 `arxiv-sentinel.yml`：

```yaml
name: arXiv Sentinel Daily Run

on:
  schedule:
    # 每天 UTC 时间 00:00 运行
    - cron: '0 0 * * *'
  workflow_dispatch:
    # 允许手动触发

jobs:
  run-sentinel:
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'
          cache: 'pip'
          
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          
      - name: Create config file
        env:
          SILICONFLOW_API_KEY: ${{ secrets.SILICONFLOW_API_KEY }}
          MKDOCS_REPO_URL: ${{ secrets.MKDOCS_REPO_URL }}
        run: |
          cat > config.json << EOF
          {
            "SILICONFLOW_API_KEY": "${{ secrets.SILICONFLOW_API_KEY }}",
            "SILICONFLOW_MODEL": "Qwen/Qwen2.5-7B-Instruct",
            "KEYWORDS": ["LLM", "large language model", "transformer", "RAG", "agent"],
            "CATEGORIES": ["cs.CL", "cs.AI", "cs.CV", "cs.LG", "cs.IR"],
            "MAX_RESULTS_PER_SEARCH": 15,
            "ENABLE_LLM_FILTER": true,
            "USE_VISION_MODE": false,
            "SEARCH_STRATEGY": "moderate",
            "USE_OR_FOR_CATEGORIES": false,
            "SEARCH_ALL_FIELDS": false,
            "MKDOCS_REPO_URL": "${{ secrets.MKDOCS_REPO_URL }}",
            "MKDOCS_DEPLOY_MODE": "push-to-branch",
            "MKDOCS_REPO_BRANCH": "gh-pages",
            "API_TIMEOUT": 180,
            "API_MAX_RETRIES": 3
          }
          EOF
          
      - name: Run arXiv Sentinel
        env:
          GITHUB_TOKEN: ${{ secrets.PERSONAL_ACCESS_TOKEN }}
        run: |
          python -m src.main
          
      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: generated-markdown
          path: output/markdown/
        if: always()
```

### 4. 配置 MkDocs 仓库

确保你的 MkDocs 仓库已启用 GitHub Pages：

1. 进入仓库 Settings
2. 选择 Pages 选项
3. Source 选择 `Deploy from a branch`
4. Branch 选择 `gh-pages`（或你配置的分支）
5. 点击 Save

### 5. 手动触发运行

1. 进入仓库 Actions 页面
2. 选择 "arXiv Sentinel Daily Run" workflow
3. 点击 "Run workflow" 按钮
4. 点击 "Run workflow" 确认

---

## 🎯 搜索策略

### 三种搜索策略

| 策略 | 说明 | 查询示例 | 适用场景 |
|------|------|----------|----------|
| **strict** | 精确短语匹配 | `ti:"large language model"` | 需要精确匹配特定术语 |
| **moderate** | 普通匹配（默认） | `ti:LLM OR abs:LLM` | 大多数常规搜索场景 |
| **broad** | 宽松匹配 | `all:LLM` | 需要尽可能多的结果时 |

### 搜索字段

| 配置 | 查询示例 | 说明 |
|------|----------|------|
| `SEARCH_ALL_FIELDS=false`（默认） | `ti:LLM OR abs:LLM` | 仅搜索标题和摘要 |
| `SEARCH_ALL_FIELDS=true` | `all:LLM` | 搜索所有字段（标题、摘要、作者、分类等） |

### 逻辑关系

| 配置 | 查询示例 | 说明 |
|------|----------|------|
| `USE_OR_FOR_CATEGORIES=false`（默认） | `(关键词) AND (分类)` | 必须同时满足关键词和分类（更严格） |
| `USE_OR_FOR_CATEGORIES=true` | `(关键词) OR (分类)` | 满足关键词或分类即可（更宽松） |

### 搜索策略组合示例

#### 最严格（高精确度）

```json
{
  "SEARCH_STRATEGY": "strict",
  "USE_OR_FOR_CATEGORIES": false,
  "SEARCH_ALL_FIELDS": false
}
```

查询逻辑：`(精确匹配关键词) AND (属于指定分类)`

#### 默认（平衡）

```json
{
  "SEARCH_STRATEGY": "moderate",
  "USE_OR_FOR_CATEGORIES": false,
  "SEARCH_ALL_FIELDS": false
}
```

查询逻辑：`(关键词匹配标题或摘要) AND (属于指定分类)`

#### 最宽松（高召回率）

```json
{
  "SEARCH_STRATEGY": "broad",
  "USE_OR_FOR_CATEGORIES": true,
  "SEARCH_ALL_FIELDS": true
}
```

查询逻辑：`(关键词匹配所有字段) OR (属于指定分类)`

---

## 📤 部署模式

### 三种部署模式

| 模式 | 值 | 说明 | 适用场景 |
|------|-----|------|----------|
| **build-only** | `"build-only"` | 仅本地构建，不执行 Git 操作 | 本地开发、测试 |
| **push-to-branch** | `"push-to-branch"` | 推送到指定分支 | 需要精确控制部署流程 |
| **gh-deploy** | `"gh-deploy"` | 使用 `mkdocs gh-deploy` 命令 | 标准 GitHub Pages 部署 |

### build-only 模式

```json
{
  "MKDOCS_DEPLOY_MODE": "build-only"
}
```

行为：
- 只执行 `mkdocs build`
- 生成的网站文件在 `site/` 目录
- 不执行任何 Git 操作

适用场景：
- 本地开发测试
- 手动部署到其他平台

### push-to-branch 模式

```json
{
  "MKDOCS_DEPLOY_MODE": "push-to-branch",
  "MKDOCS_REPO_URL": "https://github.com/username/repo.git",
  "MKDOCS_REPO_BRANCH": "gh-pages"
}
```

行为：
1. 克隆或拉取指定仓库
2. 复制 Markdown 文件
3. 更新导航和首页
4. 构建 MkDocs 网站
5. 提交更改
6. 推送到指定分支

适用场景：
- 需要精确控制部署流程
- 需要自定义提交信息
- 多分支部署

### gh-deploy 模式

```json
{
  "MKDOCS_DEPLOY_MODE": "gh-deploy",
  "MKDOCS_REPO_URL": "https://github.com/username/repo.git"
}
```

行为：
- 调用 `mkdocs gh-deploy` 命令
- 自动构建并部署到 `gh-pages` 分支
- MkDocs 自动处理历史记录

适用场景：
- 标准 GitHub Pages 部署
- 简单部署需求

---

## ❓ 常见问题

### Q1: API 密钥如何获取？

**硅基流动 API 密钥：**
1. 访问 [https://siliconflow.cn](https://siliconflow.cn)
2. 注册账号并登录
3. 在控制台获取 API Key

**GitHub Personal Access Token：**
1. 访问 [https://github.com/settings/tokens](https://github.com/settings/tokens)
2. 点击 "Generate new token"
3. 选择 `repo` 权限
4. 生成并保存 Token

### Q2: 搜索结果不相关怎么办？

可能的原因和解决方案：

**1. 关键词和分类使用 OR 逻辑**
```json
{
  "USE_OR_FOR_CATEGORIES": false  // 改为 false，使用 AND 逻辑
}
```

**2. 搜索策略太宽松**
```json
{
  "SEARCH_STRATEGY": "strict",  // 改为 strict 或 moderate
  "SEARCH_ALL_FIELDS": false     // 改为 false，仅搜索标题摘要
}
```

**3. 启用 AI 筛选**
```json
{
  "ENABLE_LLM_FILTER": true  // 启用后会在下载前过滤不相关论文
}
```

### Q3: API 请求超时怎么办？

调整超时和重试配置：

```json
{
  "API_TIMEOUT": 300,      // 增加超时时间（秒）
  "API_MAX_RETRIES": 5     // 增加重试次数
}
```

### Q4: 视觉模式和文本模式有什么区别？

| 特性 | 文本模式 | 视觉模式 |
|------|----------|----------|
| 处理方式 | 从 PDF 提取文本 | 将 PDF 转为图像 |
| 模型类型 | 普通文本模型 | 多模态视觉模型 |
| 优点 | 速度快、成本低 | 能理解图表、公式 |
| 缺点 | 可能丢失格式信息 | 速度慢、成本高 |
| 适用 | 大多数论文 | 含大量图表的论文 |

### Q5: 如何选择模型？

**免费文本模型：**
- `Qwen/Qwen2.5-7B-Instruct`（推荐，免费）
- `THUDM/glm-4-9b-chat`

**付费文本模型：**
- `deepseek-ai/deepseek-v3`
- `Qwen/Qwen2.5-14B-Instruct`

**视觉模型：**
- `Qwen/Qwen2-VL-72B-Instruct`（推荐）
- `deepseek-ai/deepseek-vl2`

### Q6: GitHub Actions 运行失败怎么办？

检查以下几点：

1. **Secrets 是否正确设置**
   - 检查 `SILICONFLOW_API_KEY`、`MKDOCS_REPO_URL`、`PERSONAL_ACCESS_TOKEN`
   - 确保 Token 有足够权限

2. **API 配额是否充足**
   - 检查硅基流动账户余额
   - 检查 API 调用频率限制

3. **查看日志**
   - 进入 Actions 页面
   - 点击失败的运行
   - 查看详细日志定位问题

### Q7: 生成的内容有乱码怎么办？

这通常是 PDF 文本提取的问题。解决方案：

1. **启用视觉模式**
```json
{
  "USE_VISION_MODE": true
}
```

2. **检查 Prompt 模板**
   - 确保 `markdown/` 目录下的模板文件编码正确（UTF-8）

### Q8: 如何自定义总结模板？

编辑 `markdown/` 目录下的 Prompt 模板文件：

| 文件 | 用途 |
|------|------|
| `summary_prompt.txt` | 整体总结 Prompt |
| `technical_route_prompt.txt` | 技术路线分析 Prompt |
| `methodology_prompt.txt` | 方法论分析 Prompt |
| `experiment_prompt.txt` | 实验方案分析 Prompt |
| `introduction_prompt.txt` | Introduction 逻辑分析 Prompt |
| `paper_template.md` | 输出 Markdown 模板 |

修改这些文件来自定义 AI 的分析角度和输出格式。

---

## 📚 相关链接

- **arXiv API 文档**: [https://arxiv.org/help/api](https://arxiv.org/help/api)
- **硅基流动 API**: [https://siliconflow.cn](https://siliconflow.cn)
- **MkDocs 文档**: [https://www.mkdocs.org](https://www.mkdocs.org)
- **Material for MkDocs**: [https://squidfunk.github.io/mkdocs-material](https://squidfunk.github.io/mkdocs-material)

---

## 📄 许可证

MIT License

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

---

**下一站：[开发指南](./docs/DEVELOPMENT.md)** → 了解如何扩展和开发 arXiv Sentinel
