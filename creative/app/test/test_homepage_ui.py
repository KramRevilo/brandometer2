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
    def _docs_for_ids(ids):
      by_id = {item.id: item for item in survey_service.list_surveys.return_value}
      return [by_id[sid] for sid in ids if sid in by_id]
    self._list_docs = mock.patch.object(
        survey_service, 'get_list_docs_by_ids', side_effect=_docs_for_ids)
    self._list_docs.start()
    self.addCleanup(self._list.stop)
    self.addCleanup(self._doc.stop)
    self.addCleanup(self._counts.stop)
    self.addCleanup(self._list_docs.stop)

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
        self.assertTrue(page.locator('#mainTable >> text=Status').first.is_visible())
        self.assertTrue(page.locator('#mainTable >> text=Result').first.is_visible())
        self.assertFalse(page.locator('#mainTable >> text=Agency').first.is_visible())
        self.assertFalse(
            page.locator('#mainTable >> text=Created by').first.is_visible())
        self.assertFalse(page.locator('#mainTable >> text=Sizes').first.is_visible())
        self.assertFalse(page.locator('#mainTable >> text=Count').first.is_visible())

        page.set_viewport_size({'width': 992, 'height': 900})
        page.wait_for_timeout(200)
        self.assertTrue(page.locator('#mainTable').is_visible())
        self.assertTrue(page.locator('#mainTable >> text=Count').first.is_visible())
        self.assertTrue(page.locator('#mainTable >> text=Last Rcvd').first.is_visible())
        self.assertFalse(
            page.locator('#mainTable >> text=Created by').first.is_visible())
        self.assertFalse(page.locator('#mainTable >> text=Sizes').first.is_visible())
        self.assertFalse(page.locator('#mainTable >> text=Agency').first.is_visible())

        page.set_viewport_size({'width': 1200, 'height': 900})
        page.wait_for_timeout(200)
        self.assertTrue(page.locator('#mainTable >> text=Agency').first.is_visible())
        self.assertTrue(
            page.locator('#mainTable >> text=Created by').first.is_visible())
        self.assertFalse(page.locator('#mainTable >> text=Sizes').first.is_visible())
        self.assertFalse(page.locator('#mainTable >> text=Progress').first.is_visible())

        page.set_viewport_size({'width': 1400, 'height': 900})
        page.wait_for_timeout(200)
        self.assertTrue(page.locator('#mainTable >> text=Sizes').first.is_visible())
        self.assertTrue(page.locator('#mainTable >> text=Progress').first.is_visible())

        page.set_viewport_size({'width': 1280, 'height': 900})
        page.goto(base + '/index', wait_until='networkidle')
        page.wait_for_selector('#mainTable a.js-preview-open')
        page.locator('#mainTable a.js-preview-open').first.click()
        page.wait_for_selector('#previewModal.show')
        frame = page.locator('#previewModalFrame')
        src = frame.get_attribute('src') or ''
        self.assertIn('/survey/preview/lift-demo', src)
        self.assertIn('frame=1', src)
        self.assertIn('submit_test=1', src)
        self.assertNotIn('embed=1', src)
        self.assertTrue(page.locator('#previewModalTest').is_visible())
        self.assertEqual(
            page.locator('#previewModalOpen').get_attribute('target'), None)
        page.locator('#previewModalTest').click()
        page.wait_for_function(
            """() => {
              const iframe = document.getElementById('previewModalFrame');
              return iframe && (iframe.getAttribute('src') || '').indexOf('embed=1') !== -1;
            }""")
        page.locator('#previewModalTest').click()
        page.wait_for_function(
            """() => {
              const iframe = document.getElementById('previewModalFrame');
              return iframe && (iframe.getAttribute('src') || '').indexOf('submit_test=1') !== -1;
            }""")
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

  def test_table_fits_without_horizontal_overflow(self):
    sync_playwright = _playwright_or_skip()
    extra = []
    for i in range(3):
      extra.append(_survey('wide-%s' % i, {
          'surveyname': (
              'Extremely long survey display name that must ellipsis '
              'instead of stretching the row %s' % i),
          'displayname': (
              'Extremely long survey display name that must ellipsis '
              'instead of stretching the row %s' % i),
          'surveytype': 'brand_track',
          'client': 'Acme Worldwide International Holdings Group',
          'agency': 'Example Media Partners LLC North America',
          'created_at': '2026-11-1%sT12:00:00Z' % (i + 1),
          'created_by': 'editor.with.a.very.long.local-part@example.com',
          'question1': 'Which cola brand did you notice?',
          'answer1a': 'Example Cola',
          'creativesizes': ['300x250', '336x280', '970x250'],
          'responsetype': 'Submit Responses at End of Survey',
      }))
    surveys = [_survey('lift-demo', _MULTI), _survey('track-two', _TRACK)] + extra
    survey_service.list_surveys.return_value = surveys
    survey_service.get_response_counts.return_value = pandas.DataFrame({
        'ID': ['lift-demo', 'lift-demo', 'track-two'] + [
            'wide-%s' % i for i in range(3)],
        'Segmentation': ['default_control', 'default_expose', 'survey'] + [
            'survey'] * 3,
        'max_date': ['2026-11-18'] * 6,
        'days_since_response': [1, 1, 2, 1, 1, 1],
        'response_count': [40, 42, 24, 8, 8, 8],
        'n_q1': [40, 42, 24, 8, 8, 8],
        'k_q1_a': [20, 21, 12, 4, 4, 4],
    })

    server, port = _start_app(main.app)
    base = 'http://127.0.0.1:%s' % port
    try:
      with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1400, 'height': 900})
        page.goto(base + '/index', wait_until='networkidle')
        page.wait_for_selector('#survey-table-wrap')
        for width in (768, 1024, 1280, 1400, 1920):
          page.set_viewport_size({'width': width, 'height': 900})
          page.wait_for_timeout(250)
          metrics = page.evaluate(
              """() => {
                const wrap = document.getElementById('survey-table-wrap');
                const table = document.getElementById('mainTable');
                const row = document.querySelector('#mainTable tbody tr');
                return {
                  wrapScroll: wrap.scrollWidth,
                  wrapClient: wrap.clientWidth,
                  tableScroll: table.scrollWidth,
                  tableClient: table.clientWidth,
                  rowHeight: row ? Math.round(row.getBoundingClientRect().height) : 0,
                  visible: !!(wrap && wrap.offsetParent !== null),
                };
              }""")
          self.assertTrue(
              metrics['visible'],
              'table hidden at %spx: %s' % (width, metrics))
          self.assertLessEqual(
              metrics['wrapScroll'], metrics['wrapClient'] + 1,
              'wrapper overflow at %spx: %s' % (width, metrics))
          self.assertLessEqual(
              metrics['tableScroll'], metrics['wrapClient'] + 1,
              'table overflow at %spx: %s' % (width, metrics))
          self.assertTrue(
              metrics['rowHeight'] <= 44,
              'row height %s at %spx' % (metrics['rowHeight'], width))
        name = page.locator('#mainTable tbody tr td.cell-name').first
        self.assertTrue(name.get_attribute('title'))
        browser.close()
    finally:
      server.shutdown()

  def test_status_filter_active_only_across_pages(self):
    sync_playwright = _playwright_or_skip()
    surveys = []
    ids = []
    days = []
    for i in range(3):
      sid = 'active-%s' % i
      ids.append(sid)
      days.append(1)
      surveys.append(_survey(sid, {
          'surveyname': 'Active seed %s' % i,
          'displayname': 'Active seed %s' % i,
          'surveytype': 'brand_track',
          'client': 'Acme',
          'agency': 'Example Media',
          'created_at': '2026-11-2%sT12:00:00Z' % i,
          'created_by': 'editor@example.com',
          'question1': 'Q',
          'answer1a': 'A',
          'answer1b': 'B',
          'creativesizes': ['300x250'],
          'responsetype': 'Submit Responses at End of Survey',
      }))
    surveys.append(_survey('stale-0', {
        'surveyname': 'Stale seed',
        'displayname': 'Stale seed',
        'surveytype': 'brand_track',
        'client': 'Acme',
        'agency': 'Example Media',
        'created_at': '2026-11-10T12:00:00Z',
        'created_by': 'editor@example.com',
        'question1': 'Q',
        'answer1a': 'A',
        'answer1b': 'B',
        'creativesizes': ['300x250'],
        'responsetype': 'Submit Responses at End of Survey',
    }))
    surveys.append(_survey('empty-0', {
        'surveyname': 'No data seed',
        'displayname': 'No data seed',
        'surveytype': 'brand_track',
        'client': 'Acme',
        'agency': 'Example Media',
        'created_at': '2026-11-08T12:00:00Z',
        'created_by': 'editor@example.com',
        'question1': 'Q',
        'answer1a': 'A',
        'answer1b': 'B',
        'creativesizes': ['300x250'],
        'responsetype': 'Submit Responses at End of Survey',
    }))
    survey_service.list_surveys.return_value = surveys
    survey_service.get_response_counts.return_value = pandas.DataFrame({
        'ID': ids + ['stale-0'],
        'Segmentation': ['survey'] * 4,
        'max_date': ['2026-11-22'] * 4,
        'days_since_response': days + [6],
        'response_count': [8, 8, 8, 8],
    })

    with mock.patch.object(survey_service, 'HOMEPAGE_PAGE_SIZE', 2):
      server, port = _start_app(main.app)
      base = 'http://127.0.0.1:%s' % port
      try:
        with sync_playwright() as playwright:
          browser = playwright.chromium.launch(headless=True)
          page = browser.new_page(viewport={'width': 1400, 'height': 900})
          page.goto(base + '/index?status=active', wait_until='networkidle')
          page.wait_for_selector('#mainTable')
          table = page.locator('#mainTable').inner_text()
          self.assertIn('Active seed 2', table)
          self.assertIn('Active seed 1', table)
          self.assertNotIn('Active seed 0', table)
          self.assertNotIn('Stale seed', table)
          self.assertNotIn('No data seed', table)
          self.assertIn('3 surveys', page.locator('body').inner_text())
          self.assertEqual(page.locator('#filter-status').input_value(), 'active')
          page.locator('a.page-link', has_text='Next').click()
          page.wait_for_function(
              """() => {
                const q = window.location.search;
                return q.indexOf('page=2') !== -1
                    && q.indexOf('status=active') !== -1
                    && document.body.innerText.indexOf('Active seed 0') !== -1;
              }""")
          table2 = page.locator('#mainTable').inner_text()
          self.assertIn('Active seed 0', table2)
          self.assertNotIn('Active seed 2', table2)
          self.assertNotIn('Stale seed', table2)
          self.assertNotIn('No data seed', table2)
          cards = page.locator('#survey-cards .survey-card')
          page.set_viewport_size({'width': 767, 'height': 900})
          page.wait_for_timeout(200)
          self.assertTrue(cards.first.is_visible())
          card_text = page.locator('#survey-cards').inner_text()
          self.assertIn('Active seed 0', card_text)
          self.assertNotIn('Stale seed', card_text)
          browser.close()
      finally:
        server.shutdown()

  def test_progress_result_sort_on_seeded_lift_surveys(self):
    sync_playwright = _playwright_or_skip()
    plan = {'n_control': 100, 'n_expose': 100}
    surveys = []
    counts_ids = []
    segs = []
    ns = []
    ks = []
    for sid, n, created in (
        ('prog-low', 20, '2026-11-22T12:00:00Z'),
        ('prog-mid', 50, '2026-11-21T12:00:00Z'),
        ('prog-high', 90, '2026-11-20T12:00:00Z'),
    ):
      surveys.append(_survey(sid, {
          'surveyname': 'Progress %s' % sid,
          'displayname': 'Progress %s' % sid,
          'surveytype': 'brand_lift',
          'client': 'Acme',
          'agency': 'Example Media',
          'created_at': created,
          'created_by': 'editor@example.com',
          'question1': 'Q',
          'answer1a': 'A',
          'creativesizes': ['300x250'],
          'sample_plan': plan,
      }))
      counts_ids.extend([sid, sid])
      segs.extend(['default_control', 'default_expose'])
      ns.extend([n, n])
      ks.extend([max(1, n // 4), max(1, n // 2)])
    surveys.append(_survey('prog-empty', {
        'surveyname': 'Progress empty',
        'displayname': 'Progress empty',
        'surveytype': 'brand_lift',
        'client': 'Acme',
        'agency': 'Example Media',
        'created_at': '2026-11-23T12:00:00Z',
        'created_by': 'editor@example.com',
        'question1': 'Q',
        'creativesizes': ['300x250'],
    }))
    survey_service.list_surveys.return_value = surveys
    survey_service.get_response_counts.return_value = pandas.DataFrame({
        'ID': counts_ids,
        'Segmentation': segs,
        'max_date': ['2026-11-22'] * len(counts_ids),
        'days_since_response': [1] * len(counts_ids),
        'response_count': ns,
        'n_q1': ns,
        'k_q1_a': ks,
    })

    server, port = _start_app(main.app)
    base = 'http://127.0.0.1:%s' % port
    try:
      with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1400, 'height': 900})
        page.goto(base + '/index?sort=progress&dir=asc', wait_until='networkidle')
        page.wait_for_selector('#mainTable')
        names = page.evaluate(
            """() => Array.from(document.querySelectorAll('#mainTable tbody tr td.cell-name'))
                 .map(el => el.textContent.trim())""")
        self.assertEqual(
            names,
            ['Progress prog-low', 'Progress prog-mid', 'Progress prog-high',
             'Progress empty'])
        self.assertIn('20%', page.locator('#progress-prog-low').inner_text())
        self.assertIn('50%', page.locator('#progress-prog-mid').inner_text())
        self.assertIn('90%', page.locator('#progress-prog-high').inner_text())
        self.assertIn('—', page.locator('#progress-prog-empty').inner_text())
        page.locator('a.sort-link', has_text='Progress').click()
        page.wait_for_function(
            """() => {
              const q = window.location.search;
              return q.indexOf('sort=progress') !== -1 && q.indexOf('dir=desc') !== -1;
            }""")
        names_desc = page.evaluate(
            """() => Array.from(document.querySelectorAll('#mainTable tbody tr td.cell-name'))
                 .map(el => el.textContent.trim())""")
        self.assertEqual(
            names_desc,
            ['Progress prog-high', 'Progress prog-mid', 'Progress prog-low',
             'Progress empty'])
        page.set_viewport_size({'width': 767, 'height': 900})
        page.wait_for_timeout(200)
        cards = page.locator('#survey-cards').inner_text()
        self.assertIn('Progress:', cards)
        self.assertTrue(
            page.locator('#progress-card-prog-high').is_visible())
        self.assertTrue(
            page.locator('#result-card-prog-high').is_visible())
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

  def test_submit_test_response_hits_receiver_and_homepage_count(self):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlparse

    sync_playwright = _playwright_or_skip()
    hits = []

    class Handler(BaseHTTPRequestHandler):
      def _reply(self):
        hits.append(self.path)
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

      def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.end_headers()

      def do_GET(self):
        self._reply()

      def do_POST(self):
        self._reply()

      def log_message(self, *_args):
        pass

    recv = HTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=recv.serve_forever, daemon=True).start()
    recv_url = 'http://127.0.0.1:%s/pixel' % recv.server_address[1]
    empty = pandas.DataFrame(
        columns=['ID', 'Segmentation', 'max_date', 'days_since_response',
                 'response_count'])
    filled = pandas.DataFrame({
        'ID': ['track-two'],
        'Segmentation': ['survey'],
        'Type': ['test'],
        'max_date': ['2026-11-22'],
        'days_since_response': [0],
        'response_count': [5],
    })

    def counts(survey_ids=None, include_test=False):
      del survey_ids
      return filled if include_test else empty

    survey_service.get_response_counts.side_effect = counts
    main.app.config['RECEIVER_HMAC_SECRET'] = 'unit-hmac-secret'
    server, port = _start_app(main.app)
    base = 'http://127.0.0.1:%s' % port
    try:
      with mock.patch.dict(os.environ, {'RECEIVER_URL': recv_url}):
        with sync_playwright() as playwright:
          browser = playwright.chromium.launch(headless=True)
          page = browser.new_page(viewport={'width': 1400, 'height': 900})
          page.goto(
              base + '/survey/preview/track-two', wait_until='networkidle')
          page.wait_for_selector('#preview-test-frame')
          self.assertTrue(page.locator('#preview-reset').is_visible())
          frame = page.frame_locator('#preview-test-frame')
          frame.locator('#option_container_0').click()
          frame.locator('#thankyou_container.thankyoucontainer').wait_for()
          page.wait_for_selector('#preview-test-status.alert-success')
          self.assertIn(
              'HTTP 204', page.locator('#preview-test-status').inner_text())
          for _ in range(25):
            if hits:
              break
            time.sleep(0.1)
          self.assertTrue(hits, 'receiver mock got no pixel request')
          query = parse_qs(urlparse(hits[0]).query)
          if not query:
            query = parse_qs(hits[0].split('?', 1)[-1])
          self.assertEqual(query.get('type', [''])[0], 'test')
          self.assertEqual(query.get('id', [''])[0], 'track-two')
          self.assertEqual(query.get('seg', [''])[0], 'preview')
          self.assertTrue(query.get('token', [''])[0])
          self.assertTrue(query.get('sub', [''])[0])
          rid = query.get('rid', [''])[0] or query.get('bomid', [''])[0]
          self.assertTrue(rid.startswith('test_'), rid)
          self.assertLessEqual(len(hits), 1)
          page.locator('#preview-reset').click()
          page.wait_for_function(
              """() => {
                const el = document.getElementById('preview-test-status');
                return el && !el.classList.contains('alert-success');
              }""")

          page.goto(base + '/index', wait_until='networkidle')
          page.wait_for_selector('#filter-include-test')
          page.wait_for_timeout(400)
          count = page.locator('#count-track-two').inner_text()
          self.assertNotIn('incl. test', count)
          self.assertNotIn('T 5', count)
          self.assertFalse(page.locator('#filter-include-test').is_checked())
          page.locator('#filter-include-test').check()
          page.wait_for_function(
              """() => location.search.indexOf('include_test=1') !== -1""")
          page.wait_for_function(
              """() => {
                const el = document.getElementById('count-track-two');
                return el && el.textContent.indexOf('T 5') !== -1
                    && el.textContent.indexOf('incl. test') === -1;
              }""")
          poller = page.locator('#stats-poller').get_attribute('hx-get') or ''
          self.assertIn('include_test=1', poller)
          browser.close()
    finally:
      server.shutdown()
      recv.shutdown()
      main.app.config['RECEIVER_HMAC_SECRET'] = ''
