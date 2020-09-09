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


var ItemLoader = function(pageSize, loadFunction, firstPageCanBeLess = false,
                          doublePageSize = false, items = []) {
  this.initialPageSize = pageSize;
  this.pageSize = pageSize;
  this.loadFunction = loadFunction;
  this.items = items;
  this.hasMore = items.length > 0;
  this.isLoading = false;
  this.lastRequest = null;
  // If true then the first page can be smaller than pageSize and more could
  // still be loaded.
  this.firstPageCanBeLess = firstPageCanBeLess;
  this.doublePageSize = doublePageSize;
};

ItemLoader.prototype.load = function(isLoadMore) {
  var offset = 0;
  var previousItems = this.items;
  if (isLoadMore) {
    offset = previousItems.length;
    if (this.doublePageSize) {
      this.pageSize = Math.max(this.pageSize * 2, 100);
    }
  } else {
    this.items = [];
    this.pageSize = this.initialPageSize;
  }
  this.isLoading = true;
  var thisRequest = {};
  this.lastRequest = thisRequest;
  var self = this;
  this.loadFunction(offset, this.pageSize, function(newItems) {
    self.itemsLoaded(newItems, thisRequest, isLoadMore, previousItems);
  });
};

ItemLoader.prototype.loadMore = function() {
  this.load(true);
};

ItemLoader.prototype.itemsLoaded = function(newItems, thisRequest,
                                            isLoadMore, previousItems) {
  if (this.lastRequest != thisRequest) {
    return;
  }
  this.isLoading = false;
  if (newItems != null) {
    if (isLoadMore) {
      this.items = previousItems.concat(newItems);
    } else {
      this.items = newItems;
    }
    this.hasMore = newItems.length == this.pageSize ||
        (this.firstPageCanBeLess && !isLoadMore && newItems.length >= 5);
  }
};
