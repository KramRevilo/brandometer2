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

"""Live preview of the editable agency disclosure badge."""
import threading
import unittest
from unittest import mock

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
    import time
    import urllib.request
    try:
      urllib.request.urlopen('http://127.0.0.1:%s/survey/create' % port, timeout=1)
      break
    except Exception:
      time.sleep(0.1)
  return server, port


_PREVIEW_BADGE_JS = """() => {
  const iframe = document.querySelector('iframe.preview-frame');
  try {
    const doc = iframe && iframe.contentDocument;
    const badge = doc && doc.querySelector('.brand-badge');
    const face = badge && badge.querySelector('.brand-badge-face');
    return {
      className: badge ? badge.className : '',
      face: face ? face.textContent.trim() : '',
      html: badge ? badge.innerHTML : ''
    };
  } catch (err) {
    return { className: '', face: '', html: String(err) };
  }
}"""


class BadgeEditorBrowserTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    main.app.config['AUTH_BYPASS'] = True
    main.app.config['WTF_CSRF_ENABLED'] = False
    self._suggest = mock.patch.object(
        survey_service, 'identity_suggestions',
        return_value={'clients': ['Acme'], 'agencies': ['Example Media']})
    self._qa = mock.patch.object(
        survey_service, 'html5_qa_for_survey', return_value=[])
    self._suggest.start()
    self._qa.start()
    self.addCleanup(self._suggest.stop)
    self.addCleanup(self._qa.stop)

  def tearDown(self):
    main.app.config['AUTH_BYPASS'] = False
    main.app.config['WTF_CSRF_ENABLED'] = True
    super().tearDown()

  def test_name_badge_live_preview_uses_typed_agency(self):
    sync_playwright = _playwright_or_skip()
    server, port = _start_app(main.app)
    base = 'http://127.0.0.1:%s' % port
    try:
      with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1400, 'height': 1100})
        page.goto(base + '/survey/create', wait_until='networkidle')
        page.wait_for_selector('#disclosure-badge')
        page.wait_for_selector('#badge_name')
        page.locator('#disclosure-badge').scroll_into_view_if_needed()
        html = page.content()
        self.assertIn('value="Name"', html)
        self.assertIn('value="B2"', html)
        self.assertIn('value="Ad"', html)
        self.assertNotIn('value="Dentsu"', html)
        self.assertIn('Agency name on badge', html)

        page.fill('#surveyname', 'badge-preview')
        page.fill('#question1', 'Which brand did you see?')
        page.fill('#answer1a', 'Example Cola')
        page.fill('#answer1b', 'Other Cola')
        page.fill('#agency', 'Example Media')
        page.locator('label.badge-icon-choice', has=page.locator('#badge_icon-Name')).click()
        page.wait_for_timeout(400)
        preview = page.evaluate(_PREVIEW_BADGE_JS)
        self.assertIn('badge-kind-wordmark', preview['className'])
        self.assertEqual(preview['face'], 'Example Media')

        page.fill('#badge_name', 'Northline Media')
        page.wait_for_timeout(400)
        preview = page.evaluate(_PREVIEW_BADGE_JS)
        self.assertEqual(preview['face'], 'Northline Media')
        self.assertNotIn('<b>', preview['html'])

        page.fill('#badge_name', '<b>Oak & Anchor</b>')
        page.wait_for_timeout(400)
        preview = page.evaluate(_PREVIEW_BADGE_JS)
        self.assertEqual(preview['face'], 'Oak & Anchor')
        self.assertNotIn('<b>', preview['html'])
        self.assertIn('Oak &amp; Anchor', preview['html'])
        browser.close()
    finally:
      server.shutdown()
