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
"""HTTP receiver: validate signed survey pixels and stream one BigQuery row."""

import datetime
import hashlib
import hmac
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

# Per hashed-IP + survey, per instance. Deploy caps instances at 20.
RATE_LIMIT_PER_MINUTE = 30
RATE_LIMIT_MAX_KEYS = 20000
_rate_hits = {}
_rate_lock = threading.Lock()

_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,128}$')
_SEG_RE = re.compile(r'^[A-Za-z0-9_.-]{0,64}$')
_TYPE_RE = re.compile(r'^[A-Za-z0-9_]{1,32}$')
_SIZE_RE = re.compile(r'^[0-9]{2,4}x[0-9]{2,4}$')
_TEXT_RE = re.compile(r'^[0-9A-Za-z:|,._\-]{0,2048}$')
_BOM_RE = re.compile(r'^[A-Za-z0-9._-]{0,128}$')
_RSRC_RE = re.compile(r'^(macro|storage|impression|bomid)$')
_TRAFFIC_RE = re.compile(r'^[A-Za-z0-9._:-]{0,128}$')
_TOKEN_RE = re.compile(r'^[A-Fa-f0-9]{64}$')
_VER_RE = re.compile(r'^[1-9][0-9]{0,6}$')
MAX_CREATIVE_VERSION = 1000000


def _reset_for_tests():
  global _bq_client, _fs_client, _table, _table_checked, _survey_cache, _rate_hits
  _bq_client = None
  _fs_client = None
  _table = None
  _table_checked = False
  _survey_cache = {}
  _rate_hits = {}


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


def _as_bytes(value):
  if isinstance(value, bytes):
    return value
  return str(value).encode('utf-8')


def parse_creative_version(value):
  if value is None or isinstance(value, bool):
    return None
  if isinstance(value, int):
    n = value
  else:
    text = str(value).strip()
    if not text:
      return None
    if _VER_RE.fullmatch(text) is None:
      return False
    n = int(text)
  if n < 1 or n > MAX_CREATIVE_VERSION:
    return False
  return n


def token_message(survey_id, version=None):
  if not survey_id:
    return b''
  parsed = version if isinstance(version, int) else None
  if parsed is None:
    return _as_bytes(survey_id)
  return _as_bytes('%s\n%s' % (survey_id, parsed))


def survey_token(survey_id, secret, version=None):
  if not secret or not survey_id:
    return ''
  return hmac.new(
      _as_bytes(secret), token_message(survey_id, version),
      hashlib.sha256).hexdigest()


def token_is_valid(survey_id, token, secret, version=None):
  expected = survey_token(survey_id, secret, version=version)
  got = token if isinstance(token, str) else ''
  if not expected or not got:
    return False
  return hmac.compare_digest(got, expected)


def utc_day_key(secret, when=None):
  when = when or datetime.datetime.now(datetime.timezone.utc)
  day = when.astimezone(datetime.timezone.utc).strftime('%Y-%m-%d')
  return hmac.new(_as_bytes(secret), day.encode('utf-8'), hashlib.sha256).digest()


def hash_ip(ip_address, secret, when=None):
  ip = '' if ip_address is None else str(ip_address)
  if not secret:
    return ''
  day_key = utc_day_key(secret, when=when)
  return hmac.new(day_key, ip.encode('utf-8'), hashlib.sha256).hexdigest()


def receiver_hmac_secret():
  return (os.environ.get('RECEIVER_HMAC_SECRET') or '').strip()


def ip_hmac_secret():
  return (os.environ.get('IP_HMAC_SECRET') or '').strip()


def allow_request(rate_key, now=None, limit=None):
  """Sliding 60s window per key, in-memory on this instance."""
  limit = RATE_LIMIT_PER_MINUTE if limit is None else limit
  now = time.monotonic() if now is None else now
  with _rate_lock:
    if len(_rate_hits) > RATE_LIMIT_MAX_KEYS:
      stale = [key for key, hits in _rate_hits.items()
               if not hits or now - hits[-1] >= 60]
      for key in stale:
        _rate_hits.pop(key, None)
    hits = [stamp for stamp in _rate_hits.get(rate_key, []) if now - stamp < 60]
    if len(hits) >= limit:
      _rate_hits[rate_key] = hits
      return False
    hits.append(now)
    _rate_hits[rate_key] = hits
    return True


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
  rid = _match(_BOM_RE, params.get('rid'), '')
  if rid is None:
    return None, 'invalid rid'
  rsrc = (params.get('rsrc') or '').strip().lower()
  if rsrc and _RSRC_RE.fullmatch(rsrc) is None:
    return None, 'invalid rsrc'
  camp = _match(_TRAFFIC_RE, params.get('camp'), '')
  if camp is None:
    return None, 'invalid camp'
  plc = _match(_TRAFFIC_RE, params.get('plc'), '')
  if plc is None:
    return None, 'invalid plc'
  site = _match(_TRAFFIC_RE, params.get('site'), '')
  if site is None:
    return None, 'invalid site'
  crid = _match(_TRAFFIC_RE, params.get('crid'), '')
  if crid is None:
    return None, 'invalid crid'
  raw_ver = params.get('ver')
  if raw_ver is None or str(raw_ver).strip() == '':
    version = None
  else:
    version = parse_creative_version(raw_ver)
    if version is None or version is False:
      return None, 'invalid ver'
  token = params.get('token') or ''
  if token and _match(_TOKEN_RE, token) is None:
    return None, 'invalid token'
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
      'RespondentID': rid or bomid,
      'RespondentIDSource': rsrc or ('bomid' if (rid or bomid) else ''),
      'CampaignID': camp,
      'PlacementID': plc,
      'SiteID': site,
      'AdCreativeID': crid,
      'CreativeVersion': version,
      'token': token,
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

  secret = receiver_hmac_secret()
  if not secret:
    _log.error('event=receiver_hmac_secret_missing')
    return _pixel_response(500, reason='hmac_secret_missing')
  if not token_is_valid(
      fields['ID'], fields.get('token'), secret,
      version=fields.get('CreativeVersion')):
    _log.info('event=receiver_reject status=403 reason=bad_token survey_id=%s',
              fields['ID'])
    return _pixel_response(403, reason='invalid_token')

  ip_secret = ip_hmac_secret()
  if not ip_secret:
    _log.error('event=receiver_ip_secret_missing')
    return _pixel_response(500, reason='ip_secret_missing')
  ip_hash = hash_ip(getattr(request, 'remote_addr', None), ip_secret)
  rate_key = '%s:%s' % (ip_hash, fields['ID'])
  if not allow_request(rate_key):
    _log.info('event=receiver_reject status=429 survey_id=%s', fields['ID'])
    return _pixel_response(429, reason='rate_limited')

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
      'RandomTimeStamp': ip_hash,
      'BomID': fields['BomID'],
      'RespondentID': fields.get('RespondentID') or fields['BomID'],
      'RespondentIDSource': fields.get('RespondentIDSource') or '',
      'CampaignID': fields.get('CampaignID') or '',
      'PlacementID': fields.get('PlacementID') or '',
      'SiteID': fields.get('SiteID') or '',
      'AdCreativeID': fields.get('AdCreativeID') or '',
      'CreativeVersion': fields.get('CreativeVersion'),
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
