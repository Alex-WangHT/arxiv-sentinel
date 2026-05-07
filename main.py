"""arxiv-sentinel entry point — see SPEC.md §4 / §5.1."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.config_loader import ConfigLoader
from src.pipeline import PipelineOrchestrator


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="arxiv-sentinel pipeline runner")
    parser.add_argument("--config", default="config.json", help="路径：config.json")
    parser.add_argument("-v", "--verbose", action="store_true", help="开启 DEBUG 日志")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    _setup_logging(args.verbose)

    config = ConfigLoader(Path(args.config)).load()
    orchestrator = PipelineOrchestrator(config)
    orchestrator.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
