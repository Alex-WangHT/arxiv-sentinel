---
title: {{ title_safe }}
date: {{ date }}
arxiv_id: "{{ arxiv_id }}"
categories: {{ categories | tojson }}
keywords: {{ keywords | tojson }}
ai_score: {{ ai_score }}
url: "{{ url }}"
authors: {{ authors | tojson }}
---

# {{ title }}

> arXiv: [{{ arxiv_id }}]({{ url }}) · 作者：{{ authors | join(", ") }}

## 原始摘要

{{ abstract }}

## AI 总结

### 相关工作 (Related Work)
{{ relative_work }}

### 导言逻辑 (Introduction)
{{ intro_summary }}

### 方法论 (Methodology)
{{ methodology }}

### 技术路线 (Technical Route)
{{ technical_route_text }}

```mermaid
{{ mermaid }}
```

### 实验与结果 (Experiments)
{{ experiments }}
