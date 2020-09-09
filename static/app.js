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

function setTheme($mdThemingProvider) {
  var config = {
    '500': '039cd8',  // blue - default color
    '800': '43b147',  // title bar
    'contrastDefaultColor': 'dark',
    'contrastLightColors': ['A200', '800', '500']
  };

  var primaryMap = $mdThemingProvider.extendPalette('teal', config);

  var accentMap = $mdThemingProvider.extendPalette('green', {
    'contrastDefaultColor': 'light',
    'A200': '43b147',  // green - accent
    'A700': '539355'  // hovered FAB
  });

  // Register the new color palette maps.
  $mdThemingProvider.definePalette('primary', primaryMap);
  $mdThemingProvider.definePalette('accent', accentMap);

  // Use that theme for the primary intentions
  $mdThemingProvider.theme('default')
      .primaryPalette('primary')
      .accentPalette('accent');

  // Enable browser color.
  // Uses color '800' from primary pallette of the 'default' theme.
  $mdThemingProvider.enableBrowserColor({});
}

angular
    .module(
        'recommendations',
        [
          'common.navStatesService',
          'common.promiseFactory',
          'common.recommendationsService',

          'recommendations.about',
          'recommendations.history',
          'recommendations.nav',
          'recommendations.popular',
          'recommendations.recommendations',
          'recommendations.settings',

          'ui.router',
          'ng-showdown',
          'ngMaterial',
          'ngStorage'
        ])

    .config(function(
        $httpProvider, $locationProvider, $urlRouterProvider, $stateProvider,
        $mdThemingProvider) {
      setTheme($mdThemingProvider);

      // Set up spinner.
      $httpProvider.interceptors.push(function($q, $rootScope) {
        var setSpinnerActive = function(active) {
          if (active) {
            $rootScope.spinnerState = 'indeterminate';
            $rootScope.hideSpinner = false;
          } else {
            $rootScope.spinnerState = null;
            $rootScope.hideSpinner = true;
          }
        };

        var pendingRequests = 0;
        setSpinnerActive(false);

        return {
          request: function(config) {
            pendingRequests++;

            setSpinnerActive(true);
            return config || $q.when(config);
          },
          response: function(response) {
            pendingRequests--;
            if (pendingRequests === 0) {
              setSpinnerActive(false);
            }

            return response || $q.when(response);
          },
          responseError: function(response) {
            pendingRequests--;
            if (pendingRequests === 0) {
              setSpinnerActive(false);
            }

            return $q.reject(response);
          }
        };
      });
    })

    .factory(
        'httpResponseErrorInterceptor',
        function($q, $rootScope, $injector) {
          return {
            'responseError': function(response) {
              // When the XSRF token is missing, the server responds with 403,
              // so we retry.
              if (response.status === 403 && response.data === 'Invalid XSRF') {
                console.log('Retrying the request...');
                return $injector.get('$http')(response.config);
              } else if (response.status === 403) {
                $rootScope.activationLink = response.data;
              }

              return $q.reject(response);
            }
          };
        })

    .config(function($httpProvider) {
      $httpProvider.interceptors.push('httpResponseErrorInterceptor');
    })

    .config([
      '$compileProvider',
      function($compileProvider) {
        $compileProvider.debugInfoEnabled(false);
      }
    ])

    .run(function(
        $rootScope, $location, $localStorage, navStatesService, promiseFactory) {

      // Initialize config from server.
      $rootScope.theme = $localStorage.theme || 'green';
      promiseFactory.getPostPromise('rest/getConfig', null, null)
          .then(function(data) {
            $rootScope.connectionInfo = data.connection_info;
            $rootScope.theme = data.theme;
            $rootScope.signedInAsName = data.signed_in_as_name;
            $rootScope.switchAccountUrl = data.switch_account_url;
            $localStorage.theme = data.theme;
          });
    })
    .controller('AppCtrl', function($scope, $rootScope) {
      $scope.rootScope = $rootScope;
    });
