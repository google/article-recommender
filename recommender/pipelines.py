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
"""MapReduce pipelines to aggregate ratings and calculate recommendations."""
from __future__ import absolute_import
from __future__ import division

from datetime import datetime
from datetime import timedelta
import logging
import pickle
from mapreduce import base_handler
from mapreduce import control as mr_control
from mapreduce import mapper_pipeline
from mapreduce import mapreduce_pipeline
from pipeline import pipeline
import webapp2

from recommender import config
from recommender import models
from recommender import recommendations

DEFAULT_SHARDS = 10 if not config.IsDev() else 1


def StartDatetimeFromContext():
  return LoadFromContext('start_datetime')


class SelfCleaningPipeline(base_handler.PipelineBase):

  def finalized(self):
    if not self.was_aborted:
      self.cleanup()


routes = []


class MapperPipeline(SelfCleaningPipeline):

  def run(self, name, entity_type, map_fn):
    yield mapper_pipeline.MapperPipeline(
        name,
        map_fn,
        'mapreduce.input_readers.DatastoreInputReader',
        params={
            'entity_kind': entity_type,
            'start_datetime': SerializeDatetime(datetime.now()),
        },
        shards=DEFAULT_SHARDS)


def CreateAdminHandler(callable_fn):

  def Call(req):
    if req is not None:
      if 'X-Appengine-Cron' not in req.headers:
        logging.warning('Admin action called directly with GET - exiting')
        return
    callable_fn(req)

  return Call


def AddHandler(name, callable_fn):
  routes.append(('/admin/' + name, CreateAdminHandler(callable_fn)))


def AddPipeline(name, pipeline_constructor):
  AddHandler(name, lambda req: pipeline_constructor().start())


def AddMapperPipeline(name, entity_type, map_fn):
  AddHandler(
      name, lambda req: MapperPipeline(name, FullName(entity_type),
                                       FullName(map_fn)).start())


def LoadFromContext(name):
  params = mr_control.handlers.context.get().mapreduce_spec.mapper.params
  return pickle.loads(params[name])


def SerializeDatetime(dt):
  return pickle.dumps(dt)


def FullName(c):
  return c.__module__ + '.' + c.__name__


def CreatePopularPagesPipeline(start_datetime):
  return mapreduce_pipeline.MapreducePipeline(
      'popular-pages',
      FullName(recommendations.PopularPagesMap),
      FullName(recommendations.PopularPagesReduce),
      'mapreduce.input_readers.DatastoreInputReader',
      mapper_params={
          'entity_kind': FullName(models.PageRating),
          'start_datetime': SerializeDatetime(start_datetime)
      },
      reducer_params={'start_datetime': SerializeDatetime(start_datetime)},
      shards=DEFAULT_SHARDS)


def GetCategoryId(category_key):
  if category_key is None:
    return None
  return category_key.id()


class CleanupPipeline(base_handler.PipelineBase):

  def run(self, start_datetime, last_start_datetime):
    # Delete all previously calculated models that haven't been updated in this
    # run of the pipeline.
    yield CreateCleanupPipeline(models.PopularPage, start_datetime)
    models.SetTimestamp('last_start', start_datetime)


def CleanupMap(model):
  if model.updated_datetime < StartDatetimeFromContext():
    model.key.delete()


def CreateCleanupPipeline(model_class, start_datetime):
  return mapper_pipeline.MapperPipeline(
      'cleanup',
      FullName(CleanupMap),
      'mapreduce.input_readers.DatastoreInputReader',
      params={
          'entity_kind': FullName(model_class),
          'start_datetime': SerializeDatetime(start_datetime)
      },
      shards=DEFAULT_SHARDS)


class MainPipeline(base_handler.PipelineBase):
  """Runs all MapReduces in sequence."""

  def run(self):
    last_start_datetime = models.GetTimestamp('last_start')
    start_datetime = datetime.now()

    with pipeline.InOrder():
      # Calculate total page ratings
      yield CreatePopularPagesPipeline(start_datetime)

      # Clean all total ratings that were not updated during the current
      # run of the pipeline.
      yield CleanupPipeline(start_datetime, last_start_datetime)

  def finalized(self):
    # Log instead of sending an email
    logging.info('The main pipeline finished')
    if not self.was_aborted:
      self.cleanup()


AddPipeline('cron/main_pipeline', MainPipeline)


def UpdateActiveConnectionStateMap(connection):
  start_datetime = StartDatetimeFromContext()
  updated = False
  if connection.active_datetime is None:
    connection.active_datetime = models.Source(
        connection.publisher_type, connection.publisher_id,
        connection.PublisherCategoryId()).GetLastRatingDatetime()
    if connection.active_datetime is None:
      return
    updated = True

  inactive_duration = start_datetime - connection.active_datetime
  active_days = [
      days for days in models.CONNECTION_ALL_ACTIVE_DAYS
      if inactive_duration < timedelta(days=days)
  ]
  if connection.active_days != active_days:
    connection.active_days = active_days
    updated = True
  if updated:
    connection.put()


AddMapperPipeline('cron/update_active_connection_state', models.Connection,
                  UpdateActiveConnectionStateMap)


AddHandler('cron/update_feeds', lambda req: recommendations.UpdateAllFeeds())

application = webapp2.WSGIApplication(routes, debug=True)
