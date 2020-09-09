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
"""Defines Datastore entities and functions to manipulate them."""

from __future__ import division

from datetime import datetime
from datetime import timedelta
import functools
import logging
import math
import pickle
from urlparse import urlparse

from google.appengine.api import memcache
from google.appengine.ext import deferred
from google.appengine.ext import ndb

from recommender import feeds
from recommender import items
from recommender import json_encoder
from recommender import ratings
from recommender import time_periods
from recommender import url_util


class Category(ndb.Model):
  name = ndb.StringProperty()

  def to_dict(self):
    result = ndb.Model.to_dict(self)
    result['id'] = self.key.id()
    return result

  def id(self):
    return self.key.id()


class User(ndb.Model):
  user_id = ndb.StringProperty()


PAGE_INFO_DICT_MEMCACHE_PREFIX = 'pd:'
PAGE_INFO_MEMCACHE_PREFIX = 'pi:'


# An object that can be used by the client the same way as
# PopularPage/Recommendation.
class DisplayableItem(ndb.Model):

  def __init__(self, url):
    self.url = url
    self.positive_ratings = 0
    self.negative_ratings = 0
    self.feed_count = 0
    self.top_feed_urls = []

  def to_dict(self):
    return self.__dict__

  def GetPageUrls(self):
    return set([self.url])

  # Saves a url->page info map to be used later in to_dict.
  def SavePageInfos(self, page_infos):
    self.page = page_infos[self.url]


def _FilterFields(dictionary, allowed_fields):
  return dict((k, v) for k, v in dictionary.iteritems() if k in allowed_fields)


class PageRating(ndb.Model):
  _EXPORTED_FIELDS = set(['url', 'date', 'rating', 'category'])

  url = ndb.StringProperty(indexed=True)
  # The user is already the parent key for each rating but we can't filter by
  # parent key in the on-demand MR to update personal recommendations so we
  # populate this property just for that MR.
  user_id = ndb.StringProperty()
  date = ndb.DateTimeProperty(auto_now_add=True)
  rating = ndb.IntegerProperty()
  source = ndb.StringProperty(indexed=True)
  category = ndb.KeyProperty(kind=Category)
  item_id = ndb.IntegerProperty()

  def to_dict(self):
    result = _FilterFields(ndb.Model.to_dict(self), PageRating._EXPORTED_FIELDS)
    result['page'] = self.page_infos[self.url]
    return result

  # Returns the list of urls this object is interested in for conversion to
  # json.
  def GetPageUrls(self):
    return set([self.url])

  # Saves a url->page info map to be used later in to_dict.
  def SavePageInfos(self, page_infos):
    self.page_infos = page_infos


def UrlToDomain(url):
  return urlparse(url).hostname or ''


class PageInfo(ndb.Model):
  url = ndb.StringProperty()
  title = ndb.StringProperty(indexed=False)
  canonical_url = ndb.StringProperty()
  description = ndb.StringProperty(indexed=False)
  # The url of the feed this page belongs to.
  feed_url = ndb.StringProperty(indexed=False)
  # The title of the feed this page belongs to.
  feed_title = ndb.StringProperty(indexed=False)
  # Whether this url is a feed.
  is_feed = ndb.BooleanProperty()
  estimated_reading_time = ndb.IntegerProperty(indexed=False)

  def to_dict(self):
    result = ndb.Model.to_dict(self)
    result['domain'] = UrlToDomain(self.url)
    return result


class ConnectionSourcePage(ndb.Model):
  url = ndb.StringProperty()
  weight = ndb.FloatProperty()


# The similarity between user A and user B (per category). It is not
# symmetrical. If user A recommended 1, 2, 3, 4, 5, 6, 7, 8 and user B
# recommended 1, 3, 5, 7 then user A recommended 100% of things recommended by
# user B, while user B recommended only 50% of things recommended by user A. So
# something new recommended by user B would show up in user A's recommendations
#  with higher confidence than the other way.
# Key: <source_user>:<source_category>:<destination_user>:<destination_category>
# Or if the source is a feed then:
# <feed url>:<destination_user>:<destination_category>
class Connection(ndb.Model):
  publisher_type = ndb.StringProperty()
  # The producer of recommendations
  # Either user id or feed url depending on the
  publisher_id = ndb.StringProperty()
  # Used only if publisher_type is 'user'.
  publisher_category = ndb.KeyProperty(kind=Category)
  # The consumer of recommendations (subscriber).
  subscriber_id = ndb.StringProperty()
  subscriber_category = ndb.KeyProperty(kind=Category)
  subscription_start_datetime = ndb.DateTimeProperty()
  positive = ndb.BooleanProperty()
  # The similarity score is between -1 and 1.
  weight = ndb.FloatProperty()
  updated_datetime = ndb.DateTimeProperty(auto_now=True)
  top_sources = ndb.LocalStructuredProperty(ConnectionSourcePage, repeated=True)
  num_shared_items = ndb.IntegerProperty(indexed=False)
  version = ndb.StringProperty()
  # Contains a list of time periods in which this connection recommended
  # anything.
  # CONNECTION_ALL_ACTIVE_DAYS
  # This helps us narrow down the list of top user connections to only ones that
  # have recommended anything in the period the user is interested in.
  active_days = ndb.IntegerProperty(repeated=True)
  active_datetime = ndb.DateTimeProperty()

  def SubscriberCategoryId(self):
    if self.subscriber_category:
      return self.subscriber_category.id()

  def SubscriberNonNullCategoryId(self):
    if self.subscriber_category:
      return self.subscriber_category.id()
    return DEFAULT_CATEGORY_ID

  def PublisherCategoryId(self):
    if self.publisher_category:
      return self.publisher_category.id()

  def SubscriberSource(self):
    return Source(SOURCE_TYPE_USER, self.subscriber_id,
                  self.SubscriberCategoryId())

  def PublisherSource(self):
    return Source(self.publisher_type, self.publisher_id,
                  self.PublisherCategoryId())

  def KeyComponents(self):
    if not hasattr(self, 'key_components'):
      self.key_components = ConnectionKeyComponents(self.publisher_type,
                                                    self.publisher_id,
                                                    self.PublisherCategoryId(),
                                                    self.subscriber_id,
                                                    self.SubscriberCategoryId(),
                                                    self.version, self.positive)
    return self.key_components


CONNECTION_ALL_ACTIVE_DAYS = [1, 3, 7, 14, 30, 60]

LOGISTIC_REGRESSION_CONNECTION = 'lr4'
POSITIVE_RATING = 1


class ConnectionKeyComponents(object):

  def __init__(self,
      publisher_type,
      publisher_id,
      publisher_category_id,
      subscriber_id,
      subscriber_category_id,
      version,
      positive=True):
    self.publisher_type = publisher_type
    self.publisher_id = publisher_id
    self.publisher_category_id = publisher_category_id
    self.subscriber_id = subscriber_id
    self.subscriber_category_id = subscriber_category_id
    self.version = version
    self.positive = positive
    self._hash = None

  def ToTuple(self):
    return (self.publisher_type, self.publisher_id, self.publisher_category_id,
            self.subscriber_id, self.subscriber_category_id, self.version,
            self.positive)

  def __hash__(self):
    if self._hash is None:
      self._hash = hash(self.ToTuple())
    return self._hash

  def __eq__(self, other):
    return self.ToTuple() == other.ToTuple()

  def SubscriberSource(self):
    return Source(SOURCE_TYPE_USER, self.subscriber_id,
                  self.subscriber_category_id)

  def PublisherSource(self):
    return Source(self.publisher_type, self.publisher_id,
                  self.publisher_category_id)

  def ToKey(self):
    return ConnectionKey(self.publisher_id, self.publisher_category_id,
                         self.subscriber_id, self.subscriber_category_id,
                         self.version, self.positive)


def ConnectionKey(publisher_id,
    publisher_category_id,
    subscriber_id,
    subscriber_category_id,
    version,
    positive=True):
  if publisher_category_id:
    publisher_category_id = long(publisher_category_id)
  if subscriber_category_id:
    subscriber_category_id = long(subscriber_category_id)
  if positive:
    parts = (str(publisher_id), publisher_category_id, str(subscriber_id),
             subscriber_category_id, str(version))
  else:
    parts = (str(publisher_id), publisher_category_id, str(subscriber_id),
             subscriber_category_id, str(version), False)
  return ndb.Key(Connection, pickle.dumps(parts))


def UserRatingToUnified(rating):
  return {
      'type': SOURCE_TYPE_USER,
      'publisher_id': rating.key.parent().id(),
      'publisher_category_id': GetCategoryId(rating.category),
      'date': rating.date,
      'rating': rating.rating,
      'url': rating.url,
  }


def FeedRatingToUnified(item):
  return {
      'type': SOURCE_TYPE_FEED,
      'publisher_id': item.feed_url,
      'publisher_category_id': None,
      'date': item.published_date,
      'rating': ratings.POSITIVE,
      'url': item.url,
  }


def GetUnifiedRatings(url, include_source_feed=True, do_not_fetch=False):
  page_info_future = GetPageInfoAsync(url, do_not_fetch=do_not_fetch)
  # Find user ratings for this url.
  user_ratings = [
      UserRatingToUnified(rating)
      for rating in PageRating.query(
          PageRating.url == url).order(-PageRating.date)
      if rating.rating != ratings.NEUTRAL
  ]

  # Find feed items for this url.
  feed_ratings = [
      FeedRatingToUnified(item) for item in feeds.FeedItem.query(
          feeds.FeedItem.url == url).order(-feeds.FeedItem.published_date)
  ]

  # We do not include the source feed if this url was downvoted because we
  # do not trust that the feed url in the page info has posted this url.
  # This is to prevent the case when a "bad" page tries to lower the reputation
  # of a "good" feed and the "bad" page puts a link to the "good" feed in the
  # <head> <meta> tag.
  if include_source_feed:
    page_info = page_info_future.get_result()
    if page_info.feed_url:
      feed_already_included = False
      for feed_rating in feed_ratings:
        if feed_rating['publisher_id'] == page_info.feed_url:
          feed_already_included = True
          break
      if not feed_already_included:
        feed_ratings.append({
            'type': SOURCE_TYPE_FEED,
            'publisher_id': page_info.feed_url,
            'publisher_category_id': None,
            # The "rating" time is used to determine how much the feed has
            # posted since then. So we set it just one day ago so the feed
            # does not get penalized for the old content.
            'date': datetime.now() - timedelta(days=1),
            'rating': ratings.POSITIVE,
        })

  merged = user_ratings + feed_ratings
  merged.sort(key=lambda r: r['date'])
  if feeds.GetFeed(url):
    # Every feed url is recommended by itself.
    merged.insert(
        0, {
            'type': SOURCE_TYPE_FEED,
            'publisher_id': url,
            'publisher_category_id': None,
            'date': datetime.min,
            'rating': ratings.POSITIVE,
        })
  return merged


def GetCategoryId(category_key):
  if category_key is None:
    return None
  return category_key.id()


class Timestamp(ndb.Model):
  date = ndb.DateTimeProperty()


def HasAccess():
  return True


def UserKey(user):
  if user is None:
    return None
  if isinstance(user, User):
    return user.key
  if isinstance(user, str) or isinstance(user, unicode):
    return ndb.Key(User, user)
  return ndb.Key(User, user.user_id())


def CategoryKey(category_id, user):
  if category_id == DEFAULT_CATEGORY_ID:
    return None
  return CategoryKeyIncludingDefault(category_id, user)


def CategoryKeyIncludingDefault(category_id, user):
  if category_id is None:
    return None
  return ndb.Key(Category, category_id, parent=UserKey(user))


def GetTimestamp(name):
  value = ndb.Key(Timestamp, name).get()
  if value is None:
    return datetime(1970, 1, 1)
  return value.date


def SetTimestamp(name, d):
  Timestamp(key=ndb.Key(Timestamp, name), date=d).put()


# Keyed by date range type, url
# Ordered within date range type by positive_ratings
class PopularPage(ndb.Model):
  url = ndb.StringProperty()
  time_period = ndb.StringProperty()
  positive_ratings = ndb.IntegerProperty()
  negative_ratings = ndb.IntegerProperty()
  updated_datetime = ndb.DateTimeProperty(auto_now=True)
  # The score of the item for ranking. It is based on how many users
  # upvoted/downvoted the item and some time-decaying.
  score = ndb.FloatProperty()

  def to_dict(self):
    result = ndb.Model.to_dict(self)
    result['page'] = self.page_infos[self.url]
    if hasattr(self, 'rating'):
      result['rating'] = self.rating
    if hasattr(self, 'category'):
      result['category'] = self.category.to_dict()
    return result

  # Returns the list of urls this object is interested in for conversion to
  # json.
  def GetPageUrls(self):
    return {self.url}

  # Saves a url->page info map to be used later in to_dict.
  def SavePageInfos(self, page_infos):
    self.page_infos = page_infos


# The page that you have in common with others that led to a recommendation.
class RecommendationSourcePage(object):
  _EXPORTED_FIELDS = {'url', 'user_count'}

  def __init__(self, url):
    self.url = url
    self.weight = 0
    self.user_count = 0

  def to_dict(self):
    return dict((k, v)
                for k, v in self.__dict__.iteritems()
                if k in RecommendationSourcePage._EXPORTED_FIELDS)


# User-item recommendation.
class Recommendation(json_encoder.Serializable):
  _EXPORTED_FIELDS = {'destination_url', 'source_category', 'weight',
                      'user_count', 'source_count',
                      'top_feed_urls', 'feed_count',
                      'rating', 'category'}

  _EXPORTED_SOURCE_PAGE_INFO_FIELDS = frozenset(['title', 'url'])

  def __init__(self,
      destination_url=None,
      source_category=None,
      weight=0,
      user_count=0,
      top_sources=[],
      source_count=0,
      first_seen_datetime=None,
      item_id=None):
    # The recommended url.
    self.destination_url = destination_url
    # The recommended item.
    self.item_id = item_id
    # The category of the recommendation.
    self.source_category = source_category
    # The weight of the recommendation
    self.weight = weight
    self.user_count = user_count
    # Items that were positively ranked by this user and other users who
    # positively ranked the recommended item.
    self.top_sources = top_sources
    # The total number of positively ranked items that co-occurred with the
    # recommended item.
    self.source_count = source_count
    # The time of the first rating for this item within the time period.
    # Used as a secondary sort field to get newer items recommended above older
    # items with the same weight. This is important for recommendations coming
    # from a single user/feed.
    self.first_seen_datetime = first_seen_datetime

    # Which connections contributed to this recommendation being shown.
    # Used to diversify the list of recommendations.
    self.connection_key_components = []

    # The xor of hashes of connection_key_components.
    self._connection_key_components_hash = None

    self.top_feed_urls = None
    self.feed_count = 0

  def to_dict(self):
    result = dict((k, v)
                  for k, v in self.__dict__.iteritems()
                  if v is not None and k in Recommendation._EXPORTED_FIELDS)
    result['destination_page'] = self._page_infos[self.destination_url]
    if self.top_sources:
      result['top_sources'] = [s.to_dict() for s in self.top_sources]
      for s in result['top_sources']:
        page_info_dict = self._page_infos[s['url']]
        s['page'] = {
            k: v
            for k, v in page_info_dict.iteritems()
            if k in Recommendation._EXPORTED_SOURCE_PAGE_INFO_FIELDS
        }
    return result

  def Serialize(self):
    return pickle.dumps(self)

  # Returns the list of urls this object is interested in for conversion to
  # json.
  def GetPageUrls(self):
    result = set([self.destination_url])
    for source in self.top_sources:
      result.add(source.url)
    return result

  # Saves a url->page info map to be used later in to_dict.
  def SavePageInfos(self, page_infos):
    self._page_infos = page_infos

  def ConnectionsHash(self):
    if self._connection_key_components_hash is None:
      self._connection_key_components_hash = functools.reduce(
          lambda a, b: a.__hash__() ^ b.__hash__(),
          self.connection_key_components, 0)
    return self._connection_key_components_hash


def DeserializeRecommendation(value):
  return pickle.loads(value)


class PastRecommendation(ndb.Model):
  user_id = ndb.StringProperty()
  item_id = ndb.IntegerProperty()
  url = ndb.StringProperty()
  weight = ndb.FloatProperty()
  # When the recommendation was made.
  date = ndb.DateTimeProperty()
  time_period_numeric = ndb.IntegerProperty()
  serialized_recommendation = ndb.BlobProperty()
  # When False then this past recommendation is not counted as an old
  # recommendation.
  committed = ndb.BooleanProperty()
  # Increasing number, one for each batch of recommendations committed at
  # the same time.
  session_number = ndb.IntegerProperty()
  index_within_page = ndb.IntegerProperty()


# Summary of a session, where a session is a list of PastRecommendations that
# have the same session_number.
# The summary is used to determine how much new recommendations to load
# initially for a new session.
class RecommendationSession(ndb.Model):
  user_id = ndb.StringProperty()
  time_period_numeric = ndb.IntegerProperty()
  # When the session was committed.
  date = ndb.DateTimeProperty(auto_now_add=True)
  median_weight = ndb.FloatProperty()
  min_weight = ndb.FloatProperty()
  max_weight = ndb.FloatProperty()
  recommendation_count = ndb.IntegerProperty()


# Is called when the user rates the url.
def DeletePastRecommendation(user_id, url):
  user_key = UserKey(user_id)
  for time_period in time_periods.TIME_PERIODS:
    ndb.Key(
        PastRecommendation,
        str(time_period['numeric']) + ':' + url,
        parent=user_key).delete()


def MarkUnread(user_id, start_url, time_period):
  """Removes past recommendations from the list to be committed.

  Args:
    user_id: The user.
    start_url: This recommended item and below should not be committed.
    time_period: The time period the user is reading recommendation in.

  Returns:
    A tuple with the number of items affected and whether the visit will not be
    counted.
  """
  time_period_numeric = time_periods.Get(time_period)['numeric']
  most_recently_saved = PastRecommendation.query(
      PastRecommendation.user_id == user_id,
      PastRecommendation.time_period_numeric == time_period_numeric,
      PastRecommendation.committed == False).order(
      -PastRecommendation.date).fetch()
  start_item = None
  for item in most_recently_saved:
    if item.url == start_url:
      start_item = item
  unread_item_keys = [
      item.key
      for item in most_recently_saved
      if ((not start_item
           ) or  # In case the item for start_url is already committed.
          (item.date > start_item.date and item.weight <= start_item.weight) or
          (item.date == start_item.date and
           item.index_within_page >= start_item.index_within_page))
  ]
  # If all items were marked as unread then we don't count this visit.
  # For example, when the user opens Recommender just to recommend something.
  visit_discarded = False
  ndb.delete_multi(unread_item_keys)
  return (len(unread_item_keys), visit_discarded)


# We do not store past recommendations by category.
def GetPastRecommendations(user_id, time_period, offset, limit):
  time_period_numeric = time_periods.Get(time_period)['numeric']
  past_recommendations = PastRecommendation.query(
      PastRecommendation.user_id == user_id,
      PastRecommendation.time_period_numeric == time_period_numeric,
      PastRecommendation.committed == True,
  ).order(-PastRecommendation.session_number, -PastRecommendation.weight).fetch(
      limit, offset=offset)
  recommendations = [
      DeserializeRecommendation(r.serialized_recommendation)
      for r in past_recommendations
  ]
  return DecorateRecommendations(user_id, recommendations)


def DecorateRecommendations(user_id, recommendations):
  urls = set()
  for p in recommendations:
    urls.add(p.destination_url)

  rated_pages_future = GetRatedPagesAsync(user_id, urls)
  PopulatePageInfos(recommendations)
  rated_pages = rated_pages_future.get_result()
  for p in recommendations:
    url = p.destination_url
    if url in rated_pages:
      rating = rated_pages[url]
      p.rating = rating.rating
      if rating.category is not None:
        p.category = rating.category
  return recommendations


@ndb.tasklet
def GetRatedPagesAsync(user, urls):
  result = {}
  user_key = UserKey(user)
  user_ratings = yield ndb.get_multi_async(
      [ndb.Key(PageRating, url, parent=user_key) for url in urls])
  for rating in user_ratings:
    if rating is not None:
      result[rating.url] = rating
  raise ndb.Return(result)


def _TimeDecayScore(score, score_date, now_date):
  time_passed = now_date - score_date
  days_passed = time_passed.days + time_passed.seconds / 86400
  return math.log(max(score + 1, 1), 10) - days_passed


def PopularPages(user, time_period, offset, limit):
  """"Returns a list of popular items.

  Args:
    user: The current user.
    time_period: The time period outside of which votes don't count.
    offset: The pagination offset.
    limit: The pagination page size.

  Returns:
    A list of popular items.
  """
  # Get all top connections.
  # We find all ratings that were left within the time_period.
  # Find the weights of top connections.
  # The score of an item is sum of:
  #   vote.value * (trust(vote.user) + nominal_weight)
  is_recent = time_period == time_periods.RECENT
  if is_recent:
    now_date = datetime.now()
    query = PageRating.query(
        projection=['url', 'user_id', 'rating', 'category', 'date', 'source'])
    if time_period != time_periods.ALL and time_period != time_periods.RECENT:
      query = query.filter(PageRating.date > now_date -
                           time_periods.Get(time_period)['timedelta'])
    fetch_limit = 1000
    if is_recent:
      fetch_limit = 200
    user_ratings = query.order(-PageRating.date).fetch(fetch_limit)

    url_to_popular_page = {}
    nominal_weight = 1
    for r in user_ratings:
      if r.rating == 0:
        continue
      if r.url in url_to_popular_page:
        popular_page = url_to_popular_page[r.url]
      else:
        popular_page = PopularPage(
            url=r.url,
            score=0,
            positive_ratings=0,
            negative_ratings=0,
            updated_datetime=r.date)
        url_to_popular_page[r.url] = popular_page
      if r.rating > 0:
        popular_page.positive_ratings += 1
      if r.rating < 0:
        popular_page.negative_ratings += 1
      if is_recent:
        popular_page.updated_datetime = min(popular_page.updated_datetime,
                                            r.date)
      else:
        popular_page.updated_datetime = max(popular_page.updated_datetime,
                                            r.date)
      weight = nominal_weight
      popular_page.score += r.rating * weight

    result = [v for v in url_to_popular_page.values() if v.score > 0]
    for v in result:
      v.score = _TimeDecayScore(v.score, v.updated_datetime, now_date)
    result.sort(key=lambda v: (v.score, v.updated_datetime), reverse=True)
    result = result[offset:offset + limit]
  else:
    query = PopularPage.query(PopularPage.time_period == time_period)
    result = query.order(-PopularPage.score).fetch(limit, offset=offset)
  urls = set()
  for p in result:
    urls.add(p.url)
  rated_pages_future = GetRatedPagesAsync(user, urls)
  PopulatePageInfos(result)
  rated_pages = rated_pages_future.get_result()
  for p in result:
    if p.url in rated_pages:
      rating = rated_pages[p.url]
      p.rating = rating.rating
      if rating.category is not None:
        p.category = rating.category.get()
  return result


SOURCE_TYPE_FEED = 'feed'
SOURCE_TYPE_USER = 'user'


def SerializeSource(source):
  return source.__dict__


def DeserializeSource(d):
  source = Source(None, None, None)
  source.__dict__ = d
  return source


class Source(object):

  def __init__(self, source_type, source_id, category_id):
    self.source_type = source_type
    self.source_id = source_id
    self.category_id = category_id

  def __hash__(self):
    return hash((self.source_type, self.source_id, self.category_id))

  def __eq__(self, other):
    return (self.source_type, self.source_id,
            self.category_id) == (other.source_type, other.source_id,
                                  other.category_id)

  def __ne__(self, other):
    # Not strictly necessary, but to avoid having both x==y and x!=y
    # True at the same time
    return not self == other

  def CategoryKey(self):
    if self.source_type == SOURCE_TYPE_USER:
      return CategoryKey(self.category_id, self.source_id)
    return None

  # How many ratings did this source submit after a given date.
  def GetNumRatingsSinceDate(self, date):
    if self.source_type == SOURCE_TYPE_USER:
      q = PageRating.query(
          PageRating.category == self.CategoryKey(),
          PageRating.date >= date,
          ancestor=UserKey(self.source_id))
    else:
      q = feeds.FeedItem.query(feeds.FeedItem.feed_url == self.source_id,
                               feeds.FeedItem.published_date >= date)
    return q.count()

  def GetLastRatingDatetime(self):
    if self.source_type == SOURCE_TYPE_USER:
      last_rating = PageRating.query(
          PageRating.category == self.CategoryKey(),
          ancestor=UserKey(self.source_id)).order(-PageRating.date).get()
      if last_rating:
        return last_rating.date
      else:
        return None
    else:
      last_item = feeds.FeedItem.query(
          feeds.FeedItem.feed_url == self.source_id).order(
          -feeds.FeedItem.published_date).get()
      if last_item:
        return last_item.published_date
      else:
        return None


def PopulatePageInfos(result):
  urls = set()
  for p in result:
    urls |= p.GetPageUrls()
  page_infos = GetBulkPageInfo(urls, log_not_found=True, do_not_fetch=False)
  for p in result:
    p.SavePageInfos(page_infos)


PAGE_INFO_PRIMARY_FIELDS = set([
    'title',
    'description',
    'estimated_reading_time',
    'is_feed',
])


def GetBulkPageInfo(urls, log_not_found=False, do_not_fetch=False):
  # First, get them all from the cache.
  page_infos = memcache.get_multi(urls,
                                  key_prefix=PAGE_INFO_DICT_MEMCACHE_PREFIX)
  urls_not_in_cache = [url for url in urls if url not in page_infos]
  if urls_not_in_cache:
    # Second, get what was not found in the cache from the datastore.
    page_info_models_list = ndb.get_multi(
        [ndb.Key(PageInfo, url) for url in urls_not_in_cache])
    page_info_models = {}
    pending = {}
    # Third, fetch in parallel what was not found in the cache and the
    # datastore.
    for url, page_info_model in zip(urls_not_in_cache, page_info_models_list):
      if page_info_model:
        page_info_models[url] = page_info_model
      else:
        pending[url] = GetPageInfoAsync(
            url,
            log_not_found=log_not_found,
            do_not_fetch=do_not_fetch,
            get_from_datastore=False)
    for url, page_info_model_future in pending.iteritems():
      # GetPageInfoAsync returns None when do_not_fetch is True.
      page_info_models[url] = page_info_model_future.get_result() or PageInfo(
          url=url, title=url)
    new_entries = {}
    for url, page_info_model in page_info_models.iteritems():
      page_info = page_info_model.to_dict()
      page_info = dict(
          (k, v)
          for k, v in page_info.iteritems()
          if v and (k in PAGE_INFO_PRIMARY_FIELDS))
      page_infos[url] = page_info
      new_entries[url] = page_info
    if new_entries:
      failed_keys = memcache.set_multi(new_entries,
                                       key_prefix=PAGE_INFO_DICT_MEMCACHE_PREFIX)
      if failed_keys:
        logging.warning('Error updating memcache')
  # Populate fields that are not stored in the cache.
  for url, page_info in page_infos.iteritems():
    page_info['domain'] = UrlToDomain(url)
    page_info['url'] = url
  return page_infos


def PrefetchPageInfos(urls):
  tasks = [GetPageInfoAsync(url) for url in urls]
  # All tasks kicked off.
  page_infos = [task.get_result() for task in tasks]
  # Prefetch canonical urls as well.
  canonical_url_tasks = [
      GetPageInfoAsync(page_info.canonical_url)
      for page_info in page_infos
      if page_info.url != page_info.canonical_url
  ]
  for task in canonical_url_tasks:
    task.get_result()


def _MetadataToPageInfo(m, key, url):
  return PageInfo(
      key=key,
      url=url,
      title=m.title,
      canonical_url=m.canonical_url,
      description=m.description,
      feed_url=m.feed_url,
      feed_title=m.feed_title,
      is_feed=m.is_feed,
      estimated_reading_time=m.estimated_reading_time)


@ndb.tasklet
def GetPageInfoAsync(
    url,
    log_not_found=False,
    do_not_fetch=False,
    raise_invalid_url=False,
    raise_error=False,
    get_from_datastore=True):
  url = url_util.Normalize(url)
  # This is the central place where we fetch url information. We remove useless
  # parameters here.
  url = url_util.RemoveUtmParameters(url)
  # NDB does not allow key names larger than 500 bytes.
  if len(url) >= 500:
    raise ndb.Return(None)
  key = ndb.Key(PageInfo, url)
  page_info = None
  if get_from_datastore:
    page_info = yield key.get_async()
  if page_info is None:
    try:
      if log_not_found:
        logging.warning('url not found in cache and datastore: %s', url)
      if do_not_fetch:
        logging.warning('returning empty details: %s', url)
        raise ndb.Return(None)
      metadata = url_util.GetPageMetadata(url)
      page_info = _MetadataToPageInfo(metadata, key, url)
      yield page_info.put_async()
      # If the original link is a redirect
      # (e.g., bit.ly/abc -> example.com/page.html) then the fetched page will
      # be the content of metadata.final_url and if it also matches the
      # canonical then we will be interested in it under the final url.
      # So we save the page info here.
      if (metadata.final_url != url and
          metadata.final_url == metadata.canonical_url):
        yield _MetadataToPageInfo(metadata, ndb.Key(PageInfo,
                                                    metadata.final_url),
                                  metadata.final_url).put_async()
    except url_util.InvalidURLError as e:
      if raise_invalid_url or raise_error:
        raise e
      raise ndb.Return(PageInfo(key=key, url=url, title=url, canonical_url=url))
    except url_util.Error as e:
      if raise_error:
        raise e
      logging.warning('Failed to get page details: %s error: %s', url, e)
      # Store the empty PageInfo so that next time we don't try to urlfetch it
      # again.
      page_info = PageInfo(key=key, url=url, title=url, canonical_url=url)
      yield page_info.put_async()
    except ValueError as e:
      logging.warning('Got ValueError for page: %s error: %s', url, e)
      page_info = PageInfo(key=key, url=url, title=url, canonical_url=url)
  # Support existing objects that didn't have the canonical url property.
  elif page_info.canonical_url is None:
    page_info.canonical_url = url
  raise ndb.Return(page_info)


def GetPageInfoOrRaise(url):
  page_info = memcache.get(PAGE_INFO_MEMCACHE_PREFIX + url)
  if page_info:
    return page_info
  page_info = GetPageInfoAsync(url, raise_error=True).get_result()
  if not memcache.set(PAGE_INFO_MEMCACHE_PREFIX + url, page_info):
    logging.warning('Error updating memcache')
  return page_info


def GetPageInfo(url):
  return GetPageInfoAsync(url).get_result()


def GetCanonicalUrl(url):
  return GetPageInfoAsync(
      url, raise_invalid_url=True).get_result().canonical_url


def MaybeAddUser(user):
  key = UserKey(user)
  value = key.get()
  if value is None:
    User(key=key).put()


def AddRating(user, url, rating, source, category_id):
  return AddRatingAtTime(
      user,
      url,
      rating,
      source,
      category_id,
      datetime.now())


def AddRatingAtTime(user,
    url,
    rating,
    source,
    category_id,
    time):
  # Get existing ratings before we the new rating is added so we can tell who
  # this user will be connecting to.
  stats = GetRatingStats(url)
  # Make sure there is a User placeholder for each user with rating so
  # we can run analysis by user.
  MaybeAddUser(user)
  user_key = UserKey(user)
  category = None
  # Clamp the rating to [-1, 1] range.
  rating = min(rating, 1)
  rating = max(rating, -1)
  if category_id is not None:
    category = CategoryKey(category_id, user)
  user_id = user_key.id()
  PageRating(
      key=ndb.Key(PageRating, url, parent=user_key),
      user_id=user_id,
      url=url,
      rating=rating,
      category=category,
      source=source,
      date=time,
      item_id=items.UrlToItemId(url)).put()
  # We do not want to show as a past recommendation anything that the user
  # downvoted.
  if rating < 0:
    deferred.defer(DeletePastRecommendation, user_id, url)
  deferred.defer(UpdateRatedItemIdsCache, user_id)
  return stats


MAX_STATS_TOP_FEEDS = 10


def GetRatingStats(url, do_not_fetch=False):
  """Returns summary of sources of a url."""
  feeds_urls = []
  stats = {'user_count': 0}
  # Get existing ratings before we the new rating is added so we can tell who
  # this user will be connecting to.
  for r in GetUnifiedRatings(url, do_not_fetch=do_not_fetch):
    if r['type'] == SOURCE_TYPE_FEED:
      feeds_urls.append(r['publisher_id'])
    # We only want to tell about the number of users who rated positively.
    if r['type'] == SOURCE_TYPE_USER and r['rating'] == ratings.POSITIVE:
      stats['user_count'] += 1
  feeds_urls = url_util.DeduplicateUrls(feeds_urls)
  stats['feed_count'] = len(feeds_urls)
  stats['top_feeds'] = feeds_urls[:MAX_STATS_TOP_FEEDS]
  return stats


def UpdateRatedItemIdsCache(user_id):
  UpdateRatedItemIdsAsync(user_id).get_result()


def GetUserRatedItemsCacheKey(user_id):
  return 'ri:' + str(user_id)


@ndb.tasklet
def GetRatedItemIdsAsync(user_id):
  client = memcache.Client()
  cached = yield client.get_multi_async([GetUserRatedItemsCacheKey(user_id)])
  if cached:
    result = cached.values()[0]
  else:
    result = yield UpdateRatedItemIdsAsync(user_id)
  result = items.ItemIdsFromBytes(result)
  raise ndb.Return(result)


def UpdateRatedItemIds(user_id):
  UpdateRatedItemIdsAsync(user_id).get_result()


@ndb.tasklet
def UpdateRatedItemIdsAsync(user_id):
  user_ratings = yield PageRating.query(
      ancestor=UserKey(user_id),
      projection=['item_id']).order(-PageRating.date).fetch_async(500)
  result = items.ItemIdsToBytes([r.item_id for r in user_ratings])
  memcache.set(GetUserRatedItemsCacheKey(user_id), result)
  raise ndb.Return(result)


def GetRatingHistory(user,
    category_id,
    any_category,
    positive_only,
    offset,
    limit):
  user_key = UserKey(user)
  q = PageRating.query(ancestor=user_key)
  if not any_category:
    category_key = None
    if category_id is not None:
      category_key = CategoryKey(category_id, user)
    q = q.filter(PageRating.category == category_key)
  if positive_only:
    q = q.filter(PageRating.rating == 1)
  q = q.order(-PageRating.date)
  result_future = q.fetch_async(limit, offset=offset)
  result = result_future.get_result()
  PopulatePageInfos(result)
  return result


# A new user is a user that hasn't submitted any ratings yet.
def IsNewUser(user):
  return PageRating.query(ancestor=UserKey(user)).get() is None


def UpdateCachedConnectionInfo(user_id):
  positive_rating_count = PageRating.query(
      PageRating.rating > 0, ancestor=UserKey(user_id)).count()
  user_count = 0
  feed_count = 0
  for c in Connection.query(
      Connection.version == LOGISTIC_REGRESSION_CONNECTION,
      Connection.subscriber_id == user_id, Connection.positive == True):
    if c.publisher_type == SOURCE_TYPE_USER:
      user_count += 1
    else:
      feed_count += 1
  info = {
      'user_count': user_count,
      'feed_count': feed_count,
      'positive_rating_count': positive_rating_count
  }
  memcache.set('ConnectionInfo:' + str(user_id), info)
  return info


def GetConnectionInfo(user_id):
  info = memcache.get('ConnectionInfo:' + str(user_id))
  if not info:
    info = UpdateCachedConnectionInfo(user_id)
  return info


def DeleteRating(user, url):
  user_key = UserKey(user)
  ndb.Key(PageRating, url, parent=user_key).delete()
  deferred.defer(UpdateRatedItemIdsCache, user_key.id())


def AddCategory(user, name):
  category = Category(parent=UserKey(user), name=name)
  category.put()
  return category


def GetOrCreateCategory(user, name):
  return (Category.query(Category.name == name, ancestor=UserKey(user)).get() or
          AddCategory(user, name))


def RenameCategory(user, category_id, name):
  if category_id == DEFAULT_CATEGORY_ID:
    return
  category = CategoryKey(category_id, user).get()
  if category is not None:
    category.name = name
    category.put()


def RemoveCategory(user, category_id):
  if category_id == DEFAULT_CATEGORY_ID:
    return
  category_key = CategoryKey(category_id, user)
  category_key.delete()
  for p in PageRating.query(
      PageRating.category == category_key, ancestor=UserKey(user)).fetch():
    p.category = None
    p.put()


def SetPageCategory(user, url, category_id, retries_left=10):
  user_key = UserKey(user)
  page_rating = ndb.Key(PageRating, url, parent=user_key).get()
  if page_rating is None:
    # It could be that the PageRating has not become available yet so we retry
    # a few times.
    if retries_left > 0:
      deferred.defer(SetPageCategory, user, url, category_id, retries_left - 1)
    return

  category = None
  if category_id is not None:
    category = CategoryKey(category_id, user)

  page_rating.category = category
  page_rating.put()


DEFAULT_CATEGORY_ID = 1
DEFAULT_CATEGORY_NAME = 'default'


def CreateDefaultCategory(user):
  category = Category(
      key=ndb.Key(Category, DEFAULT_CATEGORY_ID, parent=UserKey(user)),
      name=DEFAULT_CATEGORY_NAME)
  category.put()
  return category


def GetCategories(user):
  result = Category.query(ancestor=UserKey(user)).fetch(1000)
  result.sort(key=lambda c: (c.id() == DEFAULT_CATEGORY_ID, c.name.lower()))
  if not result or result[-1].id() != DEFAULT_CATEGORY_ID:
    result.append(CreateDefaultCategory(user))
  return result


# Suggest a category for a new page based on what the user previously put under
# which category.
def SuggestCategoryForPage(user, url):
  most_recent_category = None
  most_recent_category_set = False
  domain = UrlToDomain(url)
  for rating in PageRating.query(
      ancestor=UserKey(user)).order(-PageRating.date).fetch(50):
    if not most_recent_category_set:
      most_recent_category = rating.category
      most_recent_category_set = True
    # Second choice: the most recently used category for a recommendation from
    # the same domain.
    if UrlToDomain(rating.url) == domain:
      return rating.category
  # Third choice: the most recently used category.
  return most_recent_category
