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

angular.module('recommendations.settings', [
  'common.formatService',
  'common.navStatesService',
  'common.promiseFactory',

  'ui.router'
])

.config(function($stateProvider) {
  $stateProvider.state('root.settings', {
    url: '/settings',
    views: {
      'content': {
        templateUrl: 'settings/settings.tpl.html',
        controller: 'settingsController'
      }
    }
  });
})

.run(function(navStatesService) {
  navStatesService.addState(9 /* sortOrderValue */, 'Settings', 'root.settings',
      'build');
})

.controller('settingsController', function($scope, $http, $rootScope,
                                           $timeout,
                                           categoryService,
                                           promiseFactory,
                                           formatService) {
  $scope.categoryService = categoryService;
  $scope.rootScope = $rootScope;

  $scope.confirmRemoveCategory = function(category) {
    if (confirm('Are you sure you want to remove "' +
        category.name + '" collection?')) {
      categoryService.removeCategory(category.id);
    }
  };

  $scope.formatDuration = formatService.formatDuration;

  $scope.requestExportRatings = function() {
    promiseFactory.getPostPromise(
        'rest/requestExportRatings',
        {},
        null).then(function() {
          $scope.updateExportStatus();
        });
  };

  $scope.exportStatus = null;
  $scope.updateExportStatus = function(limit = 500) {
    promiseFactory.getPostPromise(
        'rest/exportStatus',
        {},
        null).then(function(status) {
          $scope.exportStatus = status;
          if (status && status.in_progress && limit > 0) {
            $timeout(function() {
              $scope.updateExportStatus(limit - 1);
            }, 5000);
          }
        });
  };

  $scope.updateExportStatus();

  $scope.deleteAccount = function() {
    if (confirm('This will delete all of your account data. Are you sure?')) {
      promiseFactory.getPostPromise(
          'rest/deleteAccount',
          {},
          null).then(function(data) {
            alert('Your account will be deleted in a few minutes.');
      });
    }
  };
});
