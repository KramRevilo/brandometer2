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
from unittest import mock

from mockfirestore import MockFirestore
import pandas

import creative_size
import css_theme
import receiver_crypto
import reporting
import survey_collection
import survey_service

import main


class CreativeSizeTest(unittest.TestCase):

  def test_missing_size_defaults_to_300x250(self):
    spec = creative_size.resolve({})
    self.assertEqual(spec['key'], '300x250')
    self.assertEqual(spec['width'], 300)
    self.assertEqual(spec['height'], 250)
    self.assertEqual(
        creative_size.resolve({'creativesize': 'nope'})['key'], '300x250')

  def test_160x600_meta_and_overlay(self):
    spec = creative_size.resolve({'creativesize': '160x600'})
    self.assertEqual(creative_size.ad_size_meta(spec), 'width=160,height=600')
    css = creative_size.apply_overlay('#master_container { width: 300px; }', spec)
    self.assertIn('width: 160px;', css)
    self.assertIn('height: 600px;', css)
    self.assertEqual(css.count(creative_size.SIZE_START), 1)
    again = creative_size.apply_overlay(css, '300x250')
    self.assertEqual(again.count(creative_size.SIZE_START), 1)
    self.assertIn('width: 300px;', again)


class HtmlAndReportingTest(unittest.TestCase):

  def test_html_template_uses_size_and_fifth_option(self):
    with main.app.app_context():
      html = survey_service.get_html_template(
          'sid', {
              'surveyname': 'Sky',
              'question1': 'Q',
              'answer1a': 'A',
              'answer1b': 'B',
              'answer1e': 'E',
              'creativesize': '160x600',
              'custom_css': 'body { margin: 0; }',
          }, '')
    self.assertIn('width=160,height=600', html)
    self.assertIn('"width": 160', html)
    self.assertIn('"height": 600', html)
    self.assertIn('"max_options": 8', html)
    self.assertIn('option_container_4', html)
    self.assertIn('option_container_7', html)
    self.assertIn('width: 160px;', html)

  def test_html_embeds_signed_token_and_privacy_note(self):
    previous = main.app.config.get('RECEIVER_HMAC_SECRET')
    try:
      with main.app.app_context():
        main.app.config['RECEIVER_HMAC_SECRET'] = 'unit-test-hmac'
        with mock.patch.dict(os.environ, {'RECEIVER_URL': 'https://recv.example'}):
          html = survey_service.get_html_template(
              'sid', {
                  'surveyname': 'Signed',
                  'question1': 'Q',
                  'answer1a': 'A',
                  'answer1b': 'B',
              }, '')
    finally:
      main.app.config['RECEIVER_HMAC_SECRET'] = previous or ''
    self.assertIn('&token=', html)
    self.assertIn(receiver_crypto.survey_token('sid', 'unit-test-hmac'), html)
    self.assertIn(
        'Your IP address is not stored. A daily hash limits repeat posts.',
        html)
    self.assertIn('id="privacy_note"', html)
    self.assertIn('&rid={rid}', html)
    self.assertNotIn('&ver=', html)
    self.assertIn('&rsrc={rsrc}', html)
    self.assertIn('&camp={camp}', html)
    self.assertIn('&plc={plc}', html)
    self.assertIn('var clickTag', html)
    self.assertIn('%c', html)
    self.assertIn('%epid!', html)
    self.assertIn('${GDPR}', html)
    self.assertIn('resolveRespondentId', html)
    self.assertIn('localStorage', html)
    self.assertIn('%u', html)
    self.assertNotIn('&uid=', html)

  def test_html_embeds_hmac_bound_creative_version(self):
    previous = main.app.config.get('RECEIVER_HMAC_SECRET')
    try:
      with main.app.app_context():
        main.app.config['RECEIVER_HMAC_SECRET'] = 'unit-test-hmac'
        with mock.patch.dict(os.environ, {'RECEIVER_URL': 'https://recv.example'}):
          html = survey_service.get_html_template(
              'sid', {
                  'surveyname': 'Signed',
                  'question1': 'Q',
                  'answer1a': 'A',
                  'answer1b': 'B',
              }, '', creative_version=7)
    finally:
      main.app.config['RECEIVER_HMAC_SECRET'] = previous or ''
    self.assertIn('&ver=7', html)
    self.assertIn(
        receiver_crypto.survey_token('sid', 'unit-test-hmac', version=7), html)
    self.assertNotIn(
        receiver_crypto.survey_token('sid', 'unit-test-hmac'), html)

  def test_reporting_includes_answer_e(self):
    df = pandas.DataFrame({
        'CreatedAt': pandas.to_datetime(['2026-11-18'] * 3),
        'Segmentation': ['', '', ''],
        'Response': ['1:A', '1:E', '1:E'],
        'BomID': ['a', 'b', 'c'],
    })
    report = reporting.build_report(df, {
        'question1': 'Q',
        'answer1a': 'Yes',
        'answer1e': 'Other',
    }, is_lift=False)
    ids = [ans['id'] for ans in report['questions'][0]['answers']]
    self.assertEqual(ids, ['A', 'E'])
    other = report['questions'][0]['answers'][1]
    self.assertEqual(other['text'], 'Other')
    self.assertEqual(other['total'], 2)


class VersioningTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self.client = MockFirestore()
    self.collection = self.client.collection('test_surveys')

  def tearDown(self):
    self.client.reset()
    super().tearDown()

  def test_versions_snapshot_is_not_changed_by_later_edits(self):
    with mock.patch.object(
        survey_collection, '_collection', return_value=self.collection):
      ref = self.collection.document()
      ref.set({
          'surveyname': 'Live',
          'question1': 'Original Q',
          'answer1a': 'A',
          'answer1b': 'B',
          'creativesize': '300x250',
          'surveytype': 'brand_track',
          'custom_css': 'body { color: red; }',
      })
      self.assertEqual(survey_collection.peek_next_version(ref.id), 1)
      first = survey_collection.add_version(
          ref.id, ref.get().to_dict(), actor='mark@google.com')
      self.assertEqual(first['version'], 1)
      self.assertEqual(survey_collection.peek_next_version(ref.id), 2)
      self.assertEqual(first['created_by'], 'mark@google.com')
      ref.update({'question1': 'Changed Q', 'creativesize': '160x600'})
      second = survey_collection.add_version(ref.id, ref.get().to_dict())
      self.assertEqual(second['version'], 2)
      versions = survey_collection.list_versions(ref.id)
      self.assertEqual([v['version'] for v in versions], [2, 1])
      v1 = survey_collection.get_version(ref.id, 1)
      self.assertEqual(v1['question1'], 'Original Q')
      self.assertEqual(v1['creativesize'], '300x250')
      self.assertEqual(ref.get().to_dict()['question1'], 'Changed Q')
      self.assertEqual(
          survey_collection.get_version(ref.id, 1)['custom_css'],
          'body { color: red; }')
      self.assertEqual(
          [v['id'] for v in versions], ['2', '1'])
      seq = self.collection.document(ref.id).collection('versions').document(
          survey_collection.VERSION_SEQ_DOC).get()
      self.assertTrue(seq.exists)
      self.assertEqual(seq.to_dict().get('n'), 2)

  @mock.patch.object(survey_collection, 'add_version')
  @mock.patch.object(survey_service, 'get_html_template', return_value='<html></html>')
  def test_zip_from_version_does_not_record_another_snapshot(
      self, _html_mock, version_mock):
    survey_service.zip_file(
        'sid', {'surveyname': 'v', 'question1': 'q'}, record_version=False)
    version_mock.assert_not_called()


class EditorAndPreviewRoutesTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    main.app.config['AUTH_BYPASS'] = True
    main.app.config['WTF_CSRF_ENABLED'] = False
    self.client = main.app.test_client()

  def tearDown(self):
    main.app.config['AUTH_BYPASS'] = False
    main.app.config['WTF_CSRF_ENABLED'] = True
    super().tearDown()

  def _survey(self, doc_id, data):
    class Doc(object):
      def __init__(self):
        self.id = doc_id
        self.exists = True
      def to_dict(self):
        return data
      def get(self, key, default=None):
        return data.get(key, default)
    return Doc()

  @mock.patch.object(survey_service, 'get_question_json', return_value=[])
  @mock.patch.object(survey_service, 'get_doc_by_id')
  def test_preview_uses_160x600(self, doc_mock, _json_mock):
    doc_mock.return_value = self._survey('abc', {
        'surveyname': 'Sky',
        'question1': 'Q1',
        'creativesize': '160x600',
        'responsetype': 'Submit Responses at End of Survey',
    })
    chrome = self.client.get('/survey/preview/abc')
    self.assertEqual(chrome.status_code, 200)
    self.assertIn(b'id="preview-test-frame"', chrome.data)
    response = self.client.get('/survey/preview/abc?embed=1')
    self.assertEqual(response.status_code, 200)
    self.assertIn(b'width=160,height=600', response.data)
    self.assertIn(b'"width": 160', response.data)
    self.assertIn(b'option_container_4', response.data)
    self.assertNotIn(b'&token=', response.data)
    self.assertIn(b'"response_server": ""', response.data)

  @mock.patch.object(survey_service, 'list_versions')
  @mock.patch.object(survey_service, 'get_doc_by_id')
  def test_edit_shows_version_history(self, doc_mock, versions_mock):
    doc_mock.return_value = self._survey('abc', {
        'surveyname': 'Live',
        'question1': 'Q',
        'answer1a': 'A',
        'answer1b': 'B',
        'creativesize': '300x250',
    })
    versions_mock.return_value = [{
        'version': 1,
        'created_at': '2026-11-18T21:00:00Z',
        'creativesize': '300x250',
        'surveytype': 'brand_track',
    }]
    response = self.client.get('/survey/edit?survey_id=abc')
    self.assertEqual(response.status_code, 200)
    self.assertIn(b'Version history', response.data)
    self.assertIn(b'Download this version', response.data)
    self.assertIn(b'/survey/download_zip/abc/version/1', response.data)

  @mock.patch.object(survey_service, 'list_versions', return_value=[])
  @mock.patch.object(survey_service, 'get_doc_by_id')
  def test_edit_includes_last_update_time(self, doc_mock, _versions):
    doc = self._survey('abc', {
        'surveyname': 'Live',
        'question1': 'Q',
        'answer1a': 'A',
        'answer1b': 'B',
    })
    class Stamp(object):
      def rfc3339(self):
        return '2026-11-19T12:00:00.000000Z'
    doc.update_time = Stamp()
    doc_mock.return_value = doc
    response = self.client.get('/survey/edit?survey_id=abc')
    self.assertEqual(response.status_code, 200)
    self.assertIn(b'name="last_update_time"', response.data)
    self.assertIn(b'2026-11-19T12:00:00.000000Z', response.data)

  @mock.patch.object(survey_service, 'zip_file')
  @mock.patch.object(survey_service, 'get_version')
  def test_download_version_uses_snapshot_without_recording(
      self, get_version_mock, zip_mock):
    get_version_mock.return_value = {
        'surveyname': 'Old',
        'question1': 'Original',
        'creativesize': '160x600',
    }
    zip_mock.return_value = ('old_160x600.zip', io.BytesIO(b'PK\x03\x04'))
    response = self.client.get(
        '/survey/download_zip/abc/version/2', follow_redirects=False)
    self.assertEqual(response.status_code, 200)
    zip_mock.assert_called_once()
    args, kwargs = zip_mock.call_args
    self.assertEqual(args[0], 'abc')
    self.assertEqual(args[1]['question1'], 'Original')
    self.assertIs(kwargs.get('record_version'), False)

  def test_style_presets_are_defined(self):
    ids = [item['id'] for item in css_theme.STYLE_PRESETS]
    self.assertEqual(ids[:4], ['classic', 'dark', 'contrast', 'ocean'])
    self.assertEqual(css_theme.STYLE_PRESETS[0]['label'], 'Classic green')
