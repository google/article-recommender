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
"""Helper functions to work with FeedParser."""

from datetime import datetime
import time


def GetEntryDate(entry, min_date=None, max_date=None):
  if hasattr(entry, 'published_parsed') and entry.published_parsed:
    parsed_date = entry.published_parsed
  elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
    parsed_date = entry.updated_parsed
  else:
    return None
  entry_date = datetime.fromtimestamp(time.mktime(parsed_date))
  if min_date and entry_date < min_date:
    entry_date = min_date
  if max_date and entry_date > max_date:
    entry_date = max_date
  return entry_date
