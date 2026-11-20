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

import io
import os
import unittest
import zipfile
from unittest import mock

import html5_qa
import main
import survey_service


def _codes(findings):
  return [item['code'] for item in findings]


def _inner_zip(files, name='300x250_creative.zip'):
  buf = io.BytesIO()
  with zipfile.ZipFile(buf, 'w') as zf:
    for filename, content in files:
      zf.writestr(filename, content)
  buf.seek(0)
  buf.name = name
  return buf


_CLEAN_HTML = """<!doctype html>
<html><head>
<meta name="ad.size" content="width=300,height=250">
<script>var clickTag = "https://www.google.com";</script>
<style>#master_container { width: 300px; height: 250px; }</style>
</head><body>
<div id="master_container"></div>
</body></html>
"""


class Html5QaCheckTest(unittest.TestCase):

  def test_clean_html_has_no_findings(self):
    self.assertEqual(html5_qa.check_html(_CLEAN_HTML, size_key='300x250'), [])

  def test_missing_clicktag_and_ad_size(self):
    findings = html5_qa.check_html('<html></html>', size_key='300x250')
    self.assertIn('clickTag', _codes(findings))
    self.assertIn('ad.size', _codes(findings))
    self.assertIn('size.css', _codes(findings))

  def test_ad_size_mismatch(self):
    html = _CLEAN_HTML.replace('width=300,height=250', 'width=160,height=600')
    findings = html5_qa.check_html(html, size_key='300x250')
    self.assertIn('ad.size.mismatch', _codes(findings))

  def test_external_url_flagged_macros_and_receiver_allowed(self):
    html = _CLEAN_HTML.replace(
        '</body>',
        '<img src="https://evil.example/pixel.gif">'
        '<a href="%c">x</a>'
        '<img src="https://recv.example/p">'
        '</body>')
    findings = html5_qa.check_html(
        html, size_key='300x250', receiver_url='https://recv.example/pixel')
    self.assertIn('external', _codes(findings))
    messages = ' '.join(item['message'] for item in findings)
    self.assertIn('evil.example', messages)
    self.assertNotIn('%c', messages)
    self.assertNotIn('recv.example', messages)

  def test_googleusercontent_and_clicktag_hosts_allowed(self):
    html = _CLEAN_HTML.replace(
        '</body>',
        '<img src="https://lh3.googleusercontent.com/a/photo">'
        '</body>')
    self.assertEqual(
        html5_qa.check_html(html, size_key='300x250'), [])

  def test_inner_zip_missing_index_nested_and_file_count(self):
    payload = _inner_zip([
        ('nested.zip', b'x'),
        ('extra1.txt', 'a'),
        ('extra2.txt', 'b'),
        ('extra3.txt', 'c'),
        ('extra4.txt', 'd'),
        ('extra5.txt', 'e'),
        ('extra6.txt', 'f'),
        ('extra7.txt', 'g'),
        ('extra8.txt', 'h'),
        ('extra9.txt', 'i'),
        ('extra10.txt', 'j'),
    ])
    findings = html5_qa.check_inner_zip(
        payload.getvalue(), filename='300x250_creative.zip', size_key='300x250')
    self.assertIn('index.html', _codes(findings))
    self.assertIn('nested.zip', _codes(findings))
    self.assertIn('iab.files', _codes(findings))

  def test_inner_zip_checks_index_html(self):
    payload = _inner_zip([('index.html', '<html></html>')])
    findings = html5_qa.check_inner_zip(
        payload.getvalue(), filename='300x250_creative.zip', size_key='300x250')
    self.assertIn('clickTag', _codes(findings))

  def test_format_report_empty_and_warnings(self):
    empty = html5_qa.format_report([])
    self.assertIn('No warnings', empty)
    report = html5_qa.format_report([{
        'level': 'warning',
        'code': 'clickTag',
        'message': 'missing',
        'target': '300x250',
    }])
    self.assertIn('[warning] clickTag (300x250)', report)

  def test_size_key_from_filename(self):
    self.assertEqual(
        html5_qa.size_key_from_filename('20260101_acme_160x600_creative.zip'),
        '160x600')
    self.assertIsNone(html5_qa.size_key_from_filename('readme.txt'))


class Html5QaZipAndEditorTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    main.app.config['AUTH_BYPASS'] = True
    main.app.config['WTF_CSRF_ENABLED'] = False
    self.client = main.app.test_client()

  def tearDown(self):
    main.app.config['AUTH_BYPASS'] = False
    main.app.config['WTF_CSRF_ENABLED'] = True
    super().tearDown()

  @mock.patch.object(survey_service.survey_collection, 'add_version')
  def test_zip_embeds_html5_qa_txt(self, version_mock):
    version_mock.return_value = {'version': 1}
    with main.app.app_context():
      _filename, data = survey_service.zip_file('sid', {
          'surveyname': 'qa',
          'question1': 'Q',
          'answer1a': 'A',
          'answer1b': 'B',
      })
    outer = zipfile.ZipFile(data)
    self.assertIn('html5_qa.txt', outer.namelist())
    report = outer.read('html5_qa.txt').decode('utf-8')
    self.assertIn('HTML5 spec QA', report)
    self.assertNotIn('[warning]', report)
    self.assertNotIn('[error]', report)

  @mock.patch.object(survey_service.survey_collection, 'add_version')
  @mock.patch.object(survey_service, 'get_html_template', return_value='<html></html>')
  def test_zip_report_lists_warnings_for_bad_html(self, _html, version_mock):
    version_mock.return_value = {'version': 1}
    _filename, data = survey_service.zip_file('sid', {
        'surveyname': 'qa',
        'question1': 'Q',
    })
    report = zipfile.ZipFile(data).read('html5_qa.txt').decode('utf-8')
    self.assertIn('[warning] clickTag', report)
    self.assertIn('[warning] ad.size', report)

  def test_flash_zip_html5_qa_warns_when_report_has_findings(self):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
      zf.writestr(
          'html5_qa.txt',
          html5_qa.format_report([{
              'level': 'warning',
              'code': 'clickTag',
              'message': 'missing',
          }]))
    buf.seek(0)
    with main.app.test_request_context():
      survey_service.flash_zip_html5_qa(buf)
      from flask import get_flashed_messages
      messages = get_flashed_messages(with_categories=True)
    self.assertTrue(any('HTML5 spec' in msg for _cat, msg in messages))
    self.assertEqual(buf.tell(), 0)

  def test_create_page_shows_html5_qa_card(self):
    response = self.client.get('/survey/create')
    self.assertEqual(response.status_code, 200)
    self.assertIn(b'HTML5 spec QA', response.data)
    self.assertIn(b'No warnings for the current sizes', response.data)
