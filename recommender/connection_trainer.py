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
"""Finds user-to-user connection weights using online logistic regression."""
from abc import ABCMeta
from abc import abstractmethod
import math

from recommender import ratings

# Prediction that corresponds to log-odds weight of 0.
NEUTRAL_PREDICTION = 0.5

POSITIVE = True
NEGATIVE = False


def Sigmoid(z):
  return 1 / (1 + math.exp(-z))


class Rating(object):

  def __init__(self, rating, user, weight, num_ratings_ago):
    self.rating = rating
    self.user = user
    self.weight = weight
    # How many other recommendations did this user make after recommending this
    # item.
    # This is necessary to decay the amount of credit the user gets.
    self.num_ratings_ago = num_ratings_ago


class Connection(object):

  def __init__(self, user, weight):
    self.user = user
    self.weight = weight


class ConnectionStore(object):
  """Interface for accessing/updating connections."""
  __metaclass__ = ABCMeta

  @abstractmethod
  def GetRecommendations(self, item, user, user_rating):
    pass

  @abstractmethod
  def GetWeight(self, subscriber, publisher, positive):
    pass

  @abstractmethod
  def SetWeight(self,
                subscriber,
                publisher,
                positive,
                weight,
                shared_item=None,
                publisher_voted=False,
                reverted=False):
    pass

  @abstractmethod
  def GetSubscribers(self, publisher, positive=True):
    pass

  def CanSubscribe(self, user):
    del user  # Unused in the default implementation.
    return True


class Trainer(object):
  """Updates user-to-user connection weights.

  The updates are made online as users add recommendations.
  """

  def __init__(self,
               connection_store,
               learning_rate,
               ignore_learning_rate,
               default_contribution=0.1):
    self.connection_store = connection_store
    self.learning_rate = learning_rate
    self.ignore_learning_rate = ignore_learning_rate
    self.default_contribution = default_contribution

  def GetDecayedWeight(self, initial_weight, num_items):
    weight = initial_weight
    for _ in range(num_items):
      weight -= self.ignore_learning_rate * (
          Sigmoid(weight) - NEUTRAL_PREDICTION)
    return weight

  def DecayConnectionWeightToPublisher(self, publisher, num_items=1):
    """Decay the weight of connections to a publisher.

    We batch updates (num_items > 1) when we get several new items from an RSS
    feed. This allows us to avoid doing updates for every single new item.

    Args:
      publisher: The publisher that recommended the items.
      num_items: The number of items the publisher recommended.
    """
    for connection in self.connection_store.GetSubscribers(
        publisher, positive=POSITIVE):
      # We do not decay negative weights because getting out of the negative
      # zone should be earned by posting useful content, not just a ton of
      # content that the user ignores.
      if connection.weight <= 0:
        continue
      # This could be calculated using the expected prediction.
      # w = w - a * (hypothesis(subscriber, item) - 0.5) * rating
      # But we simplify.
      weight = self.GetDecayedWeight(connection.weight, num_items)

      self.connection_store.SetWeight(
          connection.user, publisher, POSITIVE, weight, publisher_voted=True)

  def RecommendationAdded(self, user, item, rating):
    """Updates connection weights between users.

    Args:
      user: Who recommended.
      item: What was recommended.
      rating: {1, 0, -1} - positive, neutral or negative - the rating the user
        gave to the item.
    """
    if rating == ratings.NEUTRAL:
      # A neutral rating has no effect on connections.
      return
    # Update weights of user A to everyone who recommended this before.
    if self.connection_store.CanSubscribe(user):
      past_recommendations = self.connection_store.GetRecommendations(
          item, user, rating)
      if past_recommendations:
        label = 1 if rating == ratings.POSITIVE else 0
        log_odds = 0
        sum_of_weights = len(past_recommendations) * self.default_contribution
        for r in past_recommendations:
          log_odds += r.weight * r.rating
          sum_of_weights += abs(r.weight)
        hypothesis = Sigmoid(log_odds)
        for r in past_recommendations:
          shared_item = None
          if r.rating > 0 and rating > 0:
            shared_item = item
          power = ((self.default_contribution + abs(r.weight)) *
                   self.learning_rate / sum_of_weights)
          delta = -power * (hypothesis - label) * r.rating
          # delta = power * rating * r.rating
          # If user B recommended this 50 recommendations ago then we should not
          # connect user A to them as strongly as to user C who recommended this
          # only 2 recommendations ago.
          #
          # Otherwise a user (user T) can game the system and gain more
          # attention than they deserve:
          # 1) User T upvotes 1000 most popular items at once.
          # 2) When user A just happens to upvote 10 of those items in a row
          #    they get connected to user T as if the user T only upvoted those
          #    10 items and nothing else (ie, user T is a perfect predictor for
          #    user A).
          #
          # So the amount by how much we connect user A to user T should be
          # similar to when user A upvotes each item right after user T upvotes
          # it. So all the following non shared items cause the connection to be
          # decay.
          # We assume that the delta will be contributing to the linear part of
          # the sigmoid function so we apply the ignore directly to the delta in
          # the log odds space.
          delta *= (1 - self.ignore_learning_rate)**r.num_ratings_ago
          self.connection_store.SetWeight(
              user,
              r.user,
              POSITIVE if r.rating > 0 else NEGATIVE,
              r.weight + delta,
              shared_item=shared_item)

    # Decay the connection weights slightly where this user is a publisher.
    # We don't penalize negative ratings.
    if rating == ratings.POSITIVE:
      self.DecayConnectionWeightToPublisher(user)
