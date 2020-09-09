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
"""Exports user's history to a CSV file."""
from __future__ import division

import csv
from datetime import datetime
from datetime import timedelta
import os
import pickle
import webapp2

import cloudstorage as gcs
from mapreduce import mapreduce_pipeline
from mapreduce import mapper_pipeline
from google.appengine.ext import deferred
from google.appengine.ext import ndb

from recommender import config
from recommender import models
from recommender import pipelines


# Keyed by user id.
class ExportRatingsResult(ndb.Model):
  in_progress = ndb.BooleanProperty()
  date = ndb.DateTimeProperty(auto_now=True)
  # The key used to make the download url non-guessable.
  download_key = ndb.StringProperty()
  filename = ndb.StringProperty()


def ExportRatingsMap(rating):
  title = models.GetPageInfo(rating.url).title
  category_name = ''
  if rating.category:
    category = rating.category.get()
    if category:
      category_name = category.name
  yield [
      rating.user_id,
      pickle.dumps(
          [rating.url, rating.rating, rating.date, category_name, title])
  ]


HEADER_NAMES = ['date', 'url', 'rating', 'category', 'title']


def GetExportStatus(user_id):
  # Have to disable memcache because it returns the cached value with
  # in_progress = True.
  result = ndb.Key(ExportRatingsResult, user_id).get(
      use_cache=False, use_memcache=False)
  if not result:
    return None
  return {
      'in_progress': result.in_progress,
      'download_key': result.download_key,
      'generated_date': result.date,
  }


def WriteLatestExportResult(user_id, key, output):
  result = ndb.Key(ExportRatingsResult, user_id).get()
  if not result:
    return
  if result.download_key != key:
    return
  with gcs.open(result.filename) as fp:
    output.write(fp.read())


_EXPORT_RESULT_TTL = timedelta(days=2)


def ExportRatingsReduce(user_id, values):
  filename = '/' + '/'.join([config.GetBucketName(), 'export', str(user_id)])
  write_retry_params = gcs.RetryParams(backoff_factor=1.1)
  output = gcs.open(
      filename, 'w', content_type='text/csv', retry_params=write_retry_params)
  writer = csv.writer(output, doublequote=False, escapechar='\\')
  writer.writerow(HEADER_NAMES)
  for value in values:
    url, rating, date, category_name, title = pickle.loads(value)
    date_string = date.strftime('%Y-%m-%d-%H%M%S')
    writer.writerow([
        date_string,
        unicode(url).encode('utf-8'),
        str(rating),
        unicode(category_name).encode('utf-8'),
        unicode(title).encode('utf-8')
    ])
  output.close()
  ExportRatingsResult(
      key=ndb.Key(ExportRatingsResult, user_id),
      in_progress=False,
      filename=filename,
      date=datetime.now(),
      download_key=os.urandom(32).encode('hex')).put()
  # Clean up the history dump after two days so that we don't have old
  # recommendations around (in case the user deletes their previous
  # recommendations).
  deferred.defer(
      _CleanUpOldExportResult,
      user_id,
      datetime.now(),
      _countdown=_EXPORT_RESULT_TTL.total_seconds())


def _CleanUpOldExportResult(user_id, date):
  result = ndb.Key(ExportRatingsResult, user_id).get()
  if not result:
    return
  if result.date > date:
    return
  gcs.delete(result.filename)
  result.key.delete()


def CreateExportRatingsPipeline(user_id):
  ExportRatingsResult(
      key=ndb.Key(ExportRatingsResult, user_id), in_progress=True).put()

  return mapreduce_pipeline.MapreducePipeline(
      'export-ratings',
      pipelines.FullName(ExportRatingsMap),
      pipelines.FullName(ExportRatingsReduce),
      'mapreduce.input_readers.DatastoreInputReader',
      mapper_params={
          'entity_kind': pipelines.FullName(models.PageRating),
          'filters': [('user_id', '=', user_id)]
      },
      shards=pipelines.DEFAULT_SHARDS)


def CleanUpOldExportsMap(export_result):
  if datetime.now() > export_result.date + _EXPORT_RESULT_TTL:
    gcs.delete(export_result.filename)
    export_result.key.delete()


class CleanUpOldExportsPipeline(pipelines.SelfCleaningPipeline):

  def run(self):
    yield mapper_pipeline.MapperPipeline(
        'clean_up_old_exports',
        pipelines.FullName(CleanUpOldExportsMap),
        'mapreduce.input_readers.DatastoreInputReader',
        params={'entity_kind': pipelines.FullName(ExportRatingsResult)},
        shards=pipelines.DEFAULT_SHARDS)


# This pipeline is a secondary mechanism to clean up exported ratings in case
# the primary mechanism that uses deferred.defer(_CleanUpOldExportResult) fails.
class CleanUpOldExportsHandler(webapp2.RequestHandler):

  def get(self):
    CleanUpOldExportsPipeline().start()


application = webapp2.WSGIApplication([
    ('/admin/cron/clean_up_old_exports', CleanUpOldExportsHandler),
])
