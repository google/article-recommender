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
"""Config file for app."""
# This file is run before any handlers.

# Per: https://cloud.google.com/appengine/docs/standard/python/tools/using-libraries-python-27
from google.appengine.ext import vendor
import os.path

vendor.add(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'lib'))

appstats_DATASTORE_DETAILS = False
appstats_CALC_RPC_COSTS = True
# If you don't see some expensive calls recorded in /_ah/stats then try to
# increase these parameters.
appstats_MAX_REPR = 250
appstats_MAX_DEPTH = 200
appstats_MAX_STACK = 60
appstats_MAX_LOCALS = 60
appstats_FILTER_LIST = [
    {'PATH_INFO': '^/rest/.*$'},
]

# Set it to True to enable profiling. The results will be
# available at: <local or deployed address>/_ah/stats
ENABLE_PROFILING = False

def webapp_add_wsgi_middleware(app):
  from google.appengine.ext.appstats import recording
  if ENABLE_PROFILING:
    return recording.appstats_wsgi_middleware(app)
  return app
