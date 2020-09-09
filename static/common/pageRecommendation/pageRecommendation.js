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

angular.module('common.pageRecommendation', [
  'common.categoryService',
  'common.formatService',
  'common.rateService',
  'common.recommendationsService',

  'ui.router',
])

.directive('pageRecommendation', function(
    categoryService, formatService, rateService,
    $mdToast, $mdDialog, recommendationsService, $rootScope,
    $state) {
  return {
    restrict: 'A',
    replace: true,
    scope: {
      recommendation: '=pageRecommendation',
      mode: '=mode',
      timePeriod: '=timePeriod'
    },
    templateUrl: 'common/pageRecommendation/pageRecommendation.tpl.html',
    link: function(scope, iElement, iAttrs) {
      scope.MAX_SOURCES_TO_SHOW = 5;

      if ((!scope.mode) || (scope.mode.length === 0)) {
        throw 'must specify mode for pageRecommendation';
      }
      scope.categoryService = categoryService;
      scope.formatDuration = formatService.formatDuration;

      var recommendation = scope.recommendation;

      if (recommendation.page.domain.startsWith('www.')) {
        recommendation.page.domain =
            recommendation.page.domain.slice('www.'.length);
      }

      // How long a post can be to be shown fully.
      const maxUntrimmedLength = 400;
      // If the post is too long to be shown fully then this is how long the
      // preview is.
      // We make maxUntrimmedLength larger than trimLength so that the user does
      // not have to expand the preview when there are only a few more
      // characters to read.
      const trimLength = 300;
      if (recommendation.page.description &&
          scope.recommendation.page.description.length > maxUntrimmedLength &&
          scope.mode != 'ITEM') {
        recommendation.trimmedDescription =
            recommendation.page.description.substring(0, trimLength);
        recommendation.showTrimmed = true;
      }

      if (recommendation.page.is_post &&
          !recommendation.page.description &&
          recommendation.page.context_url) {
        scope.destinationUrl = recommendation.page.context_url;
        scope.linkOnlyPost = true;
        scope.visitUrl += '&original_url=' +
            window.encodeURIComponent(recommendation.page.url);
      } else {
        scope.destinationUrl = recommendation.page.url;
      }

      // We set the categoryId when the recommendation comes from the server.
      // If the recommendation is restored from a saved state then it will
      // already have categoryId initialized, so we check for it first.
      if (!scope.recommendation.categoryId) {
        if (scope.recommendation.category) {
          scope.recommendation.categoryId = scope.recommendation.category.id;
        } else if (scope.recommendation.source_category) {
          scope.recommendation.categoryId = scope.recommendation.source_category.id;
        } else {
          scope.recommendation.categoryId = categoryService.DEFAULT_CATEGORY.id;
        }
      }

      scope.$watch('recommendation.categoryId', function(newValue, oldValue) {
        if (newValue === oldValue || newValue === 'new') {
          return;
        }
        var category = categoryService.getCategoryForId(scope.recommendation.categoryId);
        categoryService.setPageCategory(scope.recommendation.page.url, category);
        scope.$emit('recommendationChanged', scope.recommendation);
      });

      scope.state = {
        expandedSources: false,
      };

      scope.undoDownvote =
          function() {
        if (scope.recommendation.rating == -1) {
          scope.ratePage(-1);
        }
      };

      scope.ratePage = function(newRating) {
        if (newRating === scope.recommendation.rating) {
          // Delete the existing rating.
          scope.recommendation.rating = null;
          scope.recommendation.rated = false;
          scope.recommendation.removed = true;

          rateService.deleteRating(
              scope.recommendation.page.url);

          return;
        }

        if (newRating == -1) {
          // Allows us to distinguish if the item was downvoted in this session
          // as opposed to it was downvoted in the past.
          // For items that were downvoted in this session we provide more
          // interactive UI that hides the item and explains the meaning of the
          // downvote action.
          scope.state.downvotedNow = true;
        }

        scope.recommendation.rating = newRating;
        scope.recommendation.rated = true;
        scope.recommendation.removed = false;
        var category = categoryService.getCategoryForId(scope.recommendation.categoryId);
        rateService.rate(
            scope.recommendation.page.url,
            scope.recommendation.rating,
            scope.mode,
            category,
            scope.recommendation.item_info).then(function(stats) {
              var message = '';
              var sources = '';
              if (stats.user_count == 1) {
                sources += '1 person';
              } else if (stats.user_count > 1) {
                sources += stats.user_count + ' people';
              }
              if (stats.own_feed) {
                if (sources != '') {
                  sources += ', ';
                }
                sources += stats.own_feed;
                // Reduce the feed count so that we don't double count the owner feed.
                stats.feed_count--;
              }
              if (stats.feed_count > 0) {
                if (sources != '') {
                  sources += ' and ';
                }
                sources += stats.feed_count;
                if (stats.feed_count == 1) {
                  sources += ' feed';
                } else {
                  sources += ' feeds';
                }
              }
              if (scope.recommendation.rating == 0) {
                message = 'This item will not be recommended to you again.';
              } else if (scope.recommendation.rating == 1 && sources != '') {
                message = 'You will see more content from ' + sources +
                    ' who recommended this.';
              } else if (scope.recommendation.rating == -1 && sources != '') {
                message = 'You will see less content from ' + sources +
                    ' who recommended this.';
              }
              if (message != '') {
                $mdToast.show(
                    $mdToast.simple()
                        .textContent(message)
                        .position('bottom')
                        .action('DISMISS')
                        .hideDelay(5000)
                    );
              }
              scope.$emit('recommendationChanged', scope.recommendation);
            });
      };

      scope.canMarkUnread = scope.mode == 'RECOMMENDATIONS' && scope.timePeriod;
      // Marks everything below this item as 'unread'. Ie, it won't be committed
      // to "Past recommendations".
      scope.markUnread = function() {
        recommendationsService.markUnread(
            scope.recommendation.page.url,
            scope.timePeriod).then(function(data) {
              var message = data.unread_count + ' items were marked as unread.';
              if (data.visit_discarded) {
                message += ' This visit will not be counted.';
              }
              $mdToast.show(
                    $mdToast.simple()
                        .textContent(message)
                        .position('bottom')
                        .action('DISMISS')
                        .hideDelay(4000)
                    );
            });
      };
      scope.rootScope = $rootScope;
    }
  };
});
