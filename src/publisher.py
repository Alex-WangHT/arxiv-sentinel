"""
arXiv Sentinel - MkDocs发布模块
==============================
本模块提供MkDocs网站的构建、部署和管理功能。

主要类：
- MkDocsPublisher: MkDocs发布管理器，整合Git操作、MkDocs构建和部署

功能概述：
- Git仓库操作（克隆、拉取、提交、推送）
- MkDocs项目初始化
- Markdown文件管理
- 导航栏自动更新
- 首页统计更新
- 本地服务器预览
- 多种部署模式支持

部署模式：
1. build-only: 仅本地构建，不执行Git操作
2. push-to-branch: 推送到指定分支
3. gh-deploy: 使用mkdocs gh-deploy命令

使用示例：
    from src.publisher import MkDocsPublisher
    from src.config import DeployMode
    
    # 创建发布器实例
    publisher = MkDocsPublisher(
        working_dir="./mkdocs_repo",
        repo_url="https://github.com/username/repo.git",
        repo_branch="gh-pages",
        deploy_mode=DeployMode.PUSH_TO_BRANCH.value,
    )
    
    # 准备仓库
    publisher.prepare_repository()
    
    # 初始化项目
    publisher.initialize_project("arXiv Sentinel", "每日论文总结")
    
    # 复制Markdown文件
    publisher.copy_markdown_files(["file1.md", "file2.md"], subfolder="papers")
    
    # 更新导航
    publisher.update_navigation("papers")
    
    # 更新首页
    publisher.update_index_page(5, ["LLM", "transformer"])
    
    # 构建
    publisher.build()
    
    # 部署
    publisher.deploy(commit_message="自动更新: 新增5篇论文")
"""

import os
import re
import shutil
import subprocess
from typing import Optional, List
from datetime import datetime
from urllib.parse import urlparse, urlunparse


class MkDocsPublisher:
    """
    MkDocs发布管理器类。
    
    提供MkDocs网站的完整管理功能，包括Git操作、项目初始化、
    文件管理、构建和部署。
    
    Attributes:
        working_dir (str): 工作目录路径
            - 默认: "./mkdocs_repo"
            - 克隆的仓库和生成的文件存储在此
        
        repo_url (str): 远程仓库URL
            - 用于Git克隆、拉取、推送操作
        
        repo_branch (str): 目标分支名称
            - 默认: "gh-pages"
            - GitHub Pages的标准分支
        
        deploy_mode (str): 部署模式
            - 默认: "build-only"
            - 可选值: "build-only", "push-to-branch", "gh-deploy"
        
        docs_dir (str): MkDocs文档目录
            - 默认为 {working_dir}/docs
            - Markdown文件放置在此目录
        
        mkdocs_yml_path (str): MkDocs配置文件路径
            - 默认为 {working_dir}/mkdocs.yml
        
        site_dir (str): 构建输出目录
            - 默认为 {working_dir}/site
            - mkdocs build 生成的静态网站文件
    
    部署模式说明：
        build-only:
            - 只执行 mkdocs build
            - 不执行任何Git操作
            - 适用于本地开发和测试
        
        push-to-branch:
            - 克隆/拉取远程仓库
            - 复制Markdown文件
            - 提交更改
            - 推送到指定分支
            - 适用于需要精确控制部署分支的场景
        
        gh-deploy:
            - 调用 mkdocs gh-deploy 命令
            - 自动构建并部署到GitHub Pages
            - 适用于标准GitHub Pages部署
    
    Example:
        from src.publisher import MkDocsPublisher
        from src.config import DeployMode
        
        # 本地开发模式
        publisher = MkDocsPublisher(
            working_dir="./mkdocs_repo",
            deploy_mode=DeployMode.BUILD_ONLY.value,
        )
        publisher.initialize_project()
        publisher.build()
        process = publisher.serve(port=8000)
        
        # 生产部署模式
        publisher = MkDocsPublisher(
            working_dir="./mkdocs_repo",
            repo_url="https://github.com/username/arxiv-papers.git",
            repo_branch="gh-pages",
            deploy_mode=DeployMode.PUSH_TO_BRANCH.value,
        )
        publisher.prepare_repository()
        publisher.copy_markdown_files(markdown_files, "papers")
        publisher.update_navigation("papers")
        publisher.update_index_page(10, ["LLM", "RAG"])
        publisher.build()
        publisher.deploy(commit_message="自动更新: 新增10篇论文")
    """
    
    def __init__(
        self,
        working_dir: str = "./mkdocs_repo",
        repo_url: str = "",
        repo_branch: str = "gh-pages",
        deploy_mode: str = "build-only",
    ):
        """
        初始化MkDocs发布器实例。
        
        配置工作目录、仓库信息和部署模式，并计算常用路径。
        
        Args:
            working_dir: 工作目录路径，默认 "./mkdocs_repo"
            repo_url: 远程仓库URL，默认空字符串
            repo_branch: 目标分支名称，默认 "gh-pages"
            deploy_mode: 部署模式，默认 "build-only"
        """
        self.working_dir = working_dir
        self.repo_url = repo_url
        self.repo_branch = repo_branch
        self.deploy_mode = deploy_mode

        self.docs_dir = os.path.join(working_dir, "docs")
        self.mkdocs_yml_path = os.path.join(working_dir, "mkdocs.yml")
        self.site_dir = os.path.join(working_dir, "site")

    def _run_git_command(self, args: List[str], cwd: Optional[str] = None) -> tuple:
        """
        内部方法：执行Git命令。
        
        使用subprocess运行Git命令，捕获输出和错误。
        
        Args:
            args: Git命令参数列表（不包含 "git" 命令本身）
            cwd: 执行命令的工作目录，默认使用 self.working_dir
        
        Returns:
            tuple: (success: bool, stdout: str, stderr: str)
            - success: 命令执行是否成功（返回码为0）
            - stdout: 标准输出内容
            - stderr: 标准错误输出内容
        
        Example:
            # 执行 git status
            success, stdout, stderr = self._run_git_command(["status", "--porcelain"])
            
            # 执行 git clone
            success, stdout, stderr = self._run_git_command(
                ["clone", url, target_dir],
                cwd="/tmp"
            )
        """
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
        """
        内部方法：获取带认证的Git仓库URL。
        
        如果环境变量中存在 GITHUB_TOKEN，将其注入到URL中用于身份认证。
        
        支持的URL格式：
        1. HTTPS格式: https://github.com/username/repo.git
           转换为: https://{token}@github.com/username/repo.git
        
        2. SSH格式: git@github.com:username/repo.git
           转换为: https://{token}@github.com/username/repo.git
        
        Args:
            无
        
        Returns:
            带认证信息的URL字符串，如果没有Token则返回原始URL
        
        Example:
            # 环境变量 GITHUB_TOKEN="abc123"
            
            # HTTPS URL
            self.repo_url = "https://github.com/user/repo.git"
            result = self._get_authenticated_url()
            # 结果: "https://abc123@github.com/user/repo.git"
            
            # SSH URL
            self.repo_url = "git@github.com:user/repo.git"
            result = self._get_authenticated_url()
            # 结果: "https://abc123@github.com/user/repo.git"
        """
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
        """
        准备Git仓库。
        
        根据工作目录的状态执行不同操作：
        1. 如果目录不存在 → 克隆仓库
        2. 如果目录存在且是Git仓库 → 拉取最新代码
        3. 如果目录存在但不是Git仓库 → 删除后克隆
        
        执行步骤：
        1. 检查仓库URL是否配置
        2. 检查工作目录状态
        3. 拉取或克隆仓库
        4. 切换到目标分支
        
        Returns:
            准备成功返回True，失败返回False
        
        Example:
            publisher = MkDocsPublisher(
                repo_url="https://github.com/user/repo.git",
                repo_branch="gh-pages",
            )
            
            success = publisher.prepare_repository()
            if success:
                print("仓库准备就绪")
            else:
                print("仓库准备失败")
        """
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
        """
        初始化MkDocs项目。
        
        创建必要的目录和文件（如果不存在）：
        1. 创建工作目录
        2. 创建docs目录
        3. 创建mkdocs.yml配置文件（如果不存在）
        4. 创建首页index.md（如果不存在）
        
        Args:
            site_name: 网站名称，默认 "arXiv Sentinel"
            description: 网站描述，默认 "每日arXiv论文总结"
        
        Example:
            publisher = MkDocsPublisher(working_dir="./site")
            publisher.initialize_project(
                site_name="My Paper Tracker",
                description="自动追踪arXiv最新论文"
            )
        """
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
        """
        内部方法：生成MkDocs配置文件内容。
        
        生成标准的mkdocs.yml配置，包含：
        - 站点元数据（名称、描述、作者）
        - Material主题配置（支持亮色/暗色模式切换）
        - 常用插件配置
        - Markdown扩展配置
        - 导航栏配置
        
        Args:
            site_name: 网站名称
            description: 网站描述
        
        Returns:
            mkdocs.yml配置文件的完整内容字符串
        """
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
        """
        内部方法：生成首页内容。
        
        生成标准的index.md首页，包含：
        - 标题
        - 描述
        - 最近更新时间
        - 使用说明
        
        Args:
            site_name: 网站名称
            description: 网站描述
        
        Returns:
            index.md文件的内容字符串
        """
        return f"""# {site_name}

{description}

## 最近更新

> 最后更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

使用 [arXiv Sentinel](https://github.com/your-repo/arxiv-sentinel) 自动生成。

## 如何使用

本网站自动汇总arXiv上的最新论文，并提供智能总结。浏览左侧导航栏查看最新论文。
"""

    def copy_markdown_files(self, markdown_files: List[str], subfolder: Optional[str] = None) -> List[str]:
        """
        复制Markdown文件到MkDocs项目目录。
        
        将生成的Markdown总结文件复制到MkDocs的docs目录下，
        可选地放置在子文件夹中。
        
        Args:
            markdown_files: 要复制的Markdown文件路径列表
            subfolder: 目标子文件夹名称（相对docs目录），为None则直接复制到docs目录
        
        Returns:
            复制成功的文件路径列表
        
        Example:
            # 复制到 docs/papers/
            files = ["./output/paper1.md", "./output/paper2.md"]
            copied = publisher.copy_markdown_files(files, subfolder="papers")
            # 结果文件位置: docs/papers/paper1.md, docs/papers/paper2.md
            
            # 直接复制到 docs/
            copied = publisher.copy_markdown_files(files)
        """
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
        """
        构建MkDocs网站。
        
        执行 mkdocs build 命令，生成静态网站文件到site目录。
        
        Returns:
            构建成功返回True，失败返回False
        
        Example:
            success = publisher.build()
            if success:
                print("网站构建成功")
            else:
                print("网站构建失败")
        """
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
        """
        启动MkDocs本地开发服务器。
        
        执行 mkdocs serve 命令，启动本地服务器用于预览网站。
        这是一个非阻塞调用，返回的进程对象可用于后续终止服务器。
        
        Args:
            port: 服务器监听端口，默认 8000
        
        Returns:
            subprocess.Popen 对象，可用于终止服务器进程
        
        Example:
            # 启动服务器
            process = publisher.serve(port=8080)
            
            # 访问 http://localhost:8080 预览
            
            # 终止服务器
            process.terminate()
            process.wait()
        """
        process = subprocess.Popen(
            ["mkdocs", "serve", "--dev-addr", f"0.0.0.0:{port}"],
            cwd=self.working_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return process

    def deploy_gh_pages(self) -> bool:
        """
        使用mkdocs gh-deploy命令部署到GitHub Pages。
        
        执行 mkdocs gh-deploy 命令，自动构建并部署到GitHub Pages。
        这是MkDocs提供的标准部署方式。
        
        特点：
        - 自动构建网站
        - 自动推送到gh-pages分支
        - 自动处理历史记录
        
        Returns:
            部署成功返回True，失败返回False
        
        Example:
            publisher = MkDocsPublisher(
                deploy_mode="gh-deploy",
                repo_url="https://github.com/user/repo.git",
            )
            success = publisher.deploy_gh_pages()
        """
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
        """
        将所有更改添加到Git暂存区。
        
        执行 git add -A 命令，暂存所有新增、修改和删除的文件。
        
        Returns:
            操作成功返回True，失败返回False
        """
        success, stdout, stderr = self._run_git_command(["add", "-A"])
        if not success:
            print(f"  Git add 失败: {stderr}")
        return success

    def git_commit(self, message: str, author_name: Optional[str] = None, author_email: Optional[str] = None) -> bool:
        """
        提交暂存区的更改。
        
        执行 git commit 命令，创建新的提交。
        
        Args:
            message: 提交消息
            author_name: 提交者名称（可选）
            author_email: 提交者邮箱（可选）
        
        Returns:
            提交成功或没有需要提交的更改时返回True，失败返回False
        
        Note:
            如果没有需要提交的更改（"nothing to commit"），视为成功，
            因为这是预期的情况。
        """
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
        """
        推送到远程仓库。
        
        执行 git push 命令，将本地提交推送到远程仓库。
        使用带认证的URL进行推送。
        
        Returns:
            推送成功返回True，失败返回False
        """
        auth_url = self._get_authenticated_url()

        success, stdout, stderr = self._run_git_command(
            ["push", auth_url, f"HEAD:{self.repo_branch}"]
        )

        if not success:
            print(f"  Git push 失败: {stderr}")
        return success

    def has_changes(self) -> bool:
        """
        检查工作目录是否有未提交的更改。
        
        执行 git status --porcelain 命令，检查是否有文件更改。
        
        Returns:
            有更改返回True，没有更改返回False
        """
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
        """
        执行部署操作。
        
        根据配置的部署模式执行相应的部署操作。
        
        部署模式行为：
        1. build-only: 跳过所有Git操作，直接返回True
        2. gh-deploy: 调用 deploy_gh_pages() 方法
        3. push-to-branch: 执行完整的Git流程
        
        push-to-branch模式流程：
        1. 检查是否有更改
        2. 添加所有文件到暂存区
        3. 提交更改
        4. 推送到远程仓库
        
        Args:
            commit_message: 提交消息模板，默认 "自动更新: 新增论文总结"
            author_name: 提交者名称（可选）
            author_email: 提交者邮箱（可选）
        
        Returns:
            部署成功返回True，失败返回False
        
        Example:
            # 使用push-to-branch模式
            publisher = MkDocsPublisher(
                deploy_mode="push-to-branch",
                repo_url="https://github.com/user/repo.git",
            )
            
            success = publisher.deploy(
                commit_message="自动更新: 新增10篇论文",
                author_name="arXiv Bot",
                author_email="bot@example.com"
            )
            
            # 使用gh-deploy模式
            publisher = MkDocsPublisher(
                deploy_mode="gh-deploy",
                repo_url="https://github.com/user/repo.git",
            )
            success = publisher.deploy()
        """
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
        """
        更新MkDocs导航栏配置。
        
        扫描papers目录下的Markdown文件，自动更新mkdocs.yml中的导航栏配置。
        文件按文件名降序排列（最新的文件在前）。
        
        执行步骤：
        1. 检查papers目录是否存在
        2. 列出所有.md文件并按降序排序
        3. 生成导航项列表
        4. 替换mkdocs.yml中的nav部分
        
        Args:
            papers_dir: 论文目录名称（相对docs目录），默认 "papers"
        
        Example:
            # 目录结构：
            # docs/papers/
            #   20240115_paper1.md
            #   20240114_paper2.md
            #   20240113_paper3.md
            
            publisher.update_navigation("papers")
            
            # 生成的导航配置：
            # nav:
            #   - 首页: index.md
            #   - 论文汇总:
            #     - "20240115 Paper1": papers/20240115_paper1.md
            #     - "20240114 Paper2": papers/20240114_paper2.md
            #     - "20240113 Paper3": papers/20240113_paper3.md
        """
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
        """
        更新首页的最近更新信息。
        
        更新index.md文件中的"最近更新"部分，包括：
        - 最后更新时间
        - 新增论文数量
        - 监控的关键词列表
        
        执行步骤：
        1. 检查index.md是否存在
        2. 读取文件内容
        3. 生成新的"最近更新"部分
        4. 替换或插入新内容
        5. 写入文件
        
        Args:
            new_papers_count: 新增论文数量
            keywords: 监控的关键词列表
        
        Example:
            publisher.update_index_page(
                new_papers_count=15,
                keywords=["LLM", "RAG", "multi-agent"]
            )
            
            # 首页显示：
            # ## 最近更新
            # > 最后更新: 2024-01-15 10:30:00
            # >
            # > 新增论文: 15 篇
            # >
            # > 监控关键词: LLM, RAG, multi-agent
        """
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
