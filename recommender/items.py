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
"""Maps urls to a numeric identifier."""

from google.appengine.api import memcache
from google.appengine.ext import ndb

from protos import cache_pb2


class Item(ndb.Model):
  url = ndb.StringProperty()

  def ItemId(self):
    return self.key.integer_id()


def UrlToItemId(url):
  item = Item.query(Item.url == url).get()
  if not item:
    item = Item(url=url)
    item.put()
  return item.key.integer_id()


def UrlsToItemIds(urls):
  """Returns a map from url to item id."""
  if not urls:
    return {}
  url_to_item_id = memcache.get_multi(urls, key_prefix='u2i:')
  urls_not_in_cache = [url for url in urls if url not in url_to_item_id]
  if urls_not_in_cache:
    new_items = {}
    for item in Item.query(Item.url.IN(urls_not_in_cache)).fetch():
      url_to_item_id[item.url] = item.ItemId()
      new_items[item.url] = item.ItemId()
    memcache.set_multi(new_items, key_prefix='u2i:')
  return url_to_item_id


def ItemIdsToUrls(item_ids):
  """Returns a map from item id to url."""
  if not item_ids:
    return {}
  item_id_string_to_url = memcache.get_multi(
      [str(item_id) for item_id in item_ids], key_prefix='i2u:')
  item_id_to_url = {
      int(item_id_string): url
      for (item_id_string, url) in item_id_string_to_url.iteritems()
  }
  item_ids_not_in_cache = [
      item_id for item_id in item_ids if item_id not in item_id_to_url
  ]
  if item_ids_not_in_cache:
    new_items = {}
    for item in ndb.get_multi(
        [ndb.Key(Item, item_id) for item_id in item_ids_not_in_cache]):
      if item:
        item_id_to_url[item.ItemId()] = item.url
        new_items[str(item.ItemId())] = item.url
    memcache.set_multi(new_items, key_prefix='i2u:')
  return item_id_to_url


def ItemIdToUrl(item_id):
  assert item_id
  item = ndb.Key(Item, item_id).get()
  if item:
    return item.url
  return None


def ItemIdsToBytes(item_ids):
  item_ids_proto = cache_pb2.ItemIds()
  item_ids_proto.item_id.extend(item_ids)
  return item_ids_proto.SerializeToString()


def ItemIdsFromBytes(string):
  item_ids = cache_pb2.ItemIds.FromString(string)
  return item_ids.item_id
