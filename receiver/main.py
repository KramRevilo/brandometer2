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
"""HTTP receiver: validate survey pixels and stream one BigQuery row."""

import datetime
import hashlib
import logging
import os
import re
import threading
import time

from google.api_core.exceptions import NotFound
from google.cloud import bigquery
from google.cloud import firestore

_log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

_bq_client = None
_fs_client = None
_table = None
_table_checked = False
_table_lock = threading.Lock()
_SURVEY_CACHE_SECONDS = 30
_survey_cache = {}
_survey_lock = threading.Lock()

_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,128}$')
_SEG_RE = re.compile(r'^[A-Za-z0-9_.-]{0,64}$')
_TYPE_RE = re.compile(r'^[A-Za-z0-9_]{1,32}$')
_SIZE_RE = re.compile(r'^[0-9]{2,4}x[0-9]{2,4}$')
_TEXT_RE = re.compile(r'^[0-9A-Za-z:|,._\-]{0,2048}$')
_BOM_RE = re.compile(r'^[A-Za-z0-9._-]{0,128}$')


def _reset_for_tests():
  global _bq_client, _fs_client, _table, _table_checked, _survey_cache
  _bq_client = None
  _fs_client = None
  _table = None
  _table_checked = False
  _survey_cache = {}


def _bq():
  global _bq_client
  if _bq_client is None:
    _bq_client = bigquery.Client()
  return _bq_client


def _firestore():
  global _fs_client
  if _fs_client is None:
    _fs_client = firestore.Client()
  return _fs_client


def _require_table():
  """Cached table lookup. Missing tables fail; this does not create them."""
  global _table, _table_checked
  with _table_lock:
    if _table_checked:
      if _table is None:
        raise NotFound('responses table missing')
      return _table
    table_id = os.environ.get('TABLE_ID')
    if not table_id:
      _table_checked = True
      _table = None
      raise NotFound('TABLE_ID is not set')
    _table = _bq().get_table(table_id)
    _table_checked = True
    return _table


def _cache_get(survey_id):
  now = time.monotonic()
  with _survey_lock:
    hit = _survey_cache.get(survey_id)
    if hit and hit[0] > now:
      return hit[1]
  return None


def _cache_put(survey_id, active):
  with _survey_lock:
    _survey_cache[survey_id] = (
        time.monotonic() + _SURVEY_CACHE_SECONDS, active)


def survey_is_active(survey_id, fs_client=None):
  """True if Surveys/{id} exists and is not archived. Cached briefly."""
  cached = _cache_get(survey_id)
  if cached is not None:
    return cached
  client = fs_client if fs_client is not None else _firestore()
  snap = client.collection('Surveys').document(survey_id).get()
  if not getattr(snap, 'exists', False):
    _cache_put(survey_id, False)
    return False
  data = snap.to_dict() or {}
  active = data.get('archived') is not True
  _cache_put(survey_id, active)
  return active


def _match(pattern, value, default=''):
  text = default if value is None else str(value)
  if pattern.fullmatch(text):
    return text
  return None


def validate_params(params):
  """Return (row_fields, error_message). error_message set on 400."""
  survey_id = _match(_ID_RE, params.get('id'))
  if survey_id is None:
    return None, 'invalid id'
  seg = _match(_SEG_RE, params.get('seg'), '')
  if seg is None:
    return None, 'invalid seg'
  type_value = _match(_TYPE_RE, params.get('type') or 'survey')
  if type_value is None:
    return None, 'invalid type'
  size = _match(_SIZE_RE, params.get('creative_size') or '300x250')
  if size is None:
    return None, 'invalid creative_size'
  response = _match(_TEXT_RE, params.get('response'), '')
  if response is None:
    return None, 'invalid response'
  visual = _match(_TEXT_RE, params.get('visual'), '')
  if visual is None:
    return None, 'invalid visual'
  bomid = _match(_BOM_RE, params.get('bomid'), '')
  if bomid is None:
    return None, 'invalid bomid'
  if not response:
    return None, 'missing response'
  return {
      'Type': type_value,
      'ID': survey_id,
      'Segmentation': seg,
      'Response': response,
      'Visual': visual,
      'CreativeSize': size,
      'BomID': bomid,
  }, None


def _pixel_response(status, errors=None, reason=None):
  """JSON body for operators; empty-enough for iframe pixels."""
  payload = {'errors': errors or [], 'ok': status < 400}
  if reason:
    payload['reason'] = reason
  headers = {'Content-Type': 'application/json'}
  return (payload, status, headers)


def receiver(request):
  params = {}
  params.update(request.args or {})
  fields, error = validate_params(params)
  if error:
    _log.info('event=receiver_reject status=400 reason=%s', error)
    return _pixel_response(400, reason=error)

  survey_id = fields['ID']
  try:
    active = survey_is_active(survey_id)
  except Exception:
    _log.exception('event=receiver_firestore_error survey_id=%s', survey_id)
    return _pixel_response(500, reason='survey_lookup_failed')
  if not active:
    _log.info('event=receiver_reject status=404 survey_id=%s', survey_id)
    return _pixel_response(404, reason='survey_not_found')

  try:
    _require_table()
  except NotFound:
    _log.error('event=receiver_table_missing')
    return _pixel_response(500, reason='table_missing')
  except Exception:
    _log.exception('event=receiver_table_error')
    return _pixel_response(500, reason='table_error')

  row_to_insert = {
      'CreatedAt': datetime.datetime.now().isoformat(),
      'Type': fields['Type'],
      'ID': fields['ID'],
      'Segmentation': fields['Segmentation'],
      'Response': fields['Response'],
      'Visual': fields['Visual'],
      'CreativeSize': fields['CreativeSize'],
      'RandomTimeStamp': hashlib.sha256(
          f'{request.remote_addr}'.encode('utf-8')).hexdigest(),
      'BomID': fields['BomID'],
  }
  try:
    errors = _bq().insert_rows_json(os.environ.get('TABLE_ID'), [row_to_insert])
  except Exception:
    _log.exception('event=receiver_insert_error survey_id=%s', survey_id)
    return _pixel_response(500, reason='insert_failed')
  if errors:
    _log.error('event=receiver_insert_rejected survey_id=%s errors=%s',
               survey_id, errors)
    return _pixel_response(500, errors=errors, reason='insert_rejected')
  _log.info('event=receiver_insert status=204 survey_id=%s', survey_id)
  return ('', 204, {})
