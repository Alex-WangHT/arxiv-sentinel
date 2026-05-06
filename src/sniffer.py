"""
arXiv Sentinel - 论文嗅探模块
================================
本模块提供从arXiv搜索、下载和管理学术论文的功能。

主要类：
- Paper: 表示一篇arXiv论文的数据结构
- SearchStrategy: 搜索策略枚举
- ArXivSniffer: arXiv API客户端，提供搜索、下载等功能

使用示例：
    from src.sniffer import ArXivSniffer, SearchStrategy
    
    sniffer = ArXivSniffer(cache_dir="./pdf_cache")
    papers = sniffer.search(
        keywords=["LLM", "transformer"],
        categories=["cs.CL", "cs.AI"],
        max_results=10,
        search_strategy=SearchStrategy.MODERATE
    )
"""

import os
import re
import time
import requests
import feedparser
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from urllib.parse import quote, urlencode


class Paper:
    """
    表示一篇arXiv论文的数据结构。
    
    该类封装了arXiv论文的所有元数据信息，包括标题、作者、摘要、
    分类、PDF链接等。同时还记录了本地下载的PDF文件路径。
    
    Attributes:
        title (str): 论文标题
        authors (List[str]): 作者列表
        summary (str): 论文摘要
        arxiv_id (str): arXiv ID，如 "2401.12345"
        pdf_url (str): PDF文件的下载链接
        published (str): 发布时间字符串
        categories (List[str]): 论文分类列表，如 ["cs.CL", "cs.AI"]
        local_pdf_path (Optional[str]): 本地下载的PDF文件路径，未下载则为None
    
    Example:
        paper = Paper(
            title="Attention Is All You Need",
            authors=["Ashish Vaswani", "Noam Shazeer"],
            summary="The dominant sequence transduction models...",
            arxiv_id="1706.03762",
            pdf_url="https://arxiv.org/pdf/1706.03762.pdf",
            published="2017-06-12",
            categories=["cs.CL", "cs.AI"]
        )
    """
    
    def __init__(
        self,
        title: str,
        authors: List[str],
        summary: str,
        arxiv_id: str,
        pdf_url: str,
        published: str,
        categories: List[str],
    ):
        """
        初始化Paper实例。
        
        Args:
            title: 论文标题
            authors: 作者列表
            summary: 论文摘要
            arxiv_id: arXiv ID
            pdf_url: PDF下载链接
            published: 发布时间
            categories: 分类列表
        """
        self.title = title
        self.authors = authors
        self.summary = summary
        self.arxiv_id = arxiv_id
        self.pdf_url = pdf_url
        self.published = published
        self.categories = categories
        self.local_pdf_path: Optional[str] = None


class SearchStrategy:
    """
    搜索策略枚举类，定义三种不同的搜索严格程度。
    
    该类用于控制arXiv API搜索的严格程度，影响关键词匹配方式。
    
    Attributes:
        STRICT (str): 严格策略，使用精确短语匹配（带双引号）
            - 查询示例: all:"LLM" 或 ti:"large language model"
            - 适用场景: 需要精确匹配特定术语时
        
        MODERATE (str): 中等策略（默认），使用普通关键词匹配
            - 查询示例: all:LLM 或 ti:transformer
            - 适用场景: 大多数常规搜索场景
        
        BROAD (str): 宽松策略，搜索所有字段
            - 查询示例: all:LLM
            - 适用场景: 需要尽可能多的结果时
    
    Example:
        from src.sniffer import SearchStrategy
        
        # 使用严格策略
        strategy = SearchStrategy.STRICT
        
        # 使用默认策略
        strategy = SearchStrategy.MODERATE
    """
    
    STRICT = "strict"
    MODERATE = "moderate"
    BROAD = "broad"


class ArXivSniffer:
    """
    arXiv API客户端，提供论文搜索、下载和管理功能。
    
    该类封装了与arXiv API的交互，支持通过关键词和分类搜索论文，
    下载PDF文件，以及管理本地缓存。
    
    Attributes:
        ARXIV_API_URL (str): arXiv API的基础URL
        PDF_BASE_URL (str): arXiv PDF下载的基础URL
        cache_dir (str): PDF文件缓存目录
    
    Example:
        sniffer = ArXivSniffer(cache_dir="./pdf_cache")
        
        # 搜索论文
        papers = sniffer.search(
            keywords=["LLM", "transformer"],
            categories=["cs.CL", "cs.AI"],
            max_results=10
        )
        
        # 下载PDF
        for paper in papers:
            sniffer.download_pdf(paper)
        
        # 使用完成后清理
        sniffer.cleanup_all_pdfs(papers)
    """
    
    ARXIV_API_URL = "http://export.arxiv.org/api/query"
    PDF_BASE_URL = "https://arxiv.org/pdf"

    def __init__(self, cache_dir: str = "./pdf_cache"):
        """
        初始化ArXivSniffer实例。
        
        创建缓存目录（如果不存在），并设置基本配置。
        
        Args:
            cache_dir: PDF文件缓存目录路径，默认为 "./pdf_cache"
        
        Example:
            # 使用默认缓存目录
            sniffer = ArXivSniffer()
            
            # 使用自定义缓存目录
            sniffer = ArXivSniffer(cache_dir="/tmp/arxiv_pdfs")
        """
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def build_query(
        self,
        keywords: List[str],
        categories: Optional[List[str]] = None,
        search_all_fields: bool = False,
        use_or_for_categories: bool = False,
        search_strategy: str = SearchStrategy.MODERATE,
    ) -> str:
        """
        构建arXiv API的搜索查询字符串。
        
        根据提供的关键词、分类和搜索策略，构建符合arXiv API语法的查询字符串。
        
        查询语法说明：
        - all:keyword - 搜索所有字段
        - ti:keyword - 仅搜索标题
        - abs:keyword - 仅搜索摘要
        - cat:category - 按分类搜索
        - "phrase" - 精确短语匹配（带双引号）
        
        Args:
            keywords: 搜索关键词列表，如 ["LLM", "transformer"]
            categories: arXiv分类列表，如 ["cs.CL", "cs.AI"]，为None则不限制分类
            search_all_fields: 是否搜索所有字段，False则仅搜索标题和摘要
            use_or_for_categories: 关键词和分类的逻辑关系，True为OR，False为AND
            search_strategy: 搜索策略，可选 SearchStrategy.STRICT/MODERATE/BROAD
        
        Returns:
            构建完成的查询字符串，可直接用于arXiv API
        
        Raises:
            ValueError: 当keywords和categories都为空时抛出
        
        Example:
            query = sniffer.build_query(
                keywords=["LLM", "transformer"],
                categories=["cs.CL", "cs.AI"],
                search_all_fields=False,
                use_or_for_categories=False,
                search_strategy=SearchStrategy.MODERATE
            )
            # 输出类似: ((ti:LLM OR abs:LLM) OR (ti:transformer OR abs:transformer)) AND (cat:cs.CL OR cat:cs.AI)
        """
        if not keywords and not categories:
            raise ValueError("必须提供至少一个关键词或分类")

        print(f"\n  构建搜索查询...")
        print(f"    关键词: {keywords}")
        print(f"    分类: {categories}")
        print(f"    搜索策略: {search_strategy}")
        print(f"    搜索所有字段: {search_all_fields}")
        print(f"    关键词和分类逻辑: {'OR' if use_or_for_categories else 'AND'}")

        keyword_part = None
        category_part = None

        if keywords:
            keyword_queries = []
            for keyword in keywords:
                if search_strategy == SearchStrategy.STRICT:
                    quoted_keyword = f'"{keyword}"'
                    if search_all_fields:
                        keyword_queries.append(f"all:{quoted_keyword}")
                    else:
                        keyword_queries.append(f"(ti:{quoted_keyword} OR abs:{quoted_keyword})")
                elif search_strategy == SearchStrategy.MODERATE:
                    if search_all_fields:
                        keyword_queries.append(f"all:{keyword}")
                    else:
                        keyword_queries.append(f"(ti:{keyword} OR abs:{keyword})")
                else:
                    keyword_queries.append(f"all:{keyword}")

            keyword_part = " OR ".join(keyword_queries)
            print(f"    关键词查询: {keyword_part}")

        if categories:
            category_queries = [f"cat:{cat}" for cat in categories]
            category_part = " OR ".join(category_queries)
            print(f"    分类查询: {category_part}")

        if not keywords:
            query = category_part
            print(f"    最终查询 (仅分类): {query}")
            return query

        if not categories:
            query = keyword_part
            print(f"    最终查询 (仅关键词): {query}")
            return query

        if use_or_for_categories:
            query = f"({keyword_part}) OR ({category_part})"
            logic = "OR"
        else:
            query = f"({keyword_part}) AND ({category_part})"
            logic = "AND"

        print(f"    最终查询 ({logic}): {query}")
        return query

    def search(
        self,
        keywords: List[str],
        categories: Optional[List[str]] = None,
        max_results: int = 10,
        sort_by: str = "submittedDate",
        search_all_fields: bool = False,
        use_or_for_categories: bool = False,
        search_strategy: str = SearchStrategy.MODERATE,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> List[Paper]:
        """
        使用arXiv API搜索论文。

        该方法构建查询字符串，调用arXiv API，解析返回的Atom Feed，
        并返回Paper对象列表。搜索结果默认按提交时间降序排列。

        Args:
            keywords: 搜索关键词列表
            categories: arXiv分类列表，为None则不限制分类
            max_results: 返回的最大结果数，默认为10
            sort_by: 排序方式，可选 "submittedDate"（提交时间）或 "relevance"（相关度）
            search_all_fields: 是否搜索所有字段，False则仅搜索标题和摘要
            use_or_for_categories: 关键词和分类的逻辑关系，True为OR，False为AND
            search_strategy: 搜索策略，可选 SearchStrategy.STRICT/MODERATE/BROAD
            date_from: 发布时间下限（含），为None则不限制开始时间，须为UTC时区
            date_to: 发布时间上限（含），为None则不限制结束时间，须为UTC时区
        
        Returns:
            Paper对象列表，按提交时间降序排列。如果搜索失败或无结果，返回空列表。
        
        Example:
            # 基本搜索
            papers = sniffer.search(
                keywords=["LLM", "transformer"],
                categories=["cs.CL", "cs.AI"],
                max_results=5
            )
            
            # 宽松搜索（OR逻辑）
            papers = sniffer.search(
                keywords=["LLM"],
                categories=["cs.CL", "cs.AI"],
                use_or_for_categories=True,
                search_all_fields=True
            )
            
            # 按相关度排序
            papers = sniffer.search(
                keywords=["attention mechanism"],
                sort_by="relevance"
            )
        """
        query = self.build_query(
            keywords=keywords,
            categories=categories,
            search_all_fields=search_all_fields,
            use_or_for_categories=use_or_for_categories,
            search_strategy=search_strategy,
        )

        params = {
            "search_query": query,
            "sortBy": sort_by,
            "sortOrder": "descending",
            "start": 0,
            "max_results": max_results,
        }

        full_url = f"{self.ARXIV_API_URL}?{urlencode(params)}"
        print(f"\n  arXiv API请求: {full_url}")

        try:
            max_retries = 5
            retry_delays = [3, 10, 30, 60, 120]
            response = None
            for attempt in range(max_retries):
                response = requests.get(self.ARXIV_API_URL, params=params, timeout=30)
                if response.status_code == 429:
                    delay = retry_delays[attempt]
                    print(f"  arXiv API限流 (429)，等待 {delay}s 后重试 ({attempt+1}/{max_retries})...")
                    time.sleep(delay)
                    continue
                response.raise_for_status()
                break
            else:
                print(f"  请求失败: arXiv API持续限流，已达最大重试次数")
                return []

            print(f"  响应状态码: {response.status_code}")
            print(f"  响应内容长度: {len(response.content)} bytes")

            feed = feedparser.parse(response.content)

            if hasattr(feed, 'bozo') and feed.bozo != 0:
                print(f"  警告: Feed解析错误: {feed.bozo_exception}")

            total_results = "N/A"
            if hasattr(feed.feed, 'opensearch_totalresults'):
                total_results = feed.feed.opensearch_totalresults
                print(f"  总匹配结果数: {total_results}")

            papers = []
            print(f"  解析到 {len(feed.entries)} 个条目")

            for i, entry in enumerate(feed.entries):
                print(f"\n    条目 {i+1}:")

                arxiv_id = self._extract_arxiv_id(entry.id)
                pdf_url = f"{self.PDF_BASE_URL}/{arxiv_id}.pdf"

                authors = []
                if hasattr(entry, 'authors'):
                    authors = [author.name for author in entry.authors]
                elif hasattr(entry, 'author'):
                    authors = [entry.author]

                categories = []
                if hasattr(entry, 'tags') and entry.tags:
                    categories = [tag.term for tag in entry.tags]

                title = getattr(entry, 'title', 'N/A').replace("\n", " ").strip()
                print(f"      arXiv ID: {arxiv_id}")
                print(f"      标题: {title[:80]}{'...' if len(title) > 80 else ''}")
                print(f"      分类: {', '.join(categories) if categories else '未知'}")
                print(f"      作者数: {len(authors)}")

                paper = Paper(
                    title=title,
                    authors=authors,
                    summary=getattr(entry, 'summary', '').replace("\n", " ").strip(),
                    arxiv_id=arxiv_id,
                    pdf_url=pdf_url,
                    published=getattr(entry, 'published', ''),
                    categories=categories,
                )
                papers.append(paper)

            if not papers and categories:
                print(f"\n  提示: 当前搜索策略可能过于严格，请考虑:")
                print(f"    1. 调整 SEARCH_STRATEGY 为 'moderate' 或 'broad'")
                print(f"    2. 设置 USE_OR_FOR_CATEGORIES=true (关键词 OR 分类)")
                print(f"    3. 扩展关键词列表")
                print(f"    4. 减少分类限制")

            if date_from or date_to:
                papers = self._filter_by_date(papers, date_from, date_to)

            return papers

        except requests.exceptions.RequestException as e:
            print(f"  请求错误: {e}")
            return []
        except Exception as e:
            print(f"  搜索过程中发生错误: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _parse_published(self, published: str) -> Optional[datetime]:
        """将 arXiv published 字符串解析为 UTC aware datetime，失败返回 None。"""
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(published, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
        return None

    def _filter_by_date(
        self,
        papers: List[Paper],
        date_from: Optional[datetime],
        date_to: Optional[datetime],
    ) -> List[Paper]:
        """按发布时间过滤论文列表，date_from/date_to 须为 UTC aware datetime。"""
        result = []
        skipped = 0
        for paper in papers:
            pub_dt = self._parse_published(paper.published)
            if pub_dt is None:
                result.append(paper)
                continue
            if date_from and pub_dt < date_from:
                skipped += 1
                continue
            if date_to and pub_dt > date_to:
                skipped += 1
                continue
            result.append(paper)
        if skipped:
            print(f"  日期过滤: 保留 {len(result)} 篇，过滤掉 {skipped} 篇")
        return result

    def _extract_arxiv_id(self, entry_id: str) -> str:
        """
        从arXiv条目ID中提取数字ID。
        
        内部方法，用于解析arXiv API返回的条目ID。
        
        arXiv ID格式：
        - 新格式: http://arxiv.org/abs/2401.12345v1 -> 2401.12345
        - 旧格式: http://arxiv.org/abs/hep-th/0412015v1 -> hep-th/0412015
        
        Args:
            entry_id: arXiv API返回的完整条目ID URL
        
        Returns:
            提取后的纯数字ID或分类前缀+数字ID
        
        Example:
            id = sniffer._extract_arxiv_id("http://arxiv.org/abs/2401.12345v1")
            # 输出: "2401.12345"
        """
        match = re.search(r"(\d+\.\d+)", entry_id)
        if match:
            return match.group(1)
        return entry_id.split("/")[-1]

    def download_pdf(self, paper: Paper) -> str:
        """
        下载单篇论文的PDF文件。
        
        从arXiv下载PDF文件到缓存目录，并更新Paper对象的local_pdf_path属性。
        如果文件已存在，则直接返回已存在的路径。
        
        Args:
            paper: Paper对象，必须包含有效的pdf_url
        
        Returns:
            本地PDF文件的完整路径
        
        Raises:
            requests.exceptions.HTTPError: 当下载失败时抛出
            requests.exceptions.Timeout: 当下载超时时抛出
        
        Example:
            paper = papers[0]
            pdf_path = sniffer.download_pdf(paper)
            print(f"PDF已保存到: {pdf_path}")
            # paper.local_pdf_path 现在包含下载路径
        """
        pdf_path = os.path.join(self.cache_dir, f"{paper.arxiv_id}.pdf")

        if os.path.exists(pdf_path):
            paper.local_pdf_path = pdf_path
            return pdf_path

        print(f"  下载PDF: {paper.pdf_url}")
        response = requests.get(paper.pdf_url, timeout=60)
        response.raise_for_status()

        with open(pdf_path, "wb") as f:
            f.write(response.content)

        paper.local_pdf_path = pdf_path
        print(f"  已保存到: {pdf_path}")
        return pdf_path

    def download_pdfs(self, papers: List[Paper]) -> List[str]:
        """
        批量下载多篇论文的PDF文件。
        
        遍历Paper列表，逐个调用download_pdf()方法下载PDF。
        如果某个论文下载失败，会打印错误信息但继续下载其他论文。
        
        Args:
            papers: Paper对象列表
        
        Returns:
            成功下载的PDF文件路径列表
        
        Example:
            papers = sniffer.search(keywords=["LLM"], max_results=5)
            downloaded = sniffer.download_pdfs(papers)
            print(f"成功下载 {len(downloaded)} 个PDF文件")
        """
        downloaded_paths = []
        for paper in papers:
            try:
                path = self.download_pdf(paper)
                downloaded_paths.append(path)
            except Exception as e:
                print(f"  下载失败 {paper.arxiv_id}: {e}")
        return downloaded_paths

    def cleanup_pdf(self, paper: Paper) -> bool:
        """
        清理单篇论文的本地PDF缓存。
        
        删除Paper对象对应的本地PDF文件，并将local_pdf_path设为None。
        
        Args:
            paper: Paper对象，其local_pdf_path应指向存在的文件
        
        Returns:
            成功删除返回True，文件不存在或删除失败返回False
        
        Example:
            # 处理完论文后清理
            for paper in papers:
                if paper.local_pdf_path:
                    sniffer.cleanup_pdf(paper)
        """
        if paper.local_pdf_path and os.path.exists(paper.local_pdf_path):
            os.remove(paper.local_pdf_path)
            paper.local_pdf_path = None
            return True
        return False

    def cleanup_all_pdfs(self, papers: List[Paper]) -> int:
        """
        批量清理所有论文的本地PDF缓存。
        
        遍历Paper列表，逐个调用cleanup_pdf()方法删除PDF文件。
        
        Args:
            papers: Paper对象列表
        
        Returns:
            成功删除的文件数量
        
        Example:
            # 全部处理完成后一次性清理
            deleted = sniffer.cleanup_all_pdfs(papers)
            print(f"已清理 {deleted} 个PDF缓存文件")
        """
        count = 0
        for paper in papers:
            if self.cleanup_pdf(paper):
                count += 1
        return count
