# Copyright 2019 Google LLC
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

import csv
import datetime
import math
import os
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

from google.api_core.exceptions import Forbidden
from google.api_core.exceptions import NotFound
from google.cloud import bigquery
from mockfirestore import MockFirestore
import pandas
import reporting
import sequential
import survey_collection
import survey_service


class TestSurveyService(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self.client = MockFirestore()
    self.collection = self.client.collection('test_surveys')
    survey_service.clear_stats_cache()

  def tearDown(self):
    self.client.reset()
    super().tearDown()

  def test_get_all(self):
    # given
    survey_collection.get_all = mock.Mock()
    # when
    survey_service.get_all()
    # then
    assert survey_collection.get_all.call_count == 1

  def test_collection_get_all_with_fields_uses_select(self):
    query = mock.Mock()
    col = mock.Mock()
    col.select.return_value = query
    with mock.patch.object(survey_collection, '_collection', return_value=col):
      survey_collection.get_all(['surveyname', 'archived'])
    col.select.assert_called_once_with(['surveyname', 'archived'])
    query.stream.assert_called_once_with()

  def test_collection_get_all_without_fields_streams_collection(self):
    col = mock.Mock()
    with mock.patch.object(survey_collection, '_collection', return_value=col):
      survey_collection.get_all()
    col.select.assert_not_called()
    col.stream.assert_called_once_with()

  def test_get_by_id(self):
    # given
    survey_collection.get_by_id = mock.Mock()
    # when
    survey_service.get_by_id('mockSurveyId')
    # then
    survey_collection.get_by_id.assert_called_once_with('mockSurveyId')

  def test_get_doc_by_id(self):
    # given
    survey_collection.get_doc_by_id = mock.Mock()
    # when
    survey_service.get_doc_by_id('mockSurveyId')
    # then
    survey_collection.get_doc_by_id.assert_called_once_with('mockSurveyId')

  def test_delete_by_id(self):
    # given
    survey_collection.delete_by_id = mock.Mock()
    # when
    survey_service.delete_by_id('mockSurveyId')
    # then
    survey_collection.delete_by_id.assert_called_once_with('mockSurveyId')

  def test_set_form_data_copies_values_from_a_document(self):
    form = {
        'field1': mock.Mock(data=None),
        'field2': mock.Mock(data='value2'),
        'field3': mock.Mock(data='untouched')
    }

    ref = self.collection.document()
    ref.set({'field1': 'something', 'field2': 'new_value2'})
    doc = ref.get()

    survey_service.set_form_data(form, doc)
    self.assertEqual(form['field1'].data, 'something')
    self.assertEqual(form['field2'].data, 'new_value2')
    self.assertEqual(form['field3'].data, 'untouched')

  def test_set_form_data_skips_keys_not_on_form(self):
    form = {'surveyname': mock.Mock(data=None)}
    ref = self.collection.document()
    ref.set({'surveyname': 'Keep', 'archived': False, 'not_a_field': 1})
    survey_service.set_form_data(form, ref.get())
    self.assertEqual(form['surveyname'].data, 'Keep')

  @mock.patch.object(survey_collection, 'add_version')
  @mock.patch.object(survey_service, 'get_html_template', return_value='<html></html>')
  def test_zip_file_returns_user_readable_filename(self, _html_mock, version_mock):
    survey_id = 'some_test_id'
    survey_dict = {
        'surveyname': 'test survey',
        'question1': 'q1 text',
    }

    version_mock.return_value = {'version': 2}
    filename, _ = survey_service.zip_file(survey_id, survey_dict)
    self.assertRegex(filename, '.*_test-survey_300x250.zip$')
    version_mock.assert_called_once_with(
        survey_id, survey_dict, actor=mock.ANY)
    self.assertEqual(_html_mock.call_args.kwargs.get('creative_version'), 2)

  @mock.patch.object(survey_collection, 'add_version')
  @mock.patch.object(survey_service, 'get_html_template', return_value='<html></html>')
  def test_zip_file_track_has_single_creative_zip(self, _html_mock, _version_mock):
    survey_id = 'some_test_id'
    survey_dict = {
        'surveyname': 'test survey',
        'question1': 'q1 text',
    }

    _, data = survey_service.zip_file(survey_id, survey_dict)
    zf = zipfile.ZipFile(data)
    names = [nzf.filename for nzf in zf.filelist]
    self.assertIn('html5_qa.txt', names)
    zips = [name for name in names if name.endswith('.zip')]
    self.assertEqual(len(zips), 1)
    self.assertRegex(zips[0], '.*_test-survey_300x250_creative.zip$')

  @mock.patch.object(survey_collection, 'add_version')
  @mock.patch.object(survey_service, 'get_html_template', return_value='<html></html>')
  def test_zip_file_includes_size_in_name(self, _html_mock, _version_mock):
    filename, data = survey_service.zip_file('id1', {
        'surveyname': 'sky',
        'question1': 'q',
        'creativesize': '160x600',
    })
    self.assertRegex(filename, '.*_sky_160x600.zip$')
    zf = zipfile.ZipFile(data)
    self.assertRegex(zf.filelist[0].filename, '.*_sky_160x600_creative.zip$')

  @mock.patch.object(survey_collection, 'add_version')
  @mock.patch.object(survey_service, 'get_html_template', return_value='<html></html>')
  def test_zip_file_brand_lift_has_control_and_expose(self, _html_mock, _version_mock):
    survey_id = 'some_test_id'
    survey_dict = {
        'surveyname': 'test survey',
        'question1': 'q1 text',
        'surveytype': 'brand_lift',
    }

    _, data = survey_service.zip_file(survey_id, survey_dict)
    zf = zipfile.ZipFile(data)
    names = sorted([nzf.filename for nzf in zf.filelist])
    self.assertIn('html5_qa.txt', names)
    zips = [name for name in names if name.endswith('.zip')]
    self.assertEqual(len(zips), 2)
    self.assertRegex(zips[0], '.*_test-survey_300x250_default_control.zip$')
    self.assertRegex(zips[1], '.*_test-survey_300x250_default_expose.zip$')

  def test_write_html_template(self):
    segments = ['segment1', 'segment2', 'segment3']
    survey_dict = {'question1': 'q1 text', 'answer1a': 'a1a test'}
    original_render = survey_service.render_template
    self.addCleanup(setattr, survey_service, 'render_template', original_render)
    survey_service.render_template = mock.Mock(
        return_value='<html>placeholder</html>')

    zips = survey_service.write_html_template('id1', survey_dict, 'test_prefix',
                                              segments)

    self.assertEqual(len(zips), len(segments))
    self.assertEqual(zips[0].filename, '/tmp/test_prefix_segment1.zip')
    self.assertEqual(zips[1].filename, '/tmp/test_prefix_segment2.zip')
    self.assertEqual(zips[2].filename, '/tmp/test_prefix_segment3.zip')

  def test_write_html_template_empty_seg_uses_creative_suffix(self):
    original_render = survey_service.render_template
    self.addCleanup(setattr, survey_service, 'render_template', original_render)
    survey_service.render_template = mock.Mock(
        return_value='<html>placeholder</html>')

    zips = survey_service.write_html_template(
        'id1', {'question1': 'q1 text'}, 'test_prefix', [''])

    self.assertEqual(len(zips), 1)
    self.assertEqual(zips[0].filename, '/tmp/test_prefix_creative.zip')

  def test_delete_tmp_zip_files(self):
    os.remove = mock.Mock()
    with tempfile.TemporaryDirectory() as tmpdir:
      zip1 = zipfile.ZipFile(tmpdir + 'mock-file-name.zip', 'w')
      zip2 = zipfile.ZipFile(tmpdir + 'mock-file-name2.zip', 'w')

      survey_service.delete_tmp_zip_files([zip1, zip2])

      expected_calls = [mock.call(zip1.filename), mock.call(zip2.filename)]
      os.remove.assert_has_calls(expected_calls)
      assert os.remove.call_count == 2

  def test_get_all_question_text(self):
    survey_dict = {
        'question1': 'q1 text',
        'question2': 'q2 text',
    }

    result = survey_service.get_all_question_text(survey_dict)

    self.assertEqual(result, ['q1 text', 'q2 text'])

  def test_get_all_question_text_includes_text_after_missed_questions(self):
    survey_dict = {
        'question1': 'q1 text',
        'question2': 'q3 text',
    }

    result = survey_service.get_all_question_text(survey_dict)

    self.assertEqual(result, ['q1 text', 'q3 text'])

  def test_get_question_json_converts_to_format_expected_by_creative(self):
    survey = {
        'question1': 'q1 text',
        'question1type': 'q1type',
        'question1order': 'ORDERED',
        'answer1a': 'a1a',
        'answer1anext': 'end',
        'answer1b': 'a1b',
        'answer1bnext': '2',
        'question2': 'q2 text',
    }
    json = survey_service.get_question_json(survey)
    self.assertDictEqual(
        json[0], {
            'answersOrder': 'ORDERED',
            'id':
                1,
            'text':
                'q1 text',
            'type':
                'q1type',
            'next_question': {
                'A': 'end',
                'B': '2'
            },
            'options': [
                {
                    'id': 'A',
                    'role': 'option',
                    'text': 'a1a'
                },
                {
                    'id': 'B',
                    'role': 'option',
                    'text': 'a1b'
                },
            ]
        })
    self.assertEqual(json[1]['text'], 'q2 text')

  def test_get_question_json_skips_empty_and_includes_answer_e(self):
    survey = {
        'question1': 'q1',
        'answer1a': 'a',
        'answer1b': 'b',
        'answer1d': 'd-skip-c',
        'answer1e': 'e',
        'answer1enext': 'end',
    }
    json = survey_service.get_question_json(survey)
    ids = [opt['id'] for opt in json[0]['options']]
    self.assertEqual(ids, ['A', 'B', 'D', 'E'])
    self.assertEqual(json[0]['next_question']['E'], 'end')
    self.assertEqual(len(json), 1)

  def test_get_thank_you_text_default(self):
    text = survey_service.get_thank_you_text({'language': 'ms'})
    self.assertEqual(text, 'Terima Kasih')

  def test_get_thank_you_text_defaults_to_english_if_no_lang(self):
    text = survey_service.get_thank_you_text({})
    self.assertEqual(text, 'Thank You')

  def test_get_thank_you_text_defaults_to_english_if_unknown_lang(self):
    text = survey_service.get_thank_you_text({'language': 'ZZ'})
    self.assertEqual(text, 'Thank You')

  def test_get_next_text_default(self):
    text = survey_service.get_next_text({'language': 'ja'})
    self.assertEqual(text, '次へ')

  def test_get_next_text_defaults_to_english_if_no_lang(self):
    text = survey_service.get_next_text({})
    self.assertEqual(text, 'Next')

  def test_get_next_text_defaults_to_english_if_unknown_lang(self):
    text = survey_service.get_next_text({'language': 'ZZ'})
    self.assertEqual(text, 'Next')

  def test_get_comment_text_default(self):
    text = survey_service.get_comment_text({'language': 'zh'})
    self.assertEqual(text, '选择所有适用的')

  def test_get_comment_text_defaults_to_english_if_no_lang(self):
    text = survey_service.get_comment_text({})
    self.assertEqual(text, 'Choose all applicable')

  def test_get_comment_text_defaults_to_english_if_unknown_lang(self):
    text = survey_service.get_comment_text({'language': 'ZZ'})
    self.assertEqual(text, 'Choose all applicable')

  def test_fetch_survey_response_rows_is_parameterized(self):
    mock_bigquery_client = mock.create_autospec(bigquery.Client)
    with mock.patch.dict(os.environ, {'TABLE_ID': 'project.responses.responses'}):
      survey_service.fetch_survey_response_rows(
          'sid-1', client=mock_bigquery_client)

    query_call = mock_bigquery_client.query.mock_calls[0]
    sql = query_call.args[0]
    survey_param = query_call.kwargs['job_config'].query_parameters[0]
    self.assertRegex(sql, 'WHERE ID = @survey_id')
    self.assertIn('BomID', sql)
    self.assertIn('RespondentID', sql)
    self.assertIn('PlacementID', sql)
    self.assertIn('CreativeSize', sql)
    self.assertIn('CreativeVersion', sql)
    self.assertIn('Type', sql)
    self.assertIn("IFNULL(Type, 'survey') != 'test'", sql)
    self.assertNotIn('STARTS_WITH', sql)
    self.assertNotIn('RandomTimeStamp', sql)
    self.assertEqual(survey_param.name, 'survey_id')
    self.assertEqual(survey_param.value, 'sid-1')

  def test_fetch_survey_response_rows_can_include_test(self):
    mock_bigquery_client = mock.create_autospec(bigquery.Client)
    with mock.patch.dict(os.environ, {'TABLE_ID': 'project.responses.responses'}):
      survey_service.fetch_survey_response_rows(
          'sid-1', client=mock_bigquery_client, include_test=True)
    sql = mock_bigquery_client.query.mock_calls[0].args[0]
    self.assertNotIn("IFNULL(Type, 'survey') != 'test'", sql)
    self.assertIn('Type', sql)

  @mock.patch.object(survey_service, '_get_bq_client')
  def test_homepage_counts_sql_collapses_bomid(self, bq_client_mock):
    client = mock.Mock()
    client.query.side_effect = NotFound('Table not found')
    bq_client_mock.return_value = client

    survey_service._fetch_all_response_counts(['sid-1', 'sid-2'])

    sql = client.query.call_args[0][0]
    job_config = client.query.call_args.kwargs['job_config']
    names = [p.name for p in job_config.query_parameters]
    self.assertIn('BomID', sql)
    self.assertIn('RespondentID', sql)
    self.assertIn('session_key', sql)
    self.assertIn('n_answers', sql)
    self.assertIn('PARTITION BY ID, session_key', sql)
    self.assertIn('ID IN UNNEST(@survey_ids)', sql)
    self.assertIn("IFNULL(Type, 'survey') != 'test'", sql)
    self.assertIn('CAST(CreatedAt AS TIMESTAMP)', sql)
    self.assertIn('TIMESTAMP_SUB', sql)
    self.assertNotIn('WHERE RespondentID IS NOT NULL', sql)
    self.assertNotIn('RandomTimeStamp', sql)
    self.assertIn('survey_ids', names)
    self.assertIn('lookback_days', names)
    survey_ids = [
        p for p in job_config.query_parameters if p.name == 'survey_ids'][0]
    self.assertEqual(survey_ids.values, ['sid-1', 'sid-2'])

  @mock.patch.object(survey_service, '_get_bq_client')
  def test_homepage_counts_sql_can_include_test(self, bq_client_mock):
    client = mock.Mock()
    client.query.side_effect = NotFound('Table not found')
    bq_client_mock.return_value = client

    survey_service._fetch_all_response_counts(
        ['sid-1'], include_test=True)

    sql = client.query.call_args[0][0]
    self.assertNotIn("IFNULL(Type, 'survey') != 'test'", sql)
    self.assertIn('ID IN UNNEST(@survey_ids)', sql)
    self.assertIn('IFNULL(Type, \'survey\') AS Type', sql)
    self.assertIn('GROUP BY 1, 2, 3', sql)

  @mock.patch.object(survey_service, '_get_bq_client')
  def test_homepage_counts_sql_can_disable_partition_filter(
      self, bq_client_mock):
    client = mock.Mock()
    client.query.side_effect = NotFound('Table not found')
    bq_client_mock.return_value = client

    with mock.patch.dict(os.environ, {'STATS_LOOKBACK_DAYS': '0'}):
      survey_service._fetch_all_response_counts(['sid-1'])

    sql = client.query.call_args[0][0]
    job_config = client.query.call_args.kwargs['job_config']
    names = [p.name for p in job_config.query_parameters]
    self.assertIn('ID IN UNNEST(@survey_ids)', sql)
    self.assertNotIn('TIMESTAMP_SUB', sql)
    self.assertNotIn('DATETIME_SUB', sql)
    self.assertNotIn('lookback_days', names)

  def test_fetch_all_response_counts_skips_bq_when_no_ids(self):
    with mock.patch.object(survey_service, '_get_bq_client') as factory:
      df = survey_service._fetch_all_response_counts([])
    factory.assert_not_called()
    self.assertTrue(df.empty)

  def test_get_survey_responses_limits_to_given_survey(self):
    mock_bigquery_client = mock.create_autospec(bigquery.Client)
    query = """
        SELECT CreatedAt, Segmentation, Response
        FROM `project.responses.responses`
        WHERE ID = @survey_id
    """

    survey_service.get_survey_responses(
        12345, query, client=mock_bigquery_client)

    query_call = mock_bigquery_client.query.mock_calls[0]
    sql = query_call.args[0]
    survey_param = query_call.kwargs['job_config'].query_parameters[0]
    self.assertRegex(sql, 'WHERE ID = @survey_id')
    self.assertEqual(survey_param.name, 'survey_id')
    self.assertEqual(survey_param.value, 12345)

  def test_get_survey_responses_missing_table_returns_empty_frame(self):
    mock_bigquery_client = mock.create_autospec(bigquery.Client)
    mock_bigquery_client.query.side_effect = NotFound('Table not found')

    df = survey_service.get_survey_responses(
        12345, 'SELECT 1', client=mock_bigquery_client)

    self.assertTrue(df.empty)
    self.assertEqual(
        list(df.columns),
        ['CreatedAt', 'Segmentation', 'Response', 'BomID',
         'RespondentID', 'RespondentIDSource',
         'CampaignID', 'PlacementID', 'SiteID', 'AdCreativeID',
         'CreativeSize', 'CreativeVersion', 'Type'])

  @mock.patch.object(survey_service, '_get_bq_client')
  def test_get_all_response_counts_missing_table_returns_empty_frame(
      self, bq_client_mock):
    client = mock.Mock()
    client.query.side_effect = NotFound('Table not found')
    bq_client_mock.return_value = client

    df = survey_service.get_response_counts(['s1'])

    self.assertTrue(df.empty)
    self.assertEqual(
        list(df.columns),
        ['ID', 'Segmentation', 'Type', 'max_date', 'days_since_response',
         'response_count', 'n_q1', 'k_q1_a'])

  def _missing_survey_doc(self):
    doc = mock.Mock()
    doc.exists = False
    doc.to_dict.return_value = {}
    return doc

  @mock.patch.object(survey_service, 'get_doc_by_id')
  @mock.patch.object(survey_service, 'get_survey_responses')
  def test_download_responses(self, responses_mock, doc_mock):
    doc_mock.return_value = self._missing_survey_doc()
    t1 = datetime.datetime.now()
    t2 = t1 + datetime.timedelta(hours=-1)
    responses_mock.return_value = pandas.DataFrame({
        'CreatedAt': [t1, t2],
        'Segmentation': ['seg1', 'seg2'],
        'Response': ['1:r1a', '1:r2b']
    })

    raw_csv = survey_service.download_responses(1)
    responses = list(csv.DictReader(raw_csv.splitlines()))

    self.assertEqual(responses[0]['Date'], str(t1))
    self.assertEqual(responses[0]['Segment'], 'seg1')
    self.assertEqual(responses[0]['Response 1'], 'r1a')
    self.assertEqual(responses[1]['Date'], str(t2))
    self.assertEqual(responses[1]['Segment'], 'seg2')
    self.assertEqual(responses[1]['Response 1'], 'r2b')
    self.assertNotIn('Dimension 2', responses[0])
    self.assertNotIn('Control/Expose', responses[0])

  @mock.patch.object(survey_service, 'get_doc_by_id')
  @mock.patch.object(survey_service, 'get_survey_responses')
  def test_download_responses_brand_lift_uses_control_expose_column(
      self, responses_mock, doc_mock):
    doc = mock.Mock()
    doc.exists = True
    doc.to_dict.return_value = {'surveytype': 'brand_lift'}
    doc_mock.return_value = doc
    responses_mock.return_value = pandas.DataFrame({
        'CreatedAt': [datetime.datetime.now()],
        'Segmentation': ['default_control'],
        'Response': ['1:r1a']
    })

    raw_csv = survey_service.download_responses(1)
    responses = list(csv.DictReader(raw_csv.splitlines()))

    self.assertEqual(responses[0]['Control/Expose'], 'default_control')
    self.assertNotIn('Dimension 2', responses[0])
    self.assertNotIn('Segment', responses[0])

  @mock.patch.object(survey_service, 'get_doc_by_id')
  @mock.patch.object(survey_service, 'get_survey_responses')
  def test_download_responses_with_multi_question_responses(
      self, responses_mock, doc_mock):
    doc_mock.return_value = self._missing_survey_doc()
    responses_mock.return_value = pandas.DataFrame({
        'CreatedAt': [datetime.datetime.now()],
        'Segmentation': ['seg1'],
        'Response': ['1:r1a|2:r1b||4:r1e|']
    })

    raw_csv = survey_service.download_responses(surveyid=1234)
    responses = list(csv.DictReader(raw_csv.splitlines()))

    self.assertEqual(responses[0]['Response 1'], 'r1a')
    self.assertEqual(responses[0]['Response 2'], 'r1b')
    self.assertEqual(responses[0]['Response 3'], '')
    self.assertEqual(responses[0]['Response 4'], 'r1e')
    self.assertEqual(responses[0]['Response 5'], '')

  @mock.patch.object(survey_service, 'get_doc_by_id')
  @mock.patch.object(survey_service, 'get_survey_responses')
  def test_download_responses_returns_empty_csv_with_no_responses(
      self, responses_mock, doc_mock):
    doc_mock.return_value = self._missing_survey_doc()
    responses_mock.return_value = pandas.DataFrame({
        'CreatedAt': [],
        'Segmentation': [],
        'Response': []
    })

    raw_csv = survey_service.download_responses(surveyid=1234)
    self.assertEqual(raw_csv.strip(), 'Date,Segment')

  @mock.patch.object(survey_service, 'get_doc_by_id')
  @mock.patch.object(survey_service, 'get_survey_responses')
  def test_download_responses_consolidates_bomid(
      self, responses_mock, doc_mock):
    doc_mock.return_value = self._missing_survey_doc()
    t1 = datetime.datetime(2026, 11, 1, 10, 0, 0)
    t2 = datetime.datetime(2026, 11, 1, 10, 1, 0)
    responses_mock.return_value = pandas.DataFrame({
        'CreatedAt': [t1, t2],
        'Segmentation': ['seg1', 'seg1'],
        'Response': ['1:A', '1:A|2:B'],
        'BomID': ['b1', 'b1'],
    })

    raw_csv = survey_service.download_responses(1)
    responses = list(csv.DictReader(raw_csv.splitlines()))

    self.assertEqual(len(responses), 1)
    self.assertEqual(responses[0]['Response 1'], 'A')
    self.assertEqual(responses[0]['Response 2'], 'B')

  @mock.patch.object(survey_service, 'get_doc_by_id')
  @mock.patch.object(survey_service, 'get_survey_responses')
  def test_download_breakouts_csv(self, responses_mock, doc_mock):
    doc = mock.Mock()
    doc.exists = True
    doc.to_dict.return_value = {
        'surveytype': 'brand_lift',
        'question1': 'Aware?',
        'answer1a': 'Yes',
        'answer1b': 'No',
    }
    doc_mock.return_value = doc
    t = datetime.datetime(2026, 11, 18, 12, 0, 0)
    responses_mock.return_value = pandas.DataFrame({
        'CreatedAt': [t, t],
        'Segmentation': ['default_control', 'default_expose'],
        'Response': ['1:A', '1:A'],
        'BomID': ['c1', 'e1'],
        'CreativeSize': ['300x250', '300x250'],
        'PlacementID': ['p1', 'p1'],
        'SiteID': ['pub-1', 'pub-1'],
        'AdCreativeID': ['cr1', 'cr1'],
    })
    raw_csv = survey_service.download_breakouts('sid-1')
    rows = list(csv.DictReader(raw_csv.splitlines()))
    self.assertTrue(rows)
    self.assertEqual(rows[0]['dimension'], 'overall')
    size_rows = [row for row in rows if row['dimension'] == 'Size']
    self.assertTrue(size_rows)
    self.assertEqual(size_rows[0]['slice'], '300x250')
    site_rows = [row for row in rows if row['dimension'] == 'Site']
    self.assertTrue(site_rows)
    self.assertEqual(site_rows[0]['slice'], 'pub-1')
    self.assertEqual(size_rows[0]['answer_id'], 'A')
    self.assertEqual(size_rows[0]['k_control'], '1')
    self.assertEqual(size_rows[0]['k_expose'], '1')

  @mock.patch.object(survey_service, 'get_doc_by_id')
  @mock.patch.object(survey_service, 'get_survey_responses')
  def test_iter_response_csv_streams_chunks(self, responses_mock, doc_mock):
    doc_mock.return_value = self._missing_survey_doc()
    t = datetime.datetime.now()
    responses_mock.return_value = pandas.DataFrame({
        'CreatedAt': [t, t, t],
        'Segmentation': ['seg1', 'seg2', 'seg3'],
        'Response': ['1:A', '1:B', '1:C'],
        'BomID': ['b1', 'b2', 'b3'],
    })

    gen = survey_service.iter_response_csv(1, chunksize=1)
    self.assertTrue(hasattr(gen, '__next__'))
    chunks = list(gen)
    self.assertEqual(len(chunks), 3)
    self.assertTrue(chunks[0].startswith('Date,'))
    self.assertIn('seg1', chunks[0])
    self.assertFalse(chunks[1].startswith('Date,'))
    self.assertIn('seg2', chunks[1])
    joined = ''.join(chunks)
    self.assertEqual(len(list(csv.DictReader(joined.splitlines()))), 3)

  @mock.patch.object(survey_service, 'get_survey_responses')
  def test_get_brand_lift_results(self, responses_mock):
    responses_mock.return_value = pandas.DataFrame({
        'CreatedAt': 4 * [datetime.datetime.now()],
        'Segmentation': ['expose', 'expose', 'control', 'control'],
        'Response': ['1:A', '1:A', '1:A', '1:B']
    })

    results = survey_service.get_brand_lift_results(1)
    q1_expose_lift = results[0][0]
    q1_control_lift = results[0][1]
    q1_lift = results[0][2]

    # Expose group has A for 2/2 of answers
    self.assertEqual(1, q1_expose_lift[0])
    # Expose group has B for 0/2 of answers
    self.assertEqual(0, q1_expose_lift[1])

    # Control group has A for 1/2 of answers
    self.assertEqual(0.5, q1_control_lift[0])
    # Control group has B for 1/2 of answers
    self.assertEqual(0.5, q1_control_lift[1])

    # Answer A is 100% more likely in expose group
    self.assertEqual(1, q1_lift[0])
    # Answer B is 100% less likely in expose group
    self.assertEqual(-1, q1_lift[1])

  @mock.patch.object(survey_service, 'get_survey_responses')
  def test_get_brand_lift_results_with_multi_question_responses(
      self, responses_mock):
    responses_mock.return_value = pandas.DataFrame({
        'CreatedAt': 4 * [datetime.datetime.now()],
        'Segmentation': ['expose', 'expose', 'control', 'control'],
        'Response': ['1:A|2:A', '1:A|2:B', '1:A|2:B', '1:B|2:B']
    })

    results = survey_service.get_brand_lift_results(1)
    q2_expose_lift = results[1][0]
    q2_control_lift = results[1][1]
    q2_lift = results[1][2]

    # Expose group has A for 1/2 of answers
    self.assertEqual(0.5, q2_expose_lift[0])
    # Expose group has B for 1/2 of answers
    self.assertEqual(0.5, q2_expose_lift[1])

    # Control group has A for 0/2 of answers
    self.assertEqual(0, q2_control_lift[0])
    # Control group has B for 2/2 of answers
    self.assertEqual(1, q2_control_lift[1])

    # Control share of A is 0, so lift is undefined (not inf).
    self.assertTrue(math.isnan(q2_lift[0]))
    # Answer B is 50% less likely in expose group
    self.assertEqual(-0.5, q2_lift[1])

  @mock.patch.object(survey_service, 'get_survey_responses')
  def test_get_brand_lift_results_with_no_responses(self, responses_mock):
    responses_mock.return_value = pandas.DataFrame({
        'CreatedAt': [],
        'Segmentation': [],
        'Response': []
    })

    results = survey_service.get_brand_lift_results(1)

    self.assertEqual(results, [])

  @mock.patch.object(survey_service, 'get_survey_responses')
  def test_get_brand_lift_results_consolidates_bomid(self, responses_mock):
    t1 = datetime.datetime(2026, 11, 1, 10, 0, 0)
    t2 = datetime.datetime(2026, 11, 1, 10, 1, 0)
    responses_mock.return_value = pandas.DataFrame({
        'CreatedAt': [t1, t2, t1, t1],
        'Segmentation': ['expose', 'expose', 'control', 'control'],
        'Response': ['1:A', '1:A|2:B', '1:A', '1:B'],
        'BomID': ['e1', 'e1', 'c1', 'c2'],
    })

    results = survey_service.get_brand_lift_results(1)
    # One expose respondent (the cumulative 1:A|2:B) and two control.
    q1_expose = results[0][0]
    self.assertEqual(1, q1_expose[0])
    self.assertEqual(0, q1_expose[1])

  @mock.patch.object(survey_service, 'get_survey_responses')
  def test_get_brand_lift_results_corrects_segment_names(self, responses_mock):
    responses_mock.return_value = pandas.DataFrame({
        'CreatedAt': 3 * [datetime.datetime.now()],
        'Segmentation': ['default_expose', 'default_expose', 'default_control'],
        'Response': ['1:A', '1:A', '1:B']
    })

    results = survey_service.get_brand_lift_results(1)
    q1_expose_lift = results[0][0]
    q1_control_lift = results[0][1]

    # Expose group has A for 2/2 of answers
    self.assertEqual(1, q1_expose_lift[0])
    # Expose group has B for 0/2 of answers
    self.assertEqual(0, q1_expose_lift[1])

    # Control group has A for 0/1 of answers
    self.assertEqual(0, q1_control_lift[0])
    # Control group has B for 1/1 of answers
    self.assertEqual(1, q1_control_lift[1])

  def test_classify_status(self):
    self.assertEqual(
        survey_service.classify_status(None), ('No data', 'secondary'))
    self.assertEqual(survey_service.classify_status(0), ('Active', 'success'))
    self.assertEqual(survey_service.classify_status(3), ('Active', 'success'))
    self.assertEqual(survey_service.classify_status(4), ('Stale', 'warning'))
    self.assertEqual(survey_service.classify_status(7), ('Stale', 'warning'))
    self.assertEqual(
        survey_service.classify_status(8), ('Timed out', 'danger'))
    self.assertEqual(
        survey_service.classify_status(14), ('Timed out', 'danger'))

  def test_parse_status_filter_canonical_slugs(self):
    self.assertEqual(survey_service.parse_status_filter(''), '')
    self.assertEqual(survey_service.parse_status_filter('All'), '')
    self.assertEqual(survey_service.parse_status_filter('bogus'), '')
    self.assertEqual(survey_service.parse_status_filter('active'), 'active')
    self.assertEqual(survey_service.parse_status_filter('Timed-Out'), 'timed_out')
    self.assertEqual(survey_service.parse_status_filter('no data'), 'no_data')
    self.assertEqual(
        [item[0] for item in survey_service.homepage_status_choices()],
        ['active', 'stale', 'timed_out', 'no_data'])

  def test_apply_status_filter_uses_one_counts_frame(self):
    docs = [
        self._survey_doc('a', {'surveyname': 'Active one'}),
        self._survey_doc('s', {'surveyname': 'Stale one'}),
        self._survey_doc('t', {'surveyname': 'Timed out one'}),
        self._survey_doc('n', {'surveyname': 'No data one'}),
    ]
    counts = pandas.DataFrame({
        'ID': ['a', 's', 't'],
        'Segmentation': ['survey', 'survey', 'survey'],
        'max_date': ['2026-11-18', '2026-11-14', '2026-11-01'],
        'days_since_response': [1, 5, 12],
        'response_count': [10, 8, 3],
    })
    self.assertEqual(
        [d.id for d in survey_service.apply_status_filter(
            docs, 'active', counts)],
        ['a'])
    self.assertEqual(
        [d.id for d in survey_service.apply_status_filter(
            docs, 'stale', counts)],
        ['s'])
    self.assertEqual(
        [d.id for d in survey_service.apply_status_filter(
            docs, 'timed_out', counts)],
        ['t'])
    self.assertEqual(
        [d.id for d in survey_service.apply_status_filter(
            docs, 'no_data', counts)],
        ['n'])
    self.assertEqual(
        [d.id for d in survey_service.apply_status_filter(docs, '', counts)],
        ['a', 's', 't', 'n'])

  def test_parse_result_filter_and_track_target_moe(self):
    self.assertEqual(survey_service.parse_result_filter(''), '')
    self.assertEqual(
        survey_service.parse_result_filter('Significant-Lift'),
        'significant_lift')
    self.assertEqual(survey_service.parse_result_filter('flat'), 'flat_negative')
    self.assertEqual(
        [item[0] for item in survey_service.homepage_result_choices()],
        ['significant_lift', 'not_yet', 'flat_negative', 'below_min_n',
         'no_data', 'precise'])
    self.assertAlmostEqual(survey_service.track_target_moe(), 0.03)
    with mock.patch.dict(os.environ, {'TRACK_TARGET_MOE': '2.5'}):
      self.assertAlmostEqual(survey_service.track_target_moe(), 0.025)
    with mock.patch.dict(os.environ, {'TRACK_TARGET_MOE': '0.04'}):
      self.assertAlmostEqual(survey_service.track_target_moe(), 0.04)

  def test_homepage_lift_progress_and_result_match_report_sequential(self):
    t = datetime.datetime(2026, 11, 18)
    rows = []
    for i in range(40):
      rows.append({
          'CreatedAt': t, 'Segmentation': 'default_control',
          'Response': '1:A' if i < 10 else '1:B', 'BomID': 'c%s' % i,
      })
    for i in range(40):
      rows.append({
          'CreatedAt': t, 'Segmentation': 'default_expose',
          'Response': '1:A' if i < 30 else '1:B', 'BomID': 'e%s' % i,
      })
    df = pandas.DataFrame(rows)
    survey = {
        'question1': 'Aware?', 'answer1a': 'Yes', 'answer1b': 'No',
        'surveytype': 'brand_lift',
        'sample_plan': {
            'baseline': 0.2, 'mde_mode': 'relative', 'mde_relative': 0.1,
            'confidence': 0.95, 'power': 0.8, 'comparisons': 1,
            'response_rate': 0.01, 'control_share': 0.5,
            'n_control': 200, 'n_expose': 200,
        },
    }
    report = reporting.build_report(df, survey, is_lift=True)
    counts = pandas.DataFrame({
        'ID': ['lift1', 'lift1'],
        'Segmentation': ['default_control', 'default_expose'],
        'max_date': ['2026-11-18', '2026-11-18'],
        'days_since_response': [1, 1],
        'response_count': [40, 40],
        'n_q1': [40, 40],
        'k_q1_a': [10, 30],
    })
    stats = survey_service.build_stat_array(
        ['lift1'], counts_df=counts,
        surveys=[self._survey_doc('lift1', survey)])
    item = stats[0]
    self.assertEqual(item['progress_text'], '20%')
    self.assertEqual(item['progress_sort'], 20.0)
    self.assertEqual(report['sequential']['status'], sequential.STATUS_POSITIVE)
    self.assertEqual(item['result_key'], 'significant_lift')
    self.assertEqual(item['result_text'], 'Significant lift')
    q1a = report['questions'][0]['answers'][0]
    self.assertEqual(q1a['k_control'], 10)
    self.assertEqual(q1a['k_expose'], 30)

  def test_homepage_lift_no_plan_uses_min_n_and_below_min_badge(self):
    counts = pandas.DataFrame({
        'ID': ['s', 's'],
        'Segmentation': ['default_control', 'default_expose'],
        'max_date': ['2026-11-18', '2026-11-18'],
        'days_since_response': [1, 1],
        'response_count': [15, 20],
        'n_q1': [15, 20],
        'k_q1_a': [4, 8],
    })
    survey = self._survey_doc('s', {'surveytype': 'brand_lift'})
    item = survey_service.build_stat_array(
        ['s'], counts_df=counts, surveys=[survey])[0]
    self.assertEqual(item['progress_text'], '50%')
    self.assertIn('30-per-arm', item['progress_title'])
    self.assertEqual(item['result_key'], 'below_min_n')
    self.assertEqual(item['result_text'], 'Below min n')

  def test_homepage_track_progress_and_margin_match_report_wilson(self):
    t = datetime.datetime(2026, 11, 18)
    rows = [{'CreatedAt': t, 'Segmentation': 'survey',
             'Response': '1:A' if i < 200 else '1:B', 'BomID': 'r%s' % i}
            for i in range(400)]
    df = pandas.DataFrame(rows)
    survey = {
        'question1': 'Aware?', 'answer1a': 'Yes', 'answer1b': 'No',
        'surveytype': 'brand_track',
    }
    report = reporting.build_report(df, survey, is_lift=False)
    q1a = report['questions'][0]['answers'][0]
    margin = reporting.wilson_margin(200, 400)
    self.assertAlmostEqual(
        (q1a['ci'][1] - q1a['ci'][0]) / 2.0, margin, places=6)
    counts = pandas.DataFrame({
        'ID': ['track1'],
        'Segmentation': ['survey'],
        'max_date': ['2026-11-18'],
        'days_since_response': [1],
        'response_count': [400],
        'n_q1': [400],
        'k_q1_a': [200],
    })
    item = survey_service.build_stat_array(
        ['track1'], counts_df=counts,
        surveys=[self._survey_doc('track1', survey)])[0]
    self.assertAlmostEqual(item['progress_sort'], min(100.0, 100.0 * 0.03 / margin), places=4)
    self.assertIn('±', item['result_text'])
    self.assertEqual(item['result_key'], 'not_yet')
    self.assertEqual(item['result_badge'], '')
    precise_counts = pandas.DataFrame({
        'ID': ['track1'],
        'Segmentation': ['survey'],
        'max_date': ['2026-11-18'],
        'days_since_response': [1],
        'response_count': [2000],
        'n_q1': [2000],
        'k_q1_a': [1000],
    })
    precise = survey_service.build_stat_array(
        ['track1'], counts_df=precise_counts,
        surveys=[self._survey_doc('track1', survey)])[0]
    self.assertEqual(precise['result_key'], 'precise')
    self.assertEqual(precise['result_badge'], 'Precise')
    self.assertEqual(precise['progress_text'], '100%')

  def test_sort_progress_and_result_missing_last(self):
    docs = [
        self._survey_doc('low', {'surveyname': 'Low', 'created_at': '2026-01-01T00:00:00Z'}),
        self._survey_doc('high', {'surveyname': 'High', 'created_at': '2026-01-02T00:00:00Z'}),
        self._survey_doc('none', {'surveyname': 'None', 'created_at': '2026-01-03T00:00:00Z'}),
    ]
    stats = {
        'low': {'progress_sort': 10.0, 'result_sort': 1},
        'high': {'progress_sort': 90.0, 'result_sort': 5},
    }
    by_progress = survey_service.sort_surveys(
        docs, 'progress', 'asc', stats_by_id=stats)
    self.assertEqual([d.id for d in by_progress], ['low', 'high', 'none'])
    by_result = survey_service.sort_surveys(
        docs, 'result', 'desc', stats_by_id=stats)
    self.assertEqual([d.id for d in by_result], ['high', 'low', 'none'])

  def test_apply_result_filter_uses_one_counts_frame(self):
    docs = [
        self._survey_doc('lift', {
            'surveyname': 'Lift', 'surveytype': 'brand_lift',
            'sample_plan': {'n_control': 40, 'n_expose': 40, 'confidence': 0.95,
                            'comparisons': 1, 'baseline': 0.2, 'mde_relative': 0.5,
                            'mde_mode': 'relative', 'power': 0.8, 'response_rate': 0.01,
                            'control_share': 0.5},
        }),
        self._survey_doc('empty', {
            'surveyname': 'Empty', 'surveytype': 'brand_lift',
        }),
    ]
    counts = pandas.DataFrame({
        'ID': ['lift', 'lift'],
        'Segmentation': ['default_control', 'default_expose'],
        'max_date': ['2026-11-18', '2026-11-18'],
        'days_since_response': [1, 1],
        'response_count': [40, 40],
        'n_q1': [40, 40],
        'k_q1_a': [10, 30],
    })
    matched = survey_service.apply_result_filter(
        docs, 'significant_lift', counts)
    self.assertEqual([d.id for d in matched], ['lift'])
    none = survey_service.apply_result_filter(docs, 'no_data', counts)
    self.assertEqual([d.id for d in none], ['empty'])

  def test_is_brand_lift_requires_explicit_type(self):
    self.assertFalse(survey_service.is_brand_lift({}))
    self.assertFalse(survey_service.is_brand_lift({'surveytype': 'brand_track'}))
    self.assertTrue(survey_service.is_brand_lift({'surveytype': 'brand_lift'}))

  def test_survey_label_prefers_display_name(self):
    self.assertEqual(
        survey_service.survey_label({'surveyname': 'id-name'}), 'id-name')
    self.assertEqual(
        survey_service.survey_label({
            'surveyname': 'id-name',
            'displayname': 'Friendly',
        }), 'Friendly')

  def test_is_archived_missing_field_is_active(self):
    self.assertFalse(survey_service.is_archived({}))
    self.assertFalse(survey_service.is_archived({'archived': False}))
    self.assertTrue(survey_service.is_archived({'archived': True}))

  def _survey_doc(self, doc_id, data):
    doc = mock.Mock()
    doc.id = doc_id
    doc.to_dict.return_value = data
    doc.exists = True
    return doc

  def test_list_surveys_requests_list_fields_without_css(self):
    with mock.patch.object(
        survey_collection, 'get_all', return_value=[]) as get_all:
      survey_service.list_surveys()
      get_all.assert_called_once_with(survey_collection.LIST_FIELDS)
      fields = get_all.call_args[0][0]
      self.assertNotIn('custom_css', fields)
      for name in (
          'surveyname', 'displayname', 'archived', 'surveytype', 'question1',
          'client', 'agency', 'created_at', 'created_by', 'creativesize',
          'creativesizes', 'sample_plan'):
        self.assertIn(name, fields)
      self.assertNotIn('campaign_id', fields)
      self.assertNotIn('placement_id', fields)

  def test_list_surveys_hides_archived_and_treats_missing_as_active(self):
    docs = [
        self._survey_doc('a', {'surveyname': 'A'}),
        self._survey_doc('b', {'surveyname': 'B', 'archived': False}),
        self._survey_doc('c', {'surveyname': 'C', 'archived': True}),
    ]
    with mock.patch.object(survey_collection, 'get_all', return_value=docs):
      active = survey_service.list_surveys(include_archived=False)
      self.assertEqual([d.id for d in active], ['a', 'b'])
      archived = survey_service.list_surveys(include_archived=True)
      self.assertEqual([d.id for d in archived], ['c'])

  def test_copy_clones_questions_settings_and_css(self):
    with mock.patch.object(
        survey_collection, '_collection', return_value=self.collection):
      original = self.collection.document()
      original.set({
          'surveyname': 'Summer',
          'displayname': 'Summer display',
          'question1': 'Q1',
          'custom_css': 'body { color: red; }',
          'surveytype': 'brand_track',
          'language': 'de',
          'archived': True,
          'client': 'Acme',
          'agency': 'OMD',
          'campaign_id': 'camp-1',
          'placement_id': 'plc-9',
          'created_at': '2024-01-02T00:00:00Z',
          'badge_icon': 'Name',
          'badge_name': 'Cedar & Pine Collective',
          'badge_text': 'Survey Type Brandometer2 Ad - powered by Google',
      })
      new_ref = survey_collection.copy(original.id)
      self.assertIsNotNone(new_ref)
      self.assertNotEqual(new_ref.id, original.id)
      data = new_ref.get().to_dict()
      self.assertEqual(data['surveyname'], 'Copy of Summer')
      self.assertEqual(data['displayname'], 'Copy of Summer display')
      self.assertEqual(data['question1'], 'Q1')
      self.assertEqual(data['custom_css'], 'body { color: red; }')
      self.assertEqual(data['surveytype'], 'brand_track')
      self.assertEqual(data['language'], 'de')
      self.assertIs(data['archived'], False)
      self.assertEqual(data['client'], 'Acme')
      self.assertEqual(data['agency'], 'OMD')
      self.assertEqual(data['campaign_id'], 'camp-1')
      self.assertEqual(data['placement_id'], 'plc-9')
      self.assertTrue(data.get('created_at'))
      self.assertNotEqual(data['created_at'], '2024-01-02T00:00:00Z')
      self.assertEqual(data['created_by'], '')
      self.assertEqual(data['updated_by'], '')
      self.assertEqual(data['badge_icon'], 'Name')
      self.assertEqual(data['badge_name'], 'Cedar & Pine Collective')
      self.assertEqual(
          data['badge_text'], 'Survey Type Brandometer2 Ad - powered by Google')

  def test_update_by_id_raises_conflict_on_failed_precondition(self):
    from google.api_core.exceptions import FailedPrecondition
    from google.cloud import firestore
    ref = mock.Mock()
    ref.update.side_effect = FailedPrecondition('stale')
    col = mock.Mock()
    col.document.return_value = ref
    option = object()
    with mock.patch.object(survey_collection, '_collection', return_value=col):
      with mock.patch.object(
          survey_collection, 'decode_update_time', return_value='ts'):
        with mock.patch.object(
            firestore.Client, 'write_option', return_value=option):
          with self.assertRaises(survey_collection.SurveyConflictError) as raised:
            survey_collection.update_by_id(
                'sid', {'surveyname': 'X', 'last_update_time': 'drop-me'},
                last_update_time='tok')
    self.assertIn('Someone else saved this survey, reload', str(raised.exception))
    ref.update.assert_called_once()
    args, kwargs = ref.update.call_args
    self.assertNotIn('last_update_time', args[0])
    self.assertIs(kwargs.get('option'), option)

  def test_copy_missing_survey_returns_none(self):
    with mock.patch.object(
        survey_collection, '_collection', return_value=self.collection):
      self.assertIsNone(survey_collection.copy('does-not-exist'))

  def test_set_archived_updates_flag(self):
    with mock.patch.object(
        survey_collection, '_collection', return_value=self.collection):
      ref = self.collection.document()
      ref.set({'surveyname': 'Keep', 'archived': False})
      survey_collection.set_archived(ref.id, True)
      self.assertTrue(ref.get().to_dict()['archived'])
      survey_collection.set_archived(ref.id, False)
      self.assertFalse(ref.get().to_dict()['archived'])

  @mock.patch.object(survey_service, 'flash')
  def test_create_writes_archived_false(self, _flash):
    form = mock.Mock()
    form.data = {'surveyname': 'New'}
    form.surveyname.data = 'New'
    with mock.patch.object(survey_collection, 'create') as create_mock:
      create_mock.return_value = mock.Mock(id='newid')
      survey_service.create(form)
      saved = create_mock.call_args[0][0]
      self.assertIs(saved['archived'], False)
      self.assertEqual(saved['surveyname'], 'New')
      self.assertTrue(saved.get('created_at'))
      self.assertRegex(saved['created_at'], r'^\d{4}-\d{2}-\d{2}T')
      self.assertEqual(saved['created_by'], 'local-dev')
      self.assertEqual(saved['updated_by'], 'local-dev')
      self.assertTrue(saved.get('updated_at'))

  def test_paginate_surveys(self):
    docs = [self._survey_doc(str(i), {'surveyname': 'S%s' % i}) for i in range(5)]
    page1, meta = survey_service.paginate_surveys(docs, page=1, page_size=2)
    self.assertEqual([d.id for d in page1], ['0', '1'])
    self.assertTrue(meta['has_next'])
    self.assertFalse(meta['has_prev'])
    self.assertEqual(meta['total'], 5)
    self.assertEqual(meta['total_pages'], 3)

    page3, meta = survey_service.paginate_surveys(docs, page=3, page_size=2)
    self.assertEqual([d.id for d in page3], ['4'])
    self.assertFalse(meta['has_next'])
    self.assertTrue(meta['has_prev'])

    empty, meta = survey_service.paginate_surveys([], page=1, page_size=50)
    self.assertEqual(empty, [])
    self.assertEqual(meta['total'], 0)
    self.assertFalse(meta['has_next'])
    self.assertFalse(meta['has_prev'])

    clamped, meta = survey_service.paginate_surveys(docs, page=99, page_size=2)
    self.assertEqual([d.id for d in clamped], ['4'])
    self.assertEqual(meta['page'], 3)

  def test_paginate_archived_list_is_independent(self):
    docs = [
        self._survey_doc('a', {'surveyname': 'A', 'archived': True}),
        self._survey_doc('b', {'surveyname': 'B', 'archived': True}),
        self._survey_doc('c', {'surveyname': 'C', 'archived': True}),
    ]
    with mock.patch.object(survey_collection, 'get_all', return_value=docs):
      archived = survey_service.list_surveys(include_archived=True)
    page1, meta = survey_service.paginate_surveys(archived, page=1, page_size=2)
    self.assertEqual([d.id for d in page1], ['a', 'b'])
    self.assertTrue(meta['has_next'])
    page2, meta = survey_service.paginate_surveys(archived, page=2, page_size=2)
    self.assertEqual([d.id for d in page2], ['c'])
    self.assertFalse(meta['has_next'])

  def test_response_counts_cached_within_ttl(self):
    frame = pandas.DataFrame({
        'ID': ['s1'],
        'Segmentation': ['seg'],
        'max_date': ['2026-11-18'],
        'days_since_response': [1],
        'response_count': [3],
    })
    with mock.patch.dict(os.environ, {'STATS_CACHE_SECONDS': '90'}):
      with mock.patch.object(
          survey_service, '_fetch_all_response_counts',
          return_value=frame) as fetch:
        first = survey_service.get_response_counts(['s1'])
        second = survey_service.get_response_counts(['s1'])
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(list(first['ID']), list(second['ID']))
        survey_service._stats_cache['expires_at'] = 0
        survey_service.get_response_counts(['s1'])
        self.assertEqual(fetch.call_count, 2)

  def test_response_counts_cache_disabled_when_ttl_zero(self):
    frame = pandas.DataFrame(columns=[
        'ID', 'Segmentation', 'max_date', 'days_since_response',
        'response_count'
    ])
    with mock.patch.dict(os.environ, {'STATS_CACHE_SECONDS': '0'}):
      with mock.patch.object(
          survey_service, '_fetch_all_response_counts',
          return_value=frame) as fetch:
        survey_service.get_response_counts(['s1'])
        survey_service.get_response_counts(['s1'])
        self.assertEqual(fetch.call_count, 2)

  def test_response_counts_cache_isolates_include_test(self):
    live = pandas.DataFrame({
        'ID': ['s1'],
        'Segmentation': ['seg'],
        'max_date': ['2026-11-18'],
        'days_since_response': [1],
        'response_count': [2],
    })
    with_test = pandas.DataFrame({
        'ID': ['s1'],
        'Segmentation': ['seg'],
        'max_date': ['2026-11-18'],
        'days_since_response': [0],
        'response_count': [9],
    })

    def fake_fetch(ids, include_test=False):
      del ids
      return with_test if include_test else live

    with mock.patch.dict(os.environ, {'STATS_CACHE_SECONDS': '90'}):
      with mock.patch.object(
          survey_service, '_fetch_all_response_counts',
          side_effect=fake_fetch) as fetch:
        excluded = survey_service.get_response_counts(['s1'])
        included = survey_service.get_response_counts(
            ['s1'], include_test=True)
        excluded_again = survey_service.get_response_counts(['s1'])
        included_again = survey_service.get_response_counts(
            ['s1'], include_test=True)
    self.assertEqual(fetch.call_count, 3)
    self.assertEqual(int(excluded['response_count'].iloc[0]), 2)
    self.assertEqual(int(included['response_count'].iloc[0]), 9)
    self.assertEqual(int(excluded_again['response_count'].iloc[0]), 2)
    self.assertEqual(int(included_again['response_count'].iloc[0]), 9)
    self.assertEqual(
        survey_service.stats_cache_key('s1', False), 's1')
    self.assertEqual(
        survey_service.stats_cache_key('s1', True), 's1|t')
    self.assertEqual(
        survey_service.stats_l2_doc_id('s1', False), 's1')
    self.assertEqual(
        survey_service.stats_l2_doc_id('s1', True), 's1__incltest')

  def test_response_counts_fetches_only_missing_ids(self):
    def fake_fetch(ids, include_test=False):
      del include_test
      return pandas.DataFrame({
          'ID': list(ids),
          'Segmentation': ['seg'] * len(ids),
          'max_date': ['2026-11-18'] * len(ids),
          'days_since_response': [1] * len(ids),
          'response_count': [2] * len(ids),
      })

    with mock.patch.dict(os.environ, {'STATS_CACHE_SECONDS': '90'}):
      with mock.patch.object(
          survey_service, '_fetch_all_response_counts',
          side_effect=fake_fetch) as fetch:
        survey_service.get_response_counts(['s1', 's2'])
        survey_service.get_response_counts(['s2', 's3'])
    self.assertEqual(fetch.call_count, 2)
    self.assertEqual(fetch.call_args_list[0].args[0], ['s1', 's2'])
    self.assertEqual(fetch.call_args_list[1].args[0], ['s3'])

  def test_concat_frames_skips_empty_and_returns_empty_template(self):
    empty = pandas.DataFrame(columns=['ID', 'response_count'])
    filled = pandas.DataFrame({'ID': ['s1'], 'response_count': [3]})
    combined = survey_service._concat_frames(
        [empty, filled, empty], ignore_index=True)
    self.assertEqual(list(combined['ID']), ['s1'])
    only_empty = survey_service._concat_frames(
        [empty, empty.copy()], ignore_index=True)
    self.assertTrue(only_empty.empty)

  def test_get_response_counts_concat_skips_empty_frames(self):
    empty = pandas.DataFrame(columns=[
        'ID', 'Segmentation', 'max_date', 'days_since_response',
        'response_count'
    ])
    with mock.patch.dict(os.environ, {'STATS_CACHE_SECONDS': '0'}):
      with mock.patch.object(
          survey_service, '_fetch_all_response_counts',
          return_value=empty):
        with warnings.catch_warnings(record=True) as caught:
          warnings.simplefilter('always')
          df = survey_service.get_response_counts(['s1', 's2', 's3'])
    futures = [
        w for w in caught if issubclass(w.category, FutureWarning)
        and 'concat' in str(w.message).lower()
    ]
    self.assertFalse(futures)
    self.assertTrue(df.empty)
    self.assertEqual(
        list(df.columns),
        ['ID', 'Segmentation', 'max_date', 'days_since_response',
         'response_count'])

  def test_created_year_unknown_when_missing(self):
    self.assertIsNone(survey_service.created_year({}))
    self.assertIsNone(survey_service.created_year({'created_at': ''}))
    self.assertEqual(
        survey_service.created_year({'created_at': '2026-11-19T02:00:00Z'}),
        '2026')
    self.assertEqual(
        survey_service.created_year({
            'created_at': datetime.datetime(2025, 3, 1, tzinfo=datetime.timezone.utc)
        }),
        '2025')

  def test_apply_homepage_filters_client_agency_year_and_search(self):
    docs = [
        self._survey_doc('a', {
            'surveyname': 'Alpha study',
            'displayname': 'Friendly A',
            'client': 'Acme',
            'agency': 'OMD',
            'created_at': '2026-01-01T00:00:00Z',
        }),
        self._survey_doc('b', {
            'surveyname': 'Beta',
            'client': 'Other',
            'agency': 'WPP',
            'created_at': '2025-06-01T00:00:00Z',
        }),
        self._survey_doc('c', {
            'surveyname': 'Gamma',
            'client': 'Acme',
            'agency': 'OMD',
        }),
    ]
    self.assertEqual(
        [d.id for d in survey_service.apply_homepage_filters(docs, client='Acme')],
        ['a', 'c'])
    self.assertEqual(
        [d.id for d in survey_service.apply_homepage_filters(docs, agency='WPP')],
        ['b'])
    self.assertEqual(
        [d.id for d in survey_service.apply_homepage_filters(docs, year='2026')],
        ['a'])
    self.assertEqual(
        [d.id for d in survey_service.apply_homepage_filters(
            docs, year=survey_service.UNKNOWN_YEAR)],
        ['c'])
    self.assertEqual(
        [d.id for d in survey_service.apply_homepage_filters(docs, q='friendly')],
        ['a'])
    self.assertEqual(
        [d.id for d in survey_service.apply_homepage_filters(
            docs, client='Acme', q='gamma')],
        ['c'])
    sized = [
        self._survey_doc('wide', {
            'surveyname': 'Wide',
            'creativesizes': ['300x250', '970x250'],
        }),
        self._survey_doc('legacy', {
            'surveyname': 'Legacy',
            'creativesize': '160x600',
        }),
        self._survey_doc('plain', {'surveyname': 'Plain'}),
    ]
    self.assertEqual(
        [d.id for d in survey_service.apply_homepage_filters(
            sized, size='970x250')],
        ['wide'])
    self.assertEqual(
        [d.id for d in survey_service.apply_homepage_filters(
            sized, size='160x600')],
        ['legacy'])
    self.assertEqual(
        [d.id for d in survey_service.apply_homepage_filters(
            sized, size='300x250')],
        ['wide', 'plain'])
    self.assertEqual(survey_service.survey_size_keys(sized[2]), ['300x250'])
    self.assertEqual(
        survey_service.survey_identity_line(docs[0]), 'Acme · OMD')
    options = survey_service.homepage_filter_options(docs)
    self.assertEqual(options['clients'], ['Acme', 'Other'])
    self.assertEqual(options['agencies'], ['OMD', 'WPP'])
    self.assertEqual(options['years'], ['2026', '2025'])
    self.assertTrue(options['has_unknown_year'])
    self.assertTrue(options['has_unknown_creator'])
    docs[0].to_dict.return_value['created_by'] = 'mark@agency.example'
    docs[1].to_dict.return_value['created_by'] = 'sam@agency.example'
    self.assertEqual(
        [d.id for d in survey_service.apply_homepage_filters(
            docs, created_by='mark@agency.example')],
        ['a'])
    self.assertEqual(
        [d.id for d in survey_service.apply_homepage_filters(
            docs, created_by=survey_service.UNKNOWN_CREATOR)],
        ['c'])

  def test_sort_surveys_newest_created_at_first_missing_last(self):
    docs = [
        self._survey_doc('old', {'created_at': '2025-01-01T00:00:00Z',
                                 'displayname': 'Zulu'}),
        self._survey_doc('new', {'created_at': '2026-11-19T00:00:00Z',
                                 'displayname': 'Alpha'}),
        self._survey_doc('none', {'displayname': 'Mid'}),
    ]
    newest = survey_service.sort_surveys(docs, 'created_at', 'desc')
    self.assertEqual([d.id for d in newest], ['new', 'old', 'none'])
    oldest = survey_service.sort_surveys(docs, 'created_at', 'asc')
    self.assertEqual([d.id for d in oldest], ['old', 'new', 'none'])
    by_name = survey_service.sort_surveys(docs, 'name', 'asc')
    self.assertEqual([d.id for d in by_name], ['new', 'none', 'old'])
    self.assertEqual(
        survey_service.parse_sort('nope', 'sideways'),
        ('created_at', 'desc'))

  def test_homepage_page_size_is_named_constant_not_env(self):
    self.assertEqual(survey_service.HOMEPAGE_PAGE_SIZE, 50)
    self.assertFalse(hasattr(survey_service, 'homepage_page_size'))

  def test_compact_count_lift_and_generic_single_segment(self):
    lift = survey_service.compact_count({
        'stats': [
            {'Segmentation': 'default_control', 'response_count': 40},
            {'Segmentation': 'default_expose', 'response_count': 42},
        ],
    })
    self.assertEqual(lift['text'], 'C 40 · E 42')
    self.assertEqual(
        lift['title'], 'default_control: 40 · default_expose: 42')
    survey = survey_service.compact_count({
        'stats': [{'Segmentation': 'survey', 'response_count': 24}],
    })
    self.assertEqual(survey['text'], '24')
    self.assertEqual(survey['title'], 'survey: 24')
    unnamed = survey_service.compact_count({
        'stats': [{'Segmentation': '', 'response_count': 3}],
    })
    self.assertEqual(unnamed['text'], '3')
    self.assertEqual(unnamed['title'], 'Unnamed: 3')
    custom = survey_service.compact_count({
        'stats': [
            {'Segmentation': 'north', 'response_count': 10},
            {'Segmentation': 'south', 'response_count': 11},
        ],
    })
    self.assertEqual(custom['text'], 'N 10 · S 11')
    self.assertEqual(custom['title'], 'north: 10 · south: 11')
    self.assertEqual(survey_service.compact_count(None)['text'], '')
    self.assertEqual(survey_service.compact_count({})['text'], '')
    live_test = survey_service.compact_count({
        'stats': [{'Segmentation': 'default_control', 'response_count': 2}],
    })
    self.assertEqual(live_test['text'], 'C 2')
    split_lift = survey_service.compact_count({
        'stats': [
            {'Segmentation': 'default_control', 'response_count': 136},
            {'Segmentation': 'default_expose', 'response_count': 140},
        ],
        'test_stats': [
            {'Segmentation': 'default_control', 'response_count': 3},
            {'Segmentation': 'default_expose', 'response_count': 5},
        ],
    })
    self.assertEqual(split_lift['text'], 'C 136 · E 140 · CT 3 · ET 5')
    self.assertEqual(split_lift['title'].count('CT: control test'), 1)
    self.assertEqual(split_lift['title'].count('ET: expose test'), 1)
    self.assertIn('CT: control test', split_lift['title'])
    self.assertIn('ET: expose test', split_lift['title'])
    omit_zero = survey_service.compact_count({
        'stats': [
            {'Segmentation': 'default_control', 'response_count': 136},
            {'Segmentation': 'default_expose', 'response_count': 140},
        ],
        'test_stats': [
            {'Segmentation': 'default_control', 'response_count': 3},
        ],
    })
    self.assertEqual(omit_zero['text'], 'C 136 · E 140 · CT 3')
    self.assertNotIn('ET', omit_zero['text'])
    track_split = survey_service.compact_count({
        'stats': [{'Segmentation': 'survey', 'response_count': 180}],
        'test_stats': [{'Segmentation': 'survey', 'response_count': 5}],
    })
    self.assertEqual(track_split['text'], '180 · T 5')
    self.assertIn('T: test responses', track_split['title'])
    only_test = survey_service.compact_count({
        'stats': [],
        'test_stats': [
            {'Segmentation': 'default_control', 'response_count': 3},
            {'Segmentation': 'default_expose', 'response_count': 5},
        ],
    })
    self.assertEqual(only_test['text'], 'CT 3 · ET 5')

  def test_build_stat_array_keeps_test_counts_separate(self):
    sid = 'lift-1'
    df = pandas.DataFrame({
        'ID': [sid, sid, sid, sid],
        'Segmentation': [
            'default_control', 'default_expose',
            'default_control', 'default_expose',
        ],
        'Type': ['survey', 'survey', 'test', 'test'],
        'max_date': ['2026-11-22'] * 4,
        'days_since_response': [1, 1, 0, 0],
        'response_count': [136, 140, 3, 5],
        'n_q1': [136, 140, 3, 5],
        'k_q1_a': [40, 50, 1, 2],
    })
    surveys = [mock.Mock()]
    surveys[0].id = sid
    surveys[0].to_dict.return_value = {
        'surveytype': 'brand_lift',
        'cells': [
            {'id': 'default_control', 'label': 'Control', 'role': 'control'},
            {'id': 'default_expose', 'label': 'Exposed', 'role': 'expose'},
        ],
        'sample_plan': {'n_control': 200, 'n_expose': 200},
    }
    rows = survey_service.build_stat_array(
        [sid], counts_df=df, surveys=surveys)
    item = rows[0]
    self.assertEqual(survey_service.compact_count(item)['text'],
                     'C 136 · E 140 · CT 3 · ET 5')
    self.assertEqual(item['result_source'], 'live')
    self.assertNotIn('(test)', item['result_text'])
    self.assertEqual(item['status'], 'Active')
    self.assertEqual(item['last_change'], 1)

  def test_build_stat_array_only_test_rows_labelled_test(self):
    sid = 'lift-test-only'
    df = pandas.DataFrame({
        'ID': [sid, sid],
        'Segmentation': ['default_control', 'default_expose'],
        'Type': ['test', 'test'],
        'max_date': ['2026-11-22', '2026-11-22'],
        'days_since_response': [0, 0],
        'response_count': [40, 40],
        'n_q1': [40, 40],
        'k_q1_a': [10, 20],
    })
    surveys = [mock.Mock()]
    surveys[0].id = sid
    surveys[0].to_dict.return_value = {
        'surveytype': 'brand_lift',
        'cells': [
            {'id': 'default_control', 'label': 'Control', 'role': 'control'},
            {'id': 'default_expose', 'label': 'Exposed', 'role': 'expose'},
        ],
    }
    rows = survey_service.build_stat_array(
        [sid], counts_df=df, surveys=surveys)
    item = rows[0]
    self.assertEqual(survey_service.compact_count(item)['text'], 'CT 40 · ET 40')
    self.assertEqual(item['result_source'], 'test')
    self.assertIn('(test)', item['result_text'])
    self.assertIn('Type=test', item['result_title'])

  def test_counts_for_survey_coerces_id_and_keeps_blank_keys(self):
    sid = 'L0hng8nGp4Bl6JjRMTrO'
    df = pandas.DataFrame({
        'ID': ['  %s  ' % sid],
        'Segmentation': ['default_control'],
        'max_date': ['2026-11-22'],
        'days_since_response': [0],
        'response_count': [2],
        'n_q1': [2],
        'k_q1_a': [1],
    })
    sliced = survey_service._counts_for_survey(df, sid)
    self.assertEqual(len(sliced), 1)
    rows = survey_service.build_stat_array([sid], counts_df=df)
    self.assertEqual(survey_service.compact_count(rows[0])['text'], 'C 2')
    self.assertEqual(rows[0]['status'], 'Active')
    self.assertFalse(survey_service._l2_rows_current([]))

  @mock.patch.object(survey_service, 'get_doc_by_id')
  @mock.patch.object(survey_service, 'get_survey_responses')
  def test_get_report_include_test_live_shaped_rows(
      self, responses_mock, doc_mock):
    sid = 'L0hng8nGp4Bl6JjRMTrO'
    now = datetime.datetime(2026, 11, 22, 23, 43, 8)
    doc = mock.Mock()
    doc.exists = True
    doc.to_dict.return_value = {
        'surveyname': 'Live test',
        'surveytype': 'brand_lift',
        'question1': 'Q1?',
        'answer1a': 'Yes',
        'answer1b': 'No',
        'cells': [
            {'id': 'default_control', 'label': 'Control', 'role': 'control'},
            {'id': 'default_expose', 'label': 'Exposed', 'role': 'expose'},
        ],
    }
    doc_mock.return_value = doc
    blank = pandas.DataFrame({
        'CreatedAt': [now, now],
        'Segmentation': ['default_control', 'default_control'],
        'Response': ['1:A', '1:A'],
        'BomID': ['', None],
        'RespondentID': [None, ''],
        'Type': ['test', 'test'],
        'CampaignID': ['', ''],
        'PlacementID': ['', ''],
        'SiteID': ['', ''],
        'AdCreativeID': ['', ''],
        'CreativeSize': ['300x250', '300x250'],
        'CreativeVersion': [None, None],
        'RespondentIDSource': ['', ''],
    })
    prefixed = blank.copy()
    prefixed['BomID'] = ['test_aaa', 'test_aaa']
    prefixed['RespondentID'] = ['test_aaa', 'test_aaa']
    responses_mock.return_value = pandas.concat([blank, prefixed], ignore_index=True)
    report = survey_service.get_report(sid, include_test=True)
    self.assertEqual(report['n_raw'], 4)
    self.assertEqual(report['n_total'], 3)
    self.assertTrue(report['has_control'])
    self.assertFalse(report['has_expose'])
    self.assertEqual(report['empty_reason'], 'no_expose')
    self.assertNotEqual(report['empty_reason'], 'no_data')
    self.assertEqual(report['lift_source'], 'test')
    self.assertEqual(report['n_test'], 3)
    self.assertEqual(report['count_summary']['source'], 'test')
    self.assertIn('CT 3', report['count_summary']['text'])

  @mock.patch.object(survey_service, 'get_doc_by_id')
  @mock.patch.object(survey_service, 'get_survey_responses')
  def test_get_report_mixed_live_and_test_keeps_lift_on_live(
      self, responses_mock, doc_mock):
    now = datetime.datetime(2026, 11, 22, 12, 0, 0)
    doc = mock.Mock()
    doc.exists = True
    doc.to_dict.return_value = {
        'surveyname': 'Mixed',
        'surveytype': 'brand_lift',
        'question1': 'Q1?',
        'answer1a': 'Yes',
        'answer1b': 'No',
        'cells': [
            {'id': 'default_control', 'label': 'Control', 'role': 'control'},
            {'id': 'default_expose', 'label': 'Exposed', 'role': 'expose'},
        ],
    }
    doc_mock.return_value = doc
    responses_mock.return_value = pandas.DataFrame({
        'CreatedAt': [now] * 6,
        'Segmentation': [
            'default_control', 'default_control',
            'default_expose', 'default_expose',
            'default_control', 'default_expose',
        ],
        'Response': ['1:A'] * 6,
        'BomID': ['live_c1', 'live_c2', 'live_e1', 'live_e2', 'test_c', 'test_e'],
        'RespondentID': [
            'live_c1', 'live_c2', 'live_e1', 'live_e2', 'test_c', 'test_e'],
        'Type': ['survey', 'survey', 'survey', 'survey', 'test', 'test'],
        'CampaignID': [''] * 6,
        'PlacementID': [''] * 6,
        'SiteID': [''] * 6,
        'AdCreativeID': [''] * 6,
        'CreativeSize': ['300x250'] * 6,
        'CreativeVersion': [None] * 6,
        'RespondentIDSource': [''] * 6,
    })
    report = survey_service.get_report('sid', include_test=True)
    self.assertEqual(report['lift_source'], 'live')
    self.assertEqual(report['n_total'], 4)
    self.assertEqual(report['control_n'], 2)
    self.assertEqual(report['expose_n'], 2)
    self.assertEqual(report['n_test'], 2)
    self.assertEqual(report['n_control_test'], 1)
    self.assertEqual(report['n_expose_test'], 1)
    self.assertEqual(report['count_summary']['text'], 'C 2 · E 2 · CT 1 · ET 1')
    self.assertNotEqual(report['empty_reason'], 'no_data')

  def test_build_stat_array_zero_days_is_active_with_date_title(self):
    df = pandas.DataFrame({
        'ID': ['s1'],
        'Segmentation': ['survey'],
        'max_date': ['2026-11-21'],
        'days_since_response': [0],
        'response_count': [3],
    })
    rows = survey_service.build_stat_array(['s1'], counts_df=df)
    self.assertEqual(rows[0]['last_change'], 0)
    self.assertEqual(rows[0]['status'], 'Active')
    self.assertIn('2026-11-21', rows[0]['last_title'])
    self.assertIn('0 days ago', rows[0]['last_title'])

  def test_last_received_title_includes_date_and_days(self):
    self.assertEqual(
        survey_service.last_received_title(1, '2026-11-18'),
        'Last received data 2026-11-18 (1 day ago)')
    self.assertEqual(
        survey_service.last_received_title(4, '2026-11-15T12:00:00Z'),
        'Last received data 2026-11-15 (4 days ago)')
    self.assertEqual(survey_service.last_received_title(None, None), '')

  def test_unavailable_stat_array_marks_each_id(self):
    rows = survey_service.unavailable_stat_array(['a', 'b'])
    self.assertEqual([row['id'] for row in rows], ['a', 'b'])
    self.assertTrue(all(row['unavailable'] for row in rows))

  def test_query_to_dataframe_uses_jobs_rest_not_storage_api(self):
    result = mock.Mock()

    def to_dataframe(**kwargs):
      if kwargs.get('bqstorage_client') is not None:
        raise Forbidden(
            "the user does not have 'bigquery.readsessions.create' "
            "permission for 'projects/brandometer2'")
      if kwargs.get('create_bqstorage_client', True):
        raise Forbidden(
            "the user does not have 'bigquery.readsessions.create' "
            "permission for 'projects/brandometer2'")
      return pandas.DataFrame({
          'ID': ['demo_1_0003'],
          'Segmentation': ['default_control'],
          'max_date': ['2026-11-22'],
          'days_since_response': [1],
          'response_count': [30],
      })

    result.to_dataframe.side_effect = to_dataframe
    client = mock.Mock()
    client.query.return_value.result.return_value = result
    df = survey_service._query_to_dataframe('SELECT 1', client=client)
    self.assertEqual(list(df['ID']), ['demo_1_0003'])
    result.to_dataframe.assert_called_once_with(create_bqstorage_client=False)
    self.assertFalse(hasattr(survey_service, 'bigquery_storage'))
    self.assertFalse(hasattr(survey_service, '_get_bqstorage_client'))

  @mock.patch.object(survey_service, '_get_bq_client')
  def test_storage_api_403_still_fills_homepage_counts(self, bq_client_mock):
    result = mock.Mock()

    def to_dataframe(**kwargs):
      if kwargs.get('create_bqstorage_client', True) or kwargs.get(
          'bqstorage_client') is not None:
        raise Forbidden(
            "the user does not have 'bigquery.readsessions.create' "
            "permission for 'projects/brandometer2'")
      return pandas.DataFrame({
          'ID': ['demo_1_0003', 'demo_1_0003'],
          'Segmentation': ['default_control', 'default_expose'],
          'max_date': ['2026-11-22', '2026-11-22'],
          'days_since_response': [1, 1],
          'response_count': [30, 28],
      })

    result.to_dataframe.side_effect = to_dataframe
    client = mock.Mock()
    client.query.return_value.result.return_value = result
    bq_client_mock.return_value = client
    survey_service.clear_stats_cache()
    with mock.patch.dict(os.environ, {
        'TABLE_ID': 'brandometer2.responses.responses',
        'STATS_CACHE_SECONDS': '0',
        'STATS_SHARED_CACHE': '0',
    }):
      rows = survey_service.build_stat_array(['demo_1_0003'])
    compact = survey_service.compact_count(rows[0])
    self.assertEqual(compact['text'], 'C 30 · E 28')
    self.assertEqual(rows[0]['status'], 'Active')
    self.assertFalse(rows[0]['unavailable'])
    result.to_dataframe.assert_called_once_with(create_bqstorage_client=False)

  def test_sizes_compact_first_plus_n(self):
    one = survey_service.sizes_compact(['300x250'])
    self.assertEqual(one['text'], '300×250')
    self.assertEqual(one['title'], '300×250')
    two = survey_service.sizes_compact(['300x250', '336x280'])
    self.assertEqual(two['text'], '300×250 +1')
    self.assertEqual(two['title'], '300×250, 336×280')
    self.assertEqual(survey_service.sizes_compact([])['text'], '')

  def test_identity_suggestions_from_existing_values(self):
    docs = [
        self._survey_doc('a', {'client': 'Acme', 'agency': 'OMD'}),
        self._survey_doc('b', {'client': 'acme', 'agency': ''}),
        self._survey_doc('c', {'client': '  ', 'agency': 'WPP'}),
    ]
    with mock.patch.object(survey_collection, 'get_all', return_value=docs):
      suggestions = survey_service.identity_suggestions()
    self.assertEqual(suggestions['clients'], ['Acme', 'acme'])
    self.assertEqual(suggestions['agencies'], ['OMD', 'WPP'])


class SharedStatsCacheTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self.fs = MockFirestore()
    self._prev_db = survey_collection._db
    self._prev_col = survey_collection._survey_collection
    survey_collection._db = self.fs
    survey_collection._survey_collection = self.fs.collection('Surveys')
    survey_service.clear_stats_cache()

  def tearDown(self):
    survey_collection._db = self._prev_db
    survey_collection._survey_collection = self._prev_col
    survey_service.clear_stats_cache()
    self.fs.reset()
    super().tearDown()

  def _frame(self, survey_id='s1', count=3):
    return pandas.DataFrame({
        'ID': [survey_id],
        'Segmentation': ['seg'],
        'max_date': ['2026-11-18'],
        'days_since_response': [1],
        'response_count': [count],
    })

  def test_l2_serves_second_instance_after_l1_cleared(self):
    frame = self._frame()
    with mock.patch.dict(os.environ, {
        'STATS_CACHE_SECONDS': '90',
        'STATS_SHARED_CACHE': '1',
    }):
      with mock.patch.object(
          survey_service, '_fetch_all_response_counts',
          return_value=frame) as fetch:
        first = survey_service.get_response_counts(['s1'])
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(int(first['response_count'].iloc[0]), 3)
        survey_service.clear_stats_cache()
        second = survey_service.get_response_counts(['s1'])
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(int(second['response_count'].iloc[0]), 3)

  def test_expired_l2_refetches_bigquery(self):
    frame = self._frame(count=4)
    with mock.patch.dict(os.environ, {
        'STATS_CACHE_SECONDS': '90',
        'STATS_SHARED_CACHE': '1',
    }):
      with mock.patch.object(
          survey_service, '_fetch_all_response_counts',
          return_value=frame) as fetch:
        survey_service.get_response_counts(['s1'])
        self.assertEqual(fetch.call_count, 1)
        past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            seconds=10)
        survey_collection.write_stats_cache(
            {'s1': survey_service._counts_rows_from_frame(frame, 's1')},
            past)
        survey_service.clear_stats_cache()
        survey_service.get_response_counts(['s1'])
        self.assertEqual(fetch.call_count, 2)

  def test_shared_cache_env_off_skips_firestore(self):
    frame = self._frame()
    with mock.patch.dict(os.environ, {
        'STATS_CACHE_SECONDS': '90',
        'STATS_SHARED_CACHE': '0',
    }):
      with mock.patch.object(
          survey_service, '_fetch_all_response_counts',
          return_value=frame) as fetch:
        survey_service.get_response_counts(['s1'])
        survey_service.clear_stats_cache()
        survey_service.get_response_counts(['s1'])
        self.assertEqual(fetch.call_count, 2)
    self.assertFalse(
        self.fs.collection('StatsCache').document('s1').get().exists)

  def test_l2_read_failure_falls_back_to_bigquery(self):
    frame = self._frame()
    with mock.patch.dict(os.environ, {
        'STATS_CACHE_SECONDS': '90',
        'STATS_SHARED_CACHE': '1',
    }):
      with mock.patch.object(
          survey_collection, 'read_stats_cache',
          side_effect=RuntimeError('unavailable')):
        with mock.patch.object(
            survey_service, '_fetch_all_response_counts',
            return_value=frame) as fetch:
          out = survey_service.get_response_counts(['s1'])
          self.assertEqual(fetch.call_count, 1)
          self.assertEqual(int(out['response_count'].iloc[0]), 3)

  def test_l2_keys_include_test_separately(self):
    live = self._frame(count=2)
    with_test = self._frame(count=9)
    with mock.patch.dict(os.environ, {
        'STATS_CACHE_SECONDS': '90',
        'STATS_SHARED_CACHE': '1',
    }):
      with mock.patch.object(
          survey_service, '_fetch_all_response_counts',
          side_effect=lambda ids, include_test=False: (
              with_test if include_test else live)) as fetch:
        survey_service.get_response_counts(['s1'])
        survey_service.get_response_counts(['s1'], include_test=True)
        self.assertEqual(fetch.call_count, 2)
        survey_service.clear_stats_cache()
        excluded = survey_service.get_response_counts(['s1'])
        included = survey_service.get_response_counts(
            ['s1'], include_test=True)
        self.assertEqual(fetch.call_count, 3)
    self.assertEqual(int(excluded['response_count'].iloc[0]), 2)
    self.assertEqual(int(included['response_count'].iloc[0]), 9)
    self.assertTrue(
        self.fs.collection('StatsCache').document('s1').get().exists)
    self.assertFalse(
        self.fs.collection('StatsCache').document('s1__incltest').get().exists)

  def test_empty_counts_are_not_cached_in_l1_or_l2(self):
    empty = pandas.DataFrame(columns=[
        'ID', 'Segmentation', 'max_date', 'days_since_response',
        'response_count', 'n_q1', 'k_q1_a',
    ])
    with mock.patch.dict(os.environ, {
        'STATS_CACHE_SECONDS': '90',
        'STATS_SHARED_CACHE': '1',
    }):
      with mock.patch.object(
          survey_service, '_fetch_all_response_counts',
          return_value=empty) as fetch:
        first = survey_service.get_response_counts(['s1'])
        self.assertTrue(first.empty)
        self.assertEqual(fetch.call_count, 1)
        survey_service.get_response_counts(['s1'])
        self.assertEqual(fetch.call_count, 2)
    self.assertFalse(
        self.fs.collection('StatsCache').document('s1').get().exists)

  def test_stale_empty_l2_doc_is_not_a_hit(self):
    filled = self._frame(count=2)
    future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        seconds=90)
    survey_collection.write_stats_cache({'s1': []}, future)
    with mock.patch.dict(os.environ, {
        'STATS_CACHE_SECONDS': '90',
        'STATS_SHARED_CACHE': '1',
    }):
      with mock.patch.object(
          survey_service, '_fetch_all_response_counts',
          return_value=filled) as fetch:
        out = survey_service.get_response_counts(['s1'])
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(int(out['response_count'].iloc[0]), 2)
