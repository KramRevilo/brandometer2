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
import hashlib
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

HMAC = 'unit-receiver-hmac'
IPSEC = 'unit-ip-hmac'


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


def _token(survey_id):
  return receiver.survey_token(survey_id, HMAC)


def _args(survey_id='abc', token=None, **extra):
  args = {
      'id': survey_id,
      'response': '1:A',
      'creative_size': '300x250',
      'seg': 'default_expose',
      'bomid': 'b1',
  }
  if token is not None:
    args['token'] = token
  elif token is not False:
    args['token'] = _token(survey_id)
  args.update(extra)
  return args


def _secrets(**extra):
  env = {
      'TABLE_ID': 'p.responses.responses',
      'RECEIVER_HMAC_SECRET': HMAC,
      'IP_HMAC_SECRET': IPSEC,
  }
  env.update(extra)
  return env


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
        'token': _token('survey_1'),
    })
    self.assertIsNone(error)
    self.assertEqual(fields['ID'], 'survey_1')
    self.assertEqual(fields['BomID'], 'a1b2c3d4-e5f6-7890-abcd-ef1234567890')

  def test_missing_response_is_400(self):
    fields, error = receiver.validate_params({'id': 'abc'})
    self.assertEqual(error, 'missing response')

  def test_invalid_token_format_is_400(self):
    fields, error = receiver.validate_params({
        'id': 'abc', 'response': '1:A', 'token': 'not-hex'})
    self.assertEqual(error, 'invalid token')

  def test_missing_hmac_secret_is_500(self):
    request = FakeRequest(_args())
    with mock.patch.dict(os.environ, {'RECEIVER_HMAC_SECRET': ''}, clear=False):
      body, status, _headers = receiver.receiver(request)
    self.assertEqual(status, 500)
    self.assertEqual(body.get('reason'), 'hmac_secret_missing')

  def test_missing_token_is_403(self):
    request = FakeRequest(_args(token=''))
    with mock.patch.dict(os.environ, _secrets()):
      body, status, _headers = receiver.receiver(request)
    self.assertEqual(status, 403)
    self.assertEqual(body.get('reason'), 'invalid_token')

  def test_wrong_token_is_403(self):
    request = FakeRequest(_args(token='a' * 64))
    with mock.patch.dict(os.environ, _secrets()):
      body, status, _headers = receiver.receiver(request)
    self.assertEqual(status, 403)
    self.assertEqual(body.get('reason'), 'invalid_token')

  def test_unknown_survey_is_404(self):
    request = FakeRequest(_args(survey_id='missing'))
    with mock.patch.object(receiver, 'survey_is_active', return_value=False):
      with mock.patch.dict(os.environ, _secrets()):
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
    request = FakeRequest(_args())
    bq = mock.Mock()
    bq.get_table.side_effect = NotFound('missing')
    with mock.patch.object(receiver, 'survey_is_active', return_value=True):
      with mock.patch.object(receiver, '_bq', return_value=bq):
        with mock.patch.dict(os.environ, _secrets()):
          body, status, _headers = receiver.receiver(request)
    self.assertEqual(status, 500)
    self.assertEqual(body.get('reason'), 'table_missing')
    bq.create_table.assert_not_called()
    bq.insert_rows_json.assert_not_called()

  def test_rate_limit_is_429(self):
    request = FakeRequest(_args())
    with mock.patch.object(receiver, 'survey_is_active', return_value=True):
      with mock.patch.object(receiver, 'allow_request', return_value=False):
        with mock.patch.dict(os.environ, _secrets()):
          body, status, _headers = receiver.receiver(request)
    self.assertEqual(status, 429)
    self.assertEqual(body.get('reason'), 'rate_limited')

  def test_allow_request_caps_per_key(self):
    self.assertTrue(receiver.allow_request('k', now=100.0, limit=2))
    self.assertTrue(receiver.allow_request('k', now=100.1, limit=2))
    self.assertFalse(receiver.allow_request('k', now=100.2, limit=2))
    self.assertTrue(receiver.allow_request('other', now=100.2, limit=2))
    self.assertTrue(receiver.allow_request('k', now=161.0, limit=2))

  def test_success_is_204_and_ip_is_daily_hmac(self):
    request = FakeRequest(_args())
    bq = mock.Mock()
    bq.get_table.return_value = mock.Mock()
    bq.insert_rows_json.return_value = []
    day = datetime.datetime(2026, 11, 19, tzinfo=datetime.timezone.utc)
    expected = receiver.hash_ip('127.0.0.1', IPSEC, when=day)
    unsalted = hashlib.sha256(b'127.0.0.1').hexdigest()
    with mock.patch.object(receiver, 'survey_is_active', return_value=True):
      with mock.patch.object(receiver, '_bq', return_value=bq):
        with mock.patch.object(receiver, 'hash_ip', return_value=expected):
          with mock.patch.dict(os.environ, _secrets()):
            body, status, headers = receiver.receiver(request)
    self.assertEqual(status, 204)
    self.assertEqual(body, '')
    bq.insert_rows_json.assert_called_once()
    row = bq.insert_rows_json.call_args[0][1][0]
    self.assertEqual(row['ID'], 'abc')
    self.assertEqual(row['Response'], '1:A')
    self.assertEqual(row['RandomTimeStamp'], expected)
    self.assertNotEqual(row['RandomTimeStamp'], unsalted)
    self.assertEqual(len(row['RandomTimeStamp']), 64)
