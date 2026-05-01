import os
import re
import requests
import feedparser
from datetime import datetime
from typing import List, Dict, Optional
from urllib.parse import quote


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

    def build_query(self, keywords: List[str], categories: Optional[List[str]] = None) -> str:
        keyword_queries = []
        for keyword in keywords:
            quoted = quote(f'"{keyword}"')
            keyword_queries.append(f"(ti:{quoted} OR abs:{quoted})")

        query_parts = [" OR ".join(keyword_queries)]

        if categories:
            category_queries = [f"cat:{cat}" for cat in categories]
            query_parts.append(f"({ ' OR '.join(category_queries)})")

        return " AND ".join(query_parts)

    def search(self, keywords: List[str], categories: Optional[List[str]] = None, max_results: int = 10) -> List[Paper]:
        query = self.build_query(keywords, categories)

        params = {
            "search_query": query,
            "sortBy": "lastUpdatedDate",
            "sortOrder": "descending",
            "start": 0,
            "max_results": max_results,
        }

        response = requests.get(self.ARXIV_API_URL, params=params, timeout=30)
        response.raise_for_status()

        feed = feedparser.parse(response.content)

        papers = []
        for entry in feed.entries:
            arxiv_id = self._extract_arxiv_id(entry.id)
            pdf_url = f"{self.PDF_BASE_URL}/{arxiv_id}.pdf"

            paper = Paper(
                title=entry.title.replace("\n", " ").strip(),
                authors=[author.name for author in entry.authors],
                summary=entry.summary.replace("\n", " ").strip(),
                arxiv_id=arxiv_id,
                pdf_url=pdf_url,
                published=entry.published,
                categories=[tag.term for tag in entry.tags] if hasattr(entry, "tags") else [],
            )
            papers.append(paper)

        return papers

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

        response = requests.get(paper.pdf_url, timeout=60)
        response.raise_for_status()

        with open(pdf_path, "wb") as f:
            f.write(response.content)

        paper.local_pdf_path = pdf_path
        return pdf_path

    def download_pdfs(self, papers: List[Paper]) -> List[str]:
        downloaded_paths = []
        for paper in papers:
            try:
                path = self.download_pdf(paper)
                downloaded_paths.append(path)
            except Exception as e:
                print(f"Failed to download PDF for {paper.arxiv_id}: {e}")
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
