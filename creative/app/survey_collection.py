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
from google.cloud import firestore

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
    'archived',
    'surveytype',
    'question1',
    'question2',
    'question3',
    'question4',
    'question5',
)


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
  _collection().document(survey_id).delete()


def update_by_id(survey_id, data):
  ref = _collection().document(survey_id)
  ref.update(data)
  return ref


def create(data):
  ref = _collection().document()
  ref.set(data)
  return ref


def set_archived(survey_id, archived):
  ref = _collection().document(survey_id)
  ref.update({'archived': bool(archived)})
  return ref


def copy(survey_id):
  """Create a new survey document cloned from survey_id."""
  doc = get_doc_by_id(survey_id)
  if not doc.exists:
    return None
  data = dict(doc.to_dict() or {})
  original_name = data.get('surveyname') or 'survey'
  data['surveyname'] = 'Copy of ' + original_name
  data['archived'] = False
  return create(data)
