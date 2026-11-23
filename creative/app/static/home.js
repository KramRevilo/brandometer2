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
  var cellSwitcher = document.getElementById('previewModalCells');
  var openLink = document.getElementById('previewModalOpen');
  var testBtn = document.getElementById('previewModalTest');
  var resetBtn = document.getElementById('previewModalReset');
  var statusEl = document.getElementById('previewModalStatus');
  var noteEl = document.getElementById('previewModalNote');
  if (!modalEl || !iframe || !window.bootstrap) return;

  var helpers = window.bv2PreviewTest || {};
  var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
  var canTest = modalEl.getAttribute('data-can-test') === '1';
  var testMode = canTest;
  var current = { id: '', sizes: [], size: '', cells: [], cell: '', label: '' };

  if (statusEl && helpers.bindPixelToast) helpers.bindPixelToast(statusEl);

  function parseSizes(value) {
    if (!value) return [];
    return value.split(',').map(function (part) {
      return part.trim();
    }).filter(Boolean);
  }

  function parseCells(value) {
    if (!value) return [];
    try {
      var parsed = JSON.parse(value);
      if (Array.isArray(parsed)) {
        return parsed.map(function (cell) {
          return {
            id: String((cell && cell.id) || ''),
            label: String((cell && cell.label) || (cell && cell.id) || '')
          };
        }).filter(function (cell) { return cell.id; });
      }
    } catch (err) { /* ignore */ }
    return [];
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

  function syncTestChrome() {
    if (testBtn) {
      testBtn.className = 'btn btn-sm ' + (testMode ? 'btn-primary' : 'btn-outline-secondary');
      testBtn.setAttribute('aria-pressed', testMode ? 'true' : 'false');
    }
    if (resetBtn) resetBtn.classList.toggle('d-none', !testMode);
    if (noteEl) noteEl.classList.toggle('d-none', !testMode);
    if (!testMode && helpers.clearStatus) helpers.clearStatus(statusEl);
  }

  function frameSrc() {
    var sizeArg = current.sizes.length ? current.size : '';
    if (testMode && helpers.testFrameUrl) {
      return helpers.testFrameUrl(current.id, sizeArg, current.cell);
    }
    if (helpers.embedFrameUrl) {
      return helpers.embedFrameUrl(current.id, sizeArg);
    }
    var url = '/survey/preview/' + encodeURIComponent(current.id) + '?embed=1';
    if (sizeArg) url += '&size=' + encodeURIComponent(sizeArg);
    return url;
  }

  function renderSwitcher(el, items, currentKey, onPick, labelFn) {
    if (!el) return;
    el.innerHTML = '';
    if (!items || items.length < 2) return;
    items.forEach(function (item) {
      var key = typeof item === 'string' ? item : item.id;
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn-sm ' + (key === currentKey ? 'btn-primary' : 'btn-outline-secondary');
      btn.textContent = labelFn(item);
      btn.addEventListener('click', function () { onPick(key); });
      el.appendChild(btn);
    });
  }

  function applyFrame() {
    iframe.src = frameSrc();
    setFrameSize(current.size || '300x250');
    if (titleEl) titleEl.textContent = current.label || 'Survey preview';
    if (openLink) {
      openLink.href = standaloneUrl(
          current.id, current.sizes.length > 1 ? current.size : '');
      openLink.removeAttribute('target');
      openLink.removeAttribute('rel');
    }
    renderSwitcher(switcher, current.sizes, current.size, function (key) {
      current.size = key;
      applyFrame();
    }, function (key) { return String(key).replace('x', '\u00d7'); });
    renderSwitcher(cellSwitcher, current.cells, current.cell, function (key) {
      current.cell = key;
      applyFrame();
    }, function (cell) { return cell.label || cell.id; });
    syncTestChrome();
  }

  function openPreview(id, sizes, size, label, cells) {
    current.id = id;
    current.sizes = sizes;
    current.size = size || sizes[0] || '300x250';
    current.cells = cells || [];
    current.cell = (cells && cells[0] && cells[0].id) || '';
    current.label = label || 'Survey preview';
    testMode = canTest;
    applyFrame();
    modal.show();
  }

  if (testBtn) {
    testBtn.addEventListener('click', function () {
      testMode = !testMode;
      applyFrame();
    });
  }
  if (resetBtn && helpers.reloadFrame) {
    resetBtn.addEventListener('click', function () {
      helpers.reloadFrame(iframe, statusEl);
    });
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
    var cells = parseCells(trigger.getAttribute('data-preview-cells') || '');
    openPreview(id, sizes, size, label, cells);
  });

  modalEl.addEventListener('hidden.bs.modal', function () {
    iframe.src = 'about:blank';
    if (helpers.clearStatus) helpers.clearStatus(statusEl);
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
