import threading

from celery.result import AsyncResult
from fastapi import FastAPI, Body, Query

from lmdb_collection import LmdbmDocumentCollection
from tasks import app as celery
from tasks import start_crawl

app = FastAPI()
running_jobs = set()


@app.post("/crawl/")
@app.post("/crawl")
async def submit_crawl(data: dict = Body(...)):
    job: AsyncResult = start_crawl.delay(data)
    running_jobs.add(job.id)
    return {"id": job.id}


@app.get("/crawl/{job_id}")
async def crawl_status(job_id: str):
    job = celery.AsyncResult(job_id)
    return {"id": job_id, "status": job.status, "info": job.info}


@app.delete("/crawl/{job_id}")
async def crawl_terminate(job_id: str):
    celery.control.revoke(job_id, terminate=True)
    running_jobs.remove(job_id)
    job = celery.AsyncResult(job_id)
    return {"id": job_id, "status": job.status, "info": job.info}


@app.get("/crawl/")
@app.get("/crawl")
async def list_active_crawls():
    jobs = []
    for id in running_jobs:
        job = celery.AsyncResult(id)
        jobs.append({"id": id, "status": job.status, "info": job.info})
    return {"jobs": jobs}


@app.get("/browse/{name}/")
@app.get("/browse/{name}")
async def browse_results(name: str, page: int = Query(default=0, ge=0)):
    collection: LmdbmDocumentCollection = LmdbmDocumentCollection(f"{name}.crawl")

    # FIXME: fully populate all content here. Right now we only print the keys
    items = list(collection.filter_keys("type", "content"))

    per_page = 20  # Number of items per page
    start = page * per_page  # Calculate start and end for slicing
    end = start + per_page
    total_pages = len(items) // per_page + (1 if len(items) % per_page else 0)  # Calculate total pages
    context = {}
    context["name"] = name
    context["items"] = items[start:end]
    context["page"] = page
    context["total_pages"] = total_pages
    context["num_records"] = len(items)
    return context


def on_task_completion(event):
    task_id = event['uuid']
    if task_id in running_jobs:
        running_jobs.remove(task_id)
    print(f"Task {task_id} completed.")


def on_task_failure(event):
    task_id = event['uuid']
    if task_id in running_jobs:
        running_jobs.remove(task_id)
    print(f"Task {task_id} failed.")


def on_task_revoked(event):
    task_id = event['uuid']
    if task_id in running_jobs:
        running_jobs.remove(task_id)
    print(f"Task {task_id} revoked.")


def monitor_tasks():
    with celery.connection() as connection:
        recv = celery.events.Receiver(connection, handlers={
            'task-succeeded': on_task_completion,
            'task-failure': on_task_failure,
            'task-revoked': on_task_revoked,
        })
        recv.capture(limit=None, timeout=None, wakeup=True)


task_monitor_thread = threading.Thread(target=monitor_tasks)
task_monitor_thread.start()
