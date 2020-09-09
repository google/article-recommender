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

angular.module('common.promiseFactory', [])

.factory('promiseFactory', function($http, $q) {
    var promiseFactory = {};
    var commonSuccessHandler = angular.noop;
    var commonErrorHandler = angular.noop;

    var checkHandler = function(handler) {
      if (!angular.isFunction(handler)) {
        throw 'handler must be a function. handler = ' + angular.toJson(handler);
      }
    };
    promiseFactory.setCommonSuccessHandler = function(handler) {
      checkHandler(handler);
      commonSuccessHandler = handler;
    };
    promiseFactory.setCommonErrorHandler = function(handler) {
      checkHandler(handler);
      commonErrorHandler = handler;
    };

    promiseFactory.getPromise = function(parameters) {
      var deferred = $q.defer();

      $http(parameters)
          .success(function(data, status, headers, config) {
            if (data === 'null') {
              data = null;
            }
            commonSuccessHandler(data, status, headers, config);
            deferred.resolve(data);
          }).error(function(data, status, headers, config) {
            commonErrorHandler(data, status, headers, config);
            deferred.reject(status);
          });

      return deferred.promise;
    };

    promiseFactory.getGetPromise = function(url, urlParams, parameters) {
      parameters = parameters || {};

      parameters.method = 'GET';
      parameters.url = url;
      parameters.params = urlParams;

      return promiseFactory.getPromise(parameters);
    };

    promiseFactory.getPostPromise = function(url, data, parameters) {
      parameters = parameters || {};

      parameters.method = 'POST';
      parameters.url = url;
      parameters.data = data;
      parameters.headers = {
        'Content-Type': 'application/json'
      };
      parameters.dataType = 'json';

      return promiseFactory.getPromise(parameters);
    };

    promiseFactory.resolveImmediately = function(data) {
      var deferred = $q.defer();
      deferred.resolve(data);
      return deferred.promise;
    };

    return promiseFactory;
})

;
