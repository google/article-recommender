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

angular.module('recommendations.popular', [
  'common.categoryService',
  'common.navStatesService',
  'common.pageRecommendation',
  'common.recommendationsService',
  'common.timePeriodSelector',
  'common.loadMore',

  'ui.router'
])

.config(function($stateProvider) {
  var views = {
    'content': {
      templateUrl: 'popular/popular.tpl.html',
      controller: 'popularController'
    }
  };
  $stateProvider.state('root.popular', {
    url: '/popular/:timePeriod/:categoryId',
    views: views
  });
  $stateProvider.state('root.defaultPopular', {
    url: '/popular',
    views: views
  });
})

.directive('popularItems', function() {
  return {
    templateUrl: 'popular/popular.tpl.html',
    controller: 'popularController',
  };
})

.run(function(navStatesService) {
  navStatesService.addState(3 /* sortOrderValue */, 'Popular',
                            'root.defaultPopular', 'explore');
})

.controller('popularController', function(
    $scope, $http, $state, $stateParams, categoryService,
    recommendationsService) {

  $scope.stateParams = {};

  $scope.embedded = $state.current.name != 'root.popular' &&
      $state.current.name != 'root.defaultPopular';
  if ($scope.embedded) {
    $scope.stateParams.timePeriod = 'RECENT';
    $scope.stateParams.categoryId = categoryService.ANY_CATEGORY.id;
  } else {
    $scope.stateParams.timePeriod = $stateParams['timePeriod'] || 'RECENT';
    $scope.stateParams.categoryId =
        $stateParams['categoryId'] || categoryService.ANY_CATEGORY.id;
  }

  $scope.$watch('stateParams', function(newValue, oldValue) {
    if ((!newValue) || (newValue === oldValue)) {
      return;
    }

    if ($scope.embedded) {
      $scope.popularPages.load();
      return;
    }

    // When state params change, reflect these changes in the browser's URL
    // and history, so that the user can go backwards and forwards between
    // states. This will destroy and recreate the controller.
    if (newValue.categoryId == categoryService.ANY_CATEGORY.id) {
      newValue.categoryId = null;
    }
    $state.go('root.popular', newValue);
  }, true);

  $scope.getNoPopularPagesString = function() {
    if ($scope.stateParams.timePeriod === 'ALL') {
      return 'No popular pages yet. Check back later!';
    }

    return 'No popular pages for this time period. ' +
      'Try a larger time period or check back later.';
  };

  var PAGE_SIZE = 20;
  $scope.personalize = false;
  $scope.popularPages = new ItemLoader(
      PAGE_SIZE,
      function(offset, pageSize, callback) {
        // For popular categories, the IDs are their names.
        var categoryName = $scope.stateParams.categoryId;
        recommendationsService.getPopularPages(
            $scope.stateParams.timePeriod, categoryName,
            $scope.personalize, offset, pageSize)
                .then(function(data) {
                  callback(data);
                });
      });
  $scope.popularPages.load();
});
