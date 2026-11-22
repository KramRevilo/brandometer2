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
import unittest
from unittest import mock

import pandas

import compare
import main
import reporting
import survey_service


class ParseIdsTest(unittest.TestCase):

  def test_unique_capped_and_rejects_injection(self):
    ids = compare.parse_ids('a, a, b;drop, c d, ' + ','.join('x%s' % i for i in range(40)))
    self.assertEqual(ids[0], 'a')
    self.assertEqual(ids[1], 'c')
    self.assertNotIn('b;drop', ids)
    self.assertEqual(len(ids), compare.COMPARE_MAX_IDS)
    self.assertTrue(all(compare._ID_RE.fullmatch(sid) for sid in ids))


class CompareModelTest(unittest.TestCase):

  def test_build_lift_and_client_groups(self):
    t = datetime.datetime(2026, 11, 18)
    df = pandas.DataFrame({
        'CreatedAt': [t, t, t, t],
        'Segmentation': [
            'default_control', 'default_control',
            'default_expose', 'default_expose'],
        'Response': ['1:A', '1:B', '1:A', '1:A'],
        'BomID': ['c1', 'c2', 'e1', 'e2'],
    })
    survey = {
        'surveyname': 'Cola',
        'displayname': 'Cola lift',
        'client': 'Acme',
        'surveytype': 'brand_lift',
        'question1': 'Aware?',
        'answer1a': 'Yes',
        'answer1b': 'No',
    }
    report = reporting.build_report(df, survey, is_lift=True)
    track = reporting.build_report(
        pandas.DataFrame({
            'CreatedAt': [t],
            'Segmentation': ['survey'],
            'Response': ['1:A'],
            'BomID': ['t1'],
        }),
        {'surveyname': 'Track', 'client': 'Acme', 'surveytype': 'brand_track',
         'question1': 'Q', 'answer1a': 'Yes'},
        is_lift=False)
    model = compare.build([
        ('lift-1', survey, report),
        ('track-1', {'surveyname': 'Track', 'client': 'Acme',
                     'surveytype': 'brand_track'}, track),
    ])
    self.assertEqual(model['n_studies'], 2)
    self.assertTrue(model['has_lift'])
    self.assertEqual(model['rows'][0]['client'], 'Acme')
    self.assertIsNotNone(model['rows'][0]['lift'])
    self.assertEqual(model['charts']['lift_by_client']['labels'], ['Acme'])
    self.assertEqual(len(model['charts']['daily']['datasets']), 2)


class CompareRouteTest(unittest.TestCase):

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
    doc = mock.Mock()
    doc.id = doc_id
    doc.to_dict.return_value = data
    doc.exists = True
    return doc

  @mock.patch.object(survey_service, 'get_compare_studies')
  def test_compare_page_charts_and_data_studio(self, studies_mock):
    t = datetime.datetime(2026, 11, 18)
    survey = {
        'surveyname': 'Cola',
        'client': 'Acme',
        'surveytype': 'brand_lift',
        'question1': 'Aware?',
        'answer1a': 'Yes',
        'answer1b': 'No',
    }
    df = pandas.DataFrame({
        'CreatedAt': [t, t, t, t],
        'Segmentation': [
            'default_control', 'default_control',
            'default_expose', 'default_expose'],
        'Response': ['1:A', '1:B', '1:A', '1:A'],
        'BomID': ['c1', 'c2', 'e1', 'e2'],
    })
    report = reporting.build_report(df, survey, is_lift=True)
    studies_mock.return_value = [('lift-1', survey, report)]
    with mock.patch.dict('os.environ', {'PROJECT_ID': 'brandometer2'}):
      response = self.client.get('/reports/compare?ids=lift-1')
    self.assertEqual(response.status_code, 200)
    self.assertIn(b'Compare studies', response.data)
    self.assertIn(b'Lift by study', response.data)
    self.assertIn(b'Daily responses', response.data)
    self.assertIn(b'n vs MIN_N', response.data)
    self.assertIn(b'Export to Data Studio', response.data)
    self.assertIn(b'datastudio.google.com/reporting/create', response.data)
    self.assertIn(b'Type=test preview rows excluded', response.data)

  def test_compare_empty_redirects(self):
    response = self.client.get('/reports/compare')
    self.assertEqual(response.status_code, 302)

  @mock.patch.object(survey_service, 'list_surveys')
  @mock.patch.object(survey_service, 'get_response_counts')
  def test_index_has_compare_controls(self, counts_mock, list_mock):
    counts_mock.return_value = pandas.DataFrame(
        columns=['ID', 'Segmentation', 'max_date', 'days_since_response',
                 'response_count'])
    list_mock.return_value = [
        self._survey('lift-1', {
            'surveyname': 'Cola',
            'surveytype': 'brand_lift',
            'question1': 'Q',
            'created_at': '2026-11-18T12:00:00Z',
        })
    ]
    response = self.client.get('/index')
    self.assertEqual(response.status_code, 200)
    self.assertIn(b'js-compare-id', response.data)
    self.assertIn(b'Compare selected', response.data)
    self.assertIn(b'Compare filtered results', response.data)
    self.assertIn(b'/reports/compare?ids=lift-1', response.data)
