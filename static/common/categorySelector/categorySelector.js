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

angular.module('common.categorySelector', [
  'common.categoryService',
  'ngMaterial',
])

.directive('categorySelector', function(categoryService, $mdDialog) {
  return {
    restrict: 'E',
    scope: {
      // This should be an object with a single property called 'categoryId'
      // to track the currently selected category. The wrapper is used to enable
      // two way binding.
      categoryIdWrapper: '=categoryIdWrapper',
      isMakeRecommendationMode: '=isMakeRecommendationMode',
      isPopularMode: '=isPopularMode',
      standalone: '=standalone',

      // Optional. Allows the caller to manually specify which categories
      // should be used. This is useful in cases where we don't want to use
      // default list of categories (eg. on the popular page, we want to show
      // popular categories for a specified time period).
      categories: '=categories',
      title: '=title',
      showAny: '=showAny',
      hideIfNoCategories: '=hideIfNoCategories',
      enableAddNew: '=enableAddNew'
    },
    templateUrl: 'common/categorySelector/categorySelector.tpl.html',
    link: function(scope, iElement, iAttrs) {
      if (!scope.categoryIdWrapper.categoryId) {
        scope.categoryIdWrapper.categoryId =
          categoryService.DEFAULT_CATEGORY.id;
      }
      scope.local = {};
      scope.categoryService = categoryService;

      scope.addCategoryAndSelect = function(name) {
        categoryService.addCategory(name).then(function(addedCategory) {
          scope.categoryIdWrapper.categoryId = addedCategory.id;
        });
      };

      scope.newCategoryId = 'new';
      scope.$watch('categoryIdWrapper.categoryId', function(newId, oldId) {
        if (newId == scope.newCategoryId) {
          var confirm = $mdDialog.prompt()
              .title('Add a new collection')
              .placeholder('New collection name')
              .ariaLabel('New collection name')
              .multiple(true)
              .ok('Add')
              .cancel('Cancel');

          $mdDialog.show(confirm).then(function(newName) {
            categoryService.addCategory(newName).then(function(addedCategory) {
              scope.categoryIdWrapper.categoryId = addedCategory.id;
            });
          }, function() {
            scope.categoryIdWrapper.categoryId = oldId;
          });
        }
      });

      scope.getRelevantCategories = function() {
        if (scope.categories) {
          return scope.categories;
        } else {
          return categoryService.categories;
        }
      };
    } // end link function
  }; // end return object
}); // end directive
