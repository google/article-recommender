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

let app = angular.module('app', []);

app.factory('httpResponseErrorInterceptor', function($q, $injector) {
  return {
    'responseError': function(response) {
      // When the XSRF token is missing, the server responds with 403.
      // So we retry.
      if (response.status === 403 && response.data === 'Invalid XSRF') {
        console.log('Retrying the request');
        let $http = $injector.get('$http');
        return $http(response.config);
      }
      return $q.reject(response);
    }
  };
});

app.config(function($httpProvider, $locationProvider) {
  $locationProvider.html5Mode(true);
  $httpProvider.interceptors.push('httpResponseErrorInterceptor');
});


function AdminCtrl($scope, $http) {
  $scope.actions = [];
  $http.post('rest/admin/actions', {})
      .success(function(data) {
        $scope.actions = data;
      })
      .error(function(data) {
        alert('Error: ' + data);
      });

  $scope.executeAction = function(name) {
    $http.post('rest/admin/executeAction', {name: name})
        .success(function(data) {
          alert('Done');
        })
        .error(function(data) {
          alert('Error: ' + data);
        });
  };
}

angular.module('app').controller('AdminCtrl', ['$scope', '$http', AdminCtrl]);
