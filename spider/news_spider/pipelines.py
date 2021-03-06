# -*- coding: utf-8 -*-

# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: http://doc.scrapy.org/en/latest/topics/item-pipeline.html
from datetime import datetime
from typing import Set
from urllib.parse import urlsplit

import pybloom_live
from scrapy.exceptions import DropItem
from peewee import Model, DateTimeField, CharField, TextField, IntegerField, SqliteDatabase

from .spiders import NewsScraper

peewee_database = SqliteDatabase('../data/7_opensources_co/news_spider.db')


class BaseModel(Model):
    class Meta:
        database = peewee_database


class ScrapedPage(BaseModel):
    batch = IntegerField(null=False)
    url = CharField(null=False)
    html = TextField(null=False)
    inserted_at = DateTimeField(null=False, default=datetime.now())
    updated_at = DateTimeField(null=False, default=datetime.now())

    # cache
    _cache_urls = None  # type: Set[int]

    @staticmethod
    def url_exists(url):
        if ScrapedPage._cache_urls is None:
            print('Getting all urls...')
            last_id = 0
            all_scraped = []
            while True:
                scraped = list(ScrapedPage
                               .select(ScrapedPage.id, ScrapedPage.url)
                               .where(ScrapedPage.id > last_id)
                               .order_by(ScrapedPage.id.asc())
                               .limit(100 * 1000))
                if len(scraped) <= 0:
                    break

                all_scraped += [sp.url for sp in scraped]
                last_id = scraped[-1].id

                print('Got %s with id: %s' % (len(all_scraped), last_id))

            ScrapedPage._cache_urls = set()
            for url in all_scraped:
                ScrapedPage._cache_urls.add(hash(url))

            print('Unique urls: %s' % len(ScrapedPage._cache_urls))

        return hash(url) in ScrapedPage._cache_urls

    class Meta:
        db_table = 'fnr_scraped_pages'

        indexes = (
            # Specify a unique multi-column index on from/to-user.
            (('batch', 'url'), True),
        )


ScrapedPage.create_table()


class NewsSpiderDropPipeline:
    def __init__(self):
        self.netlocs = set()
        ScrapedPage.url_exists('')

    def open_spider(self, spider: NewsScraper):
        for u in spider.websites_url:
            self.netlocs.add(urlsplit(u).netloc.lower())

    def process_item(self, item, spider):
        url = item['url'].replace('www.', '').lower()
        if urlsplit(url).netloc not in self.netlocs or ScrapedPage.url_exists(item['url']):
            item['html'] = None
            raise DropItem()

        ScrapedPage._cache_urls.add(hash(item['url']))

        return item


class NewsSpiderPersistencePipeline(object):
    def __init__(self):
        self.items = []

    def process_item(self, item, scraper):
        self.items.append({
            'batch': 2,
            'url': item['url'],
            'html': item['html'].replace('\x00', '')
        })

        if len(self.items) >= 100:
            self.process_bulk()

        return item

    def close_spider(self, spider):
        self.process_bulk()

    def process_bulk(self):
        if peewee_database.is_closed():
            peewee_database.connect()

        try:
            with peewee_database.atomic():
                ScrapedPage.insert_many(self.items).execute()
        except Exception as e:
            print(e)
            print('Retrying connection')
            peewee_database.connect()
            self.process_bulk()
            return

        self.items = []
