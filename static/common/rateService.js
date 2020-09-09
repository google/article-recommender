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
        'common.rateService',
        ['common.categoryService', 'common.promiseFactory'])

    .service(
        'rateService',
        function(categoryService, promiseFactory) {
          this.RATING = {THUMBS_UP: 1, NEUTRAL: 0, THUMBS_DOWN: -1};

          var ratingStringMap = {
            'up': this.RATING.THUMBS_UP,
            'neutral': this.RATING.NEUTRAL,
            'down': this.RATING.THUMBS_DOWN
          };
          this.rate = function(
              url, rating, source, category, itemInfo = null) {
            var ratingInt = null;
            if (angular.isNumber(rating)) {
              ratingInt = rating;
            } else {
              ratingInt = ratingStringMap[rating];
            }

            if (ratingInt === null) {
              throw (
                  'ERROR: Could not convert rating "' + rating +
                  '" into a proper ratingInt');
            }

            var request = {
              url: url,
              rating: ratingInt,
              source: source,
            };
            if (category) {
              request.category_id =
                  categoryService.convertClientCategoryIdToServerCategoryId(
                      category.id);
            }
            if (itemInfo) {
              request.item_info = itemInfo;
            }
            return promiseFactory.getPostPromise('rest/rate', request, null);
          };

          this.deleteRating = function(url) {
            return promiseFactory.getPostPromise(
                'rest/deleteRating', {url: url}, null);
          };

          this.getRatingHistory = function(
              categoryId, positiveOnly, offset, limit) {
            var request = {
              offset: offset,
              limit: limit,
              positive_only: positiveOnly
            };
            if (categoryId === categoryService.ANY_CATEGORY.id) {
              request.any_category = true;
            } else {
              request.category_id =
                  categoryService.convertClientCategoryIdToServerCategoryId(
                      categoryId);
            }

            return promiseFactory
                .getPostPromise('rest/ratingHistory', request, null)
                .then(categoryService
                          .convertServerCategoriesToClientCategoriesPromise);
          };
        })

    ;
