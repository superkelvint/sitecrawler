import json
import time
import unittest
import asynctest
import uuid
from unittest.mock import AsyncMock
from sitecrawler import _do_ai_parsing, RequestError

from sitecrawler import SiteCrawler, ExtractionRules, do_extract, get_type_from_url, dom_cleaner, create_id, get_path



class TestDoAIParsing(asynctest.TestCase):
    async def setUp(self):
        self.requests = [{'url': 'https://www.searchstax.com/', 'article': True}]
        self.client = asynctest.CoroutineMock()
        self.session = asynctest.CoroutineMock()
        self.create_session = asynctest.CoroutineMock(return_value=self.session)

    async def test_do_ai_parsing_success(self):
        article = {
            'headline': 'Test Headline',
            'articleBody': 'Test Body',
            'description': 'Test Description',
            'mainImage': {'url': 'https://www.example.com/image.jpg'},
            'datePublishedRaw': '2022-01-01',
            'dateModifiedRaw': '2022-01-02'
        }
        mock = AsyncMock()
        mock.return_value = {'url': 'https://www.searchstax.com/', 'article': article}

        self.client.request_parallel_as_completed.return_value = [mock()]

        with unittest.mock.patch('sitecrawler.AsyncClient', return_value=self.client):
            resp_obj = await _do_ai_parsing(self.requests)
            self.assertEqual(len(resp_obj), 1)
            self.assertEqual(resp_obj[0]['uri'], 'https://www.searchstax.com/')
            self.assertEqual(resp_obj[0]['title'], 'Test Headline')
            self.assertEqual(resp_obj[0]['content'], 'Test Body')
            self.assertEqual(resp_obj[0]['description'], 'Test Description')
            self.assertEqual(resp_obj[0]['image'], 'https://www.example.com/image.jpg')
            self.assertEqual(resp_obj[0]['datePublishedRaw'], '2022-01-01')
            self.assertEqual(resp_obj[0]['dateModifiedRaw'], '2022-01-02')

    async def test_do_ai_parsing_request_error(self):
        mock = AsyncMock()
        mock.side_effect = RequestError('Error', response_content='', history='')
        self.client.request_parallel_as_completed.return_value = [mock()]
        with unittest.mock.patch('sitecrawler.AsyncClient', return_value=self.client):
            with self.assertLogs(level='ERROR') as cm:
                resp_obj = await _do_ai_parsing(self.requests)
            self.assertEqual(len(resp_obj), 0)
            self.assertIn('Error', cm.output[0])


class TestSiteCrawler(unittest.TestCase):

    def test_valid_link_domains(self):
        crawler = SiteCrawler("testing", starting_urls=["https://www.example.com"], allow_starting_url_tld=True,
                              allow_starting_url_hostname=True)
        self.assertTrue(crawler.valid_link("https://www.example.com", "https://www.example.com"))
        self.assertTrue(crawler.valid_link("https://www.example.com", "https://www.example.com/index.html"))
        self.assertTrue(crawler.valid_link("https://www.example.com", "https://www.example.com/foo/index.html"))
        self.assertTrue(crawler.valid_link("https://www.example.com", "https://example.com/index.html"))
        self.assertTrue(crawler.valid_link("https://www.example.com", "https://foo.example.com/index.html"))
        self.assertTrue(crawler.valid_link("https://www.example.com", "http://foo.example.com/index.html"))

        self.assertFalse(crawler.valid_link("https://www.example.com", "https://google.com/index.html"))

        crawler = SiteCrawler("testing", starting_urls=["https://www.example.com"],
                              allow_starting_url_tld=False,
                              allow_starting_url_hostname=True)
        self.assertTrue(crawler.valid_link("https://www.example.com", "https://www.example.com/index.html"))
        self.assertFalse(crawler.valid_link("https://www.example.com", "https://example.com/index.html"))
        self.assertFalse(crawler.valid_link("https://www.example.com", "https://foo.example.com/index.html"))
        self.assertFalse(crawler.valid_link("https://www.example.com", "https://google.com/index.html"))

        crawler = SiteCrawler("testing", starting_urls=["https://www.example.com"],
                              allow_starting_url_tld=True,
                              allow_starting_url_hostname=False)
        self.assertTrue(crawler.valid_link("https://www.example.com", "https://www.example.com/index.html"))
        self.assertTrue(crawler.valid_link("https://www.example.com", "https://example.com/index.html"))
        self.assertTrue(crawler.valid_link("https://www.example.com", "https://foo.example.com/index.html"))
        self.assertFalse(crawler.valid_link("https://www.example.com", "https://google.com/index.html"))

        crawler = SiteCrawler("testing", starting_urls=["https://www.example.com"],
                              allowed_domains=["foo.example.com"],
                              allow_starting_url_tld=False,
                              allow_starting_url_hostname=False)
        self.assertFalse(crawler.valid_link("https://www.example.com", "https://www.example.com/index.html"))
        self.assertFalse(crawler.valid_link("https://www.example.com", "https://example.com/index.html"))
        self.assertTrue(crawler.valid_link("https://www.example.com", "https://foo.example.com/index.html"))
        self.assertFalse(crawler.valid_link("https://www.example.com", "https://google.com/index.html"))

    def test_valid_link_includes_excludes(self):
        crawler = SiteCrawler("testing", starting_urls=["https://www.example.com"],
                              allowed_regex=[".html$"],
                              denied_regex=[".css$"],
                              )
        self.assertTrue(crawler.valid_link("https://www.example.com", "https://www.example.com/index.html"))
        self.assertFalse(crawler.valid_link("https://www.example.com", "https://www.example.com/index.css"))

        # any link that is not explicitly excluded is allowed as long as it matches domain rules
        self.assertTrue(crawler.valid_link("https://www.example.com", "https://www.example.com/index.htmlsss"))

    def test_extract_css(self):
        content = "<html><title>foo</title></html>"
        rules = ExtractionRules.model_validate_json(
            json.dumps({"rules": [{"field_name": "title", "css": "title"}, {"field_name": "desc", "css": "bar"}]}))
        self.assertEqual("foo", do_extract(content, rules)["title"])
        self.assertEqual("", do_extract(content, rules)["desc"])

        content = "<html><title>foo</title><title>bar</title></html>"
        rules = ExtractionRules.model_validate_json(
            json.dumps({"rules": [{"field_name": "title", "css": "title"}, {"field_name": "desc", "css": "bar"}]}))
        self.assertEqual(["foo", "bar"], do_extract(content, rules)["title"])

    def test_extract_regex(self):
        content = "<html><title>foo</title><animal>cat</animal></html>"
        rules = ExtractionRules.model_validate_json(
            json.dumps({"rules": [{"field_name": "title", "regex": "<animal>(.*?)</animal>"}]}))
        self.assertEqual("cat", do_extract(content, rules)["title"])

        rules = ExtractionRules.model_validate_json(
            json.dumps({"rules": [{"field_name": "title", "regex": "<animals>(.*?)</animals>"}]}))
        self.assertEqual("", do_extract(content, rules)["title"])

    def test_cache_expiry(self):
        crawler = SiteCrawler("testing", [], cache_ttl_hours=-1, init_collection=False)
        crawler.collection = {"foo": {"type": "content"}}
        self.assertTrue(crawler.is_cached_url("foo"))

        crawler = SiteCrawler("testing", [], cache_ttl_hours=0.5, init_collection=False)
        crawler.collection = {"foo": {"type": "content", "crawled": time.time() - 3600}}
        self.assertFalse(crawler.is_cached_url("foo"))

    def test_get_type_from_url_with_path(self):
        url = "http://example.com/path/to/page"
        result = get_type_from_url(url)
        self.assertEqual(result, "Path")

    def test_get_type_from_url_with_dash_in_path(self):
        url = "http://example.com/path-to-page"
        result = get_type_from_url(url)
        self.assertEqual(result, "Path To Page")

    def test_get_type_from_url_with_underscore_in_path(self):
        url = "http://example.com/path_to_page"
        result = get_type_from_url(url)
        self.assertEqual(result, "Path To Page")

    def test_get_type_from_url_without_path(self):
        url = "http://example.com/"
        result = get_type_from_url(url)
        self.assertEqual(result, "Web Page")

    def test_get_type_from_url_with_nested_path(self):
        url = "http://example.com/path/to/page"
        result = get_type_from_url(url)
        self.assertEqual(result, "Path")

    def test_get_type_from_url_with_multiple_dashes_and_underscores_in_path(self):
        url = "http://example.com/path-to_page/other-path_to_page"
        result = get_type_from_url(url)
        self.assertEqual(result, "Path To Page")

    def test_dom_cleaner_removes_javascript(self):
        content = "<html><body><script type='text/javascript'>alert('test');</script></body></html>"
        cleaned_content = dom_cleaner(content)
        self.assertNotIn("<script", cleaned_content)

    def test_dom_cleaner_removes_style(self):
        content = "<html><body><style>body {color: red;}</style></body></html>"
        cleaned_content = dom_cleaner(content)
        self.assertNotIn("<style", cleaned_content)

    def test_dom_cleaner_removes_kill_tags(self):
        content = "<html><body><nav>Test</nav></body></html>"
        cleaned_content = dom_cleaner(content)
        self.assertNotIn("<div", cleaned_content)

    def test_dom_cleaner_returns_clean_html(self):
        content = "<html><body><p>Test</p></body></html>"
        cleaned_content = dom_cleaner(content)
        self.assertEqual(cleaned_content, content)

    def test_create_id(self):
        url = "http://example.com"
        expected_id = str(uuid.uuid3(uuid.NAMESPACE_URL, url))
        result_id = create_id(url)
        self.assertEqual(result_id, expected_id)

    def test_get_path_with_path(self):
        url = "http://www.example.com/test/path"
        expected_result = "test / path"
        self.assertEqual(get_path(url), expected_result)

    def test_get_path_without_path(self):
        url = "http://www.example.com"
        expected_result = "www.example.com"
        self.assertEqual(get_path(url), expected_result)

    def test_get_path_with_nested_path(self):
        url = "http://www.example.com/test/path/nested"
        expected_result = "test / path / nested"
        self.assertEqual(get_path(url), expected_result)

    def test_get_path_with_trailing_slash(self):
        url = "http://www.example.com/test/path/"
        expected_result = "test / path"
        self.assertEqual(get_path(url), expected_result)

if __name__ == '__main__':
    unittest.main()
