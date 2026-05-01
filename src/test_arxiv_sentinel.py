import os
import sys
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sniffer import ArXivSniffer, Paper
from summarizer import PDFExtractor, SiliconFlowClient, Summarizer
from publisher import MkDocsPublisher
from config import Config, ConfigManager


class TestPaper(unittest.TestCase):
    def test_paper_creation(self):
        paper = Paper(
            title="Test Paper",
            authors=["Author 1", "Author 2"],
            summary="This is a test paper.",
            arxiv_id="2401.01234",
            pdf_url="https://arxiv.org/pdf/2401.01234.pdf",
            published="2024-01-15T00:00:00Z",
            categories=["cs.AI", "cs.CL"],
        )

        self.assertEqual(paper.title, "Test Paper")
        self.assertEqual(paper.arxiv_id, "2401.01234")
        self.assertEqual(paper.authors, ["Author 1", "Author 2"])
        self.assertEqual(paper.categories, ["cs.AI", "cs.CL"])
        self.assertIsNone(paper.local_pdf_path)

    def test_paper_with_local_path(self):
        paper = Paper(
            title="Test Paper",
            authors=["Author"],
            summary="Summary",
            arxiv_id="2401.01234",
            pdf_url="https://arxiv.org/pdf/2401.01234.pdf",
            published="2024-01-15T00:00:00Z",
            categories=["cs.AI"],
        )
        paper.local_pdf_path = "/tmp/test.pdf"
        self.assertEqual(paper.local_pdf_path, "/tmp/test.pdf")


class TestArXivSniffer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.sniffer = ArXivSniffer(cache_dir=self.temp_dir)

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_build_query_with_keywords(self):
        keywords = ["LLM", "transformer"]
        query = self.sniffer.build_query(keywords)
        self.assertIn("LLM", query)
        self.assertIn("transformer", query)

    def test_build_query_with_categories(self):
        keywords = ["LLM"]
        categories = ["cs.AI", "cs.CL"]
        query = self.sniffer.build_query(keywords, categories)
        self.assertIn("LLM", query)
        self.assertIn("cs.AI", query)
        self.assertIn("cs.CL", query)

    def test_extract_arxiv_id(self):
        test_cases = [
            ("http://arxiv.org/abs/2401.01234", "2401.01234"),
            ("http://arxiv.org/abs/2401.01234v1", "2401.01234"),
            ("https://arxiv.org/pdf/2401.01234.pdf", "2401.01234"),
            ("2401.01234", "2401.01234"),
        ]

        for input_id, expected in test_cases:
            result = self.sniffer._extract_arxiv_id(input_id)
            self.assertEqual(result, expected, f"Failed for input: {input_id}")

    @patch('requests.get')
    def test_search(self, mock_get):
        mock_response = MagicMock()
        mock_response.content = self._get_mock_feed_xml()
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        papers = self.sniffer.search(keywords=["test"], max_results=2)

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].title, "Test Paper Title")
        self.assertEqual(papers[0].arxiv_id, "2401.01234")

    def _get_mock_feed_xml(self):
        return b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <link href="http://arxiv.org/api/query"/>
  <id>http://arxiv.org/api/query</id>
  <updated>2024-01-15T00:00:00Z</updated>
  <entry>
    <id>http://arxiv.org/abs/2401.01234v1</id>
    <title>Test Paper Title</title>
    <summary>This is a test summary of the paper.</summary>
    <published>2024-01-15T00:00:00Z</published>
    <author><name>Test Author</name></author>
    <category term="cs.AI"/>
    <category term="cs.CL"/>
  </entry>
</feed>"""

    def test_cleanup_pdf_nonexistent(self):
        paper = Paper(
            title="Test",
            authors=["Author"],
            summary="Summary",
            arxiv_id="2401.01234",
            pdf_url="https://arxiv.org/pdf/2401.01234.pdf",
            published="2024-01-15T00:00:00Z",
            categories=["cs.AI"],
        )
        paper.local_pdf_path = os.path.join(self.temp_dir, "nonexistent.pdf")

        result = self.sniffer.cleanup_pdf(paper)
        self.assertFalse(result)


class TestPDFExtractor(unittest.TestCase):
    def setUp(self):
        self.extractor = PDFExtractor()

    def test_extract_text_raises_on_nonexistent(self):
        with self.assertRaises(Exception):
            self.extractor.extract_text("/nonexistent/file.pdf")


class TestSiliconFlowClient(unittest.TestCase):
    def setUp(self):
        self.client = SiliconFlowClient(api_key="test_key", model="test/model")

    @patch('requests.post')
    def test_chat_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Test response from AI"}}]
        }
        mock_post.return_value = mock_response

        response = self.client.chat(prompt="Hello", system_prompt="System prompt")

        self.assertEqual(response, "Test response from AI")
        mock_post.assert_called_once()

    @patch('requests.post')
    def test_chat_api_error(self, mock_post):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("API Error")
        mock_post.return_value = mock_response

        with self.assertRaises(Exception):
            self.client.chat(prompt="Hello")


class TestSummarizer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.prompt_dir = os.path.join(self.temp_dir, "prompts")
        os.makedirs(self.prompt_dir)

        with open(os.path.join(self.prompt_dir, "summary_prompt.txt"), "w") as f:
            f.write("Summary prompt: {content}")

        with open(os.path.join(self.prompt_dir, "technical_route_prompt.txt"), "w") as f:
            f.write("Technical route prompt: {content}")

        with open(os.path.join(self.prompt_dir, "methodology_prompt.txt"), "w") as f:
            f.write("Methodology prompt: {content}")

        with open(os.path.join(self.prompt_dir, "experiment_prompt.txt"), "w") as f:
            f.write("Experiment prompt: {content}")

        with open(os.path.join(self.prompt_dir, "introduction_prompt.txt"), "w") as f:
            f.write("Introduction prompt: {content}")

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_load_prompts(self):
        summarizer = Summarizer(siliconflow_api_key="test", prompt_dir=self.prompt_dir)

        self.assertIn("summary_prompt.txt", summarizer.prompts)
        self.assertIn("technical_route_prompt.txt", summarizer.prompts)

    def test_summarize_raises_without_pdf_path(self):
        summarizer = Summarizer(siliconflow_api_key="test", prompt_dir=self.prompt_dir)
        paper = Paper(
            title="Test",
            authors=["Author"],
            summary="Summary",
            arxiv_id="2401.01234",
            pdf_url="https://arxiv.org/pdf/2401.01234.pdf",
            published="2024-01-15T00:00:00Z",
            categories=["cs.AI"],
        )

        with self.assertRaises(ValueError):
            summarizer.summarize(paper)

    def test_get_default_template(self):
        summarizer = Summarizer(siliconflow_api_key="test", prompt_dir=self.prompt_dir)
        template = summarizer._get_default_template()
        self.assertIn("title", template)
        self.assertIn("arxiv_id", template)
        self.assertIn("summary", template)


class TestConfig(unittest.TestCase):
    def test_default_config(self):
        config = Config()
        self.assertEqual(config.SILICONFLOW_MODEL, "Qwen/Qwen2.5-7B-Instruct")
        self.assertEqual(config.MAX_RESULTS_PER_SEARCH, 10)
        self.assertIn("LLM", config.KEYWORDS)

    def test_to_dict(self):
        config = Config(SILICONFLOW_API_KEY="test_key")
        data = config.to_dict()
        self.assertEqual(data["SILICONFLOW_API_KEY"], "test_key")

    def test_from_dict(self):
        data = {
            "SILICONFLOW_API_KEY": "test_key",
            "KEYWORDS": ["custom", "keywords"],
            "MAX_RESULTS_PER_SEARCH": 5,
        }
        config = Config.from_dict(data)
        self.assertEqual(config.SILICONFLOW_API_KEY, "test_key")
        self.assertEqual(config.KEYWORDS, ["custom", "keywords"])
        self.assertEqual(config.MAX_RESULTS_PER_SEARCH, 5)


class TestConfigManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = os.path.join(self.temp_dir, "test_config.json")

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_load_from_file(self):
        config_data = {
            "SILICONFLOW_API_KEY": "file_key",
            "KEYWORDS": ["test1", "test2"],
        }
        with open(self.config_file, "w") as f:
            json.dump(config_data, f)

        manager = ConfigManager(self.config_file)
        config = manager.get()

        self.assertEqual(config.SILICONFLOW_API_KEY, "file_key")
        self.assertEqual(config.KEYWORDS, ["test1", "test2"])

    def test_save_config(self):
        manager = ConfigManager(self.config_file)
        manager.update(SILICONFLOW_API_KEY="saved_key")

        self.assertTrue(os.path.exists(self.config_file))

        with open(self.config_file, "r") as f:
            data = json.load(f)

        self.assertEqual(data["SILICONFLOW_API_KEY"], "saved_key")

    def test_validate_missing_api_key(self):
        manager = ConfigManager(self.config_file)
        errors = manager.validate()
        self.assertEqual(len(errors), 1)
        self.assertIn("SILICONFLOW_API_KEY", errors[0])

    def test_validate_valid_config(self):
        manager = ConfigManager(self.config_file)
        manager.update(SILICONFLOW_API_KEY="valid_key")
        errors = manager.validate()
        self.assertEqual(len(errors), 0)


class TestMkDocsPublisher(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.page_dir = os.path.join(self.temp_dir, "page")
        self.publisher = MkDocsPublisher(page_dir=self.page_dir)

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_initialize_project(self):
        self.publisher.initialize_project(site_name="Test Site")

        self.assertTrue(os.path.exists(self.page_dir))
        self.assertTrue(os.path.exists(self.publisher.docs_dir))
        self.assertTrue(os.path.exists(self.publisher.mkdocs_yml_path))

        index_path = os.path.join(self.publisher.docs_dir, "index.md")
        self.assertTrue(os.path.exists(index_path))

    def test_generate_mkdocs_config(self):
        config = self.publisher._generate_mkdocs_config("Test Site", "Test Description")
        self.assertIn("site_name: Test Site", config)
        self.assertIn("theme:", config)

    def test_copy_markdown_files(self):
        self.publisher.initialize_project()

        test_md = os.path.join(self.temp_dir, "test.md")
        with open(test_md, "w") as f:
            f.write("# Test")

        copied = self.publisher.copy_markdown_files([test_md], subfolder="papers")
        self.assertEqual(len(copied), 1)
        self.assertTrue(os.path.exists(copied[0]))

    def test_copy_markdown_files_nonexistent(self):
        copied = self.publisher.copy_markdown_files(["/nonexistent.md"])
        self.assertEqual(len(copied), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
