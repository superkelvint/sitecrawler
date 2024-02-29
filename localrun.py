import asyncio
import os
from sitecrawler import SiteCrawler, do_extraction
from lmdb_collection import LmdbmDocumentCollection
import json
if __name__ == "__main__":
    crawler = SiteCrawler("ttu", ["https://www.ttu.edu/","https://www.depts.ttu.edu/"], max_pages=500, denied_extensions=['mp3','ics'], denied_regex=['/Location']
                          ,cache_ttl_hours=-1, extraction_rules={"rules":[
                              {
                                  "field_name":"title_t",
                                  "regex":"<title>(.*?)</title>"
                                },
                                {
                                    "field_name":"content_ts",
                                    "css":"*"
                                },
                                {
                                    "field_name":"headings1_ts",
                                    "css": "h1"
                                },
                                {
                                    "field_name":"headings2_ts",
                                    "css": "h2"
                                },
                                {
                                    "field_name":"headings3_ts",
                                    "css": "h3"
                                },
                                {
                                    "field_name":"headings4_ts",
                                    "css": "h4"
                                },
                                {
                                    "field_name":"author_s",
                                    "css": "meta[name=Author]::attr(content)"
                                },
                                {
                                    "field_name":"keywords_t",
                                    "css": "meta[name=Keywords]::attr(content)"
                                },
                                {
                                    "field_name":"description_t",
                                    "css": "meta[name=Description]::attr(content)"
                                }
                                  ]})
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(crawler.get_results())
    print(crawler.stats)
    do_extraction(crawler)

    name = 'ttu'

    collection: LmdbmDocumentCollection = LmdbmDocumentCollection(f"data/{name}.crawl")

    upload_obj = []
    for v in list(collection.filter_keys("type","content")):
        # del collection[v]['_content']
        obj = {
            'id': collection[v]['id'],
            'title_t' : collection[v]['title_t'],
            'headings1_ts' : collection[v]['headings1_ts'],
            'headings2_ts' : collection[v]['headings2_ts'],
            'headings3_ts' : collection[v]['headings3_ts'],
            'headings4_ts' : collection[v]['headings4_ts'],
            'uri' : collection[v]['uri'],
            'path_s' : collection[v]['path_s'],
            'typeUrl_s' : collection[v]['typeUrl_s'],
            'content_ts': collection[v]['content_ts'],
            'author_s': collection[v]['author_s'],
            'keywords_t': collection[v]['keywords_t'],
            'description_t': collection[v]['description_t']
        }
        upload_obj.append(obj)

    solr_url = 'https://searchcloud-2-us-east-1.searchstax.com/29847/texastudemo-1728/update'
    token = 'b4255cda0429965455086d319e8fda30d3e62ce6'
    ids = " OR ".join([k['id'] for k in upload_obj])
    delete_obj = {
        'delete': {
            'query': f'id:({ids})'
        }
    }
    import requests
    headers = {
        'Authorization': f'Token {token}'
    }
    resp = requests.post(solr_url, headers=headers, json=delete_obj)
    print(resp.text)
    batch_size = 20
    for i in range(0, len(upload_obj), batch_size):

        if i+ batch_size > len(upload_obj):
            batch = upload_obj[i:]
        else:
            batch = upload_obj[i:i+batch_size]
        # print(batch)
        response = requests.post(solr_url, headers=headers, json=batch)  # Sending the batch as JSON
        if response.status_code == 200:
            print(f"Batch {i//batch_size + 1} uploaded successfully")
        else:
            print(f"Batch {i//batch_size + 1} failed to upload. Status code: {response.status_code}")




