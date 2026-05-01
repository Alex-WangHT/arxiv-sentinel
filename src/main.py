"""
arXiv Sentinel - 主入口模块
==========================
本模块提供arXiv Sentinel工具的命令行接口和主程序逻辑。

主要类：
- arXivSentinel: 主控制器类，整合所有模块功能

主要函数：
- main(): 命令行入口函数

工作流程：
1. 搜索arXiv论文
2. AI筛选（可选）
3. 下载PDF文件
4. 生成论文总结
5. 清理PDF缓存
6. 准备MkDocs仓库
7. 构建和部署网站

使用示例：
    # 命令行使用
    python -m src.main --config config.json --keywords LLM RAG
    
    # 代码中使用
    from src.main import arXivSentinel
    
    # 创建实例并运行
    sentinel = arXivSentinel(config_file="config.json")
    processed_count = sentinel.run(
        keywords=["LLM", "transformer"],
        max_results=10
    )
"""

import os
import sys
import argparse
from typing import List, Optional
from datetime import datetime

from .config import ConfigManager, DeployMode, SearchStrategy
from .sniffer import ArXivSniffer, Paper, SearchStrategy as SnifferSearchStrategy
from .summarizer import Summarizer
from .publisher import MkDocsPublisher


class arXivSentinel:
    """
    arXiv Sentinel主控制器类。
    
    整合所有模块功能，提供完整的论文嗅探-总结-发布工作流程。
    
    主要职责：
    1. 初始化配置管理
    2. 初始化各功能模块（嗅探、总结、发布）
    3. 执行完整的工作流程
    4. 提供运行状态反馈
    
    Attributes:
        config_manager (ConfigManager): 配置管理器实例
        config (Config): 当前配置实例
        sniffer (ArXivSniffer): 论文嗅探器实例
        summarizer (Summarizer): 论文总结器实例
        publisher (MkDocsPublisher): MkDocs发布器实例
    
    工作流程：
        run() 方法执行以下步骤：
        1. 搜索arXiv论文
        2. AI论文筛选（可选）
        3. 下载PDF文件
        4. 生成论文总结
        5. 清理PDF缓存
        6. 准备MkDocs仓库
        7. 构建和部署网站
    
    Example:
        from src.main import arXivSentinel
        
        # 创建实例
        sentinel = arXivSentinel(config_file="config.json")
        
        # 运行完整流程
        processed_count = sentinel.run(
            keywords=["LLM", "RAG", "agent"],
            max_results=15
        )
        
        print(f"成功处理 {processed_count} 篇论文")
    """
    
    def __init__(self, config_file: Optional[str] = None):
        """
        初始化arXiv Sentinel实例。
        
        执行以下步骤：
        1. 初始化配置管理器
        2. 验证配置有效性
        3. 创建必要的目录
        4. 初始化各功能模块
        
        Args:
            config_file: 配置文件路径，为None则使用默认路径
        
        Raises:
            SystemExit: 如果配置验证失败，程序退出并返回错误码1
        """
        self.config_manager = ConfigManager(config_file)
        self.config = self.config_manager.get()

        self._validate_config()
        self._setup_directories()

        self.sniffer = ArXivSniffer(self.config.PDF_CACHE_DIR)
        self.summarizer = Summarizer(
            siliconflow_api_key=self.config.SILICONFLOW_API_KEY,
            prompt_dir=self.config.PROMPT_DIR,
            use_vision_mode=self.config.USE_VISION_MODE,
            text_model=self.config.SILICONFLOW_MODEL,
            vision_model=self.config.VISION_MODEL,
        )
        self.publisher = MkDocsPublisher(
            working_dir=self.config.MKDOCS_WORKING_DIR,
            repo_url=self.config.MKDOCS_REPO_URL,
            repo_branch=self.config.MKDOCS_REPO_BRANCH,
            deploy_mode=self.config.MKDOCS_DEPLOY_MODE,
        )

    def _validate_config(self):
        """
        内部方法：验证配置有效性。
        
        调用 ConfigManager.validate() 检查配置。
        如果存在错误，打印错误信息并退出程序。
        
        Raises:
            SystemExit: 如果配置验证失败，退出码为1
        """
        errors = self.config_manager.validate()
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            sys.exit(1)

    def _setup_directories(self):
        """
        内部方法：创建必要的目录。
        
        创建以下目录（如果不存在）：
        - PDF缓存目录
        - Markdown输出目录
        - Prompt模板目录
        """
        dirs_to_create = [
            self.config.PDF_CACHE_DIR,
            self.config.MARKDOWN_OUTPUT_DIR,
            self.config.PROMPT_DIR,
        ]
        for directory in dirs_to_create:
            os.makedirs(directory, exist_ok=True)

    def run(self, keywords: Optional[List[str]] = None, max_results: Optional[int] = None) -> int:
        """
        执行完整的arXiv Sentinel工作流程。
        
        这是核心方法，整合所有模块功能，执行完整的论文处理流程。
        
        工作流程步骤：
        1. 搜索arXiv论文
           - 使用配置的关键词、分类、搜索策略
           - 调用 ArXivSniffer.search()
        
        2. AI论文筛选（可选）
           - 如果 ENABLE_LLM_FILTER=True
           - 使用LLM基于标题和摘要判断相关性
           - 调用 Summarizer.filter_papers()
        
        3. 下载PDF文件
           - 为筛选后的论文下载PDF
           - 调用 ArXivSniffer.download_pdfs()
        
        4. 生成论文总结
           - 对每篇论文进行多维度分析
           - 生成Markdown格式的总结文档
           - 调用 Summarizer.summarize()
        
        5. 清理PDF缓存
           - 删除已处理的PDF文件
           - 调用 ArXivSniffer.cleanup_all_pdfs()
        
        6. 准备MkDocs仓库
           - 克隆或拉取远程仓库（根据部署模式）
           - 初始化MkDocs项目
           - 调用 MkDocsPublisher.prepare_repository() 和 initialize_project()
        
        7. 构建和部署
           - 复制Markdown文件到项目目录
           - 更新导航栏
           - 更新首页统计
           - 构建MkDocs网站
           - 部署到GitHub Pages（根据部署模式）
        
        Args:
            keywords: 搜索关键词列表，为None则使用配置中的 KEYWORDS
            max_results: 最大搜索结果数，为None则使用配置中的 MAX_RESULTS_PER_SEARCH
        
        Returns:
            成功处理并生成总结的论文数量
        
        Example:
            # 使用默认配置运行
            sentinel = arXivSentinel()
            count = sentinel.run()
            
            # 自定义关键词和数量
            count = sentinel.run(
                keywords=["LLM", "RAG", "multi-agent"],
                max_results=20
            )
        """
        keywords = keywords or self.config.KEYWORDS
        max_results = max_results or self.config.MAX_RESULTS_PER_SEARCH

        print(f"{'='*60}")
        print(f"arXiv Sentinel - 运行开始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"关键词: {', '.join(keywords)}")
        print(f"最大结果数: {max_results}")
        print(f"部署模式: {self.config.MKDOCS_DEPLOY_MODE}")
        print(f"文本模型: {self.config.SILICONFLOW_MODEL}")
        if self.config.USE_VISION_MODE:
            print(f"视觉模式: 启用 ({self.config.VISION_MODEL})")
        else:
            print(f"视觉模式: 禁用")
        print(f"{'='*60}")

        print("\n[1/7] 搜索arXiv论文...")
        papers = self.sniffer.search(
            keywords=keywords,
            categories=self.config.CATEGORIES if self.config.CATEGORIES else None,
            max_results=max_results,
            search_all_fields=self.config.SEARCH_ALL_FIELDS,
            use_or_for_categories=self.config.USE_OR_FOR_CATEGORIES,
            search_strategy=self.config.SEARCH_STRATEGY,
        )
        print(f"  找到 {len(papers)} 篇论文")

        if not papers:
            print("没有找到相关论文，任务结束。")
            return 0

        relevant_papers = papers
        irrelevant_papers = []

        if self.config.ENABLE_LLM_FILTER:
            print("\n[2/7] AI论文筛选（基于Abstract）...")
            relevant_papers, irrelevant_papers = self.summarizer.filter_papers(papers, keywords)

            if not relevant_papers:
                print("没有通过筛选的论文，任务结束。")
                return 0
        else:
            print("\n[2/7] 跳过AI筛选 (ENABLE_LLM_FILTER=false)")

        print("\n[3/7] 下载PDF文件...")
        self.sniffer.download_pdfs(relevant_papers)
        downloaded_count = sum(1 for p in relevant_papers if p.local_pdf_path)
        print(f"  成功下载 {downloaded_count} 个PDF文件")

        if downloaded_count == 0:
            print("没有成功下载任何PDF文件，任务结束。")
            return 0

        print("\n[4/7] 生成论文总结...")
        markdown_files = []
        failed_papers = []

        for paper in relevant_papers:
            if not paper.local_pdf_path:
                failed_papers.append(paper)
                continue

            try:
                print(f"  处理论文: {paper.arxiv_id}")
                summary_result = self.summarizer.summarize(paper)
                md_path = self.summarizer.generate_markdown(summary_result, self.config.MARKDOWN_OUTPUT_DIR)
                markdown_files.append(md_path)
                print(f"    已生成: {md_path}")
            except Exception as e:
                print(f"    处理失败: {e}")
                failed_papers.append(paper)

        print(f"  成功生成 {len(markdown_files)} 个Markdown文件")

        print("\n[5/7] 清理PDF缓存...")
        self.sniffer.cleanup_all_pdfs(relevant_papers)
        print(f"  已清理所有PDF缓存文件")

        print("\n[6/7] 准备MkDocs仓库...")
        if self.config.MKDOCS_DEPLOY_MODE in [DeployMode.PUSH_TO_BRANCH.value, DeployMode.GH_DEPLOY.value]:
            print(f"  克隆/更新仓库: {self.config.MKDOCS_REPO_URL}")
            success = self.publisher.prepare_repository()
            if not success:
                print("  警告: 无法准备仓库，将使用本地模式")

        self.publisher.initialize_project(self.config.SITE_NAME, self.config.SITE_DESCRIPTION)
        print(f"  MkDocs项目已准备就绪")

        print("\n[7/7] 构建和部署...")
        self.publisher.copy_markdown_files(markdown_files, subfolder="papers")
        self.publisher.update_navigation("papers")
        self.publisher.update_index_page(len(markdown_files), keywords)

        build_success = self.publisher.build()
        if not build_success:
            print(f"  警告: MkDocs构建失败")

        deploy_success = False
        if self.config.MKDOCS_DEPLOY_MODE != DeployMode.BUILD_ONLY.value:
            commit_msg = self.config.GIT_COMMIT_MESSAGE.format(count=len(markdown_files))
            deploy_success = self.publisher.deploy(
                commit_message=commit_msg,
                author_name=self.config.GIT_AUTHOR_NAME,
                author_email=self.config.GIT_AUTHOR_EMAIL,
            )
            if deploy_success:
                print(f"  部署成功！")
            else:
                print(f"  警告: 部署失败")

        print(f"\n{'='*60}")
        print(f"运行完成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"初始搜索: {len(papers)} 篇论文")
        if self.config.ENABLE_LLM_FILTER:
            print(f"AI筛选: 相关 {len(relevant_papers)} 篇，不相关 {len(irrelevant_papers)} 篇")
        print(f"成功处理: {len(markdown_files)} 篇论文")
        print(f"失败: {len(failed_papers)} 篇")
        print(f"构建状态: {'成功' if build_success else '失败'}")
        if self.config.MKDOCS_DEPLOY_MODE != DeployMode.BUILD_ONLY.value:
            print(f"部署状态: {'成功' if deploy_success else '失败'}")
        print(f"{'='*60}")

        return len(markdown_files)


def main():
    """
    命令行入口函数。
    
    解析命令行参数，创建arXivSentinel实例并执行相应操作。
    
    支持的命令行参数：
    
    配置相关：
        --config, -c      配置文件路径
        --keywords, -k    搜索关键词（覆盖配置文件）
        --max-results, -n 最大搜索结果数（覆盖配置文件）
    
    模式控制：
        --no-filter       禁用AI论文筛选
        --use-vision      启用视觉模式（多模态模型处理PDF图像）
        --no-vision       禁用视觉模式（使用文本提取）
    
    搜索策略：
        --search-strict      使用严格搜索策略（精确短语匹配）
        --search-moderate    使用中等搜索策略（默认）
        --search-broad       使用宽松搜索策略
        --use-or-categories  使用OR连接关键词和分类（更宽松）
        --use-and-categories 使用AND连接关键词和分类（更严格，默认）
        --search-all-fields  搜索所有字段（更宽松）
        --search-title-abstract 仅搜索标题和摘要（更严格，默认）
    
    服务器预览：
        --serve            启动MkDocs本地服务器预览
        --port, -p         本地服务器端口（默认: 8000）
    
    使用示例：
        # 基本使用
        python -m src.main
        
        # 使用指定配置文件
        python -m src.main --config config.json
        
        # 自定义关键词
        python -m src.main -k LLM "large language model" RAG
        
        # 使用视觉模式
        python -m src.main --use-vision
        
        # 严格搜索策略
        python -m src.main --search-strict --use-and-categories
        
        # 本地预览
        python -m src.main --serve --port 8080
    """
    parser = argparse.ArgumentParser(description="arXiv Sentinel - 自动嗅探、总结并发布arXiv论文")
    parser.add_argument("--config", "-c", type=str, help="配置文件路径")
    parser.add_argument("--keywords", "-k", type=str, nargs="+", help="搜索关键词（覆盖配置文件）")
    parser.add_argument("--max-results", "-n", type=int, help="最大搜索结果数（覆盖配置文件）")
    parser.add_argument("--serve", action="store_true", help="启动MkDocs本地服务器预览")
    parser.add_argument("--port", "-p", type=int, default=8000, help="本地服务器端口（默认: 8000）")
    parser.add_argument("--no-filter", action="store_true", help="禁用AI论文筛选")
    parser.add_argument("--use-vision", action="store_true", help="启用视觉模式（多模态模型处理PDF图像）")
    parser.add_argument("--no-vision", action="store_true", help="禁用视觉模式（使用文本提取）")
    parser.add_argument("--search-strict", action="store_true", help="使用严格搜索策略（精确短语匹配）")
    parser.add_argument("--search-moderate", action="store_true", help="使用中等搜索策略（默认）")
    parser.add_argument("--search-broad", action="store_true", help="使用宽松搜索策略")
    parser.add_argument("--use-or-categories", action="store_true", help="使用OR连接关键词和分类（更宽松）")
    parser.add_argument("--use-and-categories", action="store_true", help="使用AND连接关键词和分类（更严格，默认）")
    parser.add_argument("--search-all-fields", action="store_true", help="搜索所有字段（更宽松）")
    parser.add_argument("--search-title-abstract", action="store_true", help="仅搜索标题和摘要（更严格，默认）")

    args = parser.parse_args()

    sentinel = arXivSentinel(config_file=args.config)

    if args.no_filter:
        sentinel.config.ENABLE_LLM_FILTER = False

    if args.use_vision:
        sentinel.config.USE_VISION_MODE = True

    if args.no_vision:
        sentinel.config.USE_VISION_MODE = False

    if args.search_strict:
        sentinel.config.SEARCH_STRATEGY = SearchStrategy.STRICT.value
    if args.search_moderate:
        sentinel.config.SEARCH_STRATEGY = SearchStrategy.MODERATE.value
    if args.search_broad:
        sentinel.config.SEARCH_STRATEGY = SearchStrategy.BROAD.value

    if args.use_or_categories:
        sentinel.config.USE_OR_FOR_CATEGORIES = True
    if args.use_and_categories:
        sentinel.config.USE_OR_FOR_CATEGORIES = False

    if args.search_all_fields:
        sentinel.config.SEARCH_ALL_FIELDS = True
    if args.search_title_abstract:
        sentinel.config.SEARCH_ALL_FIELDS = False

    if args.serve:
        sentinel.publisher.initialize_project()
        print(f"启动MkDocs本地服务器，端口: {args.port}")
        print(f"按 Ctrl+C 停止服务器")
        import time
        process = sentinel.publisher.serve(args.port)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n正在停止服务器...")
            process.terminate()
            process.wait()
        return

    sentinel.run(
        keywords=args.keywords,
        max_results=args.max_results,
    )


if __name__ == "__main__":
    main()
