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

from recommender import items

from google.appengine.ext import testbed


class ItemsTest(unittest.TestCase):

  def setUp(self):
    self.testbed = testbed.Testbed()
    self.testbed.activate()
    self.testbed.init_datastore_v3_stub()
    self.testbed.init_memcache_stub()

  def tearDown(self):
    self.testbed.deactivate()

  def testSerialization(self):
    self.assertEqual([1, 2, 3],
                     items.ItemIdsFromBytes(items.ItemIdsToBytes([1, 2, 3])))

    self.assertEqual([], items.ItemIdsFromBytes(items.ItemIdsToBytes([])))

  def testConversion(self):
    # Checks that nothing is returned for non-existing item id.
    self.assertEqual({}, items.ItemIdsToUrls([123]))

    id_a = items.UrlToItemId('a')
    id_b = items.UrlToItemId('b')
    items.UrlToItemId('c')

    self.assertEqual({id_a: 'a'}, items.ItemIdsToUrls([id_a]))
    self.assertEqual({id_a: 'a', id_b: 'b'}, items.ItemIdsToUrls([id_a, id_b]))
    self.assertEqual({}, items.ItemIdsToUrls([]))
    self.assertEqual({}, items.ItemIdsToUrls([]))

    self.assertEqual({'a': id_a, 'b': id_b}, items.UrlsToItemIds(['a', 'b']))
    self.assertEqual({'a': id_a}, items.UrlsToItemIds(['a']))
    self.assertEqual({}, items.UrlsToItemIds(['z']))
    self.assertEqual({}, items.UrlsToItemIds([]))
