# arXiv Sentinel

🚀 自动化 arXiv 论文嗅探、智能分析与筛选系统。基于领域规则自动获取最新论文，使用大语言模型评估相关性，帮助你高效追踪研究前沿。

## ✨ 功能特性

- **智能嗅探**: 基于领域规则自动搜索 arXiv 最新论文，支持多分类并发获取
- **灵活筛选**: 支持 `accept_all` 和 `categories_filter` 两种模式，实现精确的交叉分类筛选
- **AI 分析**: 使用大语言模型评估论文相关性，提取核心方法和关键词
- **历史去重**: 自动记录已处理论文，避免重复分析
- **结果持久化**: 将分析结果保存为 JSON 格式，便于后续处理

## 📋 目录

- [快速开始](#快速开始)
- [安装依赖](#安装依赖)
- [配置说明](#配置说明)
- [核心概念](#核心概念)
- [使用方法](#使用方法)
- [项目结构](#项目结构)
- [常见问题](#常见问题)

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

编辑 `config.json`，填入你的硅基流动 API 密钥：

```json
{
  "siliconflow_api_key": "your_siliconflow_api_key_here",
  ...
}
```

### 4. 运行程序

```bash
# 使用默认配置运行
python -m src.pipeline
```

---

## 📦 安装依赖

### Python 版本要求

- Python 3.8+

### 依赖列表

```txt
arxiv>=2.1.0
openai>=1.0.0
fastapi>=0.100.0
uvicorn>=0.20.0
pdf2image>=1.16.0
aiohttp>=3.9.0
```

### 安装命令

```bash
pip install -r requirements.txt
```

---

## ⚙️ 配置说明

配置文件 `config.json` 包含所有可配置项。以下是详细说明：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `categories` | list[string] | - | **必需** arXiv 分类列表（如 `["cs.CV", "cs.AI"]`） |
| `keywords` | list[string] | - | **必需** 搜索关键词列表 |
| `domain_rules` | list[object] | - | **必需** 领域筛选规则列表 |
| `relevance_threshold` | string | `"MEDIUM"` | 相关性阈值：`IRRELEVANT`/`LOW`/`MEDIUM`/`HIGH` |
| `siliconflow_api_key` | string | - | **必需** 硅基流动 API 密钥 |
| `siliconflow_model` | string | `"deepseek-ai/DeepSeek-V4-Flash"` | LLM 模型名称 |
| `max_results_per_category` | int | `50` | 每个分类的最大结果数（1-200） |
| `output_dir` | string | `"./output"` | 输出目录 |
| `prompts_dir` | string | `"./prompts"` | Prompt 模板目录 |
| `log_level` | string | `"INFO"` | 日志级别：`DEBUG`/`INFO`/`WARNING`/`ERROR` |
| `history_file` | string | `"./output/history.json"` | 历史记录文件路径 |

### 领域规则配置

`domain_rules` 定义了每个 arXiv 分类的抓取策略：

```json
{
  "domain_rules": [
    {
      "category": "cs.RO",
      "mode": "accept_all"
    },
    {
      "category": "cs.CV",
      "mode": "categories_filter",
      "filter_categories": ["cs.AI", "cs.CL", "cs.RO", "cs.LG"]
    }
  ]
}
```

**两种模式说明**：

| 模式 | 说明 |
|------|------|
| `accept_all` | 接受该分类下的所有论文 |
| `categories_filter` | 交叉分类筛选：论文除了属于本分类外，还需至少属于 `filter_categories` 中的一个分类 |

---

## 🎯 核心概念

### 领域筛选规则

`categories_filter` 模式实现了智能的交叉分类筛选：

- **场景**：当你关注 `cs.CV`（计算机视觉）领域，但只对与 `cs.AI`（人工智能）、`cs.CL`（计算语言学）等交叉的论文感兴趣时
- **逻辑**：如果论文只有本领域分类，保留；如果有其他领域分类，至少有一个额外分类在 `filter_categories` 中才保留

### 相关性评估

系统使用大语言模型对每篇论文进行综合分析：

| 输出字段 | 说明 |
|----------|------|
| `score` | 相关度评分（HIGH/MEDIUM/LOW/IRRELEVANT） |
| `reason` | AI 给出的评估理由 |
| `core_methods` | 论文的核心技术方法 |
| `problem` | 论文试图解决的问题 |
| `keywords` | 提取的关键词（最多5个） |

---

## 🖥️ 使用方法

### 基本运行

```bash
# 使用默认配置文件
python -m src.pipeline

# 指定配置文件
python -m src.pipeline --config ./my-config.json
```

### 测试组件

```bash
# 测试嗅探器
python -m src.sniffer

# 测试分析器
python -m src.paper_analyzer

# 测试配置加载
python -m src.config
```

### 输出结果

分析结果保存在 `output/` 目录下：

- `analysis_results_YYYY-MM-DD.json`: 每日分析结果
- `history.json`: 已处理论文 ID 记录
- `sentinel.log`: 运行日志

---

## 📁 项目结构

```
arxiv-sentinel/
├── prompts/
│   └── paper_analyzer/
│       ├── system.md    # 系统提示词
│       └── user.md      # 用户提示词模板
├── src/
│   ├── __init__.py
│   ├── config.py        # 配置管理
│   ├── llm_client.py    # LLM 客户端
│   ├── models.py        # 数据模型
│   ├── paper_analyzer.py # 论文分析器
│   ├── pipeline.py      # 主流水线
│   └── sniffer.py       # arXiv 嗅探器
├── config.json          # 配置文件
├── requirements.txt     # 依赖列表
└── README.md            # 项目说明
```

### 模块说明

| 模块 | 职责 |
|------|------|
| `config.py` | 配置加载、校验和日志初始化 |
| `models.py` | 数据模型定义（Paper、DomainRule、AnalysisResult 等） |
| `sniffer.py` | arXiv 论文搜索和分类筛选 |
| `paper_analyzer.py` | 基于 LLM 的论文相关性分析 |
| `llm_client.py` | 大语言模型 API 客户端 |
| `pipeline.py` | 整合嗅探、分析、筛选和保存的完整流程 |

---

## ❓ 常见问题

### Q1: API 密钥如何获取？

**硅基流动 API 密钥：**
1. 访问 [https://siliconflow.cn](https://siliconflow.cn)
2. 注册账号并登录
3. 在控制台获取 API Key

### Q2: 如何配置领域规则？

```json
{
  "domain_rules": [
    {
      "category": "cs.AI",
      "mode": "accept_all"
    },
    {
      "category": "cs.CV",
      "mode": "categories_filter",
      "filter_categories": ["cs.AI", "cs.LG"]
    }
  ]
}
```

### Q3: 如何调整相关性阈值？

```json
{
  "relevance_threshold": "HIGH"  // 更严格，只保留高相关论文
}
```

可用值：`IRRELEVANT` < `LOW` < `MEDIUM` < `HIGH`

### Q4: 搜索结果不相关怎么办？

1. **调整领域规则**：使用 `categories_filter` 模式进行交叉筛选
2. **提高阈值**：将 `relevance_threshold` 设置为 `HIGH`
3. **优化关键词**：添加更精确的关键词

### Q5: 如何清理历史记录？

删除 `output/history.json` 文件，下次运行将重新处理所有论文。

---

## 📚 相关链接

- **arXiv API 文档**: [https://arxiv.org/help/api](https://arxiv.org/help/api)
- **硅基流动 API**: [https://siliconflow.cn](https://siliconflow.cn)

---

## 📄 许可证

MIT License

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！