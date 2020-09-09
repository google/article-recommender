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
"""Functions that update the state of the models in response to user actions."""

from __future__ import absolute_import
from __future__ import division

from datetime import datetime
from datetime import timedelta
import pickle

from google.appengine.ext import deferred
from google.appengine.ext import ndb

from recommender import config
from recommender import datastore_based_connection_trainer as connection_trainer
from recommender import feeds
from recommender import models
from recommender import time_periods


# Updates all feeds in batches of 10 at a time.
def UpdateAllFeeds():
  _UpdateNFeeds(None, 20, datetime.now())


def _UpdateNFeeds(min_id, batch_size, start_time):
  max_last_updated = datetime.now()
  query = feeds.Feed.query()
  if min_id:
    query = query.filter(feeds.Feed.key > ndb.Key(feeds.Feed, min_id))
  batch = query.fetch(batch_size)
  if not batch:
    return
  deferred.defer(
      _UpdateNFeeds,
      batch[-1].key.id(),
      batch_size,
      start_time,
      _queue='feed-updates')
  # Fire off all async requests in parallel so we only wait for the slowest
  # feed in the batch instead of for all serially.
  results = [(feed,
              feed.UpdateAsync(canonicalize=CanonicalizeUrl))
             for feed in batch
             if feed.last_updated < max_last_updated]
  for feed, new_items_future in results:
    new_items = new_items_future.get_result()
    if new_items:
      deferred.defer(
          _NewFeedItemsAdded,
          feed, {item.url for item in new_items},
          _queue='feed-updates')


def _NewFeedItemsAdded(feed, new_item_urls):
  _DecayConnectionWeightToFeed(feed, len(new_item_urls))
  models.PrefetchPageInfos(new_item_urls)


def UpdateFeed(feed):
  if feed:
    deferred.defer(UpdateFeedImpl, feed, _queue='feed-updates')


def UpdateFeedImpl(feed):
  new_items = feed.Update(CanonicalizeUrl)
  if new_items:
    deferred.defer(
        _DecayConnectionWeightToFeed,
        feed,
        len(new_items),
        _queue='feed-updates')
    models.PrefetchPageInfos({item.url for item in new_items})


def _DecayConnectionWeightToFeed(feed, num_new_items):
  publisher = models.Source(models.SOURCE_TYPE_FEED, feed.GetUrl(), None)
  connection_trainer.CreateTrainer().DecayConnectionWeightToPublisher(
      publisher, num_items=num_new_items)


def CanonicalizeUrl(url):
  page_info = models.GetPageInfo(url)
  if page_info:
    return page_info.canonical_url
  return url


def AddRating(user, url, rating, source, category_id):
  user_id = models.UserKey(user).id()
  stats = models.AddRating(
      user_id, url, rating, source, category_id)

  # If the page belongs to a feed then register this feed.
  page_info = models.GetPageInfo(url)
  if page_info.feed_url:
    UpdateFeed(feeds.AddFeed(page_info.feed_url, page_info.feed_title))
    stats['own_feed'] = page_info.feed_url

  # If the page itself is a feed url then also register it.
  if page_info.is_feed:
    UpdateFeed(feeds.AddFeed(page_info.canonical_url, page_info.title))
    stats['own_feed'] = page_info.canonical_url

  RatingAdded(
      models.Source(models.SOURCE_TYPE_USER, user_id, category_id), url, rating)
  return stats


DELAY_BEFORE_UPDATING_CONNECTIONS = (
    timedelta(seconds=10) if config.IsDev() else timedelta(minutes=1))


def RatingAdded(source, url, rating):
  source = models.SerializeSource(source)
  deferred.defer(
      RatingAddedImpl,
      source,
      url,
      rating,
      _queue='recommendation-updates',
      _countdown=DELAY_BEFORE_UPDATING_CONNECTIONS.total_seconds())


def RatingAddedImpl(source, url, rating):
  source = models.DeserializeSource(source)
  if source.source_type == models.SOURCE_TYPE_USER:
    deferred.defer(UpdatePopularPage, url, _queue='default')

  # Check if the user has changed the category or removed their vote.
  # In both cases we do not want to update the connection state.
  if source.source_type == models.SOURCE_TYPE_USER:
    user_key = models.UserKey(source.source_id)
    page_rating = ndb.Key(models.PageRating, url, parent=user_key).get()
    if not page_rating:
      return
    if page_rating.category != source.CategoryKey():
      # We will let the deferred task scheduled from SetPageCategory to update
      # connections for the updated category.
      return

  connection_trainer.CreateTrainer().RecommendationAdded(source, url, rating)
  models.UpdateCachedConnectionInfo(source.source_id)


def UpdatePopularPage(url):
  start_datetime = datetime.now()
  values_by_key = dict()
  for rating in models.PageRating.query(
      models.PageRating.url == url).order(-models.PageRating.date):
    for (key, value) in PopularPagesMap(rating, start_datetime):
      if key not in values_by_key:
        values_by_key[key] = [value]
      else:
        values_by_key[key].append(value)
  for key, values in values_by_key.iteritems():
    PopularPagesReduce(key, values)


def SetPageCategory(user, url, category_id, retries_left=10):
  user_key = models.UserKey(user)
  page_rating = ndb.Key(models.PageRating, url, parent=user_key).get()
  if page_rating is None:
    # It could be that the PageRating has not become available yet so we retry
    # a few times.
    if retries_left > 0:
      deferred.defer(
          SetPageCategory,
          user,
          url,
          category_id,
          retries_left - 1,
          _queue='default')
    return

  category = None
  if category_id is not None:
    category = models.CategoryKey(category_id, user)

  if page_rating.category == category:
    return

  page_rating.category = category
  page_rating.put()

  deferred.defer(
      RatingAddedImpl,
      models.SerializeSource(
          models.Source(models.SOURCE_TYPE_USER, user.user_id(), category_id)),
      url,
      page_rating.rating,
      _countdown=DELAY_BEFORE_UPDATING_CONNECTIONS.total_seconds())


# This is used in pipelines.py as part of a MapReduce.
def PopularPagesMap(rating, start_datetime=None):
  # This is a neutral rating.
  if rating.rating == 0:
    return
  # Do not count ratings added after the pipeline was started.
  if start_datetime is None:
    start_datetime = datetime.now()
  if rating.date > start_datetime:
    return

  time_passed = start_datetime - rating.date
  score = rating.rating
  for time_period in time_periods.TIME_PERIODS:
    if (time_period['name'] == time_periods.RECENT or
        time_period['name'] == time_periods.LAST_VISIT or
        time_period['name'] == time_periods.LAST_VISIT_RESTRICTED):
      continue
    if time_passed < time_period['timedelta']:
      yield [
          pickle.dumps((rating.url, time_period['name'])),
          pickle.dumps((score, time_passed))
      ]


def PopularPagesReduce(key, values):
  url, time_period = pickle.loads(key)
  popular_page = models.PopularPage(
      url=url,
      time_period=time_period,
      score=0,
      positive_ratings=0,
      negative_ratings=0)
  half_life_seconds = time_periods.Get(time_period)['timedelta'].total_seconds()
  for value in values:
    rating, time_passed = pickle.loads(value)
    if rating < 0:
      popular_page.negative_ratings += 1
    else:
      popular_page.positive_ratings += 1
    popular_page.score += rating * (0.5**(time_passed.total_seconds() /
                                          half_life_seconds))
  existing = models.PopularPage.query(
      models.PopularPage.url == url,
      models.PopularPage.time_period == popular_page.time_period).get()
  # Update the existing entry or create a new one.
  if popular_page.score > 0:
    if existing is not None:
      popular_page.key = existing.key
    popular_page.put()
  # Or delete the existing entry.
  elif existing is not None:
    existing.key.delete()
