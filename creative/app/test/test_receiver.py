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

import importlib.util
import os
import unittest
from unittest import mock

from google.api_core.exceptions import NotFound


def _load_receiver():
  path = os.path.abspath(os.path.join(
      os.path.dirname(__file__), '..', '..', '..', 'receiver', 'main.py'))
  spec = importlib.util.spec_from_file_location('brandometer_receiver', path)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


receiver = _load_receiver()


class FakeRequest(object):

  def __init__(self, args, remote_addr='127.0.0.1'):
    self.args = args
    self.remote_addr = remote_addr


class FakeSnap(object):

  def __init__(self, exists, data=None):
    self.exists = exists
    self._data = data or {}

  def to_dict(self):
    return self._data


class ReceiverTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    receiver._reset_for_tests()

  def test_validate_params_rejects_bad_id_and_javascript_size(self):
    fields, error = receiver.validate_params({'id': 'bad id', 'response': '1:A'})
    self.assertIsNone(fields)
    self.assertEqual(error, 'invalid id')
    fields, error = receiver.validate_params({
        'id': 'abc',
        'response': '1:A',
        'creative_size': 'url(javascript:alert(1))',
    })
    self.assertEqual(error, 'invalid creative_size')

  def test_validate_params_accepts_uuid_bomid(self):
    fields, error = receiver.validate_params({
        'id': 'survey_1',
        'seg': 'default_expose',
        'response': '1:A|2:B',
        'visual': '1:A',
        'creative_size': '300x250',
        'bomid': 'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
    })
    self.assertIsNone(error)
    self.assertEqual(fields['ID'], 'survey_1')
    self.assertEqual(fields['BomID'], 'a1b2c3d4-e5f6-7890-abcd-ef1234567890')

  def test_missing_response_is_400(self):
    fields, error = receiver.validate_params({'id': 'abc'})
    self.assertEqual(error, 'missing response')

  def test_unknown_survey_is_404(self):
    request = FakeRequest({
        'id': 'missing', 'response': '1:A', 'creative_size': '300x250',
        'seg': 'default_expose', 'bomid': 'b1'})
    with mock.patch.object(receiver, 'survey_is_active', return_value=False):
      body, status, _headers = receiver.receiver(request)
    self.assertEqual(status, 404)
    self.assertEqual(body.get('reason'), 'survey_not_found')

  def test_archived_survey_is_404(self):
    fs = mock.Mock()
    fs.collection.return_value.document.return_value.get.return_value = FakeSnap(
        True, {'archived': True})
    self.assertFalse(receiver.survey_is_active('sid', fs_client=fs))

  def test_active_survey_is_cached(self):
    fs = mock.Mock()
    fs.collection.return_value.document.return_value.get.return_value = FakeSnap(
        True, {'archived': False})
    self.assertTrue(receiver.survey_is_active('sid', fs_client=fs))
    self.assertTrue(receiver.survey_is_active('sid', fs_client=fs))
    fs.collection.return_value.document.return_value.get.assert_called_once()

  def test_missing_table_is_500_and_does_not_create(self):
    request = FakeRequest({
        'id': 'abc', 'response': '1:A', 'creative_size': '300x250',
        'seg': 'x', 'bomid': 'b1'})
    bq = mock.Mock()
    bq.get_table.side_effect = NotFound('missing')
    with mock.patch.object(receiver, 'survey_is_active', return_value=True):
      with mock.patch.object(receiver, '_bq', return_value=bq):
        with mock.patch.dict(os.environ, {'TABLE_ID': 'p.responses.responses'}):
          body, status, _headers = receiver.receiver(request)
    self.assertEqual(status, 500)
    self.assertEqual(body.get('reason'), 'table_missing')
    bq.create_table.assert_not_called()
    bq.insert_rows_json.assert_not_called()

  def test_success_is_204(self):
    request = FakeRequest({
        'id': 'abc', 'response': '1:A', 'creative_size': '300x250',
        'seg': 'default_expose', 'bomid': 'b1'})
    bq = mock.Mock()
    bq.get_table.return_value = mock.Mock()
    bq.insert_rows_json.return_value = []
    with mock.patch.object(receiver, 'survey_is_active', return_value=True):
      with mock.patch.object(receiver, '_bq', return_value=bq):
        with mock.patch.dict(os.environ, {'TABLE_ID': 'p.responses.responses'}):
          body, status, headers = receiver.receiver(request)
    self.assertEqual(status, 204)
    self.assertEqual(body, '')
    bq.insert_rows_json.assert_called_once()
    row = bq.insert_rows_json.call_args[0][1][0]
    self.assertEqual(row['ID'], 'abc')
    self.assertEqual(row['Response'], '1:A')
