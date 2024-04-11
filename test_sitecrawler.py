import asyncio
import inspect
import json
import time
import unittest
import asynctest
from unittest.mock import AsyncMock, MagicMock
from sitecrawler import _do_ai_parsing, RequestError
from asyncio import Future

from sitecrawler import SiteCrawler, ExtractionRules, do_extract
import os
import configparser
from typing import Iterator, Any

class AwaitableMock(AsyncMock):
    def __await__(self) :
        # self.await_count += 1
        return self.return_value

class TestDoAIParsing(asynctest.TestCase):
    async def setUp(self):
        config = configparser.ConfigParser()
        config.read('config.cfg')
        os.environ['ZYTE_API_KEY'] = config.get('DEFAULT', 'ZYTE_API_KEY')
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
        client = MagicMock()
        mock = AsyncMock()
        mock.return_value = {'url': 'https://www.searchstax.com/', 'article': article}

        client.request_parallel_as_completed.return_value = [mock]

        with unittest.mock.patch('sitecrawler.AsyncClient', return_value=client):
            # print(await client.request_parallel_as_completed()[0])
            resp_obj = await _do_ai_parsing(self.requests)
            self.assertEqual(len(resp_obj), 1)
            self.assertEqual(resp_obj[0]['uri'], 'https://www.searchstax.com/')
            self.assertEqual(resp_obj[0]['title'], 'Test Headline')
            self.assertEqual(resp_obj[0]['content'], 'Test Body')
            self.assertEqual(resp_obj[0]['description'], 'Test Description')
            self.assertEqual(resp_obj[0]['image'], 'https://www.example.com/image.jpg')
            self.assertEqual(resp_obj[0]['datePublishedRaw'], '2022-01-01')
            self.assertEqual(resp_obj[0]['dateModifiedRaw'], '2022-01-02')

    # async def test_do_ai_parsing_request_error(self):
    #     self.client.request_parallel_as_completed = asynctest.CoroutineMock(side_effect=RequestError('Error', response_content='', history=''))
    #     with self.assertLogs(level='ERROR') as cm:
    #         resp_obj = await _do_ai_parsing(self.requests)
    #     self.assertEqual(len(resp_obj), 0)
    #     self.assertIn('Error', cm.output[0])


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


if __name__ == '__main__':
    unittest.main()
