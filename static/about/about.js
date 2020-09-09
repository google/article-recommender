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

angular.module('recommendations.about', [
  'common.navStatesService',

  'ui.router',
  'ngStorage'
])

.config(function($stateProvider, $urlRouterProvider) {
  $stateProvider.state('root.about', {
    url: '/about',
    views: {
      'content': {
        templateUrl: 'about/about.tpl.html',
      }
    }
  });
})

.run(function(navStatesService) {
  navStatesService.addState(10 /* sortOrderValue */, 'About',
      'root.about', 'help');
});
