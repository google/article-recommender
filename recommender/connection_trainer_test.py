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

import unittest

from recommender import connection_trainer


class Recommendation(object):

  def __init__(self, user, rating):
    self.user = user
    self.rating = rating


class InMemoryStore(connection_trainer.ConnectionStore):

  def __init__(self):
    # A map of item to a list of users who recommended it.
    self.recommendations = {}
    # A map of user to a map of publishers users for positive votes of the
    # publisher.
    # How much do I trust positive votes of the publisher.
    self.positive_connections = {}
    # Same but for negative votes of the publisher. Ie, how much do I trust
    # negative votes of the publisher.
    self.negative_connections = {}

  def GetWeight(self, subscriber, publisher, positive):
    connections = (
        self.positive_connections if positive else self.negative_connections)
    return connections.get(subscriber, {}).get(publisher, 0)

  def SetWeight(self,
                subscriber,
                publisher,
                positive,
                weight,
                shared_item=None,
                publisher_voted=False):
    connections = (
        self.positive_connections if positive else self.negative_connections)
    connections.setdefault(subscriber, {})[publisher] = weight

  def GetRecommendations(self, item, user, user_rating):
    return [
        connection_trainer.Rating(
            rating=r.rating,
            user=r.user,
            weight=self.GetWeight(user, r.user, r.rating > 0),
            num_ratings_ago=1)
        for r in self.recommendations.get(item, [])
        if r.user != user
    ]

  def GetSubscribers(self, user, positive=True):
    connections_set = (
        self.positive_connections if positive else self.negative_connections)
    result = []
    for subscriber, connections in connections_set.iteritems():
      for publisher, weight in connections.iteritems():
        if publisher == user:
          result.append(connection_trainer.Connection(subscriber, weight))
    return result


class InMemoryTrainer(connection_trainer.Trainer):

  def __init__(self, learning_rate, ignore_learning_rate):
    connection_trainer.Trainer.__init__(self, InMemoryStore(), learning_rate,
                                        ignore_learning_rate)

  def AddRecommendation(self, user, item, rating):
    self.connection_store.recommendations.setdefault(item, []).append(
        Recommendation(user, rating))
    self.RecommendationAdded(user, item, rating)

  def GetWeight(self, subscriber, publisher, positive):
    return self.connection_store.GetWeight(subscriber, publisher, positive)


class AbstractConnectionTrainerTest(object):

  def setUp(self):
    """This method will be run before each of the test methods in the class."""
    pass

  def CreateTrainer(self):
    return None

  def testSimple(self):
    trainer = self.CreateTrainer()
    trainer.AddRecommendation("user1", "item1", 1)
    trainer.AddRecommendation("user2", "item1", 1)
    self.assertGreater(trainer.GetWeight("user2", "user1", True), 0)
    self.assertEqual(trainer.GetWeight("user1", "user2", True), 0)

    # User3 recommends item1 and becomes equally connected to user1 and user2.
    trainer.AddRecommendation("user3", "item1", 1)
    self.assertGreater(trainer.GetWeight("user3", "user1", True), 0)
    self.assertEqual(
        trainer.GetWeight("user3", "user1", True),
        trainer.GetWeight("user3", "user2", True))

    # User1 adds something new and user3 is now less connected to them.
    trainer.AddRecommendation("user1", "item2", 1)
    self.assertLess(
        trainer.GetWeight("user3", "user1", True),
        trainer.GetWeight("user3", "user2", True))

    # But then user3 recommends the same item and becomes more connected to
    # user1 than to user2.
    trainer.AddRecommendation("user3", "item2", 1)
    self.assertGreater(
        trainer.GetWeight("user3", "user1", True),
        trainer.GetWeight("user3", "user2", True))

  def testNegative(self):
    trainer = self.CreateTrainer()
    trainer.AddRecommendation("user1", "item1", 1)
    trainer.AddRecommendation("user2", "item1", -1)
    self.assertLess(trainer.GetWeight("user2", "user1", True), 0)

  def testNegativeOnNegative(self):
    # When I downvote something you downvoted then I trust your negative votes.
    trainer = self.CreateTrainer()
    trainer.AddRecommendation("user1", "item1", -1)
    trainer.AddRecommendation("user2", "item1", -1)
    self.assertGreater(trainer.GetWeight("user2", "user1", False), 0)
    # My positive connection does not change.
    self.assertEqual(trainer.GetWeight("user2", "user1", True), 0)

  def testMorePopularItemMeansWeakerConnection(self):
    trainer = self.CreateTrainer()
    trainer.AddRecommendation("user1", "item1", 1)
    trainer.AddRecommendation("user2", "item1", 1)
    trainer.AddRecommendation("user4", "item1", 1)

    trainer.AddRecommendation("user3", "item2", 1)
    trainer.AddRecommendation("user4", "item2", 1)

    self.assertGreater(
        trainer.GetWeight("user4", "user3", True),
        trainer.GetWeight("user4", "user1", True))

  def testDecayNeverReachesZero(self):
    trainer = self.CreateTrainer()
    trainer.AddRecommendation("user1", "item1", 1)
    trainer.AddRecommendation("user2", "item1", 1)
    trainer.DecayConnectionWeightToPublisher("user1", num_items=10000)
    self.assertGreater(trainer.GetWeight("user2", "user1", True), 0)


class ConnectionTrainerTest(AbstractConnectionTrainerTest, unittest.TestCase):

  def CreateTrainer(self):
    return InMemoryTrainer(0.01, 0.001)
