# SiteCrawler

A Python [asyncio](https://docs.python.org/3/library/asyncio.html) website crawler that uses a simple stack:

1. [LMDB](https://lmdb.readthedocs.io/en/release/) for saving downloaded URLs
2. [Celery](https://docs.celeryq.dev/en/stable/index.html) over [Redis](https://redis.io) for work queue management
3. [FastAPI](https://fastapi.tiangolo.com/) provides a thin API wrapper over the crawler 

It was forked from [https://github.com/tapanpandita/aiocrawler](https://github.com/tapanpandita/aiocrawler) (MIT licensed).

It is designed for speed:

- asyncio
- selectolax for fast HTML parsing
- LMDB for high read/write performance

## Features
- [x] Multiple starting URLs
- [x] Configurable metadata extraction using CSS selectors and regex
- [x] Limit depth of crawl
- [x] Limit number of pages crawled
- [x] Configurable concurrency
- [x] Download sitemaps
- [x] FastAPI API server
- [x] Celery integration
- [x] Dockerized
- [ ] Scheduling crawls
- [ ] Return full downloaded content via /browse API
- [ ] Standard webpage metadata extractors
- [ ] Integrate with unstructured to extract text from PDF, docx, pptx etc
- [ ] Javascript rendering/parsing via https://splash.readthedocs.io/en/stable/
- [ ] content_css_selector
- [ ] if_modified_since_hours

## Installation

```bash
git clone https://github.com/superkelvint/sitecrawler
cd sitecrawler
docker compose up --build
```

The FastAPI crawler API server is now available at [http://localhost:8000](http://localhost:8000).
The OpenAPI spec is available at [http://localhost:8000/docs](http://localhost:8000/docs).

## Starting your first crawl

```bash
curl -X POST http://localhost:8000/crawl \
 -H "Content-Type: application/json" \
 -d '{"name": "supermind", "starting_urls": ["https://www.supermind.org/"], "max_pages": 200, "concurrency": 5, "extraction_rules": {"rules": [{"field_name": "title", "regex": "<title>(.*?)</title>"}]}}'
```

This starts a crawl on supermind.org limited to 200 pages with a concurrency of 5.

The above command should return a UUID response like so:

```bash
{"id":"f339cef3-9839-476d-acdf-b61548515a93"} 
```

This is your job id. You can inspect the result of your crawl like so:

```bash
curl http://localhost:8000/crawl/f339cef3-9839-476d-acdf-b61548515a93
```

After the crawl is completed, you should see a response like:

```json
{
  "id": "f339cef3-9839-476d-acdf-b61548515a93",
  "status": "SUCCESS",
  "info": {
    "name": "supermind",
    "stats": {
      "total": 201,
      "cached": 191,
      "cached_redirects": 2,
      "fetched": 8,
      "new_or_updated": 8
    },
    "start_time": "2024-02-12 05:13:38.358572+0000 (UTC)",
    "end_time": "2024-02-12 05:13:41.063751+0000 (UTC)",
    "duration": "2.705178737640381 seconds"
  }
}  
```


## Design choices
This is not a distributed crawler. The entire crawl runs within a single Celery worker in an async fashion. 
It is very fast, especially if you set a high concurrency. 

Hitting a single host from a single crawler node, we can easily hit 50 URLs/s with concurrency of 10.  

The crawl job runs in 2 phases:
1. download all URLs
2. parse and extract

Each phase runs as a separate Celery task. This means it should be possible to have different workers doing different tasks. 

## Crawler configuration
| **Name**                        | **Type**        | **Default**     | **Description**                                                                                                                                                                                                        |
|---------------------------------|-----------------|-----------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **name**                        | string          |                 | Name of the crawl (required)                                                                                                                                                                                           |
| **starting_urls**               | list of strings |                 | Starting URLs (required)                                                                                                                                                                                               |
| **allowed_domains**             | list of strings |                 | Allowed domains. Additive with allow_starting_url_hostname and allow_starting_url_tld.                                                                                                                                 |
| **allowed_regex**               | list of strings |                 | URLs matching with these regexes will be allowed.                                                                                                                                                                      |
| **denied_regex**                | list of strings |                 | URLs matching with these regexes will not be crawled.                                                                                                                                                                  |
| **denied_extensions**           | list of strings |                 | URLs ending with these extensions will not be crawled.                                                                                                                                                                 |
| **is_sitemap**                  | boolean         | false           | If true, all the starting URLs will be treated as sitemaps. The entire sitemaps will be downloaded, all the URLs collected and crawled to a depth of 1. No URLs other than what is in the sitemaps will be downloaded. |
| **max_depth**                   | number          | 300             | Maximum crawler depth. The starting URL is depth of 1.                                                                                                                                                                 |
| **max_pages**                   | number          | -1              | Max number of pages to crawl. -1 means no limit (default)                                                                                                                                                              |
| **concurrency**                 | number          | 10              | Simultaneous crawler connections.                                                                                                                                                                                      |
| **allow_starting_url_hostname** | boolean         | true            | Allow all links with the same hostname as starting URLs.                                                                                                                                                               |
| **allow_starting_url_tld**      | boolean         | false           | Allow all links with the same TLD as starting URLs.                                                                                                                                                                    |
| **user_agent**                  | string          | SiteCrawler/1.0 | Crawler user-agent.                                                                                                                                                                                                    |
| **extraction_rules**            | dictionary      |                 | See ExtractionRules section.                                                                                                                                                                                           |

### Example
```json
{
  "name": "supermind",
  "starting_urls": [
    "https://www.supermind.org/"
  ],
  "max_pages": 200,
  "concurrency": 5,
  "extraction_rules": {
    "rules": [
      {
        "field_name": "title",
        "regex": "<title>(.*?)</title>"
      },
      {
        "field_name": "description",
        "css": "meta[name=description]",
        "attribute": "content"
      }
    ]
  }
}
```

## Extraction Rules
| **Name**       | **Type** | **Description**                                                                                                    |
|----------------|----------|--------------------------------------------------------------------------------------------------------------------|
| **field_name** | string   | Name of the field                                                                                                  |
| **css**        | string   | CSS selector.                                                                                                      |
| **regex**      | string   | Regex. There must be 1 matching group.                                                                             |
| **delimiter**  | string   | Not currently used.                                                                                                |
| **attribute**  | string   | **CSS only**. If specifed, the HTML element attribute it extracted. Otherwise, the element text is used (default). |

There should only be either `css` or `regex` declared. If both are declared, `css` is used. 


## Using sitecrawler as a library

```python
import asyncio

from sitecrawler import SiteCrawler, do_extraction

if __name__ == "__main__":
    crawler = SiteCrawler("test_crawl", ["https://www.supermind.org"], max_pages=10)
    asyncio.run(crawler.get_results())
    print(crawler.stats)
    do_extraction(crawler)
```

## Using sitecrawler from the command-line
```bash
source ./venv/bin/activate
python3 sitecrawler.py --name=supermind --starting_urls="https://www.supermind.org"
```

## Running celery locally

Celery is not needed to run the sitecrawler. You can run it as-is. If you do wish to run Celery locally, 
in a terminal, this is how to start the celery worker:
```bash
source ./venv/bin/activate
celery -A tasks worker --loglevel=INFO
```

You will also need Redis running locally. 

## Contributing

The 4 files of interest are:

- sitecrawler.py: the main crawler logic
- aiocrawler.py: the crawler base class that handles most of the async fetching operations
- main.py: the FastAPI wrapper around the crawler
- tasks.py: submits jobs to celery
