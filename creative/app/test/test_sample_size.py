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

import datetime
import math
import os
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

import pandas

import main
import reporting
import sample_size
import survey_service
import ui_help

_ARTIFACT_DIR = '/opt/cursor/artifacts'
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
_DOCS_IMAGES = os.path.join(_REPO_ROOT, 'docs', 'images')


class SampleSizeMathTest(unittest.TestCase):

  def test_norm_ppf_matches_z95_and_power80(self):
    self.assertAlmostEqual(sample_size.norm_ppf(0.975), reporting.Z_95, places=5)
    self.assertAlmostEqual(sample_size.norm_ppf(0.8), 0.841621, places=4)
    self.assertAlmostEqual(sample_size.norm_cdf(0.0), 0.5, places=12)

  def test_equal_n_matches_hand_formula(self):
    # p0=0.20, p1=0.30 (10 pp / 50% relative), α=0.05, 80% power, 50/50.
    p0, p1 = 0.20, 0.30
    k = 1.0
    pbar = (p0 + k * p1) / (1 + k)
    z_a = sample_size.norm_ppf(0.975)
    z_b = sample_size.norm_ppf(0.80)
    se_null = math.sqrt((1 + 1 / k) * pbar * (1 - pbar))
    se_alt = math.sqrt(p0 * (1 - p0) + p1 * (1 - p1) / k)
    n_c = ((z_a * se_null + z_b * se_alt) / (p1 - p0)) ** 2
    expected = max(reporting.MIN_N, int(math.ceil(n_c - 1e-9)))
    result = sample_size.required_n(sample_size.parse_inputs({
        'baseline': 0.20,
        'mde_mode': 'absolute',
        'mde_absolute': 0.10,
        'confidence': 0.95,
        'power': 0.80,
        'comparisons': 1,
        'control_share': 0.50,
        'response_rate': 0.01,
    }))
    self.assertIsNone(result['error'])
    self.assertEqual(result['n_control'], expected)
    self.assertEqual(result['n_expose'], expected)
    self.assertGreater(result['n_control'], 250)
    self.assertLess(result['n_control'], 400)
    self.assertEqual(
        result['impressions_control'],
        int(math.ceil(result['n_control'] / 0.01)))

  def test_min_n_floor_and_holm_alpha(self):
    huge = sample_size.required_n(sample_size.parse_inputs({
        'baseline': 0.10,
        'mde_mode': 'absolute',
        'mde_absolute': 0.70,
        'confidence': 0.95,
        'power': 0.80,
        'comparisons': 1,
        'control_share': 0.50,
        'response_rate': 1.0,
    }))
    self.assertEqual(huge['n_control'], reporting.MIN_N)
    self.assertTrue(huge['min_n_applied'])

    one = sample_size.required_n(sample_size.parse_inputs({
        'baseline': 0.20, 'mde_mode': 'relative', 'mde_relative': 0.10,
        'confidence': 0.95, 'power': 0.80, 'comparisons': 1,
        'control_share': 0.50, 'response_rate': 0.01,
    }))
    many = sample_size.required_n(sample_size.parse_inputs({
        'baseline': 0.20, 'mde_mode': 'relative', 'mde_relative': 0.10,
        'confidence': 0.95, 'power': 0.80, 'comparisons': 8,
        'control_share': 0.50, 'response_rate': 0.01,
    }))
    self.assertGreater(many['n_total'], one['n_total'])
    self.assertAlmostEqual(many['alpha'], 0.05 / 8.0, places=8)

  def test_percent_inputs_and_unequal_split(self):
    parsed = sample_size.parse_inputs({
        'baseline': 20,
        'mde_relative': 10,
        'confidence': 95,
        'power': 80,
        'response_rate': 1,
        'control_share': 30,
        'comparisons': 2,
    })
    self.assertAlmostEqual(parsed['baseline'], 0.20)
    self.assertAlmostEqual(parsed['control_share'], 0.30)
    result = sample_size.required_n(parsed)
    self.assertLess(result['n_control'], result['n_expose'])

  def test_table_includes_selected_mde(self):
    computed = sample_size.compute({
        'baseline': 0.2, 'mde_mode': 'relative', 'mde_relative': 0.12,
    })
    selected = [row for row in computed['table'] if row.get('is_selected')]
    self.assertEqual(len(selected), 1)
    self.assertAlmostEqual(selected[0]['grid_value'], 0.12)


class SampleSizeRouteTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    main.app.config['AUTH_BYPASS'] = True
    main.app.config['WTF_CSRF_ENABLED'] = False
    self.client = main.app.test_client()

  def tearDown(self):
    main.app.config['AUTH_BYPASS'] = False
    main.app.config['WTF_CSRF_ENABLED'] = True
    super().tearDown()

  def test_standalone_planner_renders_defaults_and_help(self):
    response = self.client.get('/survey/sample-size')
    self.assertEqual(response.status_code, 200)
    html = response.data.decode('utf-8')
    self.assertIn('Sample-size planner', html)
    self.assertIn('What does this mean?', html)
    self.assertIn(ui_help.ENTRIES['plan.baseline']['body'], html)
    self.assertIn(ui_help.ENTRIES['plan.n']['body'], html)
    self.assertIn('data-bs-toggle="collapse"', html)
    csp = response.headers.get('Content-Security-Policy', '')
    self.assertIn("default-src 'self'", csp)
    self.assertNotIn('cdn.jsdelivr', html)
    self.assertIn('Required sample', html)

  def test_calculate_query_changes_n(self):
    small = self.client.get(
        '/survey/sample-size?baseline=20&mde_mode=relative&mde_relative=25'
        '&confidence=0.95&power=0.8&comparisons=1&response_rate=1&control_share=50')
    large = self.client.get(
        '/survey/sample-size?baseline=20&mde_mode=relative&mde_relative=5'
        '&confidence=0.95&power=0.8&comparisons=1&response_rate=1&control_share=50')
    self.assertEqual(small.status_code, 200)
    self.assertIn(b'Required sample', large.data)
    self.assertGreater(len(large.data), 100)

  def test_viewer_can_get_but_not_post_save(self):
    doc = mock.Mock()
    doc.exists = True
    doc.id = 's1'
    doc.to_dict.return_value = {
        'surveyname': 'Lift', 'surveytype': 'brand_lift',
        'question1': 'Q', 'answer1a': 'Yes',
    }
    with mock.patch.object(survey_service, 'get_doc_by_id', return_value=doc):
      with mock.patch.object(survey_service, 'save_sample_plan') as save_mock:
        main.app.config['AUTH_BYPASS'] = False
        client = main.app.test_client()
        with client.session_transaction() as sess:
          sess['user_email'] = 'viewer@agency.example'
          sess['user_role'] = 'viewer'
          sess['user_name'] = 'Vic'
        get_ok = client.get('/survey/sample-size/s1')
        self.assertEqual(get_ok.status_code, 200)
        self.assertNotIn(b'Save plan on this survey', get_ok.data)
        post = client.post(
            '/survey/sample-size/s1',
            data={'baseline': '0.2', 'mde_mode': 'relative', 'mde_relative': '0.1',
                  'confidence': '0.95', 'power': '0.8', 'comparisons': '1',
                  'response_rate': '0.01', 'control_share': '0.5'})
        self.assertEqual(post.status_code, 403)
        save_mock.assert_not_called()

  def test_editor_save_stores_plan(self):
    doc = mock.Mock()
    doc.exists = True
    doc.id = 's1'
    doc.to_dict.return_value = {'surveyname': 'Lift', 'surveytype': 'brand_lift'}
    with mock.patch.object(survey_service, 'get_doc_by_id', return_value=doc):
      with mock.patch.object(survey_service, 'save_sample_plan') as save_mock:
        save_mock.return_value = {'n_control': 400}
        response = self.client.post(
            '/survey/sample-size/s1',
            data={'baseline': '0.2', 'mde_mode': 'relative', 'mde_relative': '0.1',
                  'confidence': '0.95', 'power': '0.8', 'comparisons': '1',
                  'response_rate': '0.01', 'control_share': '0.5'},
            follow_redirects=False)
    self.assertEqual(response.status_code, 302)
    save_mock.assert_called_once()
    stored = save_mock.call_args[0][1]
    self.assertGreaterEqual(stored['n_control'], reporting.MIN_N)
    self.assertGreaterEqual(stored['n_expose'], reporting.MIN_N)


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
      urllib.request.urlopen(
          'http://127.0.0.1:%s/survey/sample-size' % port, timeout=1)
      break
    except Exception:
      time.sleep(0.1)
  return server, port


def _optimize_png(path, max_width=1200):
  try:
    from PIL import Image
  except ImportError:
    return
  image = Image.open(path)
  if max_width and image.width > max_width:
    ratio = max_width / float(image.width)
    image = image.resize(
        (max_width, max(1, int(image.height * ratio))), Image.Resampling.LANCZOS)
  if image.mode == 'RGBA':
    background = Image.new('RGB', image.size, (248, 249, 250))
    background.paste(image, mask=image.split()[-1])
    image = background
  elif image.mode != 'RGB':
    image = image.convert('RGB')
  image.save(path, format='PNG', optimize=True)


class PlannerScreenshotTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    main.app.config['AUTH_BYPASS'] = True
    main.app.config['WTF_CSRF_ENABLED'] = False

  def tearDown(self):
    main.app.config['AUTH_BYPASS'] = False
    main.app.config['WTF_CSRF_ENABLED'] = True
    super().tearDown()

  def _write_shot(self, locator, filename):
    os.makedirs(_ARTIFACT_DIR, exist_ok=True)
    os.makedirs(_DOCS_IMAGES, exist_ok=True)
    tmp = os.path.join(tempfile.gettempdir(), filename)
    locator.screenshot(path=tmp)
    _optimize_png(tmp)
    artifact = os.path.join(_ARTIFACT_DIR, filename)
    docs = os.path.join(_DOCS_IMAGES, filename)
    shutil.copyfile(tmp, artifact)
    shutil.copyfile(tmp, docs)
    self.assertGreater(os.path.getsize(artifact), 1000)
    return artifact

  def test_headless_planner_and_sequential_screenshots(self):
    sync_playwright = _playwright_or_skip()
    t = datetime.datetime(2026, 11, 18, 12, 0, 0)
    rows = []
    for i in range(40):
      rows.append({
          'CreatedAt': t, 'Segmentation': 'default_control',
          'Response': '1:A' if i % 3 else '1:B', 'BomID': 'c-%02d' % i,
      })
    for i in range(42):
      rows.append({
          'CreatedAt': t, 'Segmentation': 'default_expose',
          'Response': '1:A' if i % 2 else '1:B', 'BomID': 'e-%02d' % i,
      })
    df = pandas.DataFrame(rows)
    survey_doc = mock.Mock()
    survey_doc.id = 'abc'
    survey_doc.exists = True
    survey_doc.to_dict.return_value = {
        'surveytype': 'brand_lift',
        'surveyname': 'Lift',
        'displayname': 'Cola awareness (lift)',
        'question1': 'Aware?',
        'answer1a': 'Yes',
        'answer1b': 'No',
        'sample_plan': {
            'baseline': 0.2, 'mde_mode': 'relative', 'mde_relative': 0.1,
            'mde_absolute': 0.05, 'confidence': 0.95, 'power': 0.8,
            'comparisons': 1, 'response_rate': 0.01, 'control_share': 0.5,
            'n_control': 200, 'n_expose': 200, 'n_total': 400,
        },
    }
    doc_patch = mock.patch.object(
        survey_service, 'get_doc_by_id', return_value=survey_doc)
    rows_patch = mock.patch.object(
        survey_service, 'get_survey_responses', return_value=df)
    doc_patch.start()
    rows_patch.start()
    self.addCleanup(doc_patch.stop)
    self.addCleanup(rows_patch.stop)

    server, port = _start_app(main.app)
    try:
      with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        page.goto(
            'http://127.0.0.1:%s/survey/sample-size' % port,
            wait_until='networkidle')
        page.wait_for_selector('#planner-results')
        page.locator('#planner-form button.help-meaning-toggle').first.click()
        page.wait_for_selector('#planner-form .help-meaning-body.show')
        self._write_shot(page.locator('#sample-size-page'), 'sample-size-planner.png')

        page.goto(
            'http://127.0.0.1:%s/survey/reporting/abc' % port,
            wait_until='networkidle')
        page.wait_for_selector('#sequential-status')
        page.locator('#sequential-status button.help-meaning-toggle').first.click()
        page.wait_for_selector('#sequential-status .help-meaning-body.show')
        self._write_shot(
            page.locator('#sequential-status'), 'report-sequential.png')
        browser.close()
    finally:
      server.shutdown()
