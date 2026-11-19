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
"""Importing Google Firestore for survey storage."""
import datetime
import threading

from google.api_core.exceptions import Aborted
from google.api_core.exceptions import FailedPrecondition
from google.cloud import firestore
from forms import ANSWER_LETTERS

VERSION_SEQ_DOC = '_seq'
_version_locks = {}
_version_locks_guard = threading.Lock()


class SurveyConflictError(Exception):
  """Raised when a survey update loses an optimistic-concurrency check."""

_db = None
_survey_collection = None


def get_db():
  """Return a Firestore client, created on first use."""
  global _db, _survey_collection
  if _db is None:
    _db = firestore.Client()
    _survey_collection = _db.collection(u'Surveys')
  return _db


def _collection():
  get_db()
  return _survey_collection


# Fields the homepage list needs. Omitting custom_css keeps list payloads small.
LIST_FIELDS = (
    'surveyname',
    'displayname',
    'archived',
    'surveytype',
    'question1',
    'question2',
    'question3',
    'question4',
    'question5',
    'client',
    'agency',
    'created_at',
    'creativesize',
    'creativesizes',
)

IDENTITY_SUGGESTION_FIELDS = ('client', 'agency')


def get_all(field_names=None):
  query = _collection()
  if field_names:
    query = query.select(list(field_names))
  return query.stream()


def is_archived_doc(survey):
  """Missing archived field is treated as active."""
  return (survey.to_dict() or {}).get('archived') is True


def get_active():
  # Filter in Python so surveys without an archived field stay visible.
  return (survey for survey in _collection().stream()
          if not is_archived_doc(survey))


def get_archived():
  return (survey for survey in _collection().stream()
          if is_archived_doc(survey))


def get_by_id(survey_id):
  return _collection().document(survey_id)


def get_doc_by_id(survey_id):
  ref = get_by_id(survey_id)
  return ref.get()


def delete_by_id(survey_id):
  ref = _collection().document(survey_id)
  for version_doc in ref.collection('versions').stream():
    version_doc.reference.delete()
  ref.delete()


def encode_update_time(snapshot):
  """Opaque token for the edit form. Empty when the snapshot has no time."""
  ut = getattr(snapshot, 'update_time', None)
  if ut is None:
    return ''
  rfc3339 = getattr(ut, 'rfc3339', None)
  if callable(rfc3339):
    return rfc3339()
  iso = getattr(ut, 'isoformat', None)
  if callable(iso):
    return iso()
  return str(ut)


def decode_update_time(token):
  if not token:
    return None
  text = str(token).strip()
  if not text:
    return None
  try:
    from google.api_core.datetime_helpers import DatetimeWithNanoseconds
    return DatetimeWithNanoseconds.from_rfc3339(text)
  except Exception:
    return text


def update_by_id(survey_id, data, last_update_time=None):
  ref = _collection().document(survey_id)
  payload = dict(data or {})
  payload.pop('last_update_time', None)
  expected = decode_update_time(last_update_time) if last_update_time else None
  if expected is None:
    ref.update(payload)
    return ref
  option = None
  write_option = getattr(firestore, 'Client', None)
  if write_option is not None:
    try:
      option = firestore.Client.write_option(last_update_time=expected)
    except Exception:
      option = None
  try:
    if option is not None:
      ref.update(payload, option=option)
    else:
      ref.update(payload)
  except TypeError:
    ref.update(payload)
  except (FailedPrecondition, Aborted) as exc:
    raise SurveyConflictError(
        'Someone else saved this survey, reload') from exc
  return ref


def utc_now_iso():
  return datetime.datetime.now(datetime.timezone.utc).strftime(
      '%Y-%m-%dT%H:%M:%SZ')


def create(data):
  payload = dict(data or {})
  if not payload.get('created_at'):
    payload['created_at'] = utc_now_iso()
  ref = _collection().document()
  ref.set(payload)
  return ref


def set_archived(survey_id, archived, actor=None):
  ref = _collection().document(survey_id)
  payload = {'archived': bool(archived)}
  if actor:
    payload['updated_by'] = actor
    payload['updated_at'] = utc_now_iso()
  ref.update(payload)
  return ref


_VERSION_SCALAR_FIELDS = (
    'surveyname',
    'displayname',
    'surveytype',
    'creativesize',
    'creativesizes',
    'custom_css',
    'language',
    'responsetype',
    'badge_icon',
    'badge_text',
)


def _snapshot_fields(survey_dict):
  """Copy questions, CSS, size and type. Editing the live doc cannot mutate this."""
  data = survey_dict or {}
  snap = {}
  for key in _VERSION_SCALAR_FIELDS:
    if key in data:
      snap[key] = data[key]
  for q in range(1, 6):
    for suffix in ('', 'type', 'order'):
      key = 'question' + str(q) + suffix
      if key in data:
        snap[key] = data[key]
    for letter in ANSWER_LETTERS:
      for suffix in ('', 'next'):
        key = 'answer' + str(q) + letter + suffix
        if key in data:
          snap[key] = data[key]
  return snap


def _versions_collection(survey_id):
  return _collection().document(survey_id).collection('versions')


def _lock_for_survey(survey_id):
  with _version_locks_guard:
    lock = _version_locks.setdefault(survey_id, threading.Lock())
  return lock


def _max_existing_version(col):
  max_n = 0
  for doc in col.stream():
    if doc.id == VERSION_SEQ_DOC:
      continue
    raw = (doc.to_dict() or {}).get('version') or 0
    try:
      n = int(raw)
    except (TypeError, ValueError):
      n = 0
    if n > max_n:
      max_n = n
  return max_n


def _next_version_number(col, seq_snap):
  if seq_snap and getattr(seq_snap, 'exists', False):
    raw = (seq_snap.to_dict() or {}).get('n') or 0
    try:
      return int(raw) + 1
    except (TypeError, ValueError):
      pass
  return _max_existing_version(col) + 1


def _google_firestore_client(survey_ref):
  client = getattr(survey_ref, '_client', None)
  module = type(client).__module__ if client is not None else ''
  if client is not None and module.startswith('google.cloud') and callable(
      getattr(client, 'transaction', None)):
    return client
  return None


def add_version(survey_id, survey_dict, actor=None):
  """Append an immutable snapshot. Version numbers are transactional 1, 2, 3, …"""
  col = _versions_collection(survey_id)
  seq_ref = col.document(VERSION_SEQ_DOC)
  fields = _snapshot_fields(survey_dict)
  survey_ref = _collection().document(survey_id)
  client = _google_firestore_client(survey_ref)

  def _payload(next_n):
    payload = dict(fields)
    payload['version'] = next_n
    payload['created_at'] = datetime.datetime.now(
        datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    payload['created_by'] = actor or ''
    return payload

  if client is not None:
    transaction = client.transaction()

    @firestore.transactional
    def _txn(transaction):
      seq_snap = seq_ref.get(transaction=transaction)
      next_n = _next_version_number(col, seq_snap)
      payload = _payload(next_n)
      transaction.set(seq_ref, {'n': next_n})
      transaction.set(col.document(str(next_n)), payload)
      return payload

    return _txn(transaction)

  with _lock_for_survey(survey_id):
    next_n = _next_version_number(col, seq_ref.get())
    payload = _payload(next_n)
    seq_ref.set({'n': next_n})
    col.document(str(next_n)).set(payload)
    return payload


def list_versions(survey_id):
  versions = []
  for doc in _versions_collection(survey_id).stream():
    if doc.id == VERSION_SEQ_DOC:
      continue
    data = doc.to_dict() or {}
    data['id'] = doc.id
    versions.append(data)
  versions.sort(key=lambda item: int(item.get('version') or 0), reverse=True)
  return versions


def get_version(survey_id, version):
  doc = _versions_collection(survey_id).document(str(version)).get()
  if not getattr(doc, 'exists', False):
    return None
  return doc.to_dict() or {}


def copy(survey_id, actor=None):
  """Create a new survey document cloned from survey_id."""
  doc = get_doc_by_id(survey_id)
  if not doc.exists:
    return None
  data = dict(doc.to_dict() or {})
  original_name = data.get('surveyname') or 'survey'
  data['surveyname'] = 'Copy of ' + original_name
  if data.get('displayname'):
    data['displayname'] = 'Copy of ' + data['displayname']
  data['archived'] = False
  now = utc_now_iso()
  data['created_at'] = now
  data['updated_at'] = now
  data['created_by'] = actor or ''
  data['updated_by'] = actor or ''
  data.pop('version_seq', None)
  return create(data)
