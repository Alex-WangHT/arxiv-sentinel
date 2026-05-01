import os
import re
import shutil
import subprocess
from typing import Optional, List
from datetime import datetime
from urllib.parse import urlparse, urlunparse


class MkDocsPublisher:
    def __init__(
        self,
        working_dir: str = "./mkdocs_repo",
        repo_url: str = "",
        repo_branch: str = "gh-pages",
        deploy_mode: str = "build-only",
    ):
        self.working_dir = working_dir
        self.repo_url = repo_url
        self.repo_branch = repo_branch
        self.deploy_mode = deploy_mode

        self.docs_dir = os.path.join(working_dir, "docs")
        self.mkdocs_yml_path = os.path.join(working_dir, "mkdocs.yml")
        self.site_dir = os.path.join(working_dir, "site")

    def _run_git_command(self, args: List[str], cwd: Optional[str] = None) -> tuple:
        cmd = ["git"] + args
        cwd = cwd or self.working_dir

        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                check=True,
            )
            return True, result.stdout, result.stderr
        except subprocess.CalledProcessError as e:
            return False, e.stdout, e.stderr

    def _get_authenticated_url(self) -> str:
        if not self.repo_url:
            return ""

        github_token = os.environ.get("GITHUB_TOKEN")
        if not github_token:
            return self.repo_url

        parsed = urlparse(self.repo_url)

        if parsed.scheme in ["http", "https"]:
            new_netloc = f"{github_token}@{parsed.netloc}"
            return urlunparse(
                (parsed.scheme, new_netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
            )
        elif self.repo_url.startswith("git@"):
            https_url = self.repo_url.replace(":", "/").replace("git@", "https://")
            parsed_https = urlparse(https_url)
            new_netloc = f"{github_token}@{parsed_https.netloc}"
            return urlunparse(
                (parsed_https.scheme, new_netloc, parsed_https.path, parsed_https.params, parsed_https.query, parsed_https.fragment)
            )

        return self.repo_url

    def prepare_repository(self) -> bool:
        if not self.repo_url:
            print("  警告: 未配置仓库地址")
            return False

        if os.path.exists(self.working_dir):
            if os.path.exists(os.path.join(self.working_dir, ".git")):
                print("  拉取最新代码...")
                success, stdout, stderr = self._run_git_command(["fetch", "origin"])
                if not success:
                    print(f"  Git fetch 失败: {stderr}")
                    return False

                success, stdout, stderr = self._run_git_command(
                    ["checkout", "-B", self.repo_branch, f"origin/{self.repo_branch}"]
                )
                if not success:
                    print(f"  Git checkout 失败: {stderr}")
                    return False
                print("  仓库已更新到最新")
                return True
            else:
                print(f"  清理已存在的非Git目录: {self.working_dir}")
                shutil.rmtree(self.working_dir)

        print(f"  克隆仓库: {self.repo_url}")
        auth_url = self._get_authenticated_url()

        success, stdout, stderr = self._run_git_command(
            ["clone", "--branch", self.repo_branch, auth_url, self.working_dir],
            cwd=os.path.dirname(self.working_dir) or ".",
        )

        if not success:
            print(f"  Git clone 失败: {stderr}")
            return False

        print("  仓库克隆成功")
        return True

    def initialize_project(self, site_name: str = "arXiv Sentinel", description: str = "每日arXiv论文总结"):
        if not os.path.exists(self.working_dir):
            os.makedirs(self.working_dir)

        if not os.path.exists(self.docs_dir):
            os.makedirs(self.docs_dir)

        if not os.path.exists(self.mkdocs_yml_path):
            mkdocs_config = self._generate_mkdocs_config(site_name, description)
            with open(self.mkdocs_yml_path, "w", encoding="utf-8") as f:
                f.write(mkdocs_config)

        index_path = os.path.join(self.docs_dir, "index.md")
        if not os.path.exists(index_path):
            index_content = self._generate_index_page(site_name, description)
            with open(index_path, "w", encoding="utf-8") as f:
                f.write(index_content)

    def _generate_mkdocs_config(self, site_name: str, description: str) -> str:
        return f"""site_name: {site_name}
site_description: {description}
site_author: arXiv Sentinel

theme:
  name: material
  features:
    - navigation.tabs
    - navigation.sections
    - navigation.top
    - search.suggest
    - search.highlight
  palette:
    - scheme: default
      primary: blue
      accent: blue
      toggle:
        icon: material/brightness-7
        name: 切换到暗色模式
    - scheme: slate
      primary: blue
      accent: blue
      toggle:
        icon: material/brightness-4
        name: 切换到亮色模式

plugins:
  - search

markdown_extensions:
  - admonition
  - codehilite
  - toc:
      permalink: true
  - pymdownx.tasklist
  - pymdownx.superfences

nav:
  - 首页: index.md
  - 论文汇总: papers/
"""

    def _generate_index_page(self, site_name: str, description: str) -> str:
        return f"""# {site_name}

{description}

## 最近更新

> 最后更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

使用 [arXiv Sentinel](https://github.com/your-repo/arxiv-sentinel) 自动生成。

## 如何使用

本网站自动汇总arXiv上的最新论文，并提供智能总结。浏览左侧导航栏查看最新论文。
"""

    def copy_markdown_files(self, markdown_files: List[str], subfolder: Optional[str] = None) -> List[str]:
        target_dir = self.docs_dir
        if subfolder:
            target_dir = os.path.join(target_dir, subfolder)
            os.makedirs(target_dir, exist_ok=True)

        copied_files = []
        for md_file in markdown_files:
            if os.path.exists(md_file):
                filename = os.path.basename(md_file)
                target_path = os.path.join(target_dir, filename)
                shutil.copy2(md_file, target_path)
                copied_files.append(target_path)

        return copied_files

    def build(self) -> bool:
        try:
            result = subprocess.run(
                ["mkdocs", "build"],
                cwd=self.working_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            print("  MkDocs build successful!")
            if result.stdout:
                print(f"  {result.stdout}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"  MkDocs build failed: {e.stderr}")
            return False

    def serve(self, port: int = 8000) -> subprocess.Popen:
        process = subprocess.Popen(
            ["mkdocs", "serve", "--dev-addr", f"0.0.0.0:{port}"],
            cwd=self.working_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return process

    def deploy_gh_pages(self) -> bool:
        try:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"

            github_token = os.environ.get("GITHUB_TOKEN")
            if github_token:
                env["GITHUB_TOKEN"] = github_token

            result = subprocess.run(
                ["mkdocs", "gh-deploy", "--force", "--message", "自动更新: arXiv论文总结"],
                cwd=self.working_dir,
                capture_output=True,
                text=True,
                check=True,
                env=env,
            )
            print("  MkDocs gh-deploy successful!")
            if result.stdout:
                print(f"  {result.stdout}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"  MkDocs gh-deploy failed: {e.stderr}")
            return False

    def git_add_all(self) -> bool:
        success, stdout, stderr = self._run_git_command(["add", "-A"])
        if not success:
            print(f"  Git add 失败: {stderr}")
        return success

    def git_commit(self, message: str, author_name: Optional[str] = None, author_email: Optional[str] = None) -> bool:
        args = ["commit", "-m", message]

        if author_name and author_email:
            args.extend(["--author", f"{author_name} <{author_email}>"])

        success, stdout, stderr = self._run_git_command(args)
        if not success:
            if "nothing to commit" in stderr or "nothing to commit" in stdout:
                print("  没有需要提交的更改")
                return True
            print(f"  Git commit 失败: {stderr}")
        return success

    def git_push(self) -> bool:
        auth_url = self._get_authenticated_url()

        success, stdout, stderr = self._run_git_command(
            ["push", auth_url, f"HEAD:{self.repo_branch}"]
        )

        if not success:
            print(f"  Git push 失败: {stderr}")
        return success

    def has_changes(self) -> bool:
        success, stdout, stderr = self._run_git_command(["status", "--porcelain"])
        if not success:
            return False
        return len(stdout.strip()) > 0

    def deploy(
        self,
        commit_message: str = "自动更新: 新增论文总结",
        author_name: Optional[str] = None,
        author_email: Optional[str] = None,
    ) -> bool:
        if self.deploy_mode == "build-only":
            print("  部署模式为 build-only，跳过Git操作")
            return True

        if self.deploy_mode == "gh-deploy":
            print("  使用 mkdocs gh-deploy 部署...")
            return self.deploy_gh_pages()

        if self.deploy_mode == "push-to-branch":
            print("  使用 push-to-branch 模式部署...")

            if not self.has_changes():
                print("  没有检测到更改，跳过部署")
                return True

            print("  添加文件到暂存区...")
            if not self.git_add_all():
                return False

            print(f"  提交更改: {commit_message}")
            if not self.git_commit(commit_message, author_name, author_email):
                return False

            print("  推送到远程仓库...")
            if not self.git_push():
                return False

            print("  推送成功！")
            return True

        print(f"  未知的部署模式: {self.deploy_mode}")
        return False

    def update_navigation(self, papers_dir: str = "papers"):
        papers_path = os.path.join(self.docs_dir, papers_dir)
        if not os.path.exists(papers_path):
            return

        md_files = sorted(
            [f for f in os.listdir(papers_path) if f.endswith(".md")],
            reverse=True,
        )

        nav_entries = []
        for md_file in md_files:
            title = md_file.replace(".md", "").replace("_", " ").title()
            nav_entries.append(f'      - "{title}": {papers_dir}/{md_file}')

        nav_section = f"""nav:
  - 首页: index.md
  - 论文汇总:
""" + "\n".join(nav_entries)

        if os.path.exists(self.mkdocs_yml_path):
            with open(self.mkdocs_yml_path, "r", encoding="utf-8") as f:
                content = f.read()

            nav_match = content.find("nav:")
            if nav_match >= 0:
                before_nav = content[:nav_match]
                new_content = before_nav + nav_section

                with open(self.mkdocs_yml_path, "w", encoding="utf-8") as f:
                    f.write(new_content)

    def update_index_page(self, new_papers_count: int, keywords: List[str]):
        index_path = os.path.join(self.docs_dir, "index.md")
        if not os.path.exists(index_path):
            return

        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()

        update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        keywords_str = ", ".join(keywords)

        new_update_section = f"""## 最近更新

> 最后更新: {update_time}
>
> 新增论文: {new_papers_count} 篇
>
> 监控关键词: {keywords_str}

"""

        if "## 最近更新" in content:
            before_section = content.split("## 最近更新")[0]
            parts = content.split("## 最近更新")[1].split("##")
            after_section = parts[1:] if len(parts) > 1 else []
            new_content = before_section + new_update_section
            if after_section:
                new_content += "##" + "##".join([""] + after_section)
        else:
            new_content = content.replace(
                "## 如何使用",
                new_update_section + "## 如何使用",
            )

        with open(index_path, "w", encoding="utf-8") as f:
            f.write(new_content)
