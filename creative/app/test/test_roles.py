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

import pandas
from mockfirestore import MockFirestore

import access
import main
import survey_collection
import survey_service


def _survey_doc(doc_id='s1', data=None):
  payload = {
      'surveyname': 'One',
      'surveytype': 'brand_track',
      'question1': 'Q',
      'answer1a': 'A',
      'answer1b': 'B',
  }
  if data:
    payload.update(data)
  doc = mock.Mock()
  doc.id = doc_id
  doc.exists = True
  doc.to_dict.return_value = payload
  return doc


class AccessRoleMigrationTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self.fs = MockFirestore()
    self._db = mock.patch.object(
        survey_collection, 'get_db', return_value=self.fs)
    self._db.start()

  def tearDown(self):
    self._db.stop()
    super().tearDown()

  def test_missing_and_unknown_roles_become_editor(self):
    access._users().document('old@agency.example').set({
        'email': 'old@agency.example',
    })
    access._users().document('weird@agency.example').set({
        'email': 'weird@agency.example',
        'role': 'superuser',
    })
    access._users().document('boss@agency.example').set({
        'email': 'boss@agency.example',
        'role': 'admin',
    })
    listed = {row['email']: row['role'] for row in access.list_users()}
    self.assertEqual(listed['old@agency.example'], 'editor')
    self.assertEqual(listed['weird@agency.example'], 'editor')
    self.assertEqual(listed['boss@agency.example'], 'admin')
    self.assertEqual(access.get_user('old@agency.example')['role'], 'editor')
    self.assertEqual(
        access.resolve_role('old@agency.example', True, '', environ={}),
        'editor')

  def test_upsert_viewer_and_audit(self):
    access.upsert_user('see@agency.example', 'viewer', actor='admin@x')
    self.assertEqual(access.get_user('see@agency.example')['role'], 'viewer')
    rows = access.list_audit()
    self.assertEqual(rows[0]['action'], 'admin_user_upsert')
    self.assertIn('see@agency.example', rows[0]['detail'])
    self.assertIn('viewer', rows[0]['detail'])

  def test_invalid_role_rejected(self):
    with self.assertRaises(access.AccessError):
      access.upsert_user('x@agency.example', 'superuser', actor='admin')

  def test_domain_default_role_viewer(self):
    access.add_domain('partner.example', actor='admin', role='viewer')
    self.assertEqual(access.domain_default_role('partner.example'), 'viewer')
    self.assertEqual(
        access.resolve_role('new@partner.example', True, '', environ={}),
        'viewer')
    rows = access.list_domain_rows()
    self.assertEqual(rows, [{'domain': 'partner.example', 'role': 'viewer'}])
    detail = access.list_audit()[0]['detail']
    self.assertIn('partner.example=viewer', detail)

  def test_existing_domain_without_role_map_stays_editor(self):
    access._config_ref().set({'domains': ['legacy.example']}, merge=True)
    self.assertEqual(access.domain_default_role('legacy.example'), 'editor')
    self.assertEqual(
        access.resolve_role('old@legacy.example', True, '', environ={}),
        'editor')

  def test_listed_user_beats_domain_default(self):
    access.add_domain('partner.example', actor='admin', role='viewer')
    access.upsert_user('ed@partner.example', 'editor', actor='admin')
    self.assertEqual(
        access.resolve_role('ed@partner.example', True, '', environ={}),
        'editor')

  def test_google_com_unlisted_stays_editor(self):
    access.add_domain('google.com', actor='admin', role='viewer')
    self.assertEqual(
        access.resolve_role('mark@google.com', True, 'google.com', environ={}),
        'editor')

  def test_bootstrap_stays_admin(self):
    self.assertEqual(
        access.resolve_role(
            'first@agency.example', True, '',
            environ={'BOOTSTRAP_ADMIN_EMAIL': 'first@agency.example'}),
        'admin')
    self.assertEqual(access.get_user('first@agency.example')['role'], 'admin')

  def test_set_domain_role_audits(self):
    access.add_domain('agency.example', actor='admin')
    access.set_domain_role('agency.example', 'viewer', actor='admin@x')
    self.assertEqual(access.domain_default_role('agency.example'), 'viewer')
    details = ' '.join(row.get('detail') or '' for row in access.list_audit())
    self.assertIn('agency.example=viewer', details)


class RoleMatrixTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    main.app.config['AUTH_BYPASS'] = False
    main.app.config['WTF_CSRF_ENABLED'] = False
    self._suggestions = mock.patch.object(
        survey_service, 'identity_suggestions',
        return_value={'clients': [], 'agencies': []})
    self._suggestions.start()
    self.addCleanup(self._suggestions.stop)
    self._doc = _survey_doc()
    self._patches = [
        mock.patch.object(
            survey_service, 'list_surveys', return_value=[self._doc]),
        mock.patch.object(
            survey_service, 'homepage_filter_options',
            return_value={
                'clients': [], 'agencies': [], 'years': [],
                'has_unknown_year': False}),
        mock.patch.object(
            survey_service, 'get_doc_by_id', return_value=self._doc),
        mock.patch.object(
            survey_service, 'get_question_json', return_value=[]),
        mock.patch.object(
            survey_service, 'get_report',
            return_value={
                'is_lift': False, 'n_total': 0, 'n_raw': 0,
                'empty_reason': 'no_data', 'daily': [], 'questions': [],
                'breakouts': [], 'segments': [],
            }),
        mock.patch.object(
            survey_service, 'iter_response_csv',
            side_effect=lambda *args, **kwargs: iter(['Date\n'])),
        mock.patch.object(
            survey_service, 'zip_file',
            side_effect=lambda *args, **kwargs: (
                'one.zip', io.BytesIO(b'PK\x03\x04'))),
        mock.patch.object(
            survey_service, 'get_version',
            return_value={'surveyname': 'Old', 'question1': 'Q'}),
        mock.patch.object(survey_service, 'delete_by_id'),
        mock.patch.object(
            survey_service, 'copy_by_id', return_value=mock.Mock(id='new1')),
        mock.patch.object(survey_service, 'set_archived'),
        mock.patch.object(survey_service, 'list_versions', return_value=[]),
        mock.patch.object(
            survey_service, 'get_response_counts',
            return_value=pandas.DataFrame(columns=[
                'ID', 'Segmentation', 'max_date', 'days_since_response',
                'response_count'])),
        mock.patch.object(access, 'list_users', return_value=[]),
        mock.patch.object(access, 'list_domain_rows', return_value=[]),
        mock.patch.object(access, 'allowed_domains', return_value=[]),
        mock.patch.object(access, 'list_audit', return_value=[]),
    ]
    for patched in self._patches:
      patched.start()
      self.addCleanup(patched.stop)

  def tearDown(self):
    main.app.config['AUTH_BYPASS'] = False
    main.app.config['WTF_CSRF_ENABLED'] = True
    super().tearDown()

  def _client(self, role):
    client = main.app.test_client()
    with client.session_transaction() as sess:
      sess['user_email'] = '%s@agency.example' % role
      sess['user_role'] = role
      sess['user_name'] = role.title()
    return client

  def _status(self, role, method, path, **kwargs):
    client = self._client(role)
    response = getattr(client, method)(path, **kwargs)
    return response.status_code

  def test_read_routes_allowed_for_all_roles(self):
    reads = (
        ('get', '/index'),
        ('get', '/index/stats-partial?ids=s1'),
        ('get', '/survey/preview/s1'),
        ('get', '/survey/reporting/s1'),
        ('get', '/survey/download_responses/s1'),
        ('get', '/survey/download_responses_context/s1'),
        ('get', '/survey/download_breakouts/s1'),
    )
    for role in ('admin', 'editor', 'viewer'):
      for method, path in reads:
        status = self._status(role, method, path)
        self.assertEqual(status, 200, '%s %s %s' % (role, method, path))

  def test_mutating_and_zip_forbidden_for_viewer(self):
    blocked = (
        ('get', '/survey/create'),
        ('post', '/survey/create'),
        ('get', '/survey/bulk'),
        ('post', '/survey/bulk'),
        ('get', '/survey/bulk/template.csv'),
        ('get', '/survey/edit?survey_id=s1'),
        ('post', '/survey/edit?survey_id=s1'),
        ('post', '/survey/delete', {'survey_id': 's1'}),
        ('post', '/survey/copy', {'survey_id': 's1'}),
        ('post', '/survey/archive', {'survey_id': 's1', 'archived': '1'}),
        ('get', '/survey/download_zip/s1'),
        ('get', '/survey/download_zip/s1/version/1'),
        ('get', '/survey/download_tags/s1'),
        ('get', '/survey/download_bulk_upload/s1'),
        ('get', '/admin'),
        ('post', '/admin', {'action': 'add_user', 'email': 'a@b.co', 'role': 'editor'}),
    )
    for item in blocked:
      method, path = item[0], item[1]
      data = item[2] if len(item) > 2 else None
      kwargs = {'data': data} if data is not None else {}
      response = getattr(self._client('viewer'), method)(
          path, follow_redirects=False, **kwargs)
      self.assertEqual(response.status_code, 403, 'viewer %s %s' % (method, path))
      self.assertIn(b'permission', response.data)

  def test_editor_can_mutate_but_not_admin(self):
    self.assertEqual(self._status('editor', 'get', '/survey/create'), 200)
    self.assertEqual(self._status('editor', 'get', '/survey/bulk'), 200)
    self.assertEqual(self._status('editor', 'get', '/survey/bulk/template.csv'), 200)
    self.assertEqual(
        self._status(
            'editor', 'post', '/survey/delete',
            data={'survey_id': 's1'}, follow_redirects=False),
        302)
    self.assertEqual(
        self._status(
            'editor', 'post', '/survey/copy',
            data={'survey_id': 's1'}, follow_redirects=False),
        302)
    self.assertEqual(
        self._status(
            'editor', 'post', '/survey/archive',
            data={'survey_id': 's1', 'archived': '1'}, follow_redirects=False),
        302)
    self.assertEqual(self._status('editor', 'get', '/survey/download_zip/s1'), 200)
    self.assertEqual(self._status('editor', 'get', '/survey/download_tags/s1'), 200)
    self.assertEqual(
        self._status('editor', 'get', '/survey/download_bulk_upload/s1'), 200)
    self.assertEqual(
        self._status('editor', 'get', '/survey/download_zip/s1/version/1'), 200)
    self.assertEqual(self._status('editor', 'get', '/admin'), 403)
    self.assertEqual(
        self._status(
            'editor', 'post', '/admin',
            data={'action': 'add_user', 'email': 'a@b.co', 'role': 'viewer'},
            follow_redirects=False),
        403)

  def test_admin_can_open_admin_and_mutate(self):
    self.assertEqual(self._status('admin', 'get', '/admin'), 200)
    self.assertEqual(self._status('admin', 'get', '/survey/create'), 200)
    self.assertEqual(self._status('admin', 'get', '/survey/download_zip/s1'), 200)
    self.assertEqual(self._status('admin', 'get', '/survey/download_tags/s1'), 200)
    self.assertEqual(
        self._status('admin', 'get', '/survey/download_bulk_upload/s1'), 200)

  def test_viewer_ui_hides_mutate_controls(self):
    response = self._client('viewer').get('/index')
    self.assertEqual(response.status_code, 200)
    self.assertNotIn(b'>Create survey</a>', response.data)
    self.assertNotIn(b'>Bulk CSV</a>', response.data)
    self.assertNotIn(b'>Admin</a>', response.data)
    self.assertNotIn(b'Download Creative Zip', response.data)
    self.assertNotIn(b'tag sheet', response.data)
    self.assertNotIn(b'bulk-upload', response.data)
    self.assertNotIn(b'title="Edit Survey"', response.data)
    self.assertNotIn(b'title="Copy Survey"', response.data)
    self.assertNotIn(b'title="Archive Survey"', response.data)
    self.assertNotIn(b'title="Delete Survey"', response.data)
    self.assertIn(b'title="View Survey"', response.data)
    self.assertIn(b'title="Download Responses"', response.data)
    self.assertIn(b'title="Download breakouts CSV"', response.data)
    self.assertIn(b'>viewer</span>', response.data)

  def test_editor_ui_keeps_mutate_controls(self):
    response = self._client('editor').get('/index')
    self.assertEqual(response.status_code, 200)
    self.assertIn(b'>Create survey</a>', response.data)
    self.assertIn(b'>Bulk CSV</a>', response.data)
    self.assertNotIn(b'>Admin</a>', response.data)
    self.assertIn(b'Download Creative Zip', response.data)
    self.assertIn(b'tag sheet', response.data)
    self.assertIn(b'bulk-upload', response.data)
    self.assertIn(b'title="Edit Survey"', response.data)
    self.assertIn(b'>editor</span>', response.data)

  def test_admin_ui_shows_admin_link(self):
    response = self._client('admin').get('/index')
    self.assertEqual(response.status_code, 200)
    self.assertIn(b'>Admin</a>', response.data)
    self.assertIn(b'>admin</span>', response.data)

  def test_can_edit_helpers(self):
    self.assertTrue(access.can_edit('admin'))
    self.assertTrue(access.can_edit('editor'))
    self.assertFalse(access.can_edit('viewer'))
    self.assertTrue(access.can_admin('admin'))
    self.assertFalse(access.can_admin('editor'))
