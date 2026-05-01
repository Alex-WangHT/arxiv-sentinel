import os
import shutil
import subprocess
from typing import Optional, List
from datetime import datetime


class MkDocsPublisher:
    def __init__(self, page_dir: str = "./page"):
        self.page_dir = page_dir
        self.docs_dir = os.path.join(page_dir, "docs")
        self.mkdocs_yml_path = os.path.join(page_dir, "mkdocs.yml")

    def initialize_project(self, site_name: str = "arXiv Sentinel", description: str = "每日arXiv论文总结"):
        if not os.path.exists(self.page_dir):
            os.makedirs(self.page_dir)

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
  - mkdocstrings:
      default_handler: python

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
                cwd=self.page_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            print("MkDocs build successful!")
            print(result.stdout)
            return True
        except subprocess.CalledProcessError as e:
            print(f"MkDocs build failed: {e.stderr}")
            return False

    def serve(self, port: int = 8000) -> subprocess.Popen:
        process = subprocess.Popen(
            ["mkdocs", "serve", "--dev-addr", f"0.0.0.0:{port}"],
            cwd=self.page_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return process

    def deploy_gh_pages(self) -> bool:
        try:
            result = subprocess.run(
                ["mkdocs", "gh-deploy", "--force"],
                cwd=self.page_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            print("MkDocs gh-deploy successful!")
            print(result.stdout)
            return True
        except subprocess.CalledProcessError as e:
            print(f"MkDocs gh-deploy failed: {e.stderr}")
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
            after_section = content.split("## 最近更新")[1].split("##")[1:] if len(content.split("## 最近更新")[1].split("##")) > 1 else []
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
