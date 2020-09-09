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
    .module('common.formatService', [])

    .service(
        'formatService',
        function() {
          this.formatDuration = function(sinceTime) {
            if (!sinceTime) {
              return '';
            }

            var durationMinutes =
                (new Date().getTime() - sinceTime) / (1000 * 60);
            if (durationMinutes < 1) {
              return 'moments ago';
            }

            var result;
            if (durationMinutes < 60) {
              result = Math.floor(durationMinutes) + 'm';
            } else if (durationMinutes < 60 * 24) {
              result = Math.floor(durationMinutes / 60) + 'h';
            } else {
              result = Math.floor(durationMinutes / (60 * 24)) + 'd';
            }

            return (result + ' ago');
          };
        })

    ;
