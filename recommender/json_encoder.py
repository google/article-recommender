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
"""A JSONEncoder that knows how to convert ndb.Models."""

from abc import ABCMeta
from abc import abstractmethod

from datetime import date
from datetime import datetime
import json
import logging
import time

from google.appengine.ext import ndb


class Serializable(object):

  __metaclass__ = ABCMeta

  @abstractmethod
  def to_dict(self):
    return {}


def TimeToMillis(t):
  # utctimetuple() and timetuple() should return the same value because App
  # Engine uses UTC.
  ms = time.mktime(t.utctimetuple()) * 1000
  ms += getattr(t, 'microseconds', 0) / 1000
  return int(ms)


class JSONEncoder(json.JSONEncoder):

  def default(self, o):
    if isinstance(o, ndb.Key):
      model = o.get()
      if model:
        return o.get().to_dict()
      else:
        logging.warn('No model found for key: %s', o)
        return None
    if isinstance(o, ndb.Model):
      return o.to_dict()
    elif isinstance(o, (datetime, date)):
      return TimeToMillis(o)
    if isinstance(o, Serializable):
      return o.to_dict()
    else:
      return json.JSONEncoder.default(self, o)
