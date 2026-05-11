import asyncio
import json
import uuid
from pathlib import Path

from fastapi import FastAPI

from src.config import Config
from src.pipeline import Pipeline

app = FastAPI(title="arxiv-sentinel", version="0.1.0")

_pipeline: Pipeline | None = None


def _get_pipeline() -> Pipeline:
    """懒加载 Pipeline 实例，首次调用时从配置文件初始化"""
    global _pipeline
    if _pipeline is None:
        config = Config.from_file()
        _pipeline = Pipeline(config)
    return _pipeline


_run_id: str | None = None


@app.post("/api/pipeline/run")
async def run_pipeline():
    """异步启动流水线，在线程池中执行同步的 pipeline.run()，立即返回运行 ID"""
    global _run_id
    pipeline = _get_pipeline()
    _run_id = str(uuid.uuid4())
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, pipeline.run)
    return {"run_id": _run_id, "status": "running"}


@app.get("/api/pipeline/status")
async def get_pipeline_status():
    """获取流水线当前状态及最近一次运行的摘要信息"""
    pipeline = _get_pipeline()
    return pipeline.get_status()


@app.get("/api/reports/latest")
async def get_latest_report():
    """扫描报告目录，返回日期最新的报告内容；无报告时返回错误提示"""
    pipeline = _get_pipeline()
    reports_dir = Path(pipeline.config.output_dir) / "reports"

    if not reports_dir.exists():
        return {"error": "暂无报告"}

    json_files = sorted(reports_dir.glob("*.json"), key=lambda f: f.stem, reverse=True)
    if not json_files:
        return {"error": "暂无报告"}

    latest = json_files[0]
    with open(latest, encoding="utf-8") as f:
        return json.load(f)
