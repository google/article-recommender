# Copyright 2020 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Keeps track of syndicated feeds (e.g, RSS).

A feed is treated by the recommendation algorithm as a pseudo user that
recommends everything in the feed.
"""

from __future__ import division

from datetime import datetime
from datetime import timedelta
import io
import logging
import time

import feedparser

from google.appengine.api import memcache
from google.appengine.api import urlfetch
from google.appengine.api import urlfetch_errors
from google.appengine.ext import db
from google.appengine.ext import ndb

from recommender import feed_util
from recommender import items
from recommender import url_util
from protos import cache_pb2

# 0 - means we do not clean up old feed items.
MAX_ITEMS_PER_FEED = 0
CLEAN_UP_ITEMS_PER_UPDATE = 1000


class Feed(ndb.Model):
  """A syndicated feed (RSS) is a source of information.

  It is treated like a pseudo user that recommends everything in the feed. Keyed
  by url.
  """
  title = ndb.StringProperty()
  item_count = ndb.IntegerProperty(default=0)
  has_active_connections = ndb.BooleanProperty(default=False)
  has_active_connections_updated = ndb.DateTimeProperty()
  # These two fields are used to save bandwidth.
  modified = ndb.DateTimeProperty()
  etag = ndb.StringProperty()
  last_updated = ndb.DateTimeProperty()

  def GetUrl(self):
    return self.key.id()

  def Update(self, canonicalize=None):
    return self.UpdateAsync(
        canonicalize=canonicalize, enable_async=False).get_result()

  # Updates the list of items in the feed.
  # Returns the list of newly added items.
  @ndb.tasklet
  def UpdateAsync(self, canonicalize=None, enable_async=True):
    now = datetime.now()
    if canonicalize is None:
      canonicalize = lambda url: url
    modified_tuple = None
    etag = self.etag
    if self.modified is not None:
      modified_tuple = self.modified.timetuple()
      # Don't use etag if we have modified time. Some servers are generating new
      # etags when nothing actually changes and modified date stays the same.
      etag = None
    url = self.GetUrl()
    if enable_async:
      if url.startswith('feed:http'):
        url = url[5:]
      elif url.startswith('feed:'):
        url = 'http:' + url[5:]
      rpc = urlfetch.create_rpc(deadline=url_util.URL_FETCH_DEADLINE_SECONDS)
      referrer = None
      auth = None
      request_headers = {}
      # Build the headers the same way feedparser.parse() does.
      # pylint: disable=protected-access
      request = feedparser._build_urllib2_request(url, feedparser.USER_AGENT,
                                                  etag, modified_tuple,
                                                  referrer, auth,
                                                  request_headers)
      # pylint: enable=protected-access
      headers = {key: value for (key, value) in request.header_items()}
      # We remove this header so that we do not get gzipped content from
      # urlfetch.
      # Without this header passed explicitly urlfetch adds this header
      # implicitly and unzips the response for us.
      headers.pop('Accept-encoding')
      try:
        result = (yield urlfetch.make_fetch_call(rpc, url, headers=headers))
      except urlfetch_errors.Error as e:
        logging.warning('Error fetching feed: %s error: %s', url, e)
        raise ndb.Return([])
      content = result.content
      if isinstance(content, unicode):
        stream = io.BytesIO(content.encode('utf-8'))
      else:
        stream = io.BytesIO(content)
      parsed = feedparser.parse(stream)
    else:
      try:
        parsed = feedparser.parse(url, etag=etag, modified=modified_tuple)
      except StandardError as e:
        logging.warning('Failed to parse feed: %s error: %s', url, e)
        # Try to read content ourselves and pass it to the parser:
        try:
          content, _, _, _ = url_util.GetPageContent(url)
          parsed = feedparser.parse(content)
        except url_util.Error as e:
          logging.warning('Failed to parse feed %s with fallback error: %s',
                          url, e)
          raise ndb.Return([])
    if hasattr(parsed, 'modified_parsed') and parsed.modified_parsed:
      self.modified = datetime.fromtimestamp(
          time.mktime(parsed.modified_parsed))
    if hasattr(parsed, 'etag'):
      self.etag = parsed.etag
    new_items = []
    for entry in parsed.entries:
      if not hasattr(entry, 'link') or not entry.link:
        continue
      if hasattr(entry, 'id') and entry.id:
        entry_id = entry.id
      else:
        # Some feeds don't specify the id so we use the link as the id.
        entry_id = entry.link
      entry_date = feed_util.GetEntryDate(
          entry, min_date=self.last_updated, max_date=now)
      if not entry_date:
        entry_date = datetime.now()
      title = None
      if hasattr(entry, 'title'):
        title = entry.title
      item = FeedItem.query(FeedItem.feed_url == self.GetUrl(),
                            FeedItem.id == entry_id).get()
      if item is None:
        try:
          canonical_url = canonicalize(entry.link)
          new_item = FeedItem(
              id=entry_id,
              url=canonical_url,
              title=title,
              feed_url=self.GetUrl(),
              retrieved_date=now,
              published_date=entry_date,
              item_id=items.UrlToItemId(canonical_url))
          new_items.append(new_item)
          new_item.put()
        except db.BadValueError as e:
          logging.warning('Error creating a feed item:' + str(e))
      # We should not be adding more new items than we are able to cleanup.
      if len(new_items) >= CLEAN_UP_ITEMS_PER_UPDATE:
        break
    self.item_count += len(new_items)
    self.last_updated = now
    self.put()
    # Remove the old items.
    if MAX_ITEMS_PER_FEED > 0:
      ndb.delete_multi(
          FeedItem.query(FeedItem.feed_url == self.GetUrl()).order(
              -FeedItem.published_date).iter(
                  keys_only=True,
                  limit=CLEAN_UP_ITEMS_PER_UPDATE,
                  offset=MAX_ITEMS_PER_FEED))
    feed_url = self.GetUrl()
    for time_period_in_days in CACHE_TIME_PERIODS_IN_DAYS:
      _UpdateCachedItemIds(feed_url, time_period_in_days).get_result()
    raise ndb.Return(new_items)


TIME_BETWEEN_UPDATES = timedelta(minutes=30)

# The time periods that we cache feed items for
CACHE_TIME_PERIODS_IN_DAYS = [1, 3, 7, 14, 30, 60, 100000]


def _TimeToMillis(t):
  ms = time.mktime(t.utctimetuple()) * 1000
  ms += getattr(t, 'microseconds', 0) / 1000
  return int(ms)


def _MillisToDatetime(ms):
  return datetime.utcfromtimestamp(ms // 1000).replace(microsecond=ms % 1000 *
                                                       1000)


ITEM_ID_CACHE_PREFIX = 'fid:'


class FeedItemId(object):

  def __init__(self, feed_url, item_id, published_date):
    self.feed_url = feed_url
    self.item_id = item_id
    self.published_date = published_date


@ndb.tasklet
def GetBulkItemIdsAsync(feed_urls, since_time):
  """Returns item ids from feeds that were published after a given time.

  Args:
    feed_urls: The list of feed urls we want the items from.
    since_time: The oldest published time that we are interested in.

  Returns:
    A map of feed url to a list of feed items. Each feed item is a tuple of item
    url and publishing date.
  """
  now = datetime.now()
  since_time_millis = _TimeToMillis(since_time)
  minimum_published_time_millis = (
      _TimeToMillis(since_time - TIME_BETWEEN_UPDATES)
      if since_time != datetime.min else since_time_millis)
  time_period_in_days = None
  for days in CACHE_TIME_PERIODS_IN_DAYS:
    time_period_in_days = days
    if timedelta(days=days) > now - since_time:
      break
  client = memcache.Client()
  feed_url_to_recent_items = yield client.get_multi_async(
      feed_urls,
      key_prefix=ITEM_ID_CACHE_PREFIX + str(time_period_in_days) + ':')
  queries = {}
  for feed_url in feed_urls:
    if feed_url in feed_url_to_recent_items:
      feed_url_to_recent_items[feed_url] = [
          item for item in cache_pb2.FeedItems.FromString(
              feed_url_to_recent_items[feed_url]).feed_item
          if (item.published_timestamp_millis > minimum_published_time_millis
              and item.retrieved_timestamp_millis > since_time_millis)
      ]
    else:
      queries[feed_url] = _UpdateCachedItemIds(feed_url, time_period_in_days)
  for feed_url, query in queries.iteritems():
    items_proto = yield query
    feed_url_to_recent_items[feed_url] = [
        item for item in items_proto.feed_item
        if (item.published_timestamp_millis > minimum_published_time_millis and
            item.retrieved_timestamp_millis > since_time_millis)
    ]
  for feed_url in feed_url_to_recent_items:
    feed_url_to_recent_items[feed_url] = [
        FeedItemId(feed_url, item.item_id,
                   _MillisToDatetime(item.published_timestamp_millis))
        for item in feed_url_to_recent_items[feed_url]
    ]
  raise ndb.Return(feed_url_to_recent_items)


@ndb.tasklet
def _UpdateCachedItemIds(feed_url, time_period_in_days):
  oldest_date = (
      datetime.now() - timedelta(days=time_period_in_days) -
      TIME_BETWEEN_UPDATES)
  feed_items = yield FeedItem.query(
      FeedItem.feed_url == feed_url, FeedItem.published_date >=
      oldest_date).order(-FeedItem.published_date).fetch_async(
          100, projection=['item_id', 'published_date', 'retrieved_date'])
  items_proto = cache_pb2.FeedItems()
  for i in feed_items:
    item_proto = items_proto.feed_item.add()
    item_proto.item_id = i.item_id
    item_proto.published_timestamp_millis = _TimeToMillis(i.published_date)
    item_proto.retrieved_timestamp_millis = _TimeToMillis(i.retrieved_date or
                                                          i.published_date)
  client = memcache.Client()
  client.set(ITEM_ID_CACHE_PREFIX + str(time_period_in_days) + ':' + feed_url,
             items_proto.SerializeToString())
  raise ndb.Return(items_proto)


def GetFeed(url):
  return ndb.Key(Feed, url).get()


def AddFeed(url, title):
  key = ndb.Key(Feed, url)
  feed = key.get()
  if feed is None:
    feed = Feed(key=key, title=title, last_updated=datetime.min)
    feed.put()
  return feed


class FeedItem(ndb.Model):
  url = ndb.StringProperty()
  id = ndb.StringProperty()
  title = ndb.StringProperty()
  feed_url = ndb.StringProperty()
  published_date = ndb.DateTimeProperty()
  retrieved_date = ndb.DateTimeProperty()
  item_id = ndb.IntegerProperty()
