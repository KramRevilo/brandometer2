/* Homepage list: stats-partial error fallback, then preview modal. */
(function () {
  var UNAVAILABLE =
      '<span class="text-muted" title="Could not load response counts from BigQuery" aria-label="unavailable">—</span>';

  function markStatsUnavailable() {
    document.querySelectorAll('[data-stats-pending]').forEach(function (el) {
      el.removeAttribute('data-stats-pending');
      el.innerHTML = UNAVAILABLE;
    });
  }

  function isStatsPoller(evt) {
    return evt.detail && evt.detail.elt && evt.detail.elt.id === 'stats-poller';
  }

  document.body.addEventListener('htmx:responseError', function (evt) {
    if (isStatsPoller(evt)) markStatsUnavailable();
  });
  document.body.addEventListener('htmx:sendError', function (evt) {
    if (isStatsPoller(evt)) markStatsUnavailable();
  });
  document.body.addEventListener('htmx:timeout', function (evt) {
    if (isStatsPoller(evt)) markStatsUnavailable();
  });
})();

(function () {
  var modalEl = document.getElementById('previewModal');
  var iframe = document.getElementById('previewModalFrame');
  var titleEl = document.getElementById('previewModalLabel');
  var switcher = document.getElementById('previewModalSizes');
  var openLink = document.getElementById('previewModalOpen');
  if (!modalEl || !iframe || !window.bootstrap) return;

  var modal = bootstrap.Modal.getOrCreateInstance(modalEl);

  function parseSizes(value) {
    if (!value) return [];
    return value.split(',').map(function (part) {
      return part.trim();
    }).filter(Boolean);
  }

  function previewUrl(id, size) {
    var url = '/survey/preview/' + encodeURIComponent(id) + '?embed=1';
    if (size) url += '&size=' + encodeURIComponent(size);
    return url;
  }

  function standaloneUrl(id, size) {
    var url = '/survey/preview/' + encodeURIComponent(id);
    if (size) url += '?size=' + encodeURIComponent(size);
    return url;
  }

  function sizeDims(key) {
    var parts = String(key || '300x250').split('x');
    var width = parseInt(parts[0], 10);
    var height = parseInt(parts[1], 10);
    return {
      w: width > 0 ? width : 300,
      h: height > 0 ? height : 250
    };
  }

  function setFrameSize(key) {
    var dims = sizeDims(key);
    iframe.style.width = dims.w + 'px';
    iframe.style.height = dims.h + 'px';
  }

  function openPreview(id, sizes, size, label) {
    var chosen = size || sizes[0] || '300x250';
    iframe.src = previewUrl(id, sizes.length ? chosen : '');
    setFrameSize(chosen);
    if (titleEl) titleEl.textContent = label || 'Survey preview';
    if (openLink) {
      openLink.href = standaloneUrl(id, sizes.length > 1 ? chosen : '');
    }
    if (switcher) {
      switcher.innerHTML = '';
      if (sizes.length > 1) {
        sizes.forEach(function (key) {
          var btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'btn btn-sm ' + (key === chosen ? 'btn-primary' : 'btn-outline-secondary');
          btn.textContent = key.replace('x', '\u00d7');
          btn.setAttribute('data-preview-size', key);
          btn.addEventListener('click', function () {
            openPreview(id, sizes, key, label);
          });
          switcher.appendChild(btn);
        });
      }
    }
    modal.show();
  }

  document.addEventListener('click', function (evt) {
    var trigger = evt.target.closest('[data-preview-id]');
    if (!trigger) return;
    if (evt.defaultPrevented || evt.button !== 0) return;
    if (evt.metaKey || evt.ctrlKey || evt.shiftKey || evt.altKey) return;
    evt.preventDefault();
    var id = trigger.getAttribute('data-preview-id');
    var sizes = parseSizes(trigger.getAttribute('data-preview-sizes'));
    var size = trigger.getAttribute('data-preview-size') || '';
    var label = trigger.getAttribute('data-preview-label') || 'Survey preview';
    openPreview(id, sizes, size, label);
  });

  modalEl.addEventListener('hidden.bs.modal', function () {
    iframe.src = 'about:blank';
  });
})();

(function () {
  var button = document.getElementById('compare-selected');
  if (!button) return;
  var MAX = 30;

  function selectedIds() {
    var seen = {};
    var ids = [];
    document.querySelectorAll('.js-compare-id:checked').forEach(function (box) {
      var id = (box.value || '').trim();
      if (!id || seen[id]) return;
      seen[id] = true;
      ids.push(id);
    });
    return ids.slice(0, MAX);
  }

  function sync() {
    var n = selectedIds().length;
    button.disabled = n < 1;
    button.textContent = n ? ('Compare selected (' + n + ')') : 'Compare selected';
  }

  document.addEventListener('change', function (evt) {
    if (evt.target && evt.target.classList && evt.target.classList.contains('js-compare-id')) {
      sync();
    }
  });
  button.addEventListener('click', function () {
    var ids = selectedIds();
    if (!ids.length) return;
    window.location.href = '/reports/compare?ids=' + encodeURIComponent(ids.join(','));
  });
  sync();
})();
