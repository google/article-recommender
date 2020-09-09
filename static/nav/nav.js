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

angular.module('recommendations.nav', [
  'common.categoryService',
  'common.navStatesService',
  'common.promiseFactory',
  'common.rateService',
  'common.recommendationsService',
  'common.addLinkDialog',

  'ngMaterial',
  'ui.router'
])

.config(function($stateProvider) {
  $stateProvider.state('root', {
    url: '',
    abstract: true,
    views: {
      'nav': {
        templateUrl: 'nav/nav.tpl.html',
        controller: 'navController'
      }
    }
  });
})

.controller('navController', function($mdSidenav, $scope, $state,
                                      $mdDialog, $timeout, $location,
                                      $rootScope,
                                      navStatesService,
                                      addLinkDialogFactory) {
  $scope.states = navStatesService.states;

  $scope.$state = $state;
  $scope.rootScope = $rootScope;


  $scope.isState = function(stateName) {
    if ((!$state.current) || (!$state.current.name)) {
      return false;
    }
    return ($state.current.name.indexOf(stateName) !== -1);
  };

  $scope.$watch('$state.current.name', function(newValue, oldValue) {
    for (var i = 0; i < $scope.states.length; i++) {
      if ($scope.states[i].id === newValue) {
        $scope.currentState = $scope.states[i];
      }
    }

    if (newValue === oldValue) {
      return;
    }
    var sidenav = $mdSidenav('leftNav');
    if (sidenav.isOpen() && !sidenav.isLockedOpen()) {
      sidenav.close();
    }
  });

  $scope.toggleNav = function() {
    $mdSidenav('leftNav').toggle();
  };

  function openLinkDialog(parameter_name) {
    if ($location.search()[parameter_name]) {
      addLinkDialogFactory.showDialog(null, $location.search()[parameter_name]);
      return true;
    }
    return false;
  }
  openLinkDialog('url') || openLinkDialog('share_text');
  $location.search('url', undefined);
  $location.search('share_text', undefined);

  $scope.addLink = function(event) {
    addLinkDialogFactory.showDialog(event);
  };
});
