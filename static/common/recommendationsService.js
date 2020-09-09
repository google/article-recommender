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
    .module(
        'common.recommendationsService',
        ['common.categoryService', 'common.promiseFactory'])

    .service(
        'recommendationsService',
        function(categoryService, promiseFactory) {
          let service = this;
          var convertSourceTypeIdToServerId = function(sourceTypeId) {
            var key;
            var options = service.sourceTypeFilterOptions;
            for (key in options) {
              if (options.hasOwnProperty(key)) {
                if (sourceTypeId === options[key].id) {
                  return options[key].serverId;
                }
              }
            }

            return sourceTypeId;
          };

          this.sourceTypeFilterOptions = {};
          this.sourceTypeFilterOptions.ANY = {
            id: -1,
            name: 'any',
            serverId: null,
          };
          this.sourceTypeFilterOptions
              .USER = {id: 1, name: 'users only', serverId: 'user'};
          this.sourceTypeFilterOptions
              .FEED = {id: 2, name: 'feeds only', serverId: 'feed'};

          this.getRecommendations = function(
              timePeriod, categoryIdFilter, sourceTypeIdFilter, includePopular,
              limit, decayRate = 1, excludeUrls = []) {
            sourceTypeIdFilter =
                convertSourceTypeIdToServerId(sourceTypeIdFilter);
            var request = {
              time_period: timePeriod,
              source_type: sourceTypeIdFilter,
              limit: limit,
              decay_rate: decayRate,
              exclude_urls: excludeUrls,
            };
            if (categoryIdFilter === categoryService.ANY_CATEGORY.id) {
              request.any_category = true;
              // If the user requested recommendations for a given category then
              // it doesn't make sense to recommend random items from people the
              // user is not connected to.
              request.include_popular = includePopular;
            } else {
              request.category_id =
                  categoryService.convertClientCategoryIdToServerCategoryId(
                      categoryIdFilter);
            }

            return promiseFactory
                .getPostPromise('rest/recommendations', request, null)
                .then(categoryService
                          .convertServerCategoriesToClientCategoriesPromise);
          };

          this.getPastRecommendations = function(timePeriod, offset, limit) {
            var request = {
              time_period: timePeriod,
              offset: offset,
              limit: limit
            };
            return promiseFactory
                .getPostPromise('rest/pastRecommendations', request, null)
                .then(categoryService
                          .convertServerCategoriesToClientCategoriesPromise);
          };

          this.getPopularPages = function(
              timePeriod, categoryName, personalize, offset, limit) {
            var request = {
              time_period: timePeriod,
              personalize: personalize,
              offset: offset,
              limit: limit
            };

            return promiseFactory
                .getPostPromise('rest/popularPages', request, null)
                .then(categoryService
                          .convertServerCategoriesToClientCategoriesPromise);
          };

          this.markUnread = function(startUrl, timePeriod) {
            return promiseFactory.getPostPromise(
                'rest/markUnread',
                {time_period: timePeriod, start_url: startUrl}, null);
          };
        });
