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
import os
import re
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

import pandas
import main
import survey_service
import ui_help


_ARTIFACT_DIR = '/opt/cursor/artifacts'


def _all_qa_findings():
  findings = []
  for code, help_id in ui_help.QA_CODE_TO_HELP.items():
    findings.append({
        'level': 'info' if code == 'receiver' else 'warning',
        'code': code,
        'message': 'Check: %s' % code,
        'help_id': help_id,
        'target': '300x250',
    })
  return findings


class UiHelpCopyTest(unittest.TestCase):

  def test_every_qa_code_has_an_entry(self):
    for code, help_id in ui_help.QA_CODE_TO_HELP.items():
      self.assertEqual(ui_help.help_id_for_code(code), help_id)
      self.assertIn(help_id, ui_help.ENTRIES)
      body = ui_help.ENTRIES[help_id]['body']
      self.assertGreater(len(body), 40, help_id)

  def test_unknown_code_falls_back(self):
    self.assertEqual(ui_help.help_id_for_code('not.a.code'), 'qa.other')
    self.assertIsNone(ui_help.entry('missing'))
    self.assertEqual(ui_help.entry('qa.clickTag')['title'], 'clickTag')

  def test_report_help_ids_exist(self):
    for help_id in (
        'report.min_n', 'report.holm', 'report.ci', 'report.pvalue',
        'report.no_control', 'report.no_expose', 'report.no_data',
        'plan.baseline', 'plan.mde', 'plan.n', 'seq.status',
        'seq.fixed_horizon', 'seq.progress'):
      self.assertIn(help_id, ui_help.ENTRIES)


class UiHelpMarkupTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    main.app.config['AUTH_BYPASS'] = True
    main.app.config['WTF_CSRF_ENABLED'] = False
    self.client = main.app.test_client()
    self._suggestions = mock.patch.object(
        survey_service, 'identity_suggestions',
        return_value={'clients': ['Acme'], 'agencies': ['Example']})
    self._suggestions.start()
    self.addCleanup(self._suggestions.stop)

  def tearDown(self):
    main.app.config['AUTH_BYPASS'] = False
    main.app.config['WTF_CSRF_ENABLED'] = True
    super().tearDown()

  def _survey(self, data):
    doc = mock.Mock()
    doc.id = 'abc'
    doc.to_dict.return_value = data
    doc.exists = True
    return doc

  def test_editor_renders_help_for_each_qa_category(self):
    findings = _all_qa_findings()
    with mock.patch.object(
        survey_service, 'html5_qa_for_survey', return_value=findings):
      response = self.client.get('/survey/create')
    self.assertEqual(response.status_code, 200)
    html = response.data.decode('utf-8')
    self.assertIn('help-meaning-toggle', html)
    self.assertGreater(html.count('What does this mean?'), 1)
    self.assertIn('data-bs-toggle="collapse"', html)
    self.assertIn('vendor/bootstrap.bundle.min.js', html)
    self.assertNotIn('cdn.jsdelivr', html)
    self.assertNotIn('<script src="http', html)
    for item in findings:
      self.assertIn('data-qa-code="%s"' % item['code'], html)
      self.assertIn('data-help-id="%s"' % item['help_id'], html)
      self.assertIn(ui_help.ENTRIES[item['help_id']]['body'], html)
    self.assertIn('text-bg-info', html)
    self.assertIn('text-bg-warning', html)
    csp = response.headers.get('Content-Security-Policy', '')
    self.assertIn("script-src 'self' 'unsafe-inline' 'unsafe-eval'", csp)
    self.assertIsNone(
        response.headers.get('Content-Security-Policy-Report-Only'))
    extra_scripts = re.findall(r'<script[^>]+src="([^"]+)"', html)
    for src in extra_scripts:
      self.assertTrue(
          src.startswith('/static/') or 'static/' in src, src)
    self.assertIn('class="collapse mt-1 help-meaning-body"', html)

  def test_reporting_renders_help_for_min_n_holm_and_ci(self):
    t = datetime.datetime(2026, 11, 18, 12, 0, 0)
    rows = pandas.DataFrame({
        'CreatedAt': [t, t, t, t],
        'Segmentation': [
            'default_control', 'default_control',
            'default_expose', 'default_expose',
        ],
        'Response': ['1:A', '1:B', '1:A', '1:A'],
        'BomID': ['c1', 'c2', 'e1', 'e2'],
    })
    survey = {
        'surveytype': 'brand_lift',
        'surveyname': 'Lift',
        'question1': 'Aware?',
        'answer1a': 'Yes',
        'answer1b': 'No',
    }
    with mock.patch.object(survey_service, 'get_doc_by_id',
                           return_value=self._survey(survey)):
      with mock.patch.object(
          survey_service, 'get_survey_responses', return_value=rows):
        response = self.client.get('/survey/reporting/abc')
    self.assertEqual(response.status_code, 200)
    html = response.data.decode('utf-8')
    self.assertIn('id="min-n-warning"', html)
    self.assertIn('What does this mean?', html)
    self.assertIn(ui_help.ENTRIES['report.min_n']['body'], html)
    self.assertIn(ui_help.ENTRIES['report.holm']['body'], html)
    self.assertIn(ui_help.ENTRIES['report.ci']['body'], html)
    self.assertIn(ui_help.ENTRIES['report.pvalue']['body'], html)
    self.assertIn('data-bs-toggle="collapse"', html)
    csp = response.headers.get('Content-Security-Policy', '')
    self.assertIn("default-src 'self'", csp)

  def test_reporting_empty_and_segment_alerts_have_help(self):
    survey = {
        'surveytype': 'brand_lift',
        'surveyname': 'Lift',
        'question1': 'Aware?',
        'answer1a': 'Yes',
        'answer1b': 'No',
    }
    empty = pandas.DataFrame({
        'CreatedAt': [], 'Segmentation': [], 'Response': [], 'BomID': [],
    })
    with mock.patch.object(survey_service, 'get_doc_by_id',
                           return_value=self._survey(survey)):
      with mock.patch.object(
          survey_service, 'get_survey_responses', return_value=empty):
        empty_page = self.client.get('/survey/reporting/abc')
    self.assertIn(ui_help.ENTRIES['report.no_data']['body'].encode('utf-8'),
                  empty_page.data)

    expose_only = pandas.DataFrame({
        'CreatedAt': [datetime.datetime(2026, 11, 18, 12, 0, 0)] * 2,
        'Segmentation': ['default_expose', 'default_expose'],
        'Response': ['1:A', '1:B'],
        'BomID': ['e1', 'e2'],
    })
    with mock.patch.object(survey_service, 'get_doc_by_id',
                           return_value=self._survey(survey)):
      with mock.patch.object(
          survey_service, 'get_survey_responses', return_value=expose_only):
        page = self.client.get('/survey/reporting/abc')
    self.assertIn(ui_help.ENTRIES['report.no_control']['body'].encode('utf-8'),
                  page.data)


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
          'http://127.0.0.1:%s/survey/create' % port, timeout=1)
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


class UiHelpScreenshotTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    main.app.config['AUTH_BYPASS'] = True
    main.app.config['WTF_CSRF_ENABLED'] = False
    self._suggestions = mock.patch.object(
        survey_service, 'identity_suggestions',
        return_value={'clients': ['Acme'], 'agencies': ['Example']})
    self._suggestions.start()
    self.addCleanup(self._suggestions.stop)

  def tearDown(self):
    main.app.config['AUTH_BYPASS'] = False
    main.app.config['WTF_CSRF_ENABLED'] = True
    super().tearDown()

  def _write_shot(self, locator, filename):
    os.makedirs(_ARTIFACT_DIR, exist_ok=True)
    tmp = os.path.join(tempfile.gettempdir(), filename)
    locator.screenshot(path=tmp)
    _optimize_png(tmp)
    artifact = os.path.join(_ARTIFACT_DIR, filename)
    shutil.copyfile(tmp, artifact)
    self.assertGreater(os.path.getsize(artifact), 1000)
    return artifact

  def test_headless_screenshots_of_expanded_help(self):
    sync_playwright = _playwright_or_skip()
    findings = _all_qa_findings()
    t = datetime.datetime(2026, 11, 18, 12, 0, 0)
    rows = pandas.DataFrame({
        'CreatedAt': [t, t, t, t],
        'Segmentation': [
            'default_control', 'default_control',
            'default_expose', 'default_expose',
        ],
        'Response': ['1:A', '1:B', '1:A', '1:A'],
        'BomID': ['c1', 'c2', 'e1', 'e2'],
    })
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
    }
    qa_patch = mock.patch.object(
        survey_service, 'html5_qa_for_survey', return_value=findings)
    doc_patch = mock.patch.object(
        survey_service, 'get_doc_by_id', return_value=survey_doc)
    rows_patch = mock.patch.object(
        survey_service, 'get_survey_responses', return_value=rows)
    qa_patch.start()
    doc_patch.start()
    rows_patch.start()
    self.addCleanup(qa_patch.stop)
    self.addCleanup(doc_patch.stop)
    self.addCleanup(rows_patch.stop)

    server, port = _start_app(main.app)
    try:
      with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        page.goto(
            'http://127.0.0.1:%s/survey/create' % port,
            wait_until='networkidle')
        page.wait_for_selector('#html5-spec-qa')
        page.locator(
            '#html5-spec-qa [data-qa-code="receiver"] button.help-meaning-toggle'
        ).click()
        page.locator(
            '#html5-spec-qa [data-qa-code="external"] button.help-meaning-toggle'
        ).click()
        page.wait_for_selector(
            '#html5-spec-qa [data-qa-code="receiver"] .help-meaning-body.show')
        page.wait_for_selector(
            '#html5-spec-qa [data-qa-code="external"] .help-meaning-body.show')
        self._write_shot(
            page.locator('#html5-spec-qa'), 'editor-html5-qa.png')

        page.goto(
            'http://127.0.0.1:%s/survey/reporting/abc' % port,
            wait_until='networkidle')
        page.wait_for_selector('#min-n-warning')
        page.locator('#min-n-warning button.help-meaning-toggle').click()
        page.wait_for_selector('#min-n-warning .help-meaning-body.show')
        self._write_shot(
            page.locator('#min-n-warning'), 'report-min-n-help.png')
        browser.close()
    finally:
      server.shutdown()
