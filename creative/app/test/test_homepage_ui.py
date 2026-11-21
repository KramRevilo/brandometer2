# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Headless homepage checks: cards below 768px, 800px table, preview modal."""

import os
import threading
import time
import unittest
from unittest import mock

import pandas

import main
import survey_service


def _playwright_or_skip():
  try:
    from playwright.sync_api import sync_playwright
    return sync_playwright
  except ImportError:
    raise unittest.SkipTest('playwright is not installed')


def _start_app(app):
  from werkzeug.serving import make_server
  server = make_server('127.0.0.1', 0, app, threaded=True)
  thread = threading.Thread(target=server.serve_forever, daemon=True)
  thread.start()
  port = server.server_port
  for _ in range(50):
    import urllib.request
    try:
      urllib.request.urlopen('http://127.0.0.1:%s/index' % port, timeout=1)
      break
    except Exception:
      time.sleep(0.1)
  return server, port


def _survey(doc_id, data):
  doc = mock.Mock()
  doc.id = doc_id
  doc.to_dict.return_value = data
  doc.exists = True
  return doc


_MULTI = {
    'surveyname': 'cola-awareness-lift',
    'displayname': 'Cola awareness (lift)',
    'surveytype': 'brand_lift',
    'client': 'Acme',
    'agency': 'Example Media',
    'created_at': '2026-11-18T12:00:00Z',
    'created_by': 'editor@example.com',
    'question1': 'Which cola brand did you notice?',
    'answer1a': 'Example Cola',
    'answer1b': 'Other Cola',
    'creativesizes': ['300x250', '970x250'],
    'responsetype': 'Submit Responses at End of Survey',
}

_TRACK = {
    'surveyname': 'snack-track',
    'displayname': 'Snack consideration',
    'surveytype': 'brand_track',
    'client': 'Northwind',
    'agency': 'Harbour Ads',
    'created_at': '2026-11-10T12:00:00Z',
    'created_by': 'admin@example.com',
    'question1': 'Would you consider this snack?',
    'answer1a': 'Yes',
    'answer1b': 'No',
    'creativesizes': ['300x250'],
    'responsetype': 'Submit Responses at End of Survey',
}


class HomepageBrowserTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    main.app.config['AUTH_BYPASS'] = True
    main.app.config['WTF_CSRF_ENABLED'] = False
    surveys = [_survey('lift-demo', _MULTI), _survey('track-two', _TRACK)]
    self._list = mock.patch.object(
        survey_service, 'list_surveys', return_value=surveys)
    self._doc = mock.patch.object(
        survey_service, 'get_doc_by_id',
        side_effect=lambda sid: _survey(sid, _MULTI if sid == 'lift-demo' else _TRACK))
    self._counts = mock.patch.object(
        survey_service, 'get_response_counts',
        return_value=pandas.DataFrame(
            columns=['ID', 'Segmentation', 'max_date', 'days_since_response',
                     'response_count']))
    self._list.start()
    self._doc.start()
    self._counts.start()
    self.addCleanup(self._list.stop)
    self.addCleanup(self._doc.stop)
    self.addCleanup(self._counts.stop)

  def tearDown(self):
    main.app.config['AUTH_BYPASS'] = False
    main.app.config['WTF_CSRF_ENABLED'] = True
    super().tearDown()

  def test_cards_below_768_table_at_800_and_preview_modal(self):
    sync_playwright = _playwright_or_skip()
    server, port = _start_app(main.app)
    base = 'http://127.0.0.1:%s' % port
    try:
      with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()

        page.set_viewport_size({'width': 767, 'height': 900})
        page.goto(base + '/index', wait_until='networkidle')
        page.wait_for_selector('#survey-cards .survey-card')
        self.assertTrue(page.locator('#survey-cards .survey-card').first.is_visible())
        self.assertFalse(page.locator('#mainTable').is_visible())
        self.assertTrue(
            page.locator('#survey-cards a.js-preview-open').first.is_visible())

        page.set_viewport_size({'width': 800, 'height': 900})
        page.wait_for_timeout(200)
        self.assertTrue(page.locator('#mainTable').is_visible())
        self.assertFalse(page.locator('#survey-cards .survey-card').first.is_visible())
        self.assertTrue(page.locator('#mainTable >> text=Client').first.is_visible())
        self.assertFalse(page.locator('#mainTable >> text=Agency').first.is_visible())
        self.assertFalse(
            page.locator('#mainTable >> text=Created by').first.is_visible())

        page.set_viewport_size({'width': 992, 'height': 900})
        page.wait_for_timeout(200)
        self.assertTrue(page.locator('#mainTable').is_visible())
        self.assertTrue(
            page.locator('#mainTable >> text=Created by').first.is_visible())
        self.assertTrue(page.locator('#mainTable >> text=Sizes').first.is_visible())
        self.assertFalse(page.locator('#mainTable >> text=Agency').first.is_visible())

        page.set_viewport_size({'width': 1200, 'height': 900})
        page.wait_for_timeout(200)
        self.assertTrue(page.locator('#mainTable >> text=Agency').first.is_visible())
        self.assertTrue(
            page.locator('#mainTable >> text=Created by').first.is_visible())

        page.set_viewport_size({'width': 1280, 'height': 900})
        page.goto(base + '/index', wait_until='networkidle')
        page.wait_for_selector('#mainTable a.js-preview-open')
        page.locator('#mainTable a.js-preview-open').first.click()
        page.wait_for_selector('#previewModal.show')
        frame = page.locator('#previewModalFrame')
        self.assertIn('embed=1', frame.get_attribute('src') or '')
        self.assertIn('/survey/preview/lift-demo', frame.get_attribute('src') or '')
        page.wait_for_function(
            """() => {
              const iframe = document.getElementById('previewModalFrame');
              try {
                const doc = iframe && iframe.contentDocument;
                return !!(doc && doc.querySelector('#master_container'));
              } catch (err) {
                return false;
              }
            }""")
        self.assertTrue(page.locator('#previewModalSizes button').count() >= 2)
        page.locator('#previewModalSizes button').nth(1).click()
        page.wait_for_function(
            """() => {
              const iframe = document.getElementById('previewModalFrame');
              return iframe && (iframe.getAttribute('src') || '').indexOf('970x250') !== -1;
            }""")
        self.assertIn('970x250', frame.get_attribute('src') or '')
        page.locator('#previewModal [data-bs-dismiss="modal"]').click()
        page.wait_for_selector('#previewModal.show', state='hidden')

        browser.close()
    finally:
      server.shutdown()

  def test_desktop_rows_are_single_line_at_1400(self):
    sync_playwright = _playwright_or_skip()
    extra = []
    for i in range(4):
      extra.append(_survey('row-%s' % i, {
          'surveyname': 'Long survey name that should truncate %s' % i,
          'displayname': 'Long survey name that should truncate %s' % i,
          'surveytype': 'brand_track',
          'client': 'Acme Worldwide International',
          'agency': 'Example Media Partners LLC',
          'created_at': '2026-11-1%sT12:00:00Z' % (i + 1),
          'created_by': 'editor.with.a.long.local-part@example.com',
          'question1': 'Which cola brand did you notice?',
          'answer1a': 'Example Cola',
          'answer1b': 'Other Cola',
          'creativesizes': ['300x250', '336x280', '970x250'],
          'responsetype': 'Submit Responses at End of Survey',
      }))
    surveys = [_survey('lift-demo', _MULTI), _survey('track-two', _TRACK)] + extra
    survey_service.list_surveys.return_value = surveys
    survey_service.get_response_counts.return_value = pandas.DataFrame({
        'ID': ['lift-demo', 'lift-demo', 'track-two'] + ['row-%s' % i for i in range(4)],
        'Segmentation': ['default_control', 'default_expose', 'survey'] + ['survey'] * 4,
        'max_date': ['2026-11-18'] * 7,
        'days_since_response': [1, 1, 2] + [1] * 4,
        'response_count': [40, 42, 24] + [8] * 4,
    })

    server, port = _start_app(main.app)
    base = 'http://127.0.0.1:%s' % port
    try:
      with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1400, 'height': 900})
        page.goto(base + '/index', wait_until='networkidle')
        page.wait_for_selector('#mainTable tbody tr')
        page.wait_for_timeout(300)
        heights = page.evaluate(
            """() => Array.from(document.querySelectorAll('#mainTable tbody tr'))
                 .map(row => Math.round(row.getBoundingClientRect().height))""")
        self.assertGreaterEqual(len(heights), 2)
        self.assertTrue(
            all(h <= 44 for h in heights),
            'row heights %s exceeded 44px' % heights)
        self.assertLessEqual(
            max(heights) - min(heights), 1,
            'row heights were not equal: %s' % heights)
        self.assertTrue(page.locator('#mainTable >> text=Agency').first.is_visible())
        self.assertTrue(page.locator('#mainTable >> text=Client').first.is_visible())
        self.assertTrue(page.locator('#mainTable >> text=C 40 · E 42').first.is_visible())
        self.assertIn('300×250 +1', page.locator('#mainTable').inner_text())
        self.assertIn('Last Rcvd', page.locator('#mainTable thead').inner_text())
        self.assertIn('Data (days)', page.locator('#mainTable thead').inner_text())
        self.assertNotIn('Loading', page.locator('#count-lift-demo').inner_text())
        self.assertNotIn('Loading', page.locator('#last-lift-demo').inner_text())
        self.assertNotIn('Loading', page.locator('#status-lift-demo').inner_text())
        browser.close()
    finally:
      server.shutdown()

  def test_stats_cells_leave_loading_after_partial(self):
    sync_playwright = _playwright_or_skip()
    survey_service.get_response_counts.return_value = pandas.DataFrame({
        'ID': ['lift-demo', 'lift-demo', 'track-two'],
        'Segmentation': ['default_control', 'default_expose', 'survey'],
        'max_date': ['2026-11-18', '2026-11-18', '2026-11-18'],
        'days_since_response': [1, 1, 2],
        'response_count': [40, 42, 24],
    })
    server, port = _start_app(main.app)
    base = 'http://127.0.0.1:%s' % port
    try:
      with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1400, 'height': 900})
        page.goto(base + '/index', wait_until='networkidle')
        page.wait_for_function(
            """() => {
              const el = document.getElementById('count-lift-demo');
              return el && el.textContent.indexOf('Loading') === -1
                  && el.textContent.indexOf('C 40') !== -1;
            }""")
        self.assertIn('C 40 · E 42', page.locator('#count-lift-demo').inner_text())
        self.assertIn('1', page.locator('#last-lift-demo').inner_text())
        self.assertIn(
            'Last received data',
            page.locator('#last-lift-demo span').get_attribute('title') or '')
        self.assertIn('Active', page.locator('#status-lift-demo').inner_text())
        self.assertNotIn('Loading', page.locator('#count-lift-demo').inner_text())
        browser.close()
    finally:
      server.shutdown()

  def test_stats_cells_show_unavailable_when_bq_fails(self):
    sync_playwright = _playwright_or_skip()
    survey_service.get_response_counts.side_effect = RuntimeError('bq down')
    server, port = _start_app(main.app)
    base = 'http://127.0.0.1:%s' % port
    try:
      with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1400, 'height': 900})
        page.goto(base + '/index', wait_until='networkidle')
        page.wait_for_function(
            """() => {
              const el = document.getElementById('count-lift-demo');
              return el && el.textContent.indexOf('Loading') === -1
                  && el.textContent.indexOf('—') !== -1;
            }""")
        self.assertIn('—', page.locator('#count-lift-demo').inner_text())
        self.assertIn('—', page.locator('#last-lift-demo').inner_text())
        self.assertIn('—', page.locator('#status-lift-demo').inner_text())
        title = page.locator('#count-lift-demo span').get_attribute('title') or ''
        self.assertIn('BigQuery', title)
        browser.close()
    finally:
      server.shutdown()
