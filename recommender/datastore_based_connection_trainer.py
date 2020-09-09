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
"""Adapts the abstract connection trainer logic to objects stored in Datastore."""
from datetime import datetime
from datetime import timedelta

from recommender import connection_trainer
from recommender import models
from recommender import ratings

LEARNING_RATE = 0.1
IGNORE_LEARNING_RATE = 0.1
MAX_TOP_SOURCES = 10

MINIMAL_CONNECTION_WEIGHT_TO_BE_SUBSCRIBED = 0

POSITIVE = connection_trainer.POSITIVE
NEGATIVE = connection_trainer.NEGATIVE


class ConnectionStore(connection_trainer.ConnectionStore):

  def __init__(self, connection_version=models.LOGISTIC_REGRESSION_CONNECTION):
    self.connection_version = connection_version

  def GetConnectionKey(self, subscriber, publisher, positive=True):
    return models.ConnectionKey(
        publisher.source_id,
        publisher.category_id,
        subscriber.source_id,
        subscriber.category_id,
        self.connection_version,
        positive=positive)

  def GetRecommendations(self, url, subscriber, subscriber_rating):
    result = []
    # We do not want to trust the feed specified by the url's meta tags if the
    # user downvoted the url. That's because the specified feed url may not
    # deserve to be punished (e.g., the url is malicious and tries to lower the
    # feeds reputation).
    include_source_feed = (subscriber_rating == ratings.POSITIVE)
    for rating in models.GetUnifiedRatings(
        url, include_source_feed=include_source_feed):
      source = models.Source(rating['type'], rating['publisher_id'],
                             rating['publisher_category_id'])
      if source == subscriber:
        # Any following recommendations are the ones made after the subscriber
        # recommended it and are not interesting to the subscriber.
        break
      num_ratings_ago = 0
      if (source.source_type == models.SOURCE_TYPE_FEED and
          source.source_id == url):
        # When the user recommends an RSS feed url then we do not want to
        # penalize it for every item that feed published from the beginning of
        # time. A freshly recommended feed should start at the same initial
        # connection weight no matter how many items the feed has published in
        # the past.
        num_ratings_ago = 0
      else:
        num_ratings_ago = source.GetNumRatingsSinceDate(rating['date'])
      # The number includes this rating so we decrease it by one.
      if num_ratings_ago > 0:
        num_ratings_ago -= 1
      result.append(
          connection_trainer.Rating(
              rating=rating['rating'],
              user=source,
              weight=self.GetWeight(subscriber, source, rating['rating'] > 0),
              num_ratings_ago=num_ratings_ago))
    return result

  def GetWeight(self, subscriber, publisher, positive):
    connection = self.GetConnectionKey(
        subscriber, publisher, positive=positive).get()
    if connection:
      return connection.weight
    return 0

  def SetWeight(self,
                subscriber,
                publisher,
                positive,
                weight,
                shared_item=None,
                publisher_voted=False):
    # We are not making recommendations to feeds so we don't care updating their
    # connection weights to other sources.
    if subscriber.source_type == models.SOURCE_TYPE_FEED:
      return
    key = self.GetConnectionKey(subscriber, publisher, positive=positive)
    connection = key.get()
    if connection is None:
      connection = models.Connection(
          key=key,
          publisher_type=publisher.source_type,
          publisher_id=publisher.source_id,
          publisher_category=models.CategoryKey(publisher.category_id,
                                                publisher.source_id),
          subscriber_id=subscriber.source_id,
          subscriber_category=models.CategoryKey(subscriber.category_id,
                                                 subscriber.source_id),
          version=self.connection_version,
          positive=positive,
          weight=weight,
          num_shared_items=0,
          top_sources=[],
          active_datetime=publisher.GetLastRatingDatetime(),
          # Make the subscription start one day before now.
          subscription_start_datetime=datetime.now() - timedelta(days=1))
      if connection.active_datetime:
        inactive_duration = datetime.now() - connection.active_datetime
        connection.active_days = [
            days for days in models.CONNECTION_ALL_ACTIVE_DAYS
            if inactive_duration < timedelta(days=days)
        ]

    # When publisher_voted == True it means that the weight is being decayed as
    # new items are being recommended by the publisher. In the case of a feed,
    # we don't want to decay connection weights for people who have just
    # subscribed because it is likely that the "new" items are actually part of
    # the initial feed import into the system.
    # But we still do want the active_days and active_datetime to be updated -
    # that's why we don't just return from this function.
    if (publisher_voted and
        connection.publisher_type == models.SOURCE_TYPE_FEED and
        connection.subscription_start_datetime >
        datetime.now() - timedelta(days=1, hours=1)):
      # We don't want to change the weight in this case.
      pass
    else:
      connection.weight = weight
    if publisher_voted:
      # The publisher recommended a new item - mark this connection as active
      # for all possible time periods.
      connection.active_days = models.CONNECTION_ALL_ACTIVE_DAYS
      connection.active_datetime = datetime.now()
    if (subscriber.source_type == models.SOURCE_TYPE_USER and
        shared_item is not None):
      connection.num_shared_items += 1
      connection.top_sources.insert(
          0, models.ConnectionSourcePage(url=shared_item, weight=1))
      if len(connection.top_sources) > MAX_TOP_SOURCES:
        connection.top_sources = connection.top_sources[:MAX_TOP_SOURCES]
    connection.put()

  def GetSubscribers(self, publisher, positive=True):
    publisher_category = models.CategoryKey(publisher.category_id,
                                            publisher.source_id)
    return [
        connection_trainer.Connection(
            models.Source(models.SOURCE_TYPE_USER, c.subscriber_id,
                          c.SubscriberCategoryId()), c.weight)
        for c in models.Connection.query(
            models.Connection.publisher_id == publisher.source_id,
            models.Connection.publisher_category == publisher_category,
            models.Connection.version == self.connection_version,
            models.Connection.positive == positive)
    ]

  def CanSubscribe(self, user):
    # Only users can subscribe to other user/feeds.
    return user.source_type == models.SOURCE_TYPE_USER


def CreateTrainer(connection_version=models.LOGISTIC_REGRESSION_CONNECTION):
  return connection_trainer.Trainer(
      ConnectionStore(connection_version), LEARNING_RATE, IGNORE_LEARNING_RATE)
