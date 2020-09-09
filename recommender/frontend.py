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
"""Handles requests from the AngularJS web ui."""

from __future__ import division

import Cookie
import json
import logging
import os
import threading
import webapp2

from google.appengine.api import users
from google.appengine.ext import ndb

from recommender import config
from recommender import delete_account
from recommender import export
from recommender import item_recommendation
from recommender import json_encoder
from recommender import models
from recommender import pipelines
from recommender import ratings
from recommender import recommendations
from recommender import time_periods
from recommender import url_util
from recommender import xsrf


class _XsrfSecretKey(ndb.Model):
  """Store secret key in datastore."""
  secret = ndb.StringProperty(required=True)


# Module level cache to store one XSRF secret value across all requests.
_xsrf_secret = None
_xsrf_secret_lock = threading.Lock()

# AngularJS reads XSRF-TOKEN cookie and adds it to every request in the
# X-XSRF-TOKEN header.
# See: https://docs.angularjs.org/api/ng/service/$http
#      #cross-site-request-forgery-xsrf-protection

XSRF_COOKIE = 'XSRF-TOKEN'
XSRF_HEADER = 'X-XSRF-TOKEN'


class RestHandler(webapp2.RequestHandler):

  def _GetXsrfSecret(self):
    """Returns XSRF secret, create it first if not set yet."""
    # Use of global needed for use of single instance.
    # pylint: disable=global-statement
    global _xsrf_secret
    with _xsrf_secret_lock:
      if not _xsrf_secret:
        _xsrf_secret = str(
            _XsrfSecretKey.get_or_insert(
                'xsrf_secret_key',
                secret=os.urandom(16).encode('base-64')).secret)
    return _xsrf_secret

  def _SetXSRFCookie(self):
    """Generates XSRF token."""
    user = users.get_current_user()
    if not user:
      return
    token = xsrf.GenerateToken(self._GetXsrfSecret(), user.user_id(), '')
    # Allow XSRF cookie over HTTP on dev server (which has no HTTPS).
    # We don't set httponly because we need the client JavaScript code to read
    # it and put it in the X-XSRF-TOKEN header.
    self.response.set_cookie(
        XSRF_COOKIE, token, httponly=False, secure=not config.IsDev())

  def _ValidateRequest(self):
    """Validates request to contain valid XSRF token."""
    user = users.get_current_user()
    if not user:
      logging.error(
          'Unable to validate XSRF token because user is not signed in. ')
      return False
    token = self.request.headers.get(XSRF_HEADER)
    if not token:
      logging.warn(XSRF_HEADER + ' header not found in request.')
      return False
    # The token we get is surrounded by '"' so we remove them.
    if token[0] == '"' and token[-1] == '"':
      token = token[1:-1]
    if not xsrf.ValidateToken(self._GetXsrfSecret(), token, user.user_id(), ''):
      logging.warn(XSRF_HEADER + ' header invalid: ' + token)
      return False
    return True

  def SendJson(self, data):
    self._SetXSRFCookie()
    self.response.headers['Content-Type'] = 'application/json'
    json.dump(data, self.response.out, cls=json_encoder.JSONEncoder)

  def post(self):
    if not self._ValidateRequest():
      self._SetXSRFCookie()
      self.error(403)
      self.response.out.write('Invalid XSRF')
      return
    data = None
    if self.request.body:
      data = json.loads(self.request.body)
    self.Handle(data)

  def Handle(self, data):
    raise NotImplementedError


class RateHandler(RestHandler):

  def Handle(self, data):
    url = data['url']
    canonical_url = models.GetCanonicalUrl(url)
    rating = ratings.NumberToRating(data['rating'])
    category_id = data.get('category_id', None)

    stats = recommendations.AddRating(
        users.get_current_user(),
        canonical_url,
        rating,
        data['source'],
        category_id)

    self.SendJson(stats)


class DeleteRatingHandler(RestHandler):

  def Handle(self, data):
    models.DeleteRating(users.get_current_user(), data['url'])
    self.response.headers['Content-Type'] = 'text/plain'
    self.response.out.write('Success')


class ExtendedPageDetailsHandler(RestHandler):

  def Handle(self, data):
    url = data['url']
    result = {}
    try:
      result['details'] = models.GetPageInfoOrRaise(url)
    except url_util.InvalidURLError as e:
      result['error'] = 'Invalid URL'
    except url_util.Error as e:
      logging.warning('Failed to get page details: ' + url + ' error: ' +
                      str(e))
      result['error'] = 'Failed to get page details'
    self.SendJson(result)


class RatingHistoryHandler(RestHandler):

  def Handle(self, data):
    category_id = data.get('category_id', None)
    any_category = data.get('any_category', False)
    positive_only = data.get('positive_only', False)
    offset = data.get('offset', 0)
    limit = data.get('limit', 100)
    self.SendJson(
        models.GetRatingHistory(
            users.get_current_user(),
            category_id,
            any_category,
            positive_only,
            offset,
            limit))


class CategoriesHandler(RestHandler):

  def Handle(self, data):
    self.SendJson(models.GetCategories(users.get_current_user()))


class AddCategoryHandler(RestHandler):

  def Handle(self, data):
    models.AddCategory(users.get_current_user(), data['name'])
    self.SendJson(models.GetCategories(users.get_current_user()))


class RenameCategoryHandler(RestHandler):

  def Handle(self, data):
    models.RenameCategory(users.get_current_user(), data['category_id'],
                          data['name'])
    self.SendJson(models.GetCategories(users.get_current_user()))


class RemoveCategoryHandler(RestHandler):

  def Handle(self, data):
    models.RemoveCategory(users.get_current_user(), data['category_id'])
    self.SendJson(models.GetCategories(users.get_current_user()))


class SetPageCategoryHandler(RestHandler):

  def Handle(self, data):
    url = data['url']
    canonical_url = url
    try:
      canonical_url = models.GetCanonicalUrl(url)
    except url_util.InvalidURLError as e:
      logging.warning('Invalid url:' + url + ' error: ' + str(e))

    recommendations.SetPageCategory(users.get_current_user(), canonical_url,
                                    data.get('category_id', None))


class SuggestCategoryHandler(RestHandler):

  def Handle(self, data):
    self.SendJson(
        models.SuggestCategoryForPage(users.get_current_user(), data['url']))


class RecommendationsHandler(RestHandler):

  def Handle(self, data):
    category_id = data.get('category_id')
    any_category = data.get('any_category', False)
    time_period = data.get('time_period', time_periods.ALL)
    include_popular = data.get('include_popular', False)
    limit = data.get('limit', 20)
    decay_rate = data.get('decay_rate', 1)
    source_type = data.get('source_type', item_recommendation.SOURCE_TYPE_ANY)
    exclude_urls = set(data.get('exclude_urls', []))
    user = users.get_current_user()

    result = item_recommendation.RecommendationsOnDemand(
        user,
        time_period,
        category_id,
        any_category,
        include_popular,
        limit,
        models.LOGISTIC_REGRESSION_CONNECTION,
        decay_rate=decay_rate,
        source_type=source_type,
        exclude_urls=exclude_urls,
        save_past_recommendations=True,
        exclude_past_recommendations=True,
        exclude_past_recommendations_from_all_time_periods=True,
        diversify=True)
    self.SendJson(result)


class PastRecommendationsHandler(RestHandler):

  def Handle(self, data):
    time_period = data.get('time_period', time_periods.ALL)
    offset = data.get('offset', 0)
    limit = data.get('limit', 20)
    user = users.get_current_user()

    result = models.GetPastRecommendations(user.user_id(), time_period, offset,
                                           limit)

    self.SendJson(result)


class MarkUnreadHandler(RestHandler):

  def Handle(self, data):
    user = users.get_current_user()
    (unread_count, visit_discarded) = models.MarkUnread(user.user_id(),
                                                        data['start_url'],
                                                        data['time_period'])
    self.SendJson({
        'unread_count': unread_count,
        'visit_discarded': visit_discarded
    })


class PopularPagesHandler(RestHandler):

  def Handle(self, data):
    time_period = data.get('time_period', 'ALL')
    offset = data.get('offset', 0)
    limit = data.get('limit', 100)
    self.SendJson(
        models.PopularPages(users.get_current_user(), time_period,
                            offset, limit))


class GetConfigHandler(RestHandler):

  def Handle(self, data):
    user = users.get_current_user()
    response = {'is_admin': users.is_current_user_admin(),
                'is_new_user': models.IsNewUser(user),
                'connection_info': models.GetConnectionInfo(user.user_id()),
                'signed_in_as_name': user.email(),
                'switch_account_url': users.create_login_url('/').replace(
                    'passive=true', 'passive=false')}
    # We replace 'passive=true' with 'passive=false' so that it shows this page
    # that allows to switch account:
    # with passive=true it just silently relogs in under the current account.
    # See also:
    # - https://p.ota.to/blog/multiple-google-account-sign-in-on-app-engine/
    if config.IsDev():
      response['theme'] = 'gray'
    else:
      response['theme'] = 'green'
    self.SendJson(response)


class RequestExportRatingsHandler(RestHandler):

  def Handle(self, data):
    user = users.get_current_user()
    export.CreateExportRatingsPipeline(user.user_id()).start()


class ExportStatusHandler(RestHandler):

  def Handle(self, data):
    user = users.get_current_user()
    self.SendJson(export.GetExportStatus(user.user_id()))


class AdminActionsHandler(RestHandler):

  def Handle(self, data):
    names = [route[0] for route in pipelines.routes]
    self.SendJson(names)


class AdminExecuteActionHandler(RestHandler):

  def Handle(self, data):
    name = data['name']
    handler = None
    for route in pipelines.routes:
      if route[0] == name:
        handler = route[1]
    handler(None)


class DeleteAccountHandler(RestHandler):

  def Handle(self, data):
    delete_account.DeleteAccount(users.get_current_user().user_id())


class DownloadHistoryHandler(webapp2.RequestHandler):

  def get(self):
    self.response.headers['Content-Type'] = 'text/csv'
    self.response.headers['Content-Disposition'] = (
        'attachment; '
        'filename="recommender_history.csv"')
    export.WriteLatestExportResult(users.get_current_user().user_id(),
                                   self.request.get('key'), self.response.out)


def ClearSessionCookie(handler):
  cookie = Cookie.SimpleCookie()
  cookie['dev_appserver_login'] = ''
  cookie['dev_appserver_login']['expires'] = -86400
  handler.response.headers.add_header(*cookie.output().split(': ', 1))
  cookie = Cookie.SimpleCookie()
  cookie['SACSID'] = ''
  cookie['SACSID']['expires'] = -86400
  handler.response.headers.add_header(*cookie.output().split(': ', 1))


class MainPageHandler(webapp2.RequestHandler):

  def get(self):
    self.redirect('index.html')


# ndb.toplevel makes sure that all *_async() functions that we didn't wait for
# with get_result() finish before the handler returns.
application = ndb.toplevel(
    webapp2.WSGIApplication(
        [
            ('/rest/ratingHistory', RatingHistoryHandler),
            ('/rest/rate', RateHandler),
            ('/rest/extendedPageDetails', ExtendedPageDetailsHandler),
            ('/rest/recommendations', RecommendationsHandler),
            ('/rest/pastRecommendations', PastRecommendationsHandler),
            ('/rest/markUnread', MarkUnreadHandler),
            ('/rest/popularPages', PopularPagesHandler),
            ('/rest/deleteRating', DeleteRatingHandler),
            ('/rest/getConfig', GetConfigHandler),
            ('/rest/categories', CategoriesHandler),
            ('/rest/addCategory', AddCategoryHandler),
            ('/rest/renameCategory', RenameCategoryHandler),
            ('/rest/removeCategory', RemoveCategoryHandler),
            ('/rest/suggestCategory', SuggestCategoryHandler),
            ('/rest/setPageCategory', SetPageCategoryHandler),
            ('/rest/requestExportRatings', RequestExportRatingsHandler),
            ('/rest/exportStatus', ExportStatusHandler),
            ('/rest/deleteAccount', DeleteAccountHandler),
            # Admin actions.
            ('/rest/admin/actions', AdminActionsHandler),
            ('/rest/admin/executeAction', AdminExecuteActionHandler),
            ('/download_history', DownloadHistoryHandler),
            ('/', MainPageHandler)
        ],
        debug=config.IsDev()))
