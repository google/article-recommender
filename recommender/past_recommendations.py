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
"""Saves past recommendations and caches the item ids of past recommendations."""

from datetime import datetime
from datetime import timedelta

from google.appengine.api import memcache
from google.appengine.ext import deferred
from google.appengine.ext import ndb

from recommender import config
from recommender import items
from recommender import models
from recommender import time_periods

TIME_TO_COMMIT_PAST_RECOMMENDATIONS = timedelta(
    minutes=20 if config.IsDev() else 60)


def SavePastRecommendations(user_id, time_period, recommendations):
  time_period_numeric = time_periods.Get(time_period)['numeric']
  user_key = models.UserKey(user_id)
  save_time = datetime.now()
  past_recommendations = [
      models.PastRecommendation(
          key=ndb.Key(
              models.PastRecommendation,
              str(time_period_numeric) + ':' + r.destination_url,
              parent=user_key),
          user_id=user_id,
          item_id=r.item_id or items.UrlToItemId(r.destination_url),
          url=r.destination_url,
          weight=r.weight,
          time_period_numeric=time_period_numeric,
          serialized_recommendation=r.Serialize(),
          committed=False,
          date=save_time,
          index_within_page=i) for i, r in enumerate(recommendations)
  ]
  ndb.put_multi(past_recommendations)
  # Commit newly saved recommendations after 30 minutes of inactivity.
  deferred.defer(
      _CommitPastRecommendations,
      user_id,
      time_period_numeric,
      save_time,
      _countdown=TIME_TO_COMMIT_PAST_RECOMMENDATIONS.total_seconds())


# Changes recently saved past recommendations to "committed" state.
# Only committed past recommendations are shown in the UI and are excluded
# when calculating fresh recommendations.
def _CommitPastRecommendations(user_id, time_period_numeric, save_time):
  most_recently_saved = models.PastRecommendation.query(
      models.PastRecommendation.user_id == user_id,
      models.PastRecommendation.time_period_numeric == time_period_numeric,
      models.PastRecommendation.committed == False).order(
          -models.PastRecommendation.date).get()
  # If there was another save then we don't need to commit anything now. It will
  # be committed by the deferred task that was scheduled for the most recent
  # save.
  if most_recently_saved and most_recently_saved.date > save_time:
    return
  most_recently_committed = models.PastRecommendation.query(
      models.PastRecommendation.user_id == user_id,
      models.PastRecommendation.time_period_numeric == time_period_numeric,
      models.PastRecommendation.committed == True).order(
          -models.PastRecommendation.date).get()
  next_session_number = 0
  if most_recently_committed:
    next_session_number = most_recently_committed.session_number + 1
  uncommitted = models.PastRecommendation.query(
      models.PastRecommendation.user_id == user_id,
      models.PastRecommendation.time_period_numeric == time_period_numeric,
      models.PastRecommendation.committed == False).order(
          -models.PastRecommendation.date).fetch()

  if len(uncommitted) == 0:
    return
  uncommitted.sort(key=lambda v: v.weight)
  min_weight = uncommitted[0].weight
  max_weight = uncommitted[-1].weight
  median_weight = uncommitted[int(len(uncommitted) / 2)].weight
  models.RecommendationSession(
      user_id=user_id,
      time_period_numeric=time_period_numeric,
      recommendation_count=len(uncommitted),
      median_weight=median_weight,
      min_weight=min_weight,
      max_weight=max_weight).put()
  for r in uncommitted:
    r.committed = True
    r.session_number = next_session_number
  ndb.put_multi(uncommitted)

  # Update the cache that is used to exclude already seen items from
  # recommendations.
  new_item_ids = [r.item_id for r in uncommitted]
  _UpdatePastRecommendationItemIdsCacheAsync(
      user_id, time_periods.TIME_PERIODS[time_period_numeric]['name'],
      new_item_ids).get_result()
  _UpdatePastRecommendationItemIdsCacheAsync(user_id, None,
                                             new_item_ids).get_result()


PAST_RECOMMENDATIONS_LIMIT = 6000


def GetPastRecommendationItemIdsAsync(user_id, time_period):
  return _UpdatePastRecommendationItemIdsCacheAsync(user_id, time_period)


@ndb.tasklet
def _UpdatePastRecommendationItemIdsCacheAsync(user_id,
                                               time_period,
                                               new_item_ids=None):
  client = memcache.Client()
  name = 'prid:' + str(user_id)
  if time_period:
    name += ':' + time_period
  cached = yield client.get_multi_async([name])
  if cached:
    item_ids = cached[name]
  else:
    query = models.PastRecommendation.query(
        models.PastRecommendation.user_id == user_id,
        models.PastRecommendation.committed == True,
        projection=['item_id'])
    if time_period:
      time_period_numeric = time_periods.Get(time_period)['numeric']
      query = query.filter(
          models.PastRecommendation.time_period_numeric == time_period_numeric)
    past_recommendations = yield query.order(
        -models.PastRecommendation.date).fetch_async(PAST_RECOMMENDATIONS_LIMIT)
    item_ids = [r.item_id for r in past_recommendations]
    # We reverse the list of seen item ids so that the newest items are in the
    # end. We do this because we append new items ids to the end and remove
    # extra items from the back.
    item_ids = list(reversed(item_ids))
  if new_item_ids:
    for item_id in new_item_ids:
      if item_id not in item_ids:
        item_ids.append(item_id)
    item_ids = item_ids[-PAST_RECOMMENDATIONS_LIMIT:]
  if new_item_ids or not cached:
    memcache.set(name, item_ids)
  raise ndb.Return(set(item_ids))
