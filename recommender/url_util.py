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

import cgi
import logging

import feedparser
import lxml.etree
import lxml.html
import lxml.html.soupparser
from recommender import reading_time_estimator
import urlparse

from google.appengine.api import urlfetch


class PageMetadata(object):
  pass


class Error(Exception):
  """Exception class for this module."""


class InvalidURLError(Error):
  """Raised when a url is obviously invalid."""


def DeduplicateUrls(urls):
  normalized_urls = set()
  unique_urls = []
  for url in urls:
    result = urlparse.urlsplit(url)
    scheme = result.scheme
    if scheme == 'http':
      scheme = 'https'
    netloc = result.netloc
    if netloc.startswith('www.'):
      netloc = netloc[len('www.'):]
    path = result.path.rstrip('/')
    normalized_result = urlparse.SplitResult(scheme, netloc, path, result.query,
                                             result.fragment)
    normalized_url = normalized_result.geturl()
    if normalized_url not in normalized_urls:
      normalized_urls.add(normalized_url)
      unique_urls.append(url)
  return unique_urls


def Normalize(url):
  if url and url.startswith('//'):
    return 'https:' + url
  return url


def RemoveUtmParameters(url):
  """Removes 'utm_*' tracking parameters from a url."""
  if 'utm_' not in url:
    return url

  parsed = list(urlparse.urlsplit(url))
  parsed[3] = '&'.join(
      [x for x in parsed[3].split('&') if not x.startswith('utm_')])
  return urlparse.urlunsplit(parsed)


def Resolve(base_url, url):
  if url:
    return urlparse.urljoin(base_url, url)
  return None


def _GetContentTypeAndCharset(headers):
  if 'content-type' not in headers:
    return None, None
  content_type, params = cgi.parse_header(headers['content-type'])
  return content_type, params.get('charset', None)


# We call urlfetch.fetch in user requests that have overall deadline of 60
# seconds.
URL_FETCH_DEADLINE_SECONDS = 15

FEED_CONTENT_TYPES = set([
    'application/atom+xml', 'application/rdf+xml', 'application/rss+xml',
    'application/x-netcdf', 'application/xml', 'text/xml'
])


def GetPageContent(url):
  url = Normalize(url)
  final_url = url
  try:
    result = urlfetch.fetch(
        url, deadline=URL_FETCH_DEADLINE_SECONDS, allow_truncated=True)
    if result.status_code == 200:
      content_type, encoding = _GetContentTypeAndCharset(result.headers)
      content = result.content
      if result.final_url:
        final_url = result.final_url
    else:
      logging.warn('Non-OK response: ' + str(result.status_code))
      raise Error('Non-OK response: ' + str(result.status_code))
  except urlfetch.InvalidURLError as e:
    raise InvalidURLError(e)
  except urlfetch.Error as e:
    raise Error(e)
  return content, content_type, encoding, final_url


def GetPageMetadata(url):
  url = Normalize(url)
  (content, content_type, encoding, final_url) = GetPageContent(url)
  parsed_feed = None
  # We set the default here because we cannot pass it explicitly into
  # feedparser.parse(url).
  urlfetch.set_default_fetch_deadline(URL_FETCH_DEADLINE_SECONDS)
  if content_type in FEED_CONTENT_TYPES:
    try:
      parsed_feed = feedparser.parse(url)
    except StandardError as e:
      logging.warning('Failed to parse as feed: ' + url + ' error: ' + str(e))
      try:
        parsed_feed = feedparser.parse(content)
      except StandardError as e:
        logging.warning('Failed to parse content of %s as a feed %s', url, e)

  if parsed_feed and parsed_feed.entries:
    result = PageMetadata()
    result.title = (
        parsed_feed.feed.title
        if hasattr(parsed_feed, 'title') else 'feed without title')
    result.canonical_url = final_url
    result.final_url = final_url
    result.description = None
    result.feed_url = None
    result.feed_title = None
    result.is_feed = True
    result.estimated_reading_time = None
    return result

  parser = None
  if encoding and encoding != 'None':
    try:
      parser = lxml.etree.HTMLParser(encoding=encoding)
    except StandardError as e:
      logging.warning('Could not create parser for: ' + url + ' error: ' +
                      str(e))

  try:
    tree = lxml.html.fromstring(content, base_url=url, parser=parser)
  except lxml.etree.LxmlError as e:
    logging.warning('Could not parse content of url: %s, %s', url, str(e))
    raise Error(e)
  except AttributeError as e:
    logging.warning('AttributeError when parsing: %s, %s', url, str(e))
    raise Error(e)

  result = PageMetadata()
  result.title = FindContent(tree, [{
      'path': './/head/meta[@property="og:title"]',
      'attribute': 'content'
  }, {
      'path': './/head/meta[@name="twitter:title"]',
      'attribute': 'content'
  }, {
      'path': './/head/title'
  }])
  result.final_url = final_url
  result.canonical_url = Resolve(
      url,
      FindContent(tree, [{
          'path': './/head/link[@rel="canonical"]',
          'attribute': 'href'
      }, {
          'path': './/head/meta[@property="og:url"]',
          'attribute': 'content'
      }]))

  if not result.canonical_url:
    result.canonical_url = final_url

  result.description = FindContent(tree, [{
      'path': './/head/meta[@property="og:description"]',
      'attribute': 'content'
  }, {
      'path': './/head/meta[@name="description"]',
      'attribute': 'content'
  }, {
      'path': './/head/meta[@name="twitter:description"]',
      'attribute': 'content'
  }])
  result.feed_url = None
  result.feed_title = None
  if not FindFeedUrl(url, tree, './/head/link[@type="application/rss+xml"]',
                     result):
    FindFeedUrl(url, tree, './/head/link[@type="application/atom+xml"]', result)

  result.is_feed = False

  try:
    result.estimated_reading_time = reading_time_estimator.Estimate(tree)
  except UnicodeDecodeError as e:
    logging.warning('Could not estimate reading time for url %s: %s', url, e)
    result.estimated_reading_time = None

  return result


def FindContent(tree, paths, filter_fn=None):
  for p in paths:
    match = tree.find(p['path'])
    if match is not None:
      if 'attribute' in p:
        result = match.get(p['attribute'])
      else:
        result = match.text
      if result:
        if filter_fn and not filter_fn(result):
          continue
        return result
  return None


def FindFeedUrl(url, tree, path, result):
  match = tree.find(path)
  if match is None:
    return False
  title = match.get('title')
  href = match.get('href')
  if href is None:
    return False
  feed_url = Resolve(url, href)
  result.feed_url = feed_url
  result.feed_title = title
  return True
