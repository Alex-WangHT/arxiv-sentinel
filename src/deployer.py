"""GithubDeployer — Git 自动化提交（SPEC §4 Step 6 / §5.3）。"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class GithubDeployer:
    def __init__(
        self,
        output_dir: Path,
        cache_dir: Path,
        remote: str = "origin",
        branch: str = "main",
        commit_prefix: str = "docs(papers): auto-publish",
        cleanup_cache: bool = True,
    ) -> None:
        self.output_dir = output_dir
        self.cache_dir = cache_dir
        self.remote = remote
        self.branch = branch
        self.commit_prefix = commit_prefix
        self.cleanup_cache = cleanup_cache

    def deploy(self, new_files: list[Path]) -> bool:
        """add → commit → pull --rebase → push → 清理 cache。返回是否成功推送。"""
        if not new_files:
            logger.info("no new files to deploy")
            return False
        self._git_add(new_files)
        self._git_commit(new_files)
        self._git_pull_rebase()
        pushed = self._git_push()
        if pushed and self.cleanup_cache:
            self._cleanup_cache()
        return pushed

    def _git_add(self, files: list[Path]) -> None:
        subprocess.run(["git", "add", *map(str, files)], check=True)

    def _git_commit(self, files: list[Path]) -> None:
        msg = f"{self.commit_prefix}: {len(files)} paper(s)"
        subprocess.run(["git", "commit", "-m", msg], check=True)

    def _git_pull_rebase(self) -> None:
        subprocess.run(["git", "pull", "--rebase", self.remote, self.branch], check=True)

    def _git_push(self) -> bool:
        result = subprocess.run(["git", "push", self.remote, self.branch])
        return result.returncode == 0

    def _cleanup_cache(self) -> None:
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir, ignore_errors=True)
