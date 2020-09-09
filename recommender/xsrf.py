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
"""Creates and validates a temporary XSRF token."""

import hmac
import time
import datetime
import hashlib

_TOKEN_TTL_SECONDS = datetime.timedelta(hours=2).total_seconds()


def GenerateToken(secret, user_id, action, valid_until_timestamp=None):
  if valid_until_timestamp is None:
    valid_until_timestamp = time.time() + _TOKEN_TTL_SECONDS
  # Round it to the nearest seconds.
  valid_until_timestamp = int(valid_until_timestamp)
  return _CreateKey(secret, user_id, action,
                    valid_until_timestamp) + ':' + str(valid_until_timestamp)


def ValidateToken(secret, token, user_id, action, now_timestamp=None):
  parts = token.split(':')
  if len(parts) != 2:
    return False
  key = parts[0]
  valid_until_timestamp = int(parts[1])
  if now_timestamp is None:
    now_timestamp = time.time()
  # The token must not be expired.
  if now_timestamp > valid_until_timestamp:
    return False
  # The token must not be valid for longer than we created it.
  if valid_until_timestamp > now_timestamp + _TOKEN_TTL_SECONDS:
    return False
  # The signature must match.
  if _CreateKey(secret, user_id, action, valid_until_timestamp) != key:
    return False
  return True


def _CreateKey(secret, user_id, action, valid_until_timestamp):
  hmac_object = hmac.new(str(secret), digestmod=hashlib.sha256)
  hmac_object.update(str(user_id))
  hmac_object.update(str(action))
  hmac_object.update(str(valid_until_timestamp))
  return hmac_object.digest().encode('hex')
