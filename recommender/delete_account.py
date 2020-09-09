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
"""Handles account deletion logic.

Deletes all objects that are related to a user. This includes:

NDB objects:
- User by user_id
- PageRating by user_id.
- Connection by publisher_id
- Connection by subscriber_id
- PastRecommendation by user_id
- RecommendationSession by user_id
- Category by parent
- export.ExportRatingResult by key

Non NDB objects:
- Memcache: "ri:<user_id>"
- Clear text search indexes:
 - rating_history:<user_id>
 - saved_for_later:<user_id>
"""

from google.appengine.api import memcache
from google.appengine.ext import deferred
from google.appengine.ext import ndb

from recommender import models


def _DeleteUser(user_id):
  models.UserKey(user_id).delete()


def _DeleteAll(keys, continuation_fn, user_id):
  if keys:
    ndb.delete_multi(keys)
    deferred.defer(continuation_fn, user_id)


def _DeletePageRating(user_id):
  _DeleteAll(
      models.PageRating.query(ancestor=models.UserKey(user_id)).fetch(
          keys_only=True, limit=500), _DeletePageRating, user_id)


def _DeleteConnectionPublisher(user_id):
  _DeleteAll(
      models.Connection.query(models.Connection.publisher_id == user_id).fetch(
          keys_only=True, limit=500), _DeleteConnectionPublisher, user_id)


def _DeleteConnectionSubscriber(user_id):
  _DeleteAll(
      models.Connection.query(models.Connection.subscriber_id == user_id).fetch(
          keys_only=True, limit=500), _DeleteConnectionSubscriber, user_id)


def _DeletePastRecommendation(user_id):
  _DeleteAll(
      models.PastRecommendation.query(
          models.PastRecommendation.user_id == user_id).fetch(
              keys_only=True, limit=500), _DeletePastRecommendation, user_id)


def _DeleteRecommendationSession(user_id):
  _DeleteAll(
      models.RecommendationSession.query(
          models.RecommendationSession.user_id == user_id).fetch(
              keys_only=True, limit=500), _DeleteRecommendationSession, user_id)


def _DeleteCategory(user_id):
  _DeleteAll(
      models.Category.query(ancestor=models.UserKey(user_id)).fetch(
          keys_only=True, limit=500), _DeleteCategory, user_id)


def _DeleteCachedRatings(user_id):
  memcache.delete(models.GetUserRatedItemsCacheKey(user_id))


HANDLERS = [
    _DeleteUser,
    _DeletePageRating,
    _DeleteConnectionPublisher,
    _DeleteConnectionSubscriber,
    _DeletePastRecommendation,
    _DeleteRecommendationSession,
    _DeleteCategory,
    _DeleteCachedRatings,
]


def DeleteAccount(user_id):
  for handler in HANDLERS:
    deferred.defer(handler, user_id)
