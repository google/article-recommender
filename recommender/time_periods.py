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
"""Defines time periods that are used in the app."""

from datetime import timedelta

LAST_VISIT_RESTRICTED = 'LAST_VISIT_RESTRICTED'
LAST_VISIT = 'LAST_VISIT'
RECENT = 'RECENT'
HOUR = 'HOUR'
DAY = 'DAY'
WEEK = 'WEEK'
MONTH = 'MONTH'
YEAR = 'YEAR'
ALL = 'ALL'

ALL_NUMERIC = 0
YEAR_NUMERIC = 1
MONTH_NUMERIC = 2
WEEK_NUMERIC = 3
DAY_NUMERIC = 4
HOUR_NUMERIC = 5
RECENT_NUMERIC = 6
LAST_VISIT_NUMERIC = 7
LAST_VISIT_RESTRICTED_NUMERIC = 8

TIME_PERIODS = [
    {
        'timedelta': timedelta.max,
        'name': ALL,
        'numeric': ALL_NUMERIC
    },
    {
        'timedelta': timedelta(days=365),
        'name': YEAR,
        'numeric': YEAR_NUMERIC
    },
    {
        'timedelta': timedelta(days=31),
        'name': MONTH,
        'numeric': MONTH_NUMERIC
    },
    {
        'timedelta': timedelta(weeks=1),
        'name': WEEK,
        'numeric': WEEK_NUMERIC
    },
    {
        'timedelta': timedelta(days=1),
        'name': DAY,
        'numeric': DAY_NUMERIC
    },
    {
        'timedelta': timedelta(hours=1),
        'name': HOUR,
        'numeric': HOUR_NUMERIC
    },
    {
        'timedelta': timedelta(hours=0),
        'name': RECENT,
        'numeric': RECENT_NUMERIC
    },
    {
        'timedelta': timedelta(hours=0),
        'name': LAST_VISIT,
        'numeric': LAST_VISIT_NUMERIC
    },
    {
        'timedelta': timedelta(hours=0),
        'name': LAST_VISIT_RESTRICTED,
        'numeric': LAST_VISIT_RESTRICTED_NUMERIC
    },
]


def Get(name):
  for time_period in TIME_PERIODS:
    if time_period['name'] == name:
      return time_period
  return TIME_PERIODS[-1]
