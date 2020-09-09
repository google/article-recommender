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
        'recommendations.recommendations',
        [
          'common.categoryService', 'common.categorySelector',
          'common.formatService', 'common.navStatesService',
          'common.pageRecommendation', 'common.recommendationsService',
          'common.loadMore', 'common.timePeriodSelector',

          'ui.router', 'ngStorage'
        ])

    .config(function ($stateProvider, $urlRouterProvider) {
      // Set default page. The number of trailing slashes must equal the number
      // of URL parameters this state has.
      $urlRouterProvider.otherwise(function ($injector, $location) {
        var defaultUrl = '/recommendations///';

        // Copy search parameters such as 'url' and 'share_text' so that the
        // addLinkDialog is shown.
        var search = $location.search();
        if (search) {
          defaultUrl += '?' +
              Object.keys(search)
                  .map(function (k) {
                    return encodeURIComponent(k) + '=' +
                        encodeURIComponent(search[k]);
                  })
                  .join('&');
        }
        return defaultUrl;
      });

      $stateProvider.state('root.recommendations', {
        url: '/recommendations/:timePeriod/:categoryId/:sourceTypeIdFilter?' +
            'includePopular&' +
            '{decay:int}',
        views: {
          'content': {
            templateUrl: 'recommendations/recommendations.tpl.html',
            controller: 'recommendationsController'
          }
        }
      });
    })

    .run(function (navStatesService) {
      navStatesService.addState(
          2 /* sortOrderValue */, 'Recommendations for you',
          'root.recommendations({timePeriod: "", categoryId: "", sourceTypeIdFilter: ""})',
          'home');
    })

    .controller(
        'recommendationsController',
        function (
            $scope, $state, $stateParams, $timeout, categoryService,
            recommendationsService, formatService, $localStorage, $window,
            $anchorScroll) {
          $scope.sourceTypeFilterOptions =
              recommendationsService.sourceTypeFilterOptions;

          // If the provided object has the specified key, and obj[key] is not
          // null or an empty string, return that value. Otherwise, return the
          // default value.
          var copyValue = function (obj, key, target) {
            if (obj.hasOwnProperty(key) && obj[key] && obj[key] !== '') {
              target[key] = obj[key];
            }
          };

          var copyIntValue = function (obj, key, target) {
            if (obj.hasOwnProperty(key) && obj[key] && obj[key] !== '') {
              var intValue = parseInt(obj[key]);
              if (intValue) {
                target[key] = intValue;
              }
            }
          };
          var copyBooleanValue = function (obj, key, target) {
            if (obj.hasOwnProperty(key) && obj[key] && obj[key] !== '') {
              var value = obj[key];
              if (value === 'true') {
                target[key] = true;
              }
              if (value === 'false') {
                target[key] = false;
              }
            }
          };

          $scope.formatDuration = formatService.formatDuration;

          $scope.defaultStateParams = {
            'timePeriod': 'MONTH',
            'categoryId': categoryService.ANY_CATEGORY.id,
            'sourceTypeIdFilter':
            recommendationsService.sourceTypeFilterOptions.ANY.id,
            'includePopular': true,
            'decay': 90,
          };

          $scope.stateParams = angular.copy($scope.defaultStateParams);

          if ($localStorage.lastRecommendationsParams) {
            Object.assign(
                $scope.stateParams, $localStorage.lastRecommendationsParams);
          }

          // Grab values from $stateParams, setting default values where
          // necessary.
          copyValue($stateParams, 'timePeriod', $scope.stateParams);
          copyIntValue($stateParams, 'categoryId', $scope.stateParams);
          copyIntValue($stateParams, 'sourceTypeIdFilter', $scope.stateParams);
          copyBooleanValue($stateParams, 'includePopular', $scope.stateParams);
          copyIntValue($stateParams, 'decay', $scope.stateParams);

          // Save the latest params for the next time the user loads this page.
          $localStorage.lastRecommendationsParams = $scope.stateParams;

          $scope.originalStateParams = angular.copy($scope.stateParams);

          $scope.savedStateRestored = false;
          // This must be incremented when saved state is no longer compatible
          // with the latest code.
          const SUPPORTED_STATE_VERSION = 1;
          // The version saved by the latest code.
          const CURRENT_STATE_VERSION = 1;
          const MAX_SAVED_LIST_SIZE = 200;

          var savedState = {
            recommendations: [],
            pastRecommendations: [],
          };
          if ($localStorage.savedState &&
              $localStorage.savedState.version >= SUPPORTED_STATE_VERSION &&
              $localStorage.savedState.stateParams.categoryId ==
              $scope.originalStateParams.categoryId &&
              $localStorage.savedState.stateParams.timePeriod ==
              $scope.originalStateParams.timePeriod) {
            $scope.savedStateRestored = true;
            $scope.lastUpdatedDate = $localStorage.savedState.date;
            savedState = angular.copy($localStorage.savedState);
            // In case we saved too many items - restore only the reasonable
            // number of most recent items (ie, from the tail of the list).
            savedState.recommendations =
                savedState.recommendations.slice(-MAX_SAVED_LIST_SIZE);
            savedState.pastRecommendations =
                savedState.pastRecommendations.slice(-MAX_SAVED_LIST_SIZE);
          } else {
            $localStorage.savedState = null;
          }

          $scope.$on('recommendationChanged', function (e, args) {
            // This event is triggered when any of the recommendations change
            // its category, rating or "saved for later" state. We want these
            // changes to be reflected in the saved state as well.
            updateSavedState();
          });

          function updateSavedState() {
            if ($scope.originalStateParams.saveState) {
              $localStorage.savedState = {
                recommendations:
                    $scope.recommendations.items.slice(-MAX_SAVED_LIST_SIZE),
                pastRecommendations: $scope.pastRecommendations.items.slice(
                    -MAX_SAVED_LIST_SIZE),
                date: $scope.lastUpdatedDate,
                version: CURRENT_STATE_VERSION,
                stateParams: angular.copy($scope.originalStateParams),
              };
            } else {
              $localStorage.savedState = null;
            }
          }

          $scope.local = {};
          $scope.categoryService = categoryService;

          $scope.introDismissed = $localStorage.introDismissed;
          $scope.dismissIntro = function () {
            $scope.introDismissed = true;
            $localStorage.introDismissed = true;
          };

          $scope.getNoRecommendationsString = function () {
            var isAllPeriod = ($scope.originalStateParams.timePeriod === 'ALL');
            var isAnyCategory =
                ($scope.originalStateParams.categoryId ===
                    categoryService.ANY_CATEGORY.id);
            if (isAllPeriod && isAnyCategory) {
              return 'Sorry, no recommendations for you yet. Check back later!';
            }

            if (isAllPeriod && (!isAnyCategory)) {
              return 'Sorry, no recommendations for this collection. ' +
                  'Try a different collection or check back later.';
            }

            if ((!isAllPeriod) && isAnyCategory) {
              return 'Sorry, no recommendations for this time period. ' +
                  'Try a larger time period or check back later.';
            }

            return 'Sorry, no recommendations. Try a larger time period or a ' +
                'different collection, or check back later.';
          };

          $scope.initialPageLoaded = $scope.savedStateRestored;

          var PAGE_SIZE = 20;
          $scope.recommendations = new ItemLoader(
              PAGE_SIZE,
              function (offset, pageSize, callback) {
                var excludeUrls = $scope.recommendations.items.map(
                    (item) => item.destination_url);
                recommendationsService
                    .getRecommendations(
                        $scope.originalStateParams.timePeriod,
                        $scope.originalStateParams.categoryId,
                        $scope.originalStateParams.sourceTypeIdFilter,
                        $scope.originalStateParams.includePopular, pageSize,
                        $scope.originalStateParams.decay / 100, excludeUrls)
                    .then(function (data) {
                      $scope.initialPageLoaded = true;
                      console.log('initial page loaded');
                      data.forEach(function (recommendation) {
                        // Make this recommendation compatible with the rest of
                        // the pageRecommendation formats.
                        recommendation.page = recommendation.destination_page;
                        delete recommendation.destination_page;
                      });
                      callback(data);
                      $scope.lastUpdatedDate = new Date().getTime();
                      updateSavedState();
                    });
              },
              true /* firstPageCanBeLess */,
              true /* doublePageSize */,
              savedState.recommendations /* items */);

          $scope.pastRecommendations = new ItemLoader(
              PAGE_SIZE,
              function (offset, pageSize, callback) {
                let timePeriod = $scope.originalStateParams.timePeriod;
                recommendationsService
                    .getPastRecommendations(timePeriod, offset, pageSize)
                    .then(function (data) {
                      data.forEach(function (recommendation) {
                        // Make this recommendation compatible with the rest of
                        // the pageRecommendation formats.
                        recommendation.page = recommendation.destination_page;
                        delete recommendation.destination_page;
                      });
                      callback(data);
                      updateSavedState();
                    });
              },
              false /* firstPageCanBeLess */, false /* doublePageSize */,
              savedState.pastRecommendations);

          $scope.reload = function () {
            $scope.savedStateRestored = false;
            $scope.initialPageLoaded = false;
            $scope.recommendations.load();
            $scope.pastRecommendations.load();
          };

          $scope.hideRated = function (recommendation) {
            return !recommendation.hasOwnProperty('rating');
          };

          $scope.resetSettings =
              function () {
                $state.go('root.recommendations', $scope.defaultStateParams);
                $scope.reload();
              }

          $scope.applySettings = function () {
            // Clear the saved state to force reload() with the new settings.
            // Otherwise the user will not see the effect until the press
            // "update".
            $localStorage.savedState = null;
            // When state params change, reflect these changes in the browser's
            // URL and history, so that the user can go backwards and forwards
            // between states. This will destroy and recreate the controller.
            $state.go('root.recommendations', $scope.stateParams);
          };

          $scope.$watch('stateParams.timePeriod',
              function (newValue, oldValue) {
                if ((!newValue) || (newValue === oldValue)) {
                  return;
                }
                $scope.applySettings();
              });

          $scope.$watch(
              'stateParams.sourceTypeIdFilter', function (newValue, oldValue) {
                if ((!newValue) || (newValue === oldValue)) {
                  return;
                }
                $scope.applySettings();
              });

          $scope.$watch('stateParams.categoryId',
              function (newValue, oldValue) {
                if ((!newValue) || (newValue === oldValue)) {
                  return;
                }
                $scope.applySettings();
              });

          if (!$scope.savedStateRestored) {
            $scope.reload();
          }
        });
