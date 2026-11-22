# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Answer options keep per-button borders and gaps across BV2 themes."""
import os
import threading
import unittest
from unittest import mock
from wsgiref.simple_server import make_server

import css_theme
import main
import survey_service
from test_thankyou import _html, _survey


def _playwright_or_skip():
  try:
    from playwright.sync_api import sync_playwright
    return sync_playwright
  except ImportError:
    raise unittest.SkipTest('playwright is not installed')


_MEASURE_JS = """() => {
  const boxes = Array.from(document.querySelectorAll('.Abox')).filter((el) => {
    const r = el.getBoundingClientRect();
    const hidden = el.className.indexOf('invisible') !== -1
      || getComputedStyle(el).display === 'none';
    return !hidden && r.height > 0;
  });
  const next = document.getElementById('next_button');
  const ad = document.getElementById('ad_text');
  const metrics = boxes.map((el) => {
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return {
      border: parseFloat(s.borderTopWidth) || 0,
      radius: parseFloat(s.borderRadius) || 0,
      top: r.top,
      bottom: r.bottom,
      height: r.height
    };
  });
  const nextStyle = next ? getComputedStyle(next) : null;
  const adStyle = ad ? getComputedStyle(ad) : null;
  return {
    count: boxes.length,
    metrics: metrics,
    nextPadding: nextStyle ? parseFloat(nextStyle.paddingLeft) || 0 : 0,
    nextBorder: nextStyle ? parseFloat(nextStyle.borderTopWidth) || 0 : 0,
    adFont: adStyle ? adStyle.fontFamily : ''
  };
}"""


class AnswerBoxChromeTest(unittest.TestCase):

  def test_theme_only_css_still_declares_borders(self):
    for preset in css_theme.STYLE_PRESETS[:6]:
      css = css_theme.combine_css(preset, '')
      self.assertIn('border: 1px solid rgba(0, 0, 0, 0.35)', css, preset['id'])
      html = _html(_survey(
          answers=4, size='300x600',
          extra={'custom_css': css, 'creativesize': '300x600'}))
      self.assertIn('gap: 6px', html, preset['id'])
      self.assertIn('border: 1px solid rgba(0, 0, 0, 0.35)', html, preset['id'])

  def test_preview_answer_boxes_have_borders_and_gaps_across_themes(self):
    sync_playwright = _playwright_or_skip()
    presets = [item for item in css_theme.STYLE_PRESETS
               if item['id'] in ('classic', 'dark', 'electric-cyan', 'hot-pink')]
    self.assertEqual(len(presets), 4)

    main.app.config['AUTH_BYPASS'] = True
    main.app.config['WTF_CSRF_ENABLED'] = False
    server = make_server('127.0.0.1', 0, main.app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_port
    try:
      with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 400, 'height': 700})
        for preset in presets:
          css = css_theme.combine_css(preset, '')
          survey = _survey(
              answers=4, size='300x600',
              extra={'custom_css': css, 'creativesize': '300x600'})

          class Doc(object):
            id = 'sid'
            exists = True
            def to_dict(self):
              return survey
            def get(self, key, default=None):
              return survey.get(key, default)

          with mock.patch.object(
              survey_service, 'get_doc_by_id', return_value=Doc()):
            page.goto(
                'http://127.0.0.1:%s/survey/preview/sid?size=300x600'
                % port,
                wait_until='networkidle')
            page.wait_for_selector('.Abox')
            measured = page.evaluate(_MEASURE_JS)
          self.assertGreaterEqual(measured['count'], 3, preset['id'])
          for item in measured['metrics']:
            self.assertGreaterEqual(item['border'], 1, preset['id'])
            self.assertGreaterEqual(item['radius'], 4, preset['id'])
            self.assertGreater(item['height'], 10, preset['id'])
          for left, right in zip(
              measured['metrics'], measured['metrics'][1:]):
            gap = right['top'] - left['bottom']
            self.assertGreaterEqual(gap, 4, '%s gap=%s' % (preset['id'], gap))
          self.assertGreaterEqual(measured['nextPadding'], 8, preset['id'])
          self.assertGreaterEqual(measured['nextBorder'], 1, preset['id'])
          self.assertRegex(measured['adFont'], r'Arial|Helvetica|sans-serif')
        browser.close()
    finally:
      server.shutdown()
      main.app.config['AUTH_BYPASS'] = False
      main.app.config['WTF_CSRF_ENABLED'] = True
