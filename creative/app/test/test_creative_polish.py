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

import os
import tempfile
import unittest
import zipfile
from unittest import mock

import creative_size
import html5_qa
import main
import survey_service
from test_thankyou import _html, _playwright_or_skip, _survey


class CreativePolishStaticTest(unittest.TestCase):

  def test_layout_has_press_fade_dots_motion_and_focus(self):
    css = creative_size.layout_fix_css()
    self.assertIn('.Abox:active', css)
    self.assertIn('scale(0.97)', css)
    self.assertIn('#survey_container.is-fading', css)
    self.assertIn('prefers-reduced-motion', css)
    self.assertIn('.progress-dot[aria-current="true"]', css)
    self.assertIn('.Abox:focus-visible', css)

  def test_html_answers_are_buttons_and_thankyou_grows(self):
    html = _html(_survey(question_count=2))
    self.assertIn('role="button"', html)
    self.assertIn('tabindex="0"', html)
    self.assertIn('id="progress_dots"', html)
    self.assertIn('handleOptionKey', html)
    self.assertIn('fitThankyouText', html)
    self.assertIn("setAttribute('role', 'status')", html)
    self.assertIn('prefersReducedMotion', html)

  @mock.patch.object(survey_service.survey_collection, 'add_version')
  def test_inner_zip_stays_under_practical_budget(self, version_mock):
    version_mock.return_value = {'version': 1}
    survey = {
        'surveyname': 'polish-size',
        'surveytype': 'brand_track',
        'question1': 'Q1', 'answer1a': 'A', 'answer1b': 'B',
        'question2': 'Q2', 'answer2a': 'A', 'answer2b': 'B',
        'creativesizes': ['300x250', '160x600'],
        'responsetype': 'Submit Responses at End of Survey',
    }
    env = {'RECEIVER_URL': 'https://recv.example/pixel'}
    with mock.patch.dict(os.environ, env):
      with main.app.app_context():
        _name, data = survey_service.zip_file('sid', survey)
    sizes = {}
    with zipfile.ZipFile(data) as zf:
      report = zf.read('html5_qa.txt').decode('utf-8')
      self.assertNotIn('[warning]', report)
      self.assertNotIn('[error]', report)
      for name in zf.namelist():
        if name.endswith('.zip'):
          sizes[name] = zf.getinfo(name).file_size
          inner = zipfile.ZipFile(zf.open(name))
          html = inner.read('index.html').decode('utf-8')
          size_key = '160x600' if '160x600' in name else '300x250'
          findings = html5_qa.check_html(
              html, size_key=size_key,
              receiver_url='https://recv.example/pixel')
          warn = [item for item in findings if item['level'] not in ('info',)]
          self.assertEqual(warn, [], warn)
    self.assertTrue(sizes)
    for name, size in sizes.items():
      self.assertLess(size, 150 * 1024, '%s is %s bytes' % (name, size))
    # Practical budget is 150 KB; current inner zips stay well under 20 KB.
    self.assertLess(max(sizes.values()), 20 * 1024)


class CreativePolishBrowserTest(unittest.TestCase):

  def test_keyboard_dots_status_and_reduced_motion(self):
    sync_playwright = _playwright_or_skip()
    html = _html(_survey(question_count=2, answers=2, size='300x250'))
    with tempfile.NamedTemporaryFile('w', suffix='.html', delete=False) as handle:
      handle.write(html)
      path = handle.name
    try:
      with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto('file://' + path)
        page.wait_for_selector('#option_container_0')
        role = page.get_attribute('#option_container_0', 'role')
        self.assertEqual(role, 'button')
        dots = page.locator('.progress-dot')
        self.assertEqual(dots.count(), 2)
        self.assertEqual(
            page.locator('.progress-dot[aria-current="true"]').count(), 1)
        page.locator('#option_container_0').focus()
        page.keyboard.press('Enter')
        page.wait_for_timeout(200)
        current = page.evaluate(
            """() => Array.from(document.querySelectorAll('.progress-dot'))
              .map(el => el.getAttribute('aria-current'))""")
        self.assertEqual(current, [None, 'true'])
        page.locator('#option_container_0').click()
        page.wait_for_selector('#thankyou_container.thankyoucontainer')
        self.assertEqual(
            page.get_attribute('#thankyou_container', 'role'), 'status')
        grown = page.evaluate(
            """() => parseFloat(getComputedStyle(
              document.getElementById('thankyou_text')).fontSize)""")
        self.assertGreaterEqual(grown, 14)
        page.close()

        reduced = browser.new_page()
        reduced.emulate_media(reduced_motion='reduce')
        reduced.goto('file://' + path)
        reduced.wait_for_selector('#option_container_0')
        reduced.locator('#option_container_0').click()
        reduced.wait_for_timeout(30)
        q2 = reduced.locator('#question_text').inner_text()
        self.assertIn('Question 2', q2)
        fading = reduced.evaluate(
            """() => document.getElementById('survey_container')
              .classList.contains('is-fading')""")
        self.assertFalse(fading)
        reduced.close()
        browser.close()
    finally:
      os.unlink(path)
