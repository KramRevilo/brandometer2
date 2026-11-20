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

from google.api_core.exceptions import NotFound
from google.cloud import bigquery
from mockfirestore import MockFirestore
import pandas
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

  @mock.patch.object(survey_service, '_get_bqstorage_client')
  def test_fetch_survey_response_rows_is_parameterized(self, _storage_mock):
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
    self.assertNotIn('STARTS_WITH', sql)
    self.assertEqual(survey_param.name, 'survey_id')
    self.assertEqual(survey_param.value, 'sid-1')

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
    self.assertIn('CreatedAt >= DATETIME_SUB', sql)
    self.assertIn('survey_ids', names)
    self.assertIn('lookback_days', names)
    survey_ids = [
        p for p in job_config.query_parameters if p.name == 'survey_ids'][0]
    self.assertEqual(survey_ids.values, ['sid-1', 'sid-2'])

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
    self.assertNotIn('DATETIME_SUB', sql)
    self.assertNotIn('lookback_days', names)

  def test_fetch_all_response_counts_skips_bq_when_no_ids(self):
    with mock.patch.object(survey_service, '_get_bq_client') as factory:
      df = survey_service._fetch_all_response_counts([])
    factory.assert_not_called()
    self.assertTrue(df.empty)

  @mock.patch.object(survey_service, '_get_bqstorage_client')
  def test_get_survey_responses_limits_to_given_survey(self, _storage_mock):
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
         'CreativeSize', 'CreativeVersion'])

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
        ['ID', 'Segmentation', 'max_date', 'days_since_response',
         'response_count'])

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
          'client', 'agency', 'created_at', 'creativesize', 'creativesizes'):
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
          'badge_icon': 'Dentsu',
          'badge_text': 'Survey Type Dentsu Ad - powered by Google',
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
      self.assertEqual(data['badge_icon'], 'Dentsu')
      self.assertEqual(
          data['badge_text'], 'Survey Type Dentsu Ad - powered by Google')

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

  def test_response_counts_fetches_only_missing_ids(self):
    def fake_fetch(ids):
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
