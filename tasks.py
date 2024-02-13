import asyncio
import json
import os
from contextlib import contextmanager
from typing import Union

from celery import Celery, current_task
from dotenv import load_dotenv

from sitecrawler import SiteCrawler, do_extraction

load_dotenv()

app = Celery('tasks', broker=os.getenv("BROKER_URL"),
             backend=os.getenv("RESULT_BACKEND"))


@contextmanager
def file_lock(lock_file):
    if os.path.exists(lock_file):
        raise FileExistsError(
            "Lock file %s exists. Another crawler with the same name is already in flight." % lock_file)
    else:
        open(lock_file, 'w').write("%s" % os.getpid())
        try:
            yield
        finally:
            os.remove(lock_file)


@app.task
def start_crawl(json_spec: Union[dict, str]):
    settings = {}
    if isinstance(json_spec, str):
        settings = json.loads(json_spec)
    elif isinstance(json_spec, dict):
        settings = json_spec

    with file_lock("/tmp/" + settings["name"] + ".lock"):
        crawler = SiteCrawler(**settings)

        crawler.attach_celery_task(current_task)
        asyncio.run(crawler.get_results())
        print(crawler.stats)
        start_extraction.delay(json_spec)
        return crawler.report()


@app.task
def start_extraction(json_spec: Union[dict, str]):
    if isinstance(json_spec, str):
        crawler = SiteCrawler.from_json(json_spec)
    elif isinstance(json_spec, dict):
        crawler = SiteCrawler(**json_spec)
    else:
        raise Exception("Invalid input", json_spec)
    do_extraction(crawler)
    # we can notify the user or call a webhook here


# if __name__ == "__main__":
#     json_str = open("crawl_settings.json").read()
#     start_crawl.delay(json_str)
