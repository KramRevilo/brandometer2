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

from google.cloud import firestore
from forms import ANSWER_LETTERS

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


def update_by_id(survey_id, data):
  ref = _collection().document(survey_id)
  ref.update(data)
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


def set_archived(survey_id, archived):
  ref = _collection().document(survey_id)
  ref.update({'archived': bool(archived)})
  return ref


_VERSION_SCALAR_FIELDS = (
    'surveyname',
    'displayname',
    'surveytype',
    'creativesize',
    'custom_css',
    'language',
    'responsetype',
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


def add_version(survey_id, survey_dict):
  """Append an immutable snapshot. version numbers are 1, 2, 3, …"""
  col = _versions_collection(survey_id)
  next_n = 1
  for doc in col.stream():
    raw = (doc.to_dict() or {}).get('version') or 0
    try:
      n = int(raw)
    except (TypeError, ValueError):
      n = 0
    if n >= next_n:
      next_n = n + 1
  payload = _snapshot_fields(survey_dict)
  payload['version'] = next_n
  payload['created_at'] = datetime.datetime.now(
      datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
  col.document(str(next_n)).set(payload)
  return payload


def list_versions(survey_id):
  versions = []
  for doc in _versions_collection(survey_id).stream():
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


def copy(survey_id):
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
  data['created_at'] = utc_now_iso()
  return create(data)
