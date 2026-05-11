import argparse
import sys
import logging

from src.config import Config
from src.pipeline import Pipeline
from src.server import app


logger = logging.getLogger(__name__)


def run_pipeline(config_path: str) -> None:
    """CLI 模式：加载配置并执行流水线"""
    config = Config.from_file(config_path)
    pipeline = Pipeline(config)
    try:
        result = pipeline.run()
        logger.info("流水线执行成功: 日期=%s, 获取=%d, 保留=%d", result.date, result.total_fetched, result.total_filtered)
    except Exception:
        logger.error("流水线执行失败")
        sys.exit(1)


def serve(host: str, port: int, config_path: str) -> None:
    """启动 FastAPI 服务"""
    import uvicorn
    # 预加载配置，确保校验通过
    Config.from_file(config_path)
    uvicorn.run(app, host=host, port=port)


def main():
    parser = argparse.ArgumentParser(description="arxiv-sentinel: 全自动 arXiv 论文追踪系统")
    subparsers = parser.add_subparsers(dest="command")

    # run 子命令
    run_parser = subparsers.add_parser("run", help="执行流水线")
    run_parser.add_argument("--config", default="./config.json", help="配置文件路径")

    # serve 子命令
    serve_parser = subparsers.add_parser("serve", help="启动 FastAPI 服务")
    serve_parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    serve_parser.add_argument("--port", type=int, default=8000, help="监听端口")
    serve_parser.add_argument("--config", default="./config.json", help="配置文件路径")

    args = parser.parse_args()

    if args.command == "run":
        run_pipeline(args.config)
    elif args.command == "serve":
        serve(args.host, args.port, args.config)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
