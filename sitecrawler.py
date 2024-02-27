import json
import logging
import os.path
import re
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Optional
from typing import Set, Tuple, Union

import xxhash
from celery.result import AsyncResult
from multidict import CIMultiDictProxy, CIMultiDict
from pydantic import BaseModel
from selectolax.parser import HTMLParser, Node
from tldextract import tldextract
from usp.tree import sitemap_tree_for_homepage

from aiocrawler import AsyncCrawler
from lmdb_collection import LmdbmDocumentCollection

global_excludes = {"\\.jpg", "\\.jpeg", "\\.png", "\\.mp4", "\\.webp", "\\.gif", "\\.css", "\\.js", "\\.pdf"}
logger = logging.getLogger('SiteCrawler')


class ExtractionRule(BaseModel):
    field_name: str
    css: Optional[str] = None
    regex: Optional[str] = None
    delimiter: Optional[str] = None
    attribute: Optional[str] = None


class ExtractionRules(BaseModel):
    rules: list[ExtractionRule]

    def compute_hash(self):
        return xxhash.xxh32_intdigest(json.dumps([k.model_dump_json() for k in self.rules]))


class SiteCrawler(AsyncCrawler):
    timeout = 10
    max_redirects = 2

    def __init__(self,
                 name: str,
                 starting_urls: list[str],
                 allowed_domains: list = None,
                 allowed_regex: list = None,
                 denied_regex: list = None,
                 denied_extensions: list = None,
                 is_sitemap=False,
                 max_depth: int = 300,
                 max_pages=-1,
                 concurrency: int = 10,
                 max_retries: int = 2,
                 if_modified_since_hours: int = -1,
                 cache_ttl_hours: float = -1,
                 allow_starting_url_hostname=True,
                 allow_starting_url_tld=False,
                 headers=None,
                 content_css_selector: str = None,
                 extraction_rules: Union[ExtractionRules, str, dict] = None,
                 user_agent: str = 'SiteCrawler/1.0',
                 data_dir: str = "data",
                 init_collection: bool = True
                 # primarily used for testing purposes to bypass creation of lmdb collection
                 ) -> None:
        if (isinstance(starting_urls, str)):
            starting_urls = [starting_urls]

        if headers is None:
            headers = {}
        if not "User-Agent" in headers:
            headers["User-Agent"] = user_agent

        if is_sitemap:
            max_depth = 1
            leaf_urls = set()
            for s in starting_urls:
                logger.info("Fetching sitemap for %s", s)
                tree = sitemap_tree_for_homepage(s)
                for page in tree.all_pages():
                    leaf_urls.add(page.url)
            super().__init__(starting_urls=list(leaf_urls), max_depth=max_depth,
                             max_pages=max_pages,
                             concurrency=concurrency,
                             max_retries=max_retries, headers=headers)
        else:
            super().__init__(starting_urls=starting_urls, max_depth=max_depth, max_pages=max_pages,
                             concurrency=concurrency,
                             max_retries=max_retries, headers=headers)
        if denied_extensions is None:
            denied_extensions = []
        if denied_regex is None:
            denied_regex = []
        if allowed_regex is None:
            allowed_regex = list()
        if allowed_domains is None:
            allowed_domains = list()
        if extraction_rules is None:
            extraction_rules = ExtractionRules(rules=[])

        self.allowed_domains = allowed_domains
        self.allowed_regex = allowed_regex
        self.denied_regex = denied_regex + list(global_excludes)
        self.denied_extensions = denied_extensions

        if isinstance(extraction_rules, str):
            self.extraction_rules = ExtractionRules.model_validate_json(extraction_rules)
        elif isinstance(extraction_rules, dict):
            self.extraction_rules = ExtractionRules.model_validate_json(json.dumps(extraction_rules))
        elif isinstance(extraction_rules, ExtractionRules):
            self.extraction_rules = extraction_rules

        self.cache_ttl_hours = cache_ttl_hours
        self.stats = Counter()

        for s in starting_urls:
            subdomain, tld = self.parse_tld(s)
            if allow_starting_url_hostname:
                self.allowed_domains.append(subdomain)
            if allow_starting_url_tld:
                self.allowed_domains.append(tld)
        self.name = name
        self.max_pages = max_pages
        self.max_redirects = 30
        timestamp = time.time()
        self.start_time = timestamp
        self.end_time = -1
        self.duration = -1
        self.celery_task: Optional[AsyncResult] = None

        if init_collection:
            if not os.path.exists(data_dir):
                os.makedirs(data_dir)
            self.collection = LmdbmDocumentCollection(data_dir + "/" + self.name + ".crawl")

    def __repr__(self) -> str:
        return f"SiteCrawler(name={self.name}, starting_urls={self.starting_urls}"

    @classmethod
    def from_json(cls, json_str: str, **kwargs) -> 'SiteCrawler':
        return cls(**json.loads(json_str), **kwargs)

    @staticmethod
    def format_duration(seconds):
        if seconds < 1:
            return "less than a second"

        words = ["year", "day", "hour", "minute", "second"]

        if not seconds:
            return "now"
        else:
            m, s = divmod(seconds, 60)
            h, m = divmod(m, 60)
            d, h = divmod(h, 24)
            y, d = divmod(d, 365)

            time = [y, d, h, m, s]

            duration = []

            for x, i in enumerate(time):
                if i == 1:
                    duration.append(f"{i} {words[x]}")
                elif i > 1:
                    duration.append(f"{i} {words[x]}s")

            if len(duration) == 1:
                return duration[0]
            elif len(duration) == 2:
                return f"{duration[0]} and {duration[1]}"
            else:
                return ", ".join(duration[:-1]) + " and " + duration[-1]

    def report(self):
        start_time = datetime.fromtimestamp(self.start_time, timezone.utc).astimezone().strftime(
            "%Y-%m-%d %H:%M:%S.%f%z (%Z)")
        if self.end_time == -1:
            end_time = "still running"
        else:
            end_time = datetime.fromtimestamp(self.end_time, timezone.utc).astimezone().strftime(
                "%Y-%m-%d %H:%M:%S.%f%z (%Z)")
        return {"name": self.name, "stats": dict(self.stats), "start_time": start_time, "end_time": end_time,
                "duration": self.format_duration(self.duration)}

    async def _make_request(self, url: str) -> Tuple[str, str, Union[str, bytes], CIMultiDictProxy[str]]:
        """
        The super method is where the actual fetching of the URL takes place.
        This overriden function takes care of handling caching, redirections and updating celery.
        :param url:
        :return:
        """
        self.stats["total"] += 1

        if self.is_cached_url(url):
            # logger.debug("Cached: " + url)
            self.stats["cached"] += 1
            if self.celery_task:
                self.celery_task.update_state(state='PROGRESS', meta={"name": self.name, "stats": self.stats})
            dict = CIMultiDict()
            cached = self.collection[url]
            dict["Last-Modified"] = cached["server_last_modified"]
            return cached["content_type"], url, cached["_content"], CIMultiDictProxy(dict)
        elif self.is_redirected_url(url):
            # logger.debug("Cached[redirected]: " + url)
            self.stats["cached_redirects"] += 1
            actual_url = self.get_redirected_url(url)
            dict = CIMultiDict()
            cached = self.collection[actual_url]
            dict["Last-Modified"] = cached["server_last_modified"]
            return cached["content_type"], actual_url, cached["_content"], CIMultiDictProxy(dict)
        else:
            print(f"Fetching {url}")

        self.stats["fetched"] += 1
        content_type, actual_url, content, headers = await super()._make_request(url)
        if self.celery_task:
            self.celery_task.update_state(state='PROGRESS', meta={"name": self.name, "stats": self.stats})
        if url != actual_url:
            self.save_redirect(url, actual_url)
        return content_type, actual_url, content, headers

    def parse_tld(self, url: str) -> tuple[str, str]:
        link_tld = tldextract.extract(url)
        tld = link_tld.domain + "." + link_tld.suffix
        return link_tld.subdomain + "." + tld, tld

    def valid_link(self, source_url: str, link: str):
        """
        Checks if we should follow the link
        :param source_url:
        :param link:
        :return:
        """
        subdomain, tld = self.parse_tld(link)
        if subdomain not in self.allowed_domains and tld not in self.allowed_domains:
            return False
        if "@" in link:
            return False

        included = False
        for s in self.allowed_regex:
            if re.findall(s, link, re.IGNORECASE):
                included = True
                break
        if included:
            return True

        excluded = False
        for s in self.denied_regex:
            if re.findall(s, link, re.IGNORECASE):
                excluded = True
                break
        if excluded:
            return False
        for s in self.denied_extensions:
            if link.endswith(s):
                excluded = True
                break
        if excluded:
            return False

        # ======================================================
        # If no regex includes were explicitly specified, then allow all
        # Otherwise, allow only those explicitly specified
        # ======================================================
        # return len(self.allowed_regex) == 0

        return True

    def is_cached_url(self, url):
        is_cached = url in self.collection and self.collection[url]["type"] == "content"
        if is_cached and self.cache_ttl_hours > -1:
            is_cache_expired = (self.start_time - self.collection[url]["crawled"]) / 3600 >= self.cache_ttl_hours
            return not is_cache_expired
        else:
            return is_cached

    def is_redirected_url(self, url):
        return url in self.collection and self.collection[url]["type"] == "redirect"

    def get_redirected_url(self, url):
        return self.collection[url]["redirected_url"]

    def save_redirect(self, source_url: str, redirected_url: str):
        self.collection.add(source_url, None, type="redirect", redirected_url=redirected_url)

    def log_error_url(self, url, error_code: int, error_message: str):
        self.stats[error_code] += 1
        self.collection.add(url, error_message, type="error", error_code=error_code)
        logging.error(url, error_code, error_message)

    def output(self, content_type: str, url: str, links: Set[str], content: Union[str, bytes],
               response_headers: CIMultiDictProxy[str]) -> Optional[Tuple[str, str]]:
        """
        Write the content to the LMDB collection.
        :param content_type:
        :param url:
        :param links:
        :param content:
        :param headers:
        :return:
        """
        try:
            if not self.is_cached_url(url):
                self.stats["new_or_updated"] += 1
                if content_type == "text/html":
                    self.collection.add_html(url, content, type="content", parsed_hash="", crawled=time.time(),
                                             server_last_modified=response_headers.get("Last-Modified"))
                else:
                    self.collection.add_binary(url, content, content_type, type="content", parsed_hash="",
                                               crawled=time.time(), server_last_modified=response_headers.get("Last-Modified"))
            else:
                # compare the last modified dates
                server_last_modified = response_headers.get("Last-Modified")
                cached = self.collection[url]
                if server_last_modified and cached["server_last_modified"] != server_last_modified:
                    self.stats["new_or_updated"] += 1
                    if content_type == "text/html":
                        self.collection.add_html(url, content, type="content", parsed_hash="", crawled=time.time(),
                                                 server_last_modified=response_headers.get("Last-Modified"))
                    else:
                        self.collection.add_binary(url, content, content_type, type="content", parsed_hash="",
                                                   crawled=time.time(),
                                                   server_last_modified=response_headers.get("Last-Modified"))

        except Exception as e:
            print("Error saving", url, e)
        return None

    def crawl_completed(self):
        self.end_time = time.time()
        self.duration = self.end_time - self.start_time

    def attach_celery_task(self, current_task):
        self.celery_task = current_task


def _extract_content(node: Node, rule: ExtractionRule) -> str:
    if rule.attribute:
        return node.attributes[rule.attribute].strip()
    else:
        return node.text().strip()


def do_extract(content: str, rules: ExtractionRules) -> dict:
    dom = HTMLParser(content)
    result = {}
    for r in rules.rules:
        if r.css:
            results = dom.css(r.css)
            if len(results) == 1:
                result[r.field_name] = _extract_content(results[0], r)
            elif len(results) > 1:
                result[r.field_name] = [_extract_content(n, r) for n in results]
        else:
            matches = re.findall(r.regex, content)
            if len(matches) > 0:
                result[r.field_name] = matches[0].strip()
        if r.field_name not in result:
            result[r.field_name] = ""
    return result


def do_extraction(crawler):
    if crawler.extraction_rules is None or len(crawler.extraction_rules.rules) == 0:
        return
    parsed_hash = crawler.extraction_rules.compute_hash()

    for k, v in crawler.collection.items():
        if crawler.collection.is_binary_key(k):
            continue
        else:
            if v["type"] == "content" and v["parsed_hash"] != parsed_hash:
                result = do_extract(v["_content"], crawler.extraction_rules)
                v.update(result)
                print(k, result)
                v["parsed_hash"] = parsed_hash
                crawler.collection[k] = v


if __name__ == '__main__':
    import sys
    import asyncio
    from collections import defaultdict

    d = defaultdict(list)
    for k, v in ((k.lstrip('-'), v) for k, v in (a.split('=') for a in sys.argv[1:])):
        d[k].append(v)
    for k in (k for k in d if len(d[k]) == 1):
        d[k] = d[k][0]
    print("Sitecrawler parameters:", d)
    crawler = SiteCrawler(**dict(d))
    asyncio.run(crawler.get_results())
    print(crawler.stats)
    do_extraction(crawler)
