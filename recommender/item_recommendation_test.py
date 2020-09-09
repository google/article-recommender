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
"""Tests user rating logic."""

from datetime import datetime
import os

from google.appengine.ext import deferred
from google.appengine.ext import testbed

import unittest
from recommender import feeds
from recommender import item_recommendation
from recommender import items
from recommender import models
from recommender import ratings
from recommender import recommendations
from recommender import time_periods


class AbstractRecommendationsTest(object):

  def setUp(self):
    self.testbed = testbed.Testbed()
    self.testbed.activate()
    self.testbed.init_datastore_v3_stub()
    self.testbed.init_memcache_stub()
    self.testbed.init_search_stub()
    self.testbed.init_taskqueue_stub()
    self.testbed.init_urlfetch_stub()
    self.testbed.init_taskqueue_stub(
        root_path=os.path.dirname(os.path.dirname(__file__)))
    self.taskqueue = self.testbed.get_stub(testbed.TASKQUEUE_SERVICE_NAME)

    # The main user we test recommendations for.
    self.user = FakeUser('user')

  def tearDown(self):
    self.testbed.deactivate()

  def assertLen(self, container, expected_length):
    self.assertEqual(len(container), expected_length)

  def GetConnectionVersion(self):
    return None

  def _RunAllTasks(self):
    """Dequeue and run tasks until there's no more task."""
    while True:
      tasks = self.taskqueue.get_filtered_tasks()
      if not tasks:
        break
      for task in tasks:
        deferred.run(task.payload)
        queue_name = task.headers['X-AppEngine-QueueName']
        task_name = task.headers['X-AppEngine-TaskName']
        # Delete from all task queues.
        self.taskqueue.DeleteTask(queue_name, task_name)
        self.taskqueue.DeleteTask('default', task_name)
        self.taskqueue.DeleteTask('recommendation-updates', task_name)

  def _AddRating(self,
                 user,
                 url,
                 rating,
                 source='fake_source',
                 category_id=None):
    recommendations.AddRating(user, url, rating, source, category_id)
    self._RunAllTasks()

  def _AddFeed(self, feed_url, item_urls):
    feeds.AddFeed(feed_url, 'unused feed title')

    for item_url in item_urls:
      self._AddFeedItem(feed_url, item_url)

  def _AddFeedItem(self, feed_url, item_url):
    feeds.FeedItem(
        url=item_url,
        item_id=items.UrlToItemId(item_url),
        feed_url=feed_url,
        published_date=datetime.now()).put()

  def _GetRecommendations(self,
                          user,
                          time_period=time_periods.DAY,
                          category_id=None,
                          any_category=False,
                          include_popular=False,
                          limit=20,
                          connection_version=None,
                          decay_rate=1,
                          save_past_recommendations=False,
                          exclude_past_recommendations=False,
                          exclude_urls=frozenset()):
    if connection_version is None:
      connection_version = self.GetConnectionVersion()
    return item_recommendation.RecommendationsOnDemand(
        user,
        time_period,
        category_id,
        any_category,
        include_popular,
        limit,
        connection_version,
        decay_rate=decay_rate,
        exclude_urls=exclude_urls,
        save_past_recommendations=save_past_recommendations,
        exclude_past_recommendations=exclude_past_recommendations)

  def testAddRating(self):
    user1 = FakeUser('1')
    self._AddRating(user1, 'http://b.test', ratings.POSITIVE)
    history = models.GetRatingHistory(user1, None, True, True, 0, 20)
    self.assertLen(history, 1)

    self._AddRating(user1, 'http://a.test', ratings.POSITIVE)
    history = models.GetRatingHistory(user1, None, True, True, 0, 20)
    self.assertLen(history, 2)
    self.assertEqual('http://a.test', history[0].url)
    self.assertEqual('http://b.test', history[1].url)

  def testRecommendations(self):
    user1 = FakeUser('1')
    user2 = FakeUser('2')
    self._AddRating(user1, 'http://a.test', ratings.POSITIVE)
    self._AddRating(user2, 'http://a.test', ratings.POSITIVE)

    result = self._GetRecommendations(user2, any_category=True)
    self.assertLen(result, 0)

    self._AddRating(user1, 'http://b.test', ratings.POSITIVE)

    result = self._GetRecommendations(user2, any_category=True)
    self.assertLen(result, 1)
    self.assertEqual('http://b.test', result[0].destination_url)

    popular = models.PopularPages(user2, time_periods.DAY, 0, 20)
    self.assertLen(popular, 2)
    self.assertEqual('http://a.test', popular[0].url)
    self.assertEqual(2, popular[0].positive_ratings)
    self.assertEqual('http://b.test', popular[1].url)
    self.assertEqual(1, popular[1].positive_ratings)

  def testPastRecommendations(self):
    user1 = FakeUser('1')
    user2 = FakeUser('2')
    self._AddRating(user1, 'http://a.test', ratings.POSITIVE)
    self._AddRating(user1, 'http://b.test', ratings.POSITIVE)
    self._AddRating(user2, 'http://a.test', ratings.POSITIVE)

    result = self._GetRecommendations(user2, any_category=True)
    self.assertLen(result, 1)
    self.assertEqual('http://b.test', result[0].destination_url)

  def testChangeCategory(self):
    user1 = FakeUser('1')
    user2 = FakeUser('2')
    self._AddRating(user1, 'http://a.test', ratings.POSITIVE)
    self._AddRating(user1, 'http://b.test', ratings.POSITIVE)
    self._AddRating(user2, 'http://a.test', ratings.POSITIVE)

    result = self._GetRecommendations(user2)
    self.assertLen(result, 1)
    self.assertEqual('http://b.test', result[0].destination_url)
    old_weight = result[0].weight

    self._AddRating(
        user1,
        'http://c.test',
        ratings.POSITIVE,
        category_id=models.AddCategory(user1, 'news').id())
    # Change it back to default category.
    recommendations.SetPageCategory(user1, 'http://c.test', None)
    self._RunAllTasks()

    result = self._GetRecommendations(user2)
    self.assertLen(result, 2)
    self.assertEqual(result[0].weight, result[1].weight)
    self.assertLess(result[0].weight, old_weight)

  def testPopularPagesNoDoubleCounting(self):
    user1 = FakeUser('1')
    self._AddRating(user1, 'http://a.test', ratings.POSITIVE)
    self._AddRating(user1, 'http://a.test', ratings.POSITIVE)
    self._AddRating(user1, 'http://a.test', ratings.POSITIVE)

    popular = models.PopularPages(user1, time_periods.DAY, 0, 20)
    self.assertLen(popular, 1)
    self.assertEqual('http://a.test', popular[0].url)
    self.assertEqual(1, popular[0].positive_ratings)

  def testRecommendationWeightDecays(self):
    user1 = FakeUser('1')
    user2 = FakeUser('2')
    user3 = FakeUser('3')
    # All users recommend the same page so the user 3 should be connected
    # equally strongly to user1 and user 2
    self._AddRating(user1, 'http://a.test', ratings.POSITIVE)
    self._AddRating(user2, 'http://a.test', ratings.POSITIVE)
    self._AddRating(user3, 'http://a.test', ratings.POSITIVE)

    self._AddRating(user1, 'http://b.test', ratings.POSITIVE)
    self._AddRating(user2, 'http://c.test', ratings.POSITIVE)

    result = self._GetRecommendations(user3, any_category=True)
    self.assertLen(result, 2)
    self.assertEqual(result[0].weight, result[1].weight)

    self._AddRating(user1, 'http://bb.test', ratings.POSITIVE)

    result = self._GetRecommendations(user3, any_category=True)
    self.assertLen(result, 3)
    # Recommendation of user2 should score higher than the two
    # recommendations of user1.
    self.assertEqual('http://c.test', result[0].destination_url)

  # Neutral ratings are only used to hide an item from the user and it should
  # not affect the user's weight to sources that recommended it.
  def testNeutralRating(self):
    user1 = FakeUser('1')
    user2 = FakeUser('2')
    self._AddRating(user1, 'http://a.test', ratings.POSITIVE)
    # user2 connects to user1.
    self._AddRating(user2, 'http://a.test', ratings.POSITIVE)

    # user1 recommends two items that will be recommended to user2.
    self._AddRating(user1, 'http://b.test', ratings.POSITIVE)
    self._AddRating(user1, 'http://c.test', ratings.POSITIVE)

    result = self._GetRecommendations(
        user2, any_category=True, save_past_recommendations=False)
    self.assertLen(result, 2)
    # c.test goes first because it is more recent.
    self.assertEqual('http://c.test', result[0].destination_url)
    self.assertEqual('http://b.test', result[1].destination_url)
    self.assertEqual(result[0].weight, result[1].weight)

    score_before_neutral_rating = result[0].weight

    self._AddRating(user2, 'http://b.test', ratings.NEUTRAL)

    result = self._GetRecommendations(
        user2, any_category=True, save_past_recommendations=False)
    self.assertLen(result, 1)
    self.assertEqual('http://c.test', result[0].destination_url)
    self.assertEqual(score_before_neutral_rating, result[0].weight)

  def testNegativeRating(self):
    user1 = FakeUser('1')
    user2 = FakeUser('2')
    self._AddRating(user1, 'http://a.test', ratings.POSITIVE)
    self._AddRating(user1, 'http://a1.test', ratings.POSITIVE)
    # user2 connects to user1.
    self._AddRating(user2, 'http://a.test', ratings.POSITIVE)
    self._AddRating(user2, 'http://a1.test', ratings.POSITIVE)

    # user1 recommends two items that will be recommended to user2.
    self._AddRating(user1, 'http://b.test', ratings.POSITIVE)
    self._AddRating(user1, 'http://c.test', ratings.POSITIVE)

    result = self._GetRecommendations(user2, any_category=True)
    self.assertLen(result, 2)
    # c.test goes first because it is more recent.
    self.assertEqual('http://c.test', result[0].destination_url)
    self.assertEqual('http://b.test', result[1].destination_url)
    self.assertEqual(result[0].weight, result[1].weight)

    score_before_negative_rating = result[0].weight

    self._AddRating(user2, 'http://b.test', ratings.NEGATIVE)

    result = self._GetRecommendations(user2, any_category=True)
    self.assertLen(result, 1)
    self.assertEqual('http://c.test', result[0].destination_url)
    self.assertLess(result[0].weight, score_before_negative_rating)


  def testNoDupes(self):
    user1 = FakeUser('1')
    user2 = FakeUser('2')
    self._AddRating(user1, 'http://a.test', ratings.POSITIVE)
    self._AddRating(user1, 'http://c.test', ratings.POSITIVE)

    self._AddRating(user2, 'http://b.test', ratings.POSITIVE)
    self._AddRating(user2, 'http://c.test', ratings.POSITIVE)

    user3 = FakeUser('3')

    # User 3 gets connected to user 1 through category c1 and to user 2 through
    # category c2.
    self._AddRating(
        user3,
        'http://a.test',
        ratings.POSITIVE,
        category_id=models.AddCategory(user3, 'c1').id())
    self._AddRating(
        user3,
        'http://b.test',
        ratings.POSITIVE,
        category_id=models.AddCategory(user3, 'c2').id())

    # c.test should be recommended only once, instead of being recommended for
    # each category: c1 and c2.
    self.assertLen(self._GetRecommendations(user3, any_category=True), 1)

  def testExcludeUrlsFromUsers(self):
    user1 = FakeUser('1')
    user2 = FakeUser('2')
    self._AddRating(user1, 'http://a.test', ratings.POSITIVE)
    self._AddRating(user1, 'http://b.test', ratings.POSITIVE)
    self._AddRating(user1, 'http://c.test', ratings.POSITIVE)

    self._AddRating(user2, 'http://a.test', ratings.POSITIVE)

    # b.test and c.test are recommended.
    self.assertLen(self._GetRecommendations(user2, any_category=True), 2)

    # Only c.test should be recommended because we exclude b.test.
    self.assertEqual(
        1,
        len(
            self._GetRecommendations(
                user2, any_category=True, exclude_urls=['http://b.test'])))

  def testExcludeUrlsFromFeeds(self):
    user1 = FakeUser('1')
    self._AddFeed('http://example.test/feed',
                  ['http://a.test', 'http://b.test', 'http://c.test'])

    self._AddRating(user1, 'http://a.test', ratings.POSITIVE)

    # b.test and c.test are recommended.
    self.assertLen(self._GetRecommendations(user1), 2)

    # Only c.test should be recommended because we exclude b.test.
    self.assertEqual(
        1, len(self._GetRecommendations(user1, exclude_urls=['http://b.test'])))

  def testNegativeUserConnection(self):
    user1 = FakeUser('1')
    user2 = FakeUser('2')

    self._AddRating(user1, 'http://a.test', ratings.NEGATIVE)
    self._AddRating(user1, 'http://b.test', ratings.POSITIVE)
    self._AddRating(user1, 'http://c.test', ratings.POSITIVE)

    # Both users didn't like item 'a'. This should make user 2 trust negative
    # ratings of user 1, but it does not make them trust positive ratings.
    self._AddRating(user2, 'http://a.test', ratings.NEGATIVE)

    self.assertLen(self._GetRecommendations(user2, any_category=True), 0)

  def testUserConnectionDecays(self):
    user1 = FakeUser('1')

    # Create a connection to user1.
    self._AddRating(user1, 'item1', ratings.POSITIVE)
    self._AddRating(self.user, 'item1', ratings.POSITIVE)

    # User1 recommends two items.
    self._AddRating(user1, 'less_recent_item', ratings.POSITIVE)
    self._AddRating(user1, 'most_recent_item', ratings.POSITIVE)

    result = self._GetRecommendations(self.user, decay_rate=0.9)
    self.assertLen(result, 2)
    self.assertEqual(result[0].destination_url, 'most_recent_item')
    self.assertEqual(result[1].destination_url, 'less_recent_item')
    # The less recent item should have a smaller weight because it should be
    # multiplied by the decay_rate.
    self.assertGreater(result[0].weight, result[1].weight)

  def CreateGoodCritic(self):
    good_critic = FakeUser('good_critic')
    # The user downvoted the item that the good critic downvoted.
    self._AddRating(good_critic, 'shared item 8234', ratings.NEGATIVE)
    self._AddRating(self.user, 'shared item 8234', ratings.NEGATIVE)
    return good_critic

  def CreateBadCritic(self):
    # The user upvoted the item that the bad critic downvoted.
    bad_critic = FakeUser('bad_critic')
    self._AddRating(bad_critic, 'bad critic item', ratings.NEGATIVE)
    self._AddRating(self.user, 'bad critic item', ratings.POSITIVE)
    return bad_critic

  def CreateGoodCurator(self):
    # The user upvoted the item that the good curator upvoted.
    good_curator = FakeUser('good_curator')
    self._AddRating(good_curator, 'good curator item', ratings.POSITIVE)
    self._AddRating(self.user, 'good curator item', ratings.POSITIVE)
    return good_curator

  def CreateWeakCurator(self):
    # The user upvoted the item that the weak curator upvoted, but the weak
    # curator voted on a lot of other stuff that we already saw.
    weak_curator = FakeUser('weak')
    self._AddRating(weak_curator, 'weak item', ratings.POSITIVE)
    seen_urls = ['ignored1', 'ignored2', 'ignored3']
    for url in seen_urls:
      self._AddRating(weak_curator, url, ratings.POSITIVE)
      self._AddRating(self.user, url, ratings.NEUTRAL)
    self._AddRating(self.user, 'weak item', ratings.POSITIVE)
    return weak_curator

  def CreateBadCurator(self):
    # The user downvoted the item that the bad curator upvoted.
    bad_curator = FakeUser('bad_curator')
    self._AddRating(bad_curator, 'http://e.test', ratings.POSITIVE)
    self._AddRating(self.user, 'http://e.test', ratings.NEGATIVE)
    return bad_curator

  def testGoodCriticDownvoteStrongerThanWeakCuratorUpvote(self):
    good_critic = self.CreateGoodCritic()
    weak_curator = self.CreateWeakCurator()

    # At the start there are no interesting recommendations.
    self.assertLen(self._GetRecommendations(self.user), 0)

    self._AddRating(weak_curator, 'not_good', ratings.POSITIVE)
    self.assertLen(self._GetRecommendations(self.user), 1)
    self._AddRating(good_critic, 'not_good', ratings.NEGATIVE)

    # A downvote of the good critic counts more than an upvote of a weak
    # curator.
    self.assertLen(self._GetRecommendations(self.user), 0)

  def testGoodCuratorDownvoteDoesNotCount(self):
    good_curator = self.CreateGoodCurator()
    weak_curator = self.CreateWeakCurator()

    # At the start there are no interesting recommendations.
    self.assertLen(self._GetRecommendations(self.user), 0)

    # A downvote of the good curator does not count.
    self._AddRating(weak_curator, 'weak_good', ratings.POSITIVE)
    self.assertLen(self._GetRecommendations(self.user), 1)
    self._AddRating(good_curator, 'weak_good', ratings.NEGATIVE)
    self.assertLen(self._GetRecommendations(self.user), 1)

  def testGoodCuratorUpvoteStrongerThanWeakCuratorUpvote(self):
    good_curator = self.CreateGoodCurator()
    weak_curator = self.CreateWeakCurator()

    # At the start there are no interesting recommendations.
    self.assertLen(self._GetRecommendations(self.user), 0)

    # An upvote of the good curator counts more than an upvote of a weak
    # curator.
    self._AddRating(good_curator, 'good', ratings.POSITIVE)
    self._AddRating(weak_curator, 'weak_good2', ratings.POSITIVE)

    result = self._GetRecommendations(self.user)
    self.assertLen(result, 2)
    self.assertEqual(result[0].destination_url, 'good')
    self.assertEqual(result[1].destination_url, 'weak_good2')

  def testWeakCuratorUpvoteStrongerThanBadCriticDownvote(self):
    weak_curator = self.CreateWeakCurator()
    bad_critic = self.CreateBadCritic()

    # At the start there are no interesting recommendations.
    self.assertLen(self._GetRecommendations(self.user), 0)

    # An upvote of the weak critic is not affected by the bad curator.
    self._AddRating(weak_curator, 'weak_good', ratings.POSITIVE)
    self._AddRating(bad_critic, 'weak_good', ratings.NEGATIVE)

    result = self._GetRecommendations(self.user)
    self.assertLen(result, 1)
    self.assertEqual(result[0].destination_url, 'weak_good')


class FakeUser(object):

  def __init__(self, user_id):
    self.id = user_id

  # pylint: disable=invalid-name
  def nickname(self):
    return self.id

  # pylint: disable=invalid-name
  def user_id(self):
    return self.id


class RecommendationsTest(AbstractRecommendationsTest, unittest.TestCase):

  def GetConnectionVersion(self):
    # Makes all recommendations to use connections created by the trainer that
    # uses logistic regression to update connections.
    return models.LOGISTIC_REGRESSION_CONNECTION

