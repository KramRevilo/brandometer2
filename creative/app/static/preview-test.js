/* Shared toast + reset for inline Type=test preview iframes. */
(function (window) {
  'use strict';

  var SANDBOX = 'allow-scripts allow-same-origin allow-popups';

  function showStatus(statusEl, ok, text) {
    if (!statusEl) return;
    statusEl.textContent = text;
    statusEl.className = 'alert py-2 mb-2 alert-' + (ok ? 'success' : 'danger');
  }

  function clearStatus(statusEl) {
    if (!statusEl) return;
    statusEl.textContent = '';
    statusEl.className = 'alert py-2 mb-2';
  }

  function testFrameUrl(id, size, cell) {
    var url = '/survey/preview/' + encodeURIComponent(id) + '?frame=1&submit_test=1';
    if (size) url += '&size=' + encodeURIComponent(size);
    if (cell) url += '&cell=' + encodeURIComponent(cell);
    return url;
  }

  function embedFrameUrl(id, size) {
    var url = '/survey/preview/' + encodeURIComponent(id) + '?embed=1';
    if (size) url += '&size=' + encodeURIComponent(size);
    return url;
  }

  function reloadFrame(frame, statusEl) {
    if (!frame) return;
    var url = frame.getAttribute('src') || '';
    url = url.replace(/([?&])cb=[^&]*/g, '$1').replace(/[?&]$/, '');
    var sep = url.indexOf('?') >= 0 ? '&' : '?';
    frame.src = url + sep + 'cb=' + Date.now();
    clearStatus(statusEl);
  }

  function bindPixelToast(statusEl) {
    if (!statusEl || statusEl.getAttribute('data-bv2-bound') === '1') return;
    statusEl.setAttribute('data-bv2-bound', '1');
    window.addEventListener('message', function (evt) {
      var data = evt.data || {};
      if (evt.origin !== window.location.origin) return;
      if (data.source !== 'brandometer2' || data.kind !== 'pixel_result') return;
      var status = data.status;
      var ok = status >= 200 && status < 300;
      showStatus(
          statusEl,
          ok,
          'Receiver HTTP ' + status + (ok ? ' — test response saved.' : ' — not saved.'));
    });
  }

  window.bv2PreviewTest = {
    SANDBOX: SANDBOX,
    testFrameUrl: testFrameUrl,
    embedFrameUrl: embedFrameUrl,
    reloadFrame: reloadFrame,
    bindPixelToast: bindPixelToast,
    clearStatus: clearStatus
  };
})(window);
