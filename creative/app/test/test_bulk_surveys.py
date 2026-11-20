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
import unittest
from unittest import mock

import bulk_surveys
import main
import survey_service


def _csv(body):
  header = 'surveyname,surveytype,creativesize,question1,answer1a,answer1b\n'
  return (header + body).encode('utf-8')


class BulkSurveyParseTest(unittest.TestCase):

  def test_template_has_surveyname_and_example(self):
    text = bulk_surveys.template_csv().decode('utf-8-sig')
    self.assertTrue(text.startswith('surveyname,'))
    self.assertIn('Acme lift 300x250', text)
    self.assertIn('brand_lift', text)

  def test_valid_row_and_aliases(self):
    rows, errors = bulk_surveys.parse_csv(_csv(
        'Sky,Brand Lift,"300x250,160x600",Q?,Yes,No\n'))
    self.assertEqual(errors, [])
    self.assertEqual(len(rows), 1)
    self.assertTrue(rows[0]['ok'])
    payload = rows[0]['payload']
    self.assertEqual(payload['surveytype'], 'brand_lift')
    self.assertEqual(payload['creativesize'], ['300x250', '160x600'])
    self.assertEqual(payload['question1'], 'Q?')
    self.assertEqual(payload['answer1anext'], 'end')

  def test_missing_required_and_bad_size(self):
    rows, errors = bulk_surveys.parse_csv(_csv(
        ',brand_track,999x111,Q?,Yes,No\n'))
    self.assertEqual(errors, [])
    self.assertFalse(rows[0]['ok'])
    joined = ' '.join(rows[0]['errors'])
    self.assertIn('surveyname', joined)
    self.assertIn('999x111', joined)

  def test_fh_answers_rejected_on_medium_size(self):
    header = (
        'surveyname,creativesize,question1,answer1a,answer1b,answer1f\n')
    raw = (header + 'Tall,300x250,Q?,A,B,F\n').encode('utf-8')
    rows, errors = bulk_surveys.parse_csv(raw)
    self.assertEqual(errors, [])
    self.assertFalse(rows[0]['ok'])
    self.assertTrue(any('F–H' in err or 'F-H' in err for err in rows[0]['errors']))

  def test_empty_csv(self):
    rows, errors = bulk_surveys.parse_csv(b'surveyname,question1\n')
    self.assertEqual(rows, [])
    self.assertTrue(errors)


class BulkSurveyRoutesTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    main.app.config['AUTH_BYPASS'] = True
    main.app.config['WTF_CSRF_ENABLED'] = False
    self.client = main.app.test_client()

  def tearDown(self):
    main.app.config['AUTH_BYPASS'] = False
    main.app.config['WTF_CSRF_ENABLED'] = True
    super().tearDown()

  def test_template_download(self):
    response = self.client.get('/survey/bulk/template.csv')
    self.assertEqual(response.status_code, 200)
    self.assertIn(b'surveyname', response.data)
    self.assertIn('csv', response.mimetype)

  def test_preview_then_commit(self):
    preview = self.client.post(
        '/survey/bulk',
        data={
            'action': 'preview',
            'csv_file': (io.BytesIO(
                _csv('Bulk One,brand_track,300x250,Q?,Yes,No\n')), 'surveys.csv'),
        })
    self.assertEqual(preview.status_code, 200)
    self.assertIn(b'Bulk One', preview.data)
    self.assertIn(b'Create 1 survey', preview.data)
    rows, _errors = bulk_surveys.parse_csv(
        _csv('Bulk One,brand_track,300x250,Q?,Yes,No\n'))
    payloads = bulk_surveys.dumps_payloads(rows)

    with mock.patch.object(survey_service, 'create_from_payload') as create_mock:
      create_mock.return_value = mock.Mock(id='new1')
      commit = self.client.post(
          '/survey/bulk',
          data={'action': 'commit', 'payloads_json': payloads},
          follow_redirects=False)
    self.assertEqual(commit.status_code, 302)
    create_mock.assert_called_once()
    saved = create_mock.call_args[0][0]
    self.assertEqual(saved['surveyname'], 'Bulk One')
    self.assertEqual(saved['question1'], 'Q?')
