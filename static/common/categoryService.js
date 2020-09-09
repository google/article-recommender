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

angular.module('common.categoryService', [
  'common.promiseFactory'
])

.service('categoryService', function(promiseFactory) {
  let service = this;

  service.ANY_CATEGORY = {
    id: -1, // to be used client-side only
    serverId: 'ANY',
    name: 'any' // to be displayed client-side
  };
  service.DEFAULT_CATEGORY = {
    id: 1, // to be used client-side only
    serverId: null,
    name: 'default' // to be displayed client-side
  };

  service.convertClientCategoryIdToServerCategoryId =
      function(clientCategoryId) {
    if (clientCategoryId === service.DEFAULT_CATEGORY.id) {
      return service.DEFAULT_CATEGORY.serverId;
    } else if (clientCategoryId === service.ANY_CATEGORY.id) {
      return service.ANY_CATEGORY.serverId;
    }

    return clientCategoryId;
  };

  // If obj[key] matches the server's representation of ANY_CATEGORY or
  // DEFAULT_CATEGORY, convert obj[key] to the client's representation of that
  // category.
  var modifyCategoryIfApplicable = function(obj, key) {
    var category = obj[key];
    if (category === service.ANY_CATEGORY.serverId) {
      obj[key] = service.ANY_CATEGORY;
    } else if (category === service.DEFAULT_CATEGORY.serverId) {
      obj[key] = service.DEFAULT_CATEGORY;
    }
  };

  service.convertServerCategoriesToClientCategories =
      function(recommendations) {
        if (angular.isArray(recommendations)) {
          recommendations.forEach(function(recommendation) {
            if (recommendation.hasOwnProperty('category')) {
              modifyCategoryIfApplicable(recommendation, 'category');
            } else if (recommendation.hasOwnProperty('source_category')) {
              modifyCategoryIfApplicable(recommendation, 'source_category');
            } else {
              // If the recommendation had neither 'category', nor 'source_category'
              // properties, then set 'category' to the default value.
              recommendation.category = service.DEFAULT_CATEGORY;
            }
          });
        }
      };

  service.convertServerCategoriesToClientCategoriesPromise =
      function(recommendations) {
    if (angular.isArray(recommendations)) {
      recommendations.forEach(function(recommendation) {
        if (recommendation.hasOwnProperty('category')) {
          modifyCategoryIfApplicable(recommendation, 'category');
        } else if (recommendation.hasOwnProperty('source_category')) {
          modifyCategoryIfApplicable(recommendation, 'source_category');
        } else {
          // If the recommendation had neither 'category', nor 'source_category'
          // properties, then set 'category' to the default value.
          recommendation.category = service.DEFAULT_CATEGORY;
        }
      });
    }

    return promiseFactory.resolveImmediately(recommendations);
  };

  service.categories = [];

  service.getCategoryForId = function(categoryId) {
    if (categoryId === service.DEFAULT_CATEGORY.id) {
      return service.DEFAULT_CATEGORY;
    }
    if (categoryId === service.ANY_CATEGORY.id) {
      return service.ANY_CATEGORY;
    }

    var i;
    for (i = 0; i < service.categories.length; i++) {
      var currentCategory = service.categories[i];
      if (currentCategory.id === categoryId) {
        return currentCategory;
      }
    }

    return service.DEFAULT_CATEGORY;
  };

  service.refreshCategories = function() {
    return promiseFactory.getPostPromise(
      'rest/categories',
      null,
      null)
    .then(function(data) {
      service.categories = data;
    });
  };
  // Initialize categories values.
  service.refreshCategories();

  service.addCategory = function(name) {
    return promiseFactory.getPostPromise(
        'rest/addCategory',
        {name: name},
        null)
    .then(function(categories) {
      var i;

      service.categories = categories;

      // Find which category was the one we just added.
      for (i = 0; i < categories.length; i++) {
        if (categories[i].name === name) {
          return categories[i];
        }
      }

      console.log('ERROR: Could not find added category');
      return null;
    });
  };

  service.setPageCategory = function(destinationPageUrl, category) {
    var request = {
      url: destinationPageUrl
    };

    if (category) {
      request.category_id =
        service.convertClientCategoryIdToServerCategoryId(category.id);
    }

    return promiseFactory.getPostPromise(
        'rest/setPageCategory',
        request,
        null);
  };

  service.renameCategory = function(categoryId, name) {
    return promiseFactory.getPostPromise(
        'rest/renameCategory',
        {
          category_id: categoryId,
          name: name
        },
        null)
      .then(function(categories) {
        service.categories = categories;
      });
  };

  service.removeCategory = function(categoryId) {
    return promiseFactory.getPostPromise(
        'rest/removeCategory',
        {category_id: categoryId},
        null)
      .then(function(categories) {
        service.categories = categories;
      });
  };
});
