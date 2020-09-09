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

import unittest

from recommender import url_util


class UrlUtilTest(unittest.TestCase):

  def testDeduplicate(self):
    self.assertEqual(['https://a.test'],
                     url_util.DeduplicateUrls(
                         ['https://a.test', 'http://a.test']))
    self.assertEqual(['http://a.test', 'http://b.test'],
                     url_util.DeduplicateUrls([
                         'http://a.test', 'https://a.test///', 'HTTP://a.test/',
                         'http://www.a.test/', 'http://b.test'
                     ]))

  def testRemoveUtmParameters(self):
    # Unchanged URL:
    self.assertEqual(
        'https://a.test/some/path?param1=a&param2=b#fragment',
        url_util.RemoveUtmParameters(
            'https://a.test/some/path?param1=a&param2=b#fragment'))

    self.assertEqual(
        'https://a.test/some/path?param1=a#fragment',
        url_util.RemoveUtmParameters(
            'https://a.test/some/path?param1=a&utm_campaign=bla#fragment'))

    self.assertEqual(
        'https://a.test/some/utm_path#utm_fragment',
        url_util.RemoveUtmParameters(
            'https://a.test/some/utm_path?utm_campaign=bla&utm_source=bla#utm_fragment'
        ))

    self.assertEqual(
        'invalid_url_with_utm_string',
        url_util.RemoveUtmParameters('invalid_url_with_utm_string'))
