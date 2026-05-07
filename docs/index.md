# arXiv Sentinel

全自动 arXiv 论文追踪、AI 总结与发布系统。系统按"嗅探 → 摘要筛 → 导言筛 → 多模态总结 → 发布"五阶段流水线运转，每篇被收录的论文都有一份独立的 Markdown 总结存放于 [papers/](papers/) 目录下。

## 工作流概览

1. **嗅探**：依据订阅关键词查询 arXiv API，按 `arxiv_id` 去重并对历史记录做增量过滤。
2. **摘要筛**：让 AI 对 `title + abstract` 与关键词的相关度打分（IRRELEVANT / LOW / MEDIUM / HIGH）。
3. **导言筛**：双栏裁剪提取 PDF 前 2-3 页 Introduction，再次让 AI 评估创新性与质量。
4. **总结**：将 PDF 前 5 页转为图片送至多模态模型，回填到标准 Jinja2 模板。
5. **发布**：`git pull --rebase` 后推送，触发 GitHub Actions 完成 MkDocs 构建。

## 浏览论文

请前往 [papers/](papers/) 查看全部 AI 总结。每篇文档头部带有 YAML Front Matter，可被 MkDocs 用于分类、标签与搜索。
