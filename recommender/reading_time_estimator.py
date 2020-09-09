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
"""Estimates the reading time of an html page by its content."""
from __future__ import division
import math

import urllib
import lxml.html.soupparser

# The average number of characters per minute a person can read.
# Source:
# https://en.wikipedia.org/wiki/Words_per_minute#Reading_and_comprehension
CHARACTERS_PER_MINUTE = 860


def Estimate(tree):
  """Estimates how much time it takes to read a page.

  Args:
    tree: A parsed page tree.

  Returns:
    Estimated time in minutes.
  """
  texts = tree.xpath('//text()')
  filtered_texts = [text for text in texts if _IsVisible(text)]
  stripped_texts = [unicode(text).strip() for text in filtered_texts]

  # Round up the result because nothing is 0-minutes long.
  return int(
      math.ceil(_CountCharacters(stripped_texts) / CHARACTERS_PER_MINUTE))


def _IsVisible(element):
  if not isinstance(element.getparent().tag, basestring):
    return False
  if element.getparent().tag in [
      'style', 'script', '[document]', 'head', 'title'
  ]:
    return False
  if len(unicode(element).strip()) < 15:
    return False
  return True


def _CountCharacters(texts):
  result = 0
  for text in texts:
    result += len(text)
  return result


# For running stand-alone.
def EstimateUrl(url):
  html = urllib.urlopen(url).read()
  encoding = None
  parser = lxml.etree.HTMLParser(encoding=encoding)
  tree = lxml.html.fromstring(html, base_url=url, parser=parser)

  return Estimate(tree)
