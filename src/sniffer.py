import os
import re
import requests
import feedparser
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from urllib.parse import quote, urlencode


class Paper:
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
        self.title = title
        self.authors = authors
        self.summary = summary
        self.arxiv_id = arxiv_id
        self.pdf_url = pdf_url
        self.published = published
        self.categories = categories
        self.local_pdf_path: Optional[str] = None


class ArXivSniffer:
    ARXIV_API_URL = "http://export.arxiv.org/api/query"
    PDF_BASE_URL = "https://arxiv.org/pdf"

    def __init__(self, cache_dir: str = "./pdf_cache"):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def build_query(
        self,
        keywords: List[str],
        categories: Optional[List[str]] = None,
        search_all_fields: bool = False,
        use_or_for_categories: bool = True,
    ) -> str:
        keyword_queries = []
        for keyword in keywords:
            if search_all_fields:
                keyword_queries.append(f"all:{keyword}")
            else:
                keyword_queries.append(f"(ti:{keyword} OR abs:{keyword})")

        keyword_part = " OR ".join(keyword_queries)

        if not categories:
            return keyword_part

        category_queries = [f"cat:{cat}" for cat in categories]
        category_part = " OR ".join(category_queries)

        if use_or_for_categories:
            return f"({keyword_part}) OR ({category_part})"
        else:
            return f"({keyword_part}) AND ({category_part})"

    def search(
        self,
        keywords: List[str],
        categories: Optional[List[str]] = None,
        max_results: int = 10,
        sort_by: str = "submittedDate",
        search_all_fields: bool = True,
    ) -> List[Paper]:
        query = self.build_query(
            keywords=keywords,
            categories=categories,
            search_all_fields=search_all_fields,
        )

        params = {
            "search_query": query,
            "sortBy": sort_by,
            "sortOrder": "descending",
            "start": 0,
            "max_results": max_results,
        }

        full_url = f"{self.ARXIV_API_URL}?{urlencode(params)}"
        print(f"  arXiv API请求: {full_url}")

        try:
            response = requests.get(self.ARXIV_API_URL, params=params, timeout=30)
            response.raise_for_status()

            print(f"  响应状态码: {response.status_code}")
            print(f"  响应内容长度: {len(response.content)} bytes")

            feed = feedparser.parse(response.content)

            if hasattr(feed, 'bozo') and feed.bozo != 0:
                print(f"  警告: Feed解析错误: {feed.bozo_exception}")

            if hasattr(feed.feed, 'opensearch_totalresults'):
                print(f"  总匹配结果数: {feed.feed.opensearch_totalresults}")

            papers = []
            print(f"  解析到 {len(feed.entries)} 个条目")

            for i, entry in enumerate(feed.entries):
                print(f"    条目 {i+1}: title={getattr(entry, 'title', 'N/A')[:50]}...")

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

                paper = Paper(
                    title=entry.title.replace("\n", " ").strip() if hasattr(entry, 'title') else "",
                    authors=authors,
                    summary=entry.summary.replace("\n", " ").strip() if hasattr(entry, 'summary') else "",
                    arxiv_id=arxiv_id,
                    pdf_url=pdf_url,
                    published=entry.published if hasattr(entry, 'published') else "",
                    categories=categories,
                )
                papers.append(paper)

            return papers

        except requests.exceptions.RequestException as e:
            print(f"  请求错误: {e}")
            return []
        except Exception as e:
            print(f"  搜索过程中发生错误: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _extract_arxiv_id(self, entry_id: str) -> str:
        match = re.search(r"(\d+\.\d+)", entry_id)
        if match:
            return match.group(1)
        return entry_id.split("/")[-1]

    def download_pdf(self, paper: Paper) -> str:
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
        downloaded_paths = []
        for paper in papers:
            try:
                path = self.download_pdf(paper)
                downloaded_paths.append(path)
            except Exception as e:
                print(f"  下载失败 {paper.arxiv_id}: {e}")
        return downloaded_paths

    def cleanup_pdf(self, paper: Paper) -> bool:
        if paper.local_pdf_path and os.path.exists(paper.local_pdf_path):
            os.remove(paper.local_pdf_path)
            paper.local_pdf_path = None
            return True
        return False

    def cleanup_all_pdfs(self, papers: List[Paper]) -> int:
        count = 0
        for paper in papers:
            if self.cleanup_pdf(paper):
                count += 1
        return count
