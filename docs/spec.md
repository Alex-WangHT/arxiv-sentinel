# Logic SPEC: arxiv-sentinel

## 1. 项目愿景
全自动 arXiv 论文追踪系统。系统周期性执行“嗅探-筛选-总结”流水线

## 2. 技术栈约束
* **核心语言**: Python 3.10+
* **论文嗅探框架**：arxiv
* **AI 接口**: OpenAI (需支持结构化输出，使用硅基流动的API：base_url="https://api.siliconflow.cn/v1")
* **强制依赖**: FastAPI (轻量化Server框架), pdf2image (转图片)

## 3. 后台自动化流水线逻辑

### Step 1: 初始化 (Config)
1. 从`config.json`中获取初始化的信息，包括：
    - 大模型平台：
        - 访问硅基流动的secret id
    - 本地缓存：
        - arXiv论文总结的缓存文件夹路径
    - 关键词：
        - arXiv检索领域
        - 论文检索关键词
    - Abstract筛选： 
        - Abstract筛选等级
        - Abstract筛选时调用的默认模型
    - Introduction总结
        - Introduction总结时调用的多模态模型
2. 初始化导入的程序代码文件放在`./src/config.py`中。

### Step 2: 嗅探 (ArxivSniffer)
1. **多关键词检索与聚合**: 
   - 从 `config.json` 读取 `keywords` 列表。
   - 遍历关键词列表，依次调用 arXiv API 获取最新论文。
   - **去重与合并**: 使用 `arxiv_id` 作为唯一键进行聚合。若同一篇论文被多个关键词命中，系统必须将其 `keywords` 字段进行并集处理（例如：同时记录为 `["LLM", "Agent"]`），确保单篇论文对象包含所有触发它的原始标签。
2. **增量过滤 (Incremental Filtering)**:
   - **事实来源**: 优先检查 `cache/repo/history.json` 中的 `processed_ids`。
   - **辅助校验**: 同时扫描 `cache/repo/papers/` 文件夹下的 Markdown 文件名称，过滤掉历史上已经处理过的 `arxiv_id`。如果历史上处理过的`arxiv_id`更新版本，保留最新版，作为未曾处理过的论文。
   - 仅保留未曾处理过的新论文进入 Pipeline 下一阶段。
3. **合规性频率限制**: 
   - 严格遵守 arXiv 官方爬虫协议，在每个关键词的 API 请求之间强制执行 `time.sleep(3)`，防止 IP 被暂时封禁。
4. **代码实现**: 
   - 核心逻辑封装在 `./src/sniffer.py` 中，需确保输出的 `PaperObject` 包含聚合后的完整元数据。

### Step 3: Abstract的AI筛选 (AbstractFilter)
1. 获取`arxiv_id`对应论文的`title`和`abstract`
2. 将 `keywords`,`title`和`abstract`交给AI，让AI评价相关度
3. 相关度分为`IRRELEVANT`,`LOW`,`MEDIUM`,`HIGH`，AI返回的结果应该是：`{"score": "HIGH", "reason": "..."}`
4. 根据`config.json`提取相关度阈值，将不相关的论文对应的`arxiv_id`筛选掉
5. 将剩下的`arxiv_id`对应的论文PDF下载到缓存文件夹中
6. 这里需要实现`system prompt`，`user prompt`和程序的解耦，prompt单独存放在`./prompts/abstract_filter`中，代码文件放在`./src/abstract_filter.py`中


