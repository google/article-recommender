/**
 * Copyright 2020 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

'use strict';

angular
    .module(
        'common.addLinkDialog',
        [
          'common.categoryService',
          'common.promiseFactory',
          'common.rateService',
          'common.recommendationsService',
          'ngMaterial',
        ])
    .factory(
        'addLinkDialogFactory',
        function($mdDialog) {
          var factory = {};

          factory.showDialog = function(event, url) {
            $mdDialog.show({
              controller: 'addLinkDialogController',
              templateUrl: 'common/addLinkDialog/addLinkDialog.tpl.html',
              parent: angular.element(document.body),
              targetEvent: event,
              clickOutsideToClose: true,
              fullscreen: true,
              locals: {
                url: url,
              },
            });
          };
          return factory;
        })
    .controller(
        'addLinkDialogController',
        function(
            $scope, $mdDialog, categoryService, promiseFactory, rateService,
            $timeout, url, $rootScope) {
          // The number of milliseconds to wait after user has entered text
          // in the newRating.url field before actually acting on that
          // information. This stops us from spamming the server with a
          // bunch of invalid requests if the user is typing a url.
          var FETCH_DELAY_MILLIS = 500;

          $scope.input = {
            url: url || '',
            urlValid: false,
            categoryId: categoryService.DEFAULT_CATEGORY.id
          };

          $scope.cancel = function() {
            $mdDialog.cancel();
          };

          $scope.recommend = function() {
            var ratingDone = function() {
              $scope.status = 'done';
              $mdDialog.hide();
            };
            var category =
                categoryService.getCategoryForId($scope.input.categoryId);
            $scope.status = 'in progress';
            rateService
                .rate(
                    $scope.input.url,              // url
                    rateService.RATING.THUMBS_UP,  // rating
                    'fab_dialog',                  // source
                    category, null /* itemInfo*/)
                .then(ratingDone);
          };

          var mostRecentUrl = '';
          var fetchRecommendationPageDetails = function(url) {
            if (url !== mostRecentUrl) {
              // The user has changed the url since we set a timeout, so wait
              // for the next timeout before making the request.
              return;
            }

            promiseFactory
                .getPostPromise('rest/extendedPageDetails', {url: url}, null)
                .then(
                    function(data) {
                      if (url !== $scope.input.url) {
                        return;
                      }
                      if (data['error']) {
                        $scope.input.pageDetailsError = data['error'];
                        $scope.input.urlValid = false;
                      } else {
                        $scope.input.details = data['details'];
                        $scope.input.urlValid = true;
                      }
                      $scope.input.validating = false;
                    },
                    function(error) {
                      if (url !== $scope.input.url) {
                        return;
                      }
                      $scope.input.pageDetailsError = 'unknown error';
                      $scope.input.urlValid = false;
                      $scope.input.validating = false;
                    });
            promiseFactory
                .getPostPromise('rest/suggestCategory', {url: url}, null)
                .then(function(data) {
                  if (url !== $scope.input.url) {
                    return;
                  }
                  if (data && data.id) {
                    $scope.input.categoryId = data.id;
                  } else {
                    $scope.input.categoryId =
                        categoryService.DEFAULT_CATEGORY.id;
                  }
                });
          };

          // Get the title of the page the user is trying to recommend.
          $scope.$watch('input.url', function() {
            $scope.ratingStatus = null;
            $scope.input.urlValid = false;
            $scope.input.details = null;
            $scope.input.pageDetailsError = null;

            var url = $scope.input.url;
            if ((!url) || (url === '')) {
              return;
            }
            $scope.input.validating = true;
            mostRecentUrl = url;
            $timeout(function() {
              fetchRecommendationPageDetails(url);
            }, FETCH_DELAY_MILLIS);
          });
        });
