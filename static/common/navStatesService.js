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

angular.module('common.navStatesService', [])

.service('navStatesService', function() {
  var service = this;

  service.states = [];

  service.addState = function(sortOrderValue, stateName, stateId,
      stateIcon) {
    service.states.push({
      sortOrderValue: sortOrderValue,
      name: stateName,
      id: stateId,
      icon: stateIcon
    });
    service.states.sort(function(s1, s2) {
      return (s1.sortOrderValue < s2.sortOrderValue ? -1 : 1);
    });
  };

  service.updateStateName = function(newStateName, existingStateId) {
    var i;
    for (i = 0; i < service.states.length; i++) {
      if (service.states[i].id === existingStateId) {
        service.states[i].name = newStateName;
        return;
      }
    }

    console.log('error: navStatesService.updateStateName - ' +
        'could not find state with id "' + existingStateId + '"');
  };
})

;
