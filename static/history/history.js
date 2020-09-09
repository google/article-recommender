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

angular.module('recommendations.history', [
  'common.categoryService',
  'common.categorySelector',
  'common.navStatesService',
  'common.pageRecommendation',
  'common.loadMore',

  'ui.router'
])

.config(function($stateProvider) {
  $stateProvider.state('root.history', {
    url: '/history',
    views: {
      'content': {
        templateUrl: 'history/history.tpl.html',
        controller: 'historyController'
      }
    }
  });
})

.run(function(navStatesService) {
  navStatesService.addState(4 /* sortOrderValue */, 'Your vote history',
                            'root.history', 'hourglass_empty');
})

.controller('historyController', function($scope, categoryService, rateService) {
  $scope.categoryService = categoryService;

  $scope.categoryIdWrapper = {
    categoryId: categoryService.ANY_CATEGORY.id
  };

  $scope.getSelectedCategoryName = function() {
    return categoryService.getCategoryForId(
        $scope.categoryIdWrapper.categoryId).name;
  };

  $scope.$watch('categoryIdWrapper.categoryId', function(newValue, oldValue) {
    if (newValue === oldValue) {
      return;
    }
    $scope.ratingHistory.load();
  });
  $scope.$watch('positiveOnly', function(newValue, oldValue) {
    if (newValue === oldValue) {
      return;
    }
    $scope.ratingHistory.load();
  });

  var PAGE_SIZE = 20;
  $scope.positiveOnly = true;
  $scope.ratingHistory = new ItemLoader(
      PAGE_SIZE,
      function(offset, pageSize, callback) {
        rateService.getRatingHistory(
            $scope.categoryIdWrapper.categoryId, $scope.positiveOnly,
            offset, pageSize)
                .then(function(data) {
                  callback(data);
                });
      });
  $scope.ratingHistory.load();
})

;
