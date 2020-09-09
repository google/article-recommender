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
"""Functionality to create recommendations for a user."""

from __future__ import division

from datetime import datetime
from datetime import timedelta

from recommender import feeds
from recommender import items
from recommender import models
from recommender import past_recommendations
from recommender import time_periods
from recommender import url_util

from google.appengine.ext import ndb

# How many sources to include for each recommendation.
MAX_TOP_SOURCES = 10

NOMINAL_USER_VOTE_WEIGHT = 0.0001

SOURCE_TYPE_ANY = None
SOURCE_TYPE_FEED = 'feed'
SOURCE_TYPE_USER = 'user'


def RecommendationsOnDemand(
    user,
    time_period,
    category_id,
    any_category,
    include_popular,
    limit,
    connection_version,
    decay_rate=1,
    source_type=SOURCE_TYPE_ANY,
    exclude_urls=frozenset(),
    save_past_recommendations=False,
    exclude_past_recommendations=False,
    exclude_past_recommendations_from_all_time_periods=False,
    external_connections=None,
    exclude_rated_items=True,
    diversify=False):
  """Calculates recommendations for a user on demand.

  The recommendations are calculated from raw user ratings, feed items and top
  connection of this user to other users and other feeds.

  Args:
    user: The user we are making recommendations for.
    time_period: The time period that the user is interested in
    category_id: The category that user wants recommendations for.
    any_category: Whether the user wants recommendations for all categories.
    include_popular: Whether to include recommendations from other users that
      this users is not connected to.
    limit: Pagination size.
    connection_version: The version of connections to use.
    decay_rate: How much to penalize older items from the same source.
    source_type: Whether to return recommendations only from feeds, users or
      both.
    exclude_urls: The set of items that should not be returned.
    save_past_recommendations: Whether to save the returned recommendations as
      past recommendations.
    exclude_past_recommendations: Whether to exclude past committed
      recommendations.
    exclude_past_recommendations_from_all_time_periods: Whether to exclude past
      recommendations that were shown for other time periods. Otherwise only
      excludes past recommendations that were shown for the same time period as
      time_period.
    external_connections: If None, then these models.Connection objects will be
      used instead of getting them from Datastore for this user.
    exclude_rated_items: Whether to exclude items already rated by the user from
      the returned recommendations.
    diversify: If True, then recommendations from the same sources will be
      forced to be separated with recommendations from other sources.

  Returns:
    A list of recommendations.
  """
  exclude_item_ids = set(items.UrlsToItemIds(exclude_urls).values())
  subscriber_id = models.UserKey(user).id()
  now = datetime.now()
  since_time = _GetSinceTime(time_period, now)

  past_recommendation_item_ids_future = None
  past_recommendation_item_ids = frozenset()
  if exclude_past_recommendations:
    past_recommendation_item_ids_future = (
        past_recommendations.GetPastRecommendationItemIdsAsync(
            subscriber_id,
            (None if exclude_past_recommendations_from_all_time_periods else
             time_period)))
  if exclude_rated_items:
    recent_rated_item_ids_future = models.GetRatedItemIdsAsync(subscriber_id)
  else:
    recent_rated_item_ids_future = ndb.Future()
    recent_rated_item_ids_future.set_result([])

  connection_active_days = None
  for days in models.CONNECTION_ALL_ACTIVE_DAYS:
    if timedelta(days=days) >= now - since_time:
      connection_active_days = days
      break

  if source_type == SOURCE_TYPE_FEED or source_type == SOURCE_TYPE_ANY:
    feed_info_future = _GetRecommendedFeedItems(
        user, since_time, category_id, any_category, connection_version,
        connection_active_days, external_connections)
  else:
    feed_info_future = ndb.Future()
    feed_info_future.set_result(([], []))

  def GetConnections(connection_version=connection_version):
    if external_connections:
      promise = ndb.Future()
      promise.set_result([])
      return promise
    query = models.Connection.query(
        models.Connection.publisher_type == models.SOURCE_TYPE_USER,
        models.Connection.subscriber_id == subscriber_id,
        models.Connection.version == connection_version).order(
        -models.Connection.weight)
    if connection_active_days:
      query = query.filter(
          models.Connection.active_days == connection_active_days)
    if not any_category:
      subscriber_category = models.CategoryKey(category_id, user)
      query = query.filter(
          models.Connection.subscriber_category == subscriber_category)
    return query.fetch_async(100)

  connections_future = GetConnections()

  query = models.PageRating.query(
      projection=['item_id', 'user_id', 'rating', 'category', 'date'])
  if since_time != datetime.min:
    query = query.filter(models.PageRating.date > since_time)
  user_ratings = query.order(-models.PageRating.date).fetch(1000)

  if past_recommendation_item_ids_future:
    past_recommendation_item_ids = (
        past_recommendation_item_ids_future.get_result())
  positive_sources = set()
  negative_sources = set()
  for r in user_ratings:
    if r.rating == 0:
      continue
    if r.item_id in past_recommendation_item_ids:
      continue
    if r.item_id in exclude_item_ids:
      continue
    if r.key.parent().id() == subscriber_id:
      continue
    publisher_id = r.key.parent().id()
    publisher_category_id = models.GetCategoryId(r.category)
    source = (publisher_id, publisher_category_id)
    if r.rating < 0:
      negative_sources.add(source)
    else:
      positive_sources.add(source)
    r.rating_source = source

  positive_source_to_connection = {}
  negative_source_to_connection = {}
  connections = connections_future.get_result()
  if external_connections:
    connections = [
        c for c in external_connections
        if c.publisher_type == models.SOURCE_TYPE_USER
    ]

  for connection in connections:
    source = (connection.publisher_id, connection.PublisherCategoryId())
    # The user may be subscribed to the same source from multiple collections.
    # We only count the strongest connection here.
    if (connection.positive and source in positive_sources and
        source not in positive_source_to_connection):
      positive_source_to_connection[source] = connection
    if (not connection.positive and source in negative_sources and
        source not in negative_source_to_connection):
      negative_source_to_connection[source] = connection

  item_id_to_recommendation = {}
  recent_rated_item_ids = set(recent_rated_item_ids_future.get_result())
  nominal_weight = NOMINAL_USER_VOTE_WEIGHT if include_popular else 0
  num_matched_past_recommendations = 0
  # Keyed by (user_id, category_id).
  seen_items_from_user = {}
  for r in user_ratings:
    item_id = r.item_id
    assert item_id
    if r.rating == 0:
      continue
    if r.item_id in past_recommendation_item_ids:
      num_matched_past_recommendations += 1
      continue
    if r.item_id in exclude_item_ids:
      continue
    if r.item_id in recent_rated_item_ids:
      continue
    if r.key.parent().id() == subscriber_id:
      continue
    if r.rating > 0:
      connection = positive_source_to_connection.get(r.rating_source, None)
    else:
      connection = negative_source_to_connection.get(r.rating_source, None)
    if connection:
      category_id = connection.SubscriberCategoryId()
      category = connection.subscriber_category
    else:
      category = None
      category_id = None
    key = (r.item_id, category_id)
    if key in item_id_to_recommendation:
      (recommendation, top_sources, source_users,
       feed_connections) = item_id_to_recommendation[key]
    else:
      recommendation = models.Recommendation(
          item_id=r.item_id,
          source_category=category,
          first_seen_datetime=r.date)
      top_sources = {}
      source_users = {}
      feed_connections = []
      item_id_to_recommendation[key] = (recommendation, top_sources,
                                        source_users, feed_connections)
    recommendation.first_seen_datetime = min(recommendation.first_seen_datetime,
                                             r.date)
    weight = nominal_weight
    if connection:
      connection_weight = connection.weight
      connection_top_sources = connection.top_sources
      publisher_id = connection.publisher_id
      if r.rating > 0 and connection_weight > 0:
        for source in connection_top_sources:
          if source.url not in top_sources:
            top_sources[source.url] = models.RecommendationSourcePage(
                source.url)
          top_sources[source.url].weight += connection_weight
          top_sources[source.url].user_count += 1
        source_users[publisher_id] = connection_weight
        recommendation.connection_key_components.append(
            connection.KeyComponents())
      # Skip positive recommendations if the publisher has no positive
      # recommendations in common with the subscriber
      # (ie, num_shared_items == 0).
      if r.rating > 0 and connection.num_shared_items == 0:
        pass
      else:
        if decay_rate < 1:
          key = (publisher_id, connection.PublisherCategoryId())
          seen_items = seen_items_from_user.get(key, 0)
          seen_items_from_user[key] = seen_items + 1
          # We are processing user ratings in most-recent first order. The most
          # recent rated item gets the full weight of the connection, the older
          # ones get progressively smaller weight.
          # We apply the decay rate only to the earned connection weight and
          # leave the nominal weight alone. That way a new user will see purely
          # popularity based ranking where each rating has the same weight, no
          # matter who those ratings came from.
          connection_weight *= decay_rate ** seen_items
        weight += connection_weight
    if weight > 0:
      recommendation.weight += r.rating * weight
      if r.rating > 0:
        recommendation.user_count += 1

  (feed_items, feed_url_to_connection) = feed_info_future.get_result()
  seen_items_from_feed = {}
  if decay_rate < 1:
    # We need to sort so that the decay rate is applied from most recent items
    # to less recent items.
    feed_items.sort(key=lambda item: item.published_date, reverse=True)

  num_feed_items_matched_past_recommendations = 0
  for item in feed_items:
    item_id = item.item_id
    if item_id in recent_rated_item_ids:
      continue
    if item_id in past_recommendation_item_ids:
      num_feed_items_matched_past_recommendations += 1
      continue
    connection = feed_url_to_connection.get(item.feed_url, None)
    if not connection:
      continue
    seen_items = 0
    # We need to count urls in the exclude list before we ignore them.
    if decay_rate < 1:
      seen_items = seen_items_from_feed.get(item.feed_url, 0)
      seen_items_from_feed[item.feed_url] = seen_items + 1
    if item_id in exclude_item_ids:
      continue
    category = connection['category']
    key = (item_id, models.GetCategoryId(category))
    if key in item_id_to_recommendation:
      (recommendation, top_sources, source_users,
       feed_connections) = item_id_to_recommendation[key]
    else:
      recommendation = models.Recommendation(
          item_id=item_id,
          source_category=category,
          first_seen_datetime=item.published_date)
      top_sources = {}
      source_users = {}
      feed_connections = []
      item_id_to_recommendation[key] = (recommendation, top_sources,
                                        source_users, feed_connections)
    recommendation.first_seen_datetime = min(recommendation.first_seen_datetime,
                                             item.published_date)
    weight = connection['weight']
    if decay_rate < 1:
      weight = connection['weight'] * (decay_rate ** seen_items)
    feed_connections.append(connection)
    recommendation.weight += weight
    recommendation.connection_key_components.append(
        connection['key_components'])

  for _, (recommendation, top_sources, source_users,
          feed_connections) in item_id_to_recommendation.iteritems():
    recommendation.source_count = len(top_sources)
    recommendation.top_sources = sorted(
        top_sources.values(), key=lambda v: v.weight,
        reverse=True)[:MAX_TOP_SOURCES]
    feed_connections = sorted(
        feed_connections, key=lambda c: c['weight'], reverse=True)
    unique_feed_urls = set(
        url_util.DeduplicateUrls([c['publisher_id'] for c in feed_connections]))
    recommendation.top_feed_urls = _GetTopFeedUrls(feed_connections,
                                                   unique_feed_urls)
    recommendation.feed_count = len(unique_feed_urls)

  result = [
      r for (r, _, _, _) in item_id_to_recommendation.values() if r.weight > 0
  ]
  result.sort(key=lambda v: (v.weight, v.first_seen_datetime), reverse=True)
  seen = set()
  seen_add = seen.add
  # Remove duplicate items that may have been recommended under different
  # categories.
  result = [r for r in result if not (r.item_id in seen or seen_add(r.item_id))]
  if diversify:
    result = _DiversifyByKey(result, limit, lambda r: r.ConnectionsHash())
  result = result[:limit]

  # The recommendations only have item_id populated. We need to add
  # destination_url.
  item_id_to_url = items.ItemIdsToUrls([r.item_id for r in result])
  for r in result:
    r.destination_url = item_id_to_url.get(r.item_id, '#invalid_item')

  if save_past_recommendations:
    past_recommendations.SavePastRecommendations(subscriber_id, time_period,
                                                 result)

  return models.DecorateRecommendations(subscriber_id, result)


MAX_TOP_FEEDS = 10


def _GetTopFeedUrls(feed_connections, unique_feed_urls):
  urls = None
  for c in feed_connections:
    url = c['publisher_id']
    if url in unique_feed_urls:
      if urls is None:
        urls = [url]
      else:
        urls.append(url)
      if len(urls) >= MAX_TOP_FEEDS:
        break
  return urls


def _DiversifyByKey(all_items, limit, key):
  """Returns a subset of all_items such that no two items next to each other have the same key."""
  if len(all_items) < 2:
    return all_items
  if len(all_items) < limit:
    limit = len(all_items)
  diverse_items = []
  previous_key = None
  added_indexes = set([])
  for _ in range(0, limit):
    found_diverse = False
    first_not_added_index = -1
    for index, item in enumerate(all_items):
      if index in added_indexes:
        continue
      if first_not_added_index == -1:
        first_not_added_index = index
      current_key = key(item)
      if current_key != previous_key:
        diverse_items.append(item)
        added_indexes.add(index)
        previous_key = current_key
        found_diverse = True
        break
    # If we didn't find a new item, then we add the next not added item with
    # the same hash.
    if not found_diverse:
      diverse_items.append(all_items[first_not_added_index])
      added_indexes.add(first_not_added_index)
  return diverse_items


@ndb.tasklet
def _GetRecommendedFeedItems(user, since_time, category_id, any_category,
    connection_version, connection_active_days,
    external_connections):
  """Finds recent items from feeds that the user is connected to most."""
  subscriber_id = models.UserKey(user).id()
  subscriber_category = None if any_category else models.CategoryKey(
      category_id, user)

  def GetConnections(connection_version=connection_version,
      subscriber_id=subscriber_id,
      count=400,
      any_category=any_category,
      negative=False):
    if external_connections:
      promise = ndb.Future()
      promise.set_result([])
      return promise
    default_properties = ['publisher_id', 'weight', 'updated_datetime']
    properties = default_properties
    query = models.Connection.query(
        models.Connection.version == connection_version,
        models.Connection.publisher_type == models.SOURCE_TYPE_FEED,
        models.Connection.subscriber_id == subscriber_id)
    if negative:
      query = query.filter(models.Connection.weight < 0).order(
          models.Connection.weight)
    else:
      query = query.filter(
          models.Connection.weight > 0).order(-models.Connection.weight)
    # When we filter by subscriber category we cannot include it in the
    # projection. Otherwise we get this error:
    # BadRequestError: Cannot use projection on a property with an equality
    # filter.
    if any_category:
      properties.append('subscriber_category')
    else:
      query = query.filter(
          models.Connection.subscriber_category == subscriber_category)
    # We do not filter negative connections out by active_days because we do
    # not update "active_days" field for negative connections.
    if connection_active_days and not negative:
      query = query.filter(
          models.Connection.active_days == connection_active_days)
    return query.fetch_async(count, projection=properties)

  def ConnectionsToDict(connections):
    return [ConnectionToDict(c) for c in connections]

  def ConnectionToDict(connection):
    # We do not use connection.KeyComponents() because the connection object is
    # a projection that does not have all the fields that KeyComponents()
    # accesses.
    key_components = models.ConnectionKeyComponents(
        models.SOURCE_TYPE_FEED, connection.publisher_id, None, subscriber_id,
        connection.SubscriberCategoryId() if any_category else
        models.GetCategoryId(subscriber_category), connection_version)
    return {
        'weight': connection.weight,
        'category': (connection.subscriber_category
                     if any_category else subscriber_category),
        'updated_datetime': connection.updated_datetime,
        'publisher_id': connection.publisher_id,
        'key_components': key_components
    }

  connections_future = GetConnections()
  connections = yield connections_future
  if external_connections:
    connections = [
        c for c in external_connections
        if c.publisher_type == models.SOURCE_TYPE_FEED
    ]
  connections = ConnectionsToDict(connections)

  feed_url_to_connection = {}
  feed_urls = []
  for connection in connections:
    # The connection weight is update each time new items are added to the feed.
    # It means that there is no point looking up items for a feed that was
    # updated before the time period we are interested in.
    if connection['updated_datetime'] < since_time:
      continue
    weight = connection['weight']
    feed_url = connection['publisher_id']
    if feed_url not in feed_url_to_connection:
      feed_url_to_connection[feed_url] = connection
      feed_urls.append(feed_url)
    else:
      feed_url_to_connection[feed_url]['weight'] += weight

  feed_url_to_items = yield feeds.GetBulkItemIdsAsync(feed_urls, since_time)

  feed_items = []
  for feed_url, item_list in feed_url_to_items.iteritems():
    feed_items.extend(item_list)
  raise ndb.Return((feed_items, feed_url_to_connection))


def _GetSinceTime(time_period, now):
  if time_period == time_periods.ALL:
    return datetime.min
  return now - time_periods.Get(time_period)['timedelta']
