# Copyright 2023 Google LLC
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
import unittest
from unittest import mock

import pandas
import survey_service

import main


_COUNTS_COLUMNS = [
    'ID', 'Segmentation', 'max_date', 'days_since_response', 'response_count'
]


class MainRoutesTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    main.app.config['BASIC_AUTH_FORCE'] = False
    self.client = main.app.test_client()
    survey_service.clear_stats_cache()

  def tearDown(self):
    main.app.config['BASIC_AUTH_FORCE'] = True
    super().tearDown()

  def _survey(self, doc_id, data):
    doc = mock.Mock()
    doc.id = doc_id
    doc.to_dict.return_value = data
    doc.exists = True
    return doc

  @mock.patch.object(survey_service, 'get_all_response_counts')
  @mock.patch.object(survey_service, 'list_surveys')
  def test_index_lists_surveys_once(self, list_mock, counts_mock):
    list_mock.return_value = []
    counts_mock.return_value = pandas.DataFrame(columns=_COUNTS_COLUMNS)

    response = self.client.get('/index')

    self.assertEqual(response.status_code, 200)
    list_mock.assert_called_once_with(include_archived=False)
    self.assertIn(b'Show archived', response.data)
    self.assertIn(b'No surveys yet', response.data)

  @mock.patch.object(survey_service, 'get_all_response_counts')
  @mock.patch.object(survey_service, 'list_surveys')
  def test_index_show_archived(self, list_mock, counts_mock):
    list_mock.return_value = []
    counts_mock.return_value = pandas.DataFrame(columns=_COUNTS_COLUMNS)

    response = self.client.get('/index?archived=1')

    self.assertEqual(response.status_code, 200)
    list_mock.assert_called_once_with(include_archived=True)
    self.assertIn(b'Hide archived', response.data)

  @mock.patch.object(survey_service, 'get_all_response_counts')
  @mock.patch.object(survey_service, 'list_surveys')
  def test_index_status_chip_and_no_stats_for_track(
      self, list_mock, counts_mock):
    list_mock.return_value = [
        self._survey('s1', {
            'surveyname': 'Track one',
            'surveytype': 'brand_track',
            'question1': 'Q1',
        })
    ]
    counts_mock.return_value = pandas.DataFrame(columns=_COUNTS_COLUMNS)

    response = self.client.get('/index')

    self.assertEqual(response.status_code, 200)
    self.assertIn(b'No data', response.data)
    self.assertIn(b'text-bg-secondary', response.data)
    self.assertNotIn(b'View Brand Lift Stats', response.data)
    self.assertIn(b'Copy Survey', response.data)
    self.assertIn(b'Archive Survey', response.data)

  @mock.patch.object(survey_service, 'get_all_response_counts')
  @mock.patch.object(survey_service, 'list_surveys')
  def test_index_shows_stats_for_brand_lift(self, list_mock, counts_mock):
    list_mock.return_value = [
        self._survey('s2', {
            'surveyname': 'Lift one',
            'surveytype': 'brand_lift',
            'question1': 'Q1',
        })
    ]
    counts_mock.return_value = pandas.DataFrame({
        'ID': ['s2'],
        'Segmentation': ['default_expose'],
        'max_date': ['2026-11-18'],
        'days_since_response': [1],
        'response_count': [4],
    })

    response = self.client.get('/index')

    self.assertEqual(response.status_code, 200)
    self.assertIn(b'View Brand Lift Stats', response.data)
    self.assertIn(b'Active', response.data)
    self.assertIn(b'text-bg-success', response.data)
    self.assertIn(b'htmx.org', response.data)
    self.assertIn(b'every 30s', response.data)
    self.assertIn(b'document.hidden', response.data)
    self.assertIn(b'/index/stats-partial', response.data)

  @mock.patch.object(survey_service, 'get_all_response_counts')
  @mock.patch.object(survey_service, 'list_surveys')
  def test_index_pagination_preserves_archived(
      self, list_mock, counts_mock):
    list_mock.return_value = [
        self._survey('s%s' % i, {
            'surveyname': 'Survey %s' % i,
            'surveytype': 'brand_track',
            'question1': 'Q',
            'archived': True,
        }) for i in range(5)
    ]
    counts_mock.return_value = pandas.DataFrame(columns=_COUNTS_COLUMNS)

    with mock.patch.object(survey_service, 'HOMEPAGE_PAGE_SIZE', 2):
      response = self.client.get('/index?archived=1&page=2')

    self.assertEqual(response.status_code, 200)
    list_mock.assert_called_once_with(include_archived=True)
    self.assertIn(b'Survey 2', response.data)
    self.assertNotIn(b'Survey 0', response.data)
    self.assertIn(b'archived=1', response.data)
    self.assertIn(b'page=1', response.data)
    self.assertIn(b'page=3', response.data)
    self.assertIn(b'Previous', response.data)
    self.assertIn(b'Next', response.data)

  @mock.patch.object(survey_service, 'get_all_response_counts')
  @mock.patch.object(survey_service, 'list_surveys')
  def test_stats_partial_returns_oob_cells(self, list_mock, counts_mock):
    counts_mock.return_value = pandas.DataFrame({
        'ID': ['s1'],
        'Segmentation': ['default_expose'],
        'max_date': ['2026-11-18'],
        'days_since_response': [1],
        'response_count': [9],
    })

    response = self.client.get('/index/stats-partial?ids=s1')

    self.assertEqual(response.status_code, 200)
    list_mock.assert_not_called()
    self.assertIn(b'id="count-s1"', response.data)
    self.assertIn(b'id="last-s1"', response.data)
    self.assertIn(b'id="status-s1"', response.data)
    self.assertIn(b'hx-swap-oob="true"', response.data)
    self.assertIn(b'9', response.data)
    self.assertIn(b'Active', response.data)

  @mock.patch.object(survey_service, 'list_surveys')
  @mock.patch.object(survey_service, '_fetch_all_response_counts')
  def test_stats_partial_does_not_requery_bq_within_ttl(
      self, fetch_mock, list_mock):
    fetch_mock.return_value = pandas.DataFrame({
        'ID': ['s1'],
        'Segmentation': ['seg'],
        'max_date': ['2026-11-18'],
        'days_since_response': [1],
        'response_count': [4],
    })
    with mock.patch.dict(os.environ, {'STATS_CACHE_SECONDS': '90'}):
      self.client.get('/index/stats-partial?ids=s1')
      self.client.get('/index/stats-partial?ids=s1')
    self.assertEqual(fetch_mock.call_count, 1)
    list_mock.assert_not_called()

  def test_create_page_uses_iframe_preview_and_bootstrap5(self):
    response = self.client.get('/survey/create')
    self.assertEqual(response.status_code, 200)
    self.assertIn(b'bootstrap@5.3.3', response.data)
    self.assertIn(b'navbar-toggler', response.data)
    self.assertNotIn(b'navbar-header', response.data)
    self.assertIn(b'Live preview', response.data)
    self.assertIn(b'<iframe', response.data)
    self.assertIn(b'alpinejs', response.data)
    self.assertIn(b'Advanced (CSS)', response.data)
    self.assertIn(b'Display name', response.data)
    self.assertNotIn(b'refreshFromCssSample', response.data)
    self.assertIn(b'scrolling="no"', response.data)
    self.assertIn(b'width: 302px', response.data)
    self.assertIn(b'height: 252px', response.data)

  @mock.patch.object(survey_service, 'copy_by_id')
  def test_copy_opens_editor(self, copy_mock):
    copy_mock.return_value = mock.Mock(id='new123')

    response = self.client.get(
        '/survey/copy?survey_id=old', follow_redirects=False)

    self.assertEqual(response.status_code, 302)
    self.assertIn('/survey/edit', response.headers['Location'])
    self.assertIn('survey_id=new123', response.headers['Location'])

  @mock.patch.object(survey_service, 'set_archived')
  def test_archive_redirects_home(self, archive_mock):
    response = self.client.get(
        '/survey/archive?survey_id=abc&archived=1', follow_redirects=False)

    archive_mock.assert_called_once_with('abc', True)
    self.assertEqual(response.status_code, 302)

  @mock.patch.object(survey_service, 'set_archived')
  def test_unarchive_from_archived_view(self, archive_mock):
    response = self.client.get(
        '/survey/archive?survey_id=abc&archived=0&view=archived',
        follow_redirects=False)

    archive_mock.assert_called_once_with('abc', False)
    self.assertIn('archived=1', response.headers['Location'])

  @mock.patch.object(survey_service, 'get_doc_by_id')
  def test_reporting_gated_to_brand_lift(self, doc_mock):
    doc_mock.return_value = self._survey('abc', {
        'surveytype': 'brand_track',
        'surveyname': 'Track',
    })

    response = self.client.get(
        '/survey/reporting/abc', follow_redirects=False)

    self.assertEqual(response.status_code, 302)
    self.assertIn('/index', response.headers['Location'])

  @mock.patch.object(survey_service, 'get_question_json', return_value=[])
  @mock.patch.object(survey_service, 'get_doc_by_id')
  def test_preview_does_not_post_to_receiver(self, doc_mock, _json_mock):
    doc_mock.return_value = self._survey('abc', {
        'surveyname': 'Track',
        'question1': 'Q1',
        'responsetype': 'Submit Responses at End of Survey',
    })

    response = self.client.get('/survey/preview/abc')

    self.assertEqual(response.status_code, 200)
    self.assertNotIn(b'?type=survey', response.data)
    self.assertNotIn(b'AW-968433116', response.data)
