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

"""Thank-you end screen: JS validity plus optional headless click-through."""
import os
import re
import subprocess
import tempfile
import threading
import unittest
from unittest import mock
from urllib.request import urlopen
from wsgiref.simple_server import make_server

from flask import render_template as flask_render_template

import css_theme
import main
import survey_service


def _survey(question_count=1, answers=2, size='300x250', surveytype='brand_track',
            extra=None):
  data = {
      'surveyname': 'Thanks',
      'surveytype': surveytype,
      'creativesize': size,
      'language': 'en',
      'responsetype': 'Submit Responses at End of Survey',
  }
  letters = 'abcdefgh'
  for q in range(1, question_count + 1):
    data['question%s' % q] = 'Question %s?' % q
    data['question%stype' % q] = 'SINGLE_OPTION'
    for i in range(answers):
      data['answer%s%s' % (q, letters[i])] = 'Ans %s%s' % (q, letters[i].upper())
      data['answer%s%snext' % (q, letters[i])] = (
          'end' if q == question_count else str(q + 1))
  if extra:
    data.update(extra)
  return data


def _html(survey, receiver_url='', seg='', size=None):
  # Other tests replace survey_service.render_template with a Mock and leak it.
  survey_service.render_template = flask_render_template
  with main.app.app_context():
    with mock.patch.dict(os.environ, {'RECEIVER_URL': receiver_url}):
      return survey_service.get_html_template(
          'sid', survey, seg, size=size or survey.get('creativesize'))


def _inline_scripts(html):
  return re.findall(r'<script(?![^>]+src=)[^>]*>(.*?)</script>', html, re.I | re.S)


class ThankyouHtmlTest(unittest.TestCase):

  def test_macro_script_is_valid_javascript(self):
    html = _html(_survey())
    self.assertNotIn('var window.cookie', html)
    scripts = _inline_scripts(html)
    self.assertGreaterEqual(len(scripts), 2)
    for index, source in enumerate(scripts):
      with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False) as handle:
        handle.write(source)
        path = handle.name
      try:
        result = subprocess.run(
            ['node', '--check', path], capture_output=True, text=True)
      finally:
        os.unlink(path)
      self.assertEqual(
          result.returncode, 0,
          'script %s failed node --check:\n%s\n%s' % (
              index, result.stderr, source[:400]))

  def test_pixel_cannot_block_thank_you(self):
    html = _html(_survey())
    self.assertIn('controller.renderThankyou();', html)
    thank_index = html.index('controller.renderThankyou();')
    fire_index = html.index('controller.fireTrackingPixel();')
    send_index = html.index('controller.sendCollectedResponseToServer();')
    self.assertLess(fire_index, thank_index)
    self.assertLess(send_index, thank_index)
    self.assertRegex(html, r'try \{\s*controller\.fireTrackingPixel\(\);')
    self.assertIn('if (!url)', html)
    self.assertIn('if (!trackers[i])', html)

  def test_preview_response_server_is_empty(self):
    # main.preview passes receiver_url=''. Same creative JS as the zip.
    html = _html(_survey(), receiver_url='')
    self.assertIn('"response_server": ""', html)


def _playwright_or_skip():
  try:
    from playwright.sync_api import sync_playwright
    return sync_playwright
  except ImportError:
    raise unittest.SkipTest('playwright is not installed')


class ThankyouBrowserTest(unittest.TestCase):
  """Headless click-through of preview-like and zip-like creatives."""

  def _click_through(self, page, clicks, expect_text='Thank You'):
    errors = []
    page.on('pageerror', lambda exc: errors.append(str(exc)))
    page.on('console', lambda msg: errors.append(msg.text) if msg.type == 'error' else None)
    page.wait_for_selector('#option_container_0')
    for _ in range(clicks):
      page.locator('#option_container_0').click()
      page.wait_for_timeout(150)
    page.wait_for_selector('#thankyou_container.thankyoucontainer')
    body = page.locator('#thankyou_container').inner_text()
    self.assertIn(expect_text, body)
    survey = page.locator('#survey_container')
    self.assertIn('invisible', survey.get_attribute('class') or '')
    js_errors = [item for item in errors if 'favicon' not in item.lower()]
    self.assertEqual(js_errors, [], msg=js_errors)
    return page.locator('#master_container').screenshot()

  def test_file_creatives_show_thank_you(self):
    sync_playwright = _playwright_or_skip()
    cases = [
        ('track-300-2', _survey(1, 2, '300x250'), '', 1),
        ('track-receiver-down', _survey(1, 2, '300x250'),
         'http://127.0.0.1:9/no-receiver', 1),
        ('track-160-8', _survey(1, 8, '160x600'), '', 1),
        ('track-two-questions', _survey(2, 2, '300x250'), '', 2),
        ('lift-control', _survey(1, 2, '300x250', 'brand_lift'), '', 1),
        ('lift-expose', _survey(1, 2, '300x250', 'brand_lift'), '', 1),
        ('wide-970', _survey(1, 4, '970x250'), '', 1),
    ]
    segs = {
        'lift-control': 'default_control',
        'lift-expose': 'default_expose',
    }
    with tempfile.TemporaryDirectory() as tmp:
      paths = []
      for name, survey, receiver, clicks in cases:
        html = _html(survey, receiver_url=receiver, seg=segs.get(name, ''))
        path = os.path.join(tmp, name + '.html')
        with open(path, 'w', encoding='utf-8') as handle:
          handle.write(html)
        paths.append((name, path, clicks))
      shot = None
      with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
          for name, path, clicks in paths:
            page = browser.new_page()
            page.goto('file://' + path)
            png = self._click_through(page, clicks)
            if name == 'track-300-2':
              shot = png
            page.close()
        finally:
          browser.close()
      artifacts = '/opt/cursor/artifacts'
      if shot and os.path.isdir('/opt/cursor'):
        os.makedirs(artifacts, exist_ok=True)
        with open(os.path.join(artifacts, 'thank-you-screen.png'), 'wb') as handle:
          handle.write(shot)

  def test_flask_preview_with_csp_shows_thank_you(self):
    sync_playwright = _playwright_or_skip()
    survey = _survey(1, 2, '300x250')

    class Doc(object):
      id = 'sid'
      exists = True
      def to_dict(self):
        return survey
      def get(self, key, default=None):
        return survey.get(key, default)

    main.app.config['AUTH_BYPASS'] = True
    main.app.config['WTF_CSRF_ENABLED'] = False
    server = make_server('127.0.0.1', 0, main.app)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
      with mock.patch.object(survey_service, 'get_doc_by_id', return_value=Doc()):
        # Warm the app so the patch is visible in the serving thread? The
        # patch is process-wide, so the WSGI thread sees it.
        with sync_playwright() as playwright:
          browser = playwright.chromium.launch(headless=True)
          page = browser.new_page()
          errors = []
          page.on('pageerror', lambda exc: errors.append(str(exc)))
          page.goto('http://127.0.0.1:%s/survey/preview/sid' % port)
          csp = urlopen('http://127.0.0.1:%s/survey/preview/sid' % port).headers.get(
              'Content-Security-Policy', '')
          self.assertIn("script-src 'self' 'unsafe-inline'", csp)
          self._click_through(page, 1)
          browser.close()
    finally:
      server.shutdown()
      main.app.config['AUTH_BYPASS'] = False
      main.app.config['WTF_CSRF_ENABLED'] = True

  def test_themed_preview_and_zip_use_bv2_colours_then_thank_you(self):
    sync_playwright = _playwright_or_skip()
    theme = dict(css_theme.DEFAULT_THEME)
    theme.update({
        'bg': '#1122aa',
        'answer_bg': '#ffcc00',
        'question_color': '#ffffff',
        'answer_color': '#111111',
        'accent': '#ffcc00',
        'panel': 'rgba(0, 0, 0, 0.35)',
    })
    survey = _survey(extra={'custom_css': css_theme.combine_css(theme, '')})
    zip_html = _html(survey, receiver_url='')
    self.assertIn('--bv2-bg: #1122aa', zip_html)
    self.assertIn('BV2_THEME_START', zip_html)
    self.assertIn('var(--bv2-bg)', zip_html)

    class Doc(object):
      id = 'sid'
      exists = True
      def to_dict(self):
        return survey
      def get(self, key, default=None):
        return survey.get(key, default)

    main.app.config['AUTH_BYPASS'] = True
    main.app.config['WTF_CSRF_ENABLED'] = False
    server = make_server('127.0.0.1', 0, main.app)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    artifacts = '/opt/cursor/artifacts'
    os.makedirs(artifacts, exist_ok=True)
    try:
      with tempfile.TemporaryDirectory() as tmp:
        zip_path = os.path.join(tmp, 'themed-zip.html')
        with open(zip_path, 'w', encoding='utf-8') as handle:
          handle.write(zip_html)
        with mock.patch.object(
            survey_service, 'get_doc_by_id', return_value=Doc()):
          with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto('http://127.0.0.1:%s/survey/preview/sid' % port)
            rgb = page.evaluate(
                "getComputedStyle(document.getElementById('master_container'))"
                ".backgroundColor")
            self.assertEqual(rgb, 'rgb(17, 34, 170)')
            answer = page.evaluate(
                "getComputedStyle(document.querySelector('.Abox'))"
                ".backgroundColor")
            self.assertEqual(answer, 'rgb(255, 204, 0)')
            token = page.evaluate(
                "getComputedStyle(document.documentElement)"
                ".getPropertyValue('--bv2-bg').trim()")
            self.assertEqual(token, '#1122aa')
            page.screenshot(path=os.path.join(
                artifacts, 'theme-preview-bv2-colours.png'))
            self._click_through(page, 1)
            page.close()

            zip_page = browser.new_page()
            zip_page.goto('file://' + zip_path)
            zip_rgb = zip_page.evaluate(
                "getComputedStyle(document.getElementById('master_container'))"
                ".backgroundColor")
            self.assertEqual(zip_rgb, 'rgb(17, 34, 170)')
            png = self._click_through(zip_page, 1)
            with open(os.path.join(
                artifacts, 'theme-zip-thank-you.png'), 'wb') as handle:
              handle.write(png)
            zip_page.close()
            browser.close()
    finally:
      server.shutdown()
      main.app.config['AUTH_BYPASS'] = False
      main.app.config['WTF_CSRF_ENABLED'] = True

  def test_editor_live_preview_applies_bv2_theme(self):
    sync_playwright = _playwright_or_skip()
    main.app.config['AUTH_BYPASS'] = True
    main.app.config['WTF_CSRF_ENABLED'] = False
    server = make_server('127.0.0.1', 0, main.app)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    artifacts = '/opt/cursor/artifacts'
    os.makedirs(artifacts, exist_ok=True)
    try:
      with mock.patch.object(
          survey_service, 'identity_suggestions',
          return_value={'clients': [], 'agencies': []}):
        with sync_playwright() as playwright:
          browser = playwright.chromium.launch(headless=True)
          page = browser.new_page()
          page.goto('http://127.0.0.1:%s/survey/create' % port)
          page.wait_for_selector('iframe.preview-frame')
          page.wait_for_timeout(400)
          rgb = page.evaluate("""() => {
            const iframe = document.querySelector('iframe.preview-frame');
            const doc = iframe && iframe.contentDocument;
            const el = doc && doc.getElementById('master_container');
            return el ? getComputedStyle(el).backgroundColor : '';
          }""")
          self.assertEqual(rgb, 'rgb(0, 128, 0)')
          srcdoc = page.evaluate(
              "document.querySelector('iframe.preview-frame').srcdoc || ''")
          self.assertIn('--bv2-bg', srcdoc)
          self.assertIn('BV2_THEME_START', srcdoc)
          frame = page.locator('iframe.preview-frame')
          frame.scroll_into_view_if_needed()
          frame.screenshot(path=os.path.join(
              artifacts, 'theme-editor-live-preview.png'))
          browser.close()
    finally:
      server.shutdown()
      main.app.config['AUTH_BYPASS'] = False
      main.app.config['WTF_CSRF_ENABLED'] = True
