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

import os
import unittest
from unittest import mock

from flask import Flask
from mockfirestore import MockFirestore

import access
import app_security
import google_auth
import main
import survey_collection
import survey_service


class AuthAndRedirectTest(unittest.TestCase):

  def tearDown(self):
    main.app.config['AUTH_BYPASS'] = False

  def test_root_redirect_is_relative_when_auth_bypassed(self):
    main.app.config['AUTH_BYPASS'] = True
    client = main.app.test_client()
    response = client.get('/', follow_redirects=False)
    self.assertEqual(response.status_code, 302)
    self.assertEqual(response.headers['Location'], '/index')
    self.assertNotIn('://', response.headers['Location'])

  def test_root_redirects_to_login_when_not_signed_in(self):
    main.app.config['AUTH_BYPASS'] = False
    client = main.app.test_client()
    response = client.get('/', follow_redirects=False)
    self.assertEqual(response.status_code, 302)
    self.assertTrue(response.headers['Location'].endswith('/login'))

  def test_login_page_renders_without_oauth(self):
    main.app.config['AUTH_BYPASS'] = False
    main.app.config['GOOGLE_OAUTH_CLIENT_ID'] = ''
    client = main.app.test_client()
    response = client.get('/login')
    self.assertEqual(response.status_code, 200)
    self.assertIn(b'Sign in with your Google account', response.data)
    self.assertIn(b'Brandometer2', response.data)
    self.assertIn('Sign in · Brandometer2'.encode('utf-8'), response.data)
    self.assertIn(b'DISABLE_BASIC_AUTH=1', response.data)
    self.assertIn(b'rel="icon"', response.data)
    self.assertIn(b'favicon.svg', response.data)
    self.assertIn(b'apple-touch-icon.png', response.data)

  def test_favicon_is_public(self):
    main.app.config['AUTH_BYPASS'] = False
    client = main.app.test_client()
    response = client.get('/favicon.ico')
    self.assertEqual(response.status_code, 200)
    self.assertGreater(len(response.data), 500)
    self.assertTrue(
        response.data.startswith(b'\x00\x00\x01\x00') or
        response.data[:8] == b'\x89PNG\r\n\x1a\n')
    self.assertIn(b'favicon.svg', client.get('/login').data)

  def test_login_google_without_oauth_redirects_to_login(self):
    main.app.config['AUTH_BYPASS'] = False
    with mock.patch.object(google_auth, '_oauth', None):
      client = main.app.test_client()
      response = client.get('/auth/google', follow_redirects=False)
    self.assertEqual(response.status_code, 302)
    self.assertTrue(response.headers['Location'].endswith('/login'))

  def test_logout_clears_session(self):
    main.app.config['AUTH_BYPASS'] = False
    client = main.app.test_client()
    with client.session_transaction() as sess:
      sess['user_email'] = 'editor@example.com'
      sess['user_role'] = 'editor'
      sess['user_name'] = 'Ed'
      sess['user_picture'] = 'https://lh3.googleusercontent.com/a/old'
    response = client.get('/logout', follow_redirects=False)
    self.assertEqual(response.status_code, 302)
    self.assertTrue(response.headers['Location'].endswith('/login'))
    with client.session_transaction() as sess:
      self.assertNotIn('user_email', sess)
      self.assertNotIn('user_picture', sess)

  def test_signed_in_editor_cannot_open_admin(self):
    main.app.config['AUTH_BYPASS'] = False
    client = main.app.test_client()
    with client.session_transaction() as sess:
      sess['user_email'] = 'editor@example.com'
      sess['user_role'] = 'editor'
    response = client.get('/admin')
    self.assertEqual(response.status_code, 403)

  def test_signed_in_admin_sees_admin_page(self):
    main.app.config['AUTH_BYPASS'] = False
    main.app.config['WTF_CSRF_ENABLED'] = False
    client = main.app.test_client()
    with client.session_transaction() as sess:
      sess['user_email'] = 'admin@example.com'
      sess['user_role'] = 'admin'
    with mock.patch.object(access, 'list_users', return_value=[]):
      with mock.patch.object(access, 'allowed_domains', return_value=[]):
        with mock.patch.object(access, 'list_domain_rows', return_value=[]):
          with mock.patch.object(access, 'list_audit', return_value=[]):
            response = client.get('/admin')
    self.assertEqual(response.status_code, 200)
    self.assertIn(b'Allowed users', response.data)
    self.assertIn(b'Audit log', response.data)
    self.assertIn(b'value="viewer"', response.data)
    self.assertIn(b'Default role', response.data)
    main.app.config['WTF_CSRF_ENABLED'] = True

  def test_open_redirect_on_callback_is_ignored(self):
    main.app.config['AUTH_BYPASS'] = False
    oauth = mock.Mock()
    oauth.google.authorize_access_token.return_value = {
        'userinfo': {
            'email': 'mark@google.com',
            'email_verified': True,
            'hd': 'google.com',
            'name': 'Mark',
            'picture': 'https://lh3.googleusercontent.com/a/test-photo',
        }
    }
    with mock.patch.object(google_auth, '_oauth', oauth):
      with mock.patch.object(
          google_auth.access, 'resolve_role', return_value='editor'):
        client = main.app.test_client()
        with client.session_transaction() as sess:
          sess['next'] = 'https://evil.example/phish'
        response = client.get('/auth/callback', follow_redirects=False)
        with client.session_transaction() as sess:
          self.assertEqual(
              sess.get('user_picture'),
              'https://lh3.googleusercontent.com/a/test-photo')
          self.assertEqual(sess.get('user_email'), 'mark@google.com')
    self.assertEqual(response.status_code, 302)
    self.assertTrue(response.headers['Location'].endswith('/index'))

  def test_app_engine_refuses_default_secret_bypass_and_missing_oauth(self):
    app = Flask('guard-test')
    app.config['SECRET_KEY'] = app_security.DEFAULT_SECRET_KEY
    with self.assertRaises(RuntimeError):
      app_security.apply_runtime_guards(
          app, environ={'GAE_ENV': 'standard'})
    app.config['SECRET_KEY'] = 'not-the-default'
    with self.assertRaises(RuntimeError):
      app_security.apply_runtime_guards(
          app, environ={'GAE_ENV': 'standard', 'DISABLE_BASIC_AUTH': '1'})
    with self.assertRaises(RuntimeError):
      app_security.apply_runtime_guards(
          app, environ={'GAE_ENV': 'standard'})
    app.config['GOOGLE_OAUTH_CLIENT_ID'] = 'id'
    app.config['GOOGLE_OAUTH_CLIENT_SECRET'] = 'secret'
    with self.assertRaises(RuntimeError):
      app_security.apply_runtime_guards(
          app, environ={'GAE_ENV': 'standard'})
    app.config['RECEIVER_HMAC_SECRET'] = 'hmac'
    app_security.apply_runtime_guards(
        app, environ={'GAE_ENV': 'standard'})

  def test_load_secret_prefers_env(self):
    value = app_security.load_secret(
        'GOOGLE_OAUTH_CLIENT_ID', app_security.SECRET_OAUTH_CLIENT_ID,
        environ={'GOOGLE_OAUTH_CLIENT_ID': 'from-env', 'PROJECT_ID': 'p'})
    self.assertEqual(value, 'from-env')

  def test_secret_manager_loader_caches_and_fails_fast(self):
    app_security._secret_cache.clear()
    payload = mock.Mock()
    payload.payload.data = b'oauth-id-value'
    client = mock.Mock()
    client.access_secret_version.return_value = payload
    with mock.patch(
        'google.cloud.secretmanager.SecretManagerServiceClient',
        return_value=client):
      first = app_security.load_secret(
          'GOOGLE_OAUTH_CLIENT_ID', app_security.SECRET_OAUTH_CLIENT_ID,
          environ={'PROJECT_ID': 'brandometer2'})
      second = app_security.load_secret(
          'GOOGLE_OAUTH_CLIENT_ID', app_security.SECRET_OAUTH_CLIENT_ID,
          environ={'PROJECT_ID': 'brandometer2'})
    self.assertEqual(first, 'oauth-id-value')
    self.assertEqual(second, 'oauth-id-value')
    client.access_secret_version.assert_called_once_with(
        name='projects/brandometer2/secrets/brandometer-oauth-client-id/versions/latest')
    app_security._secret_cache.clear()
    client.access_secret_version.side_effect = Exception('404 Secret not found')
    with mock.patch(
        'google.cloud.secretmanager.SecretManagerServiceClient',
        return_value=client):
      with self.assertLogs('app_security', level='ERROR') as logs:
        with self.assertRaises(RuntimeError) as raised:
          app_security.load_secret(
              'GOOGLE_OAUTH_CLIENT_SECRET',
              app_security.SECRET_OAUTH_CLIENT_SECRET,
              environ={'PROJECT_ID': 'brandometer2'},
              required=True)
    self.assertIn('brandometer-oauth-client-secret', str(raised.exception))
    self.assertTrue(any('Failed to load secret' in line for line in logs.output))
    app_security._secret_cache.clear()
    with mock.patch.object(
        app_security, '_from_secret_manager', return_value='from-sm'):
      app = Flask('sm-startup')
      app_security.configure_app(app, environ={
          'GAE_ENV': 'standard',
          'PROJECT_ID': 'brandometer2',
      })
    self.assertEqual(app.config['SECRET_KEY'], 'from-sm')
    self.assertEqual(app.config['GOOGLE_OAUTH_CLIENT_ID'], 'from-sm')

  def test_session_cookie_secure_only_on_app_engine(self):
    app = Flask('cookie-test')
    with mock.patch.object(app_security, 'load_secret', side_effect=lambda *a, **k: {
        'SECRET_KEY': 'k',
        'GOOGLE_OAUTH_CLIENT_ID': 'id',
        'GOOGLE_OAUTH_CLIENT_SECRET': 'secret',
        'RECEIVER_HMAC_SECRET': 'hmac',
    }.get(a[0], k.get('default'))):
      app_security.configure_app(app, environ={})
    self.assertFalse(app.config['SESSION_COOKIE_SECURE'])
    self.assertEqual(app.config['SESSION_COOKIE_SAMESITE'], 'Lax')
    self.assertTrue(app.config['SESSION_COOKIE_HTTPONLY'])
    self.assertTrue(app.config['AUTH_BYPASS'] in (False, True))
    app2 = Flask('cookie-gae')
    with mock.patch.object(app_security, 'load_secret', side_effect=lambda *a, **k: {
        'SECRET_KEY': 'k',
        'GOOGLE_OAUTH_CLIENT_ID': 'id',
        'GOOGLE_OAUTH_CLIENT_SECRET': 'secret',
        'RECEIVER_HMAC_SECRET': 'hmac',
    }.get(a[0], k.get('default'))):
      app_security.configure_app(app2, environ={'GAE_ENV': 'standard'})
    self.assertTrue(app2.config['SESSION_COOKIE_SECURE'])

  def test_accept_google_identity_requires_verified_google_com(self):
    user, error = google_auth.accept_google_identity({
        'email': 'mark@google.com',
        'email_verified': False,
        'hd': 'google.com',
    })
    self.assertIsNone(user)
    self.assertIn('verify', error)

  def _navbar_index(self, sess_fields):
    main.app.config['AUTH_BYPASS'] = False
    main.app.config['WTF_CSRF_ENABLED'] = False
    client = main.app.test_client()
    with client.session_transaction() as sess:
      sess.update(sess_fields)
    with mock.patch.object(
        survey_service, 'identity_suggestions',
        return_value={'clients': [], 'agencies': []}):
      with mock.patch.object(survey_service, 'list_surveys', return_value=[]):
        with mock.patch.object(
            survey_service, 'homepage_filter_options',
            return_value={
                'clients': [], 'agencies': [], 'years': [],
                'has_unknown_year': False}):
          response = client.get('/index')
    main.app.config['WTF_CSRF_ENABLED'] = True
    return response

  def test_navbar_shows_signed_in_user(self):
    response = self._navbar_index({
        'user_email': 'editor@agency.example',
        'user_role': 'editor',
        'user_name': 'Ed',
    })
    self.assertEqual(response.status_code, 200)
    self.assertIn(b'editor@agency.example', response.data)
    self.assertIn(b'Sign out', response.data)
    self.assertIn(b'>editor</span>', response.data)
    self.assertIn(b'>Create survey</a>', response.data)
    self.assertIn(b'>Bulk CSV</a>', response.data)
    self.assertNotIn(b'>Admin</a>', response.data)
    self.assertNotIn(b'navbar-text', response.data)
    self.assertIn(b'navbar-avatar-fallback', response.data)
    self.assertIn(b'>E</span>', response.data)
    self.assertNotIn(b'class="navbar-avatar rounded-circle"', response.data)
    self.assertIn(b'navbar-avatar.js', response.data)
    self.assertIn(b'd-flex align-items-center', response.data)

  def test_navbar_renders_google_picture_when_present(self):
    photo = 'https://lh3.googleusercontent.com/a/mark-photo'
    response = self._navbar_index({
        'user_email': 'mdoliver@gmail.com',
        'user_role': 'editor',
        'user_name': 'Mark',
        'user_picture': photo,
    })
    self.assertEqual(response.status_code, 200)
    self.assertIn(photo.encode(), response.data)
    self.assertIn(b'class="navbar-avatar rounded-circle"', response.data)
    self.assertIn(b'referrerpolicy="no-referrer"', response.data)
    self.assertIn(b'navbar-avatar-fallback d-none', response.data)
    self.assertIn(b'mdoliver@gmail.com', response.data)
    self.assertIn(b'Sign out', response.data)

  def test_accept_google_identity_stores_https_picture_only(self):
    user, error = google_auth.accept_google_identity({
        'email': 'mark@google.com',
        'email_verified': True,
        'hd': 'google.com',
        'name': 'Mark',
        'picture': 'https://lh3.googleusercontent.com/a/ok',
    })
    self.assertIsNone(error)
    self.assertEqual(user['picture'], 'https://lh3.googleusercontent.com/a/ok')
    user, error = google_auth.accept_google_identity({
        'email': 'mark@google.com',
        'email_verified': True,
        'hd': 'google.com',
        'name': 'Mark',
        'picture': 'javascript:alert(1)',
    })
    self.assertIsNone(error)
    self.assertEqual(user['picture'], '')
    self.assertEqual(google_auth.avatar_initial(user), 'M')


class AccessControlTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self.fs = MockFirestore()
    self._db = mock.patch.object(
        survey_collection, 'get_db', return_value=self.fs)
    self._db.start()

  def tearDown(self):
    self._db.stop()
    super().tearDown()

  def test_google_com_verified_is_editor(self):
    role = access.resolve_role(
        'Mark@Google.com', True, 'google.com', environ={})
    self.assertEqual(role, 'editor')

  def test_google_com_wrong_hd_is_rejected(self):
    self.assertIsNone(access.resolve_role(
        'mark@google.com', True, 'evil.com', environ={}))

  def test_unverified_email_is_rejected(self):
    self.assertIsNone(access.resolve_role(
        'mark@google.com', False, 'google.com', environ={}))

  def test_bootstrap_admin_wins(self):
    role = access.resolve_role(
        'first@agency.example', True, '',
        environ={'BOOTSTRAP_ADMIN_EMAIL': 'first@agency.example'})
    self.assertEqual(role, 'admin')
    listed = access.get_user('first@agency.example')
    self.assertEqual(listed['role'], 'admin')

  def test_listed_user_and_allowed_domain(self):
    access.upsert_user('ed@agency.example', 'editor', actor='admin')
    self.assertEqual(
        access.resolve_role('ed@agency.example', True, '', environ={}),
        'editor')
    access.add_domain('partner.example', actor='admin')
    self.assertEqual(
        access.resolve_role('new@partner.example', True, '', environ={}),
        'editor')
    self.assertIsNone(access.resolve_role(
        'nope@other.example', True, '', environ={}))

  def test_cannot_remove_last_admin_without_bootstrap(self):
    access.upsert_user('only@agency.example', 'admin', actor='seed')
    with mock.patch.object(access, 'bootstrap_admin_email', return_value=''):
      with self.assertRaises(access.AccessError):
        access.delete_user('only@agency.example')

  def test_audit_log_records_admin_change(self):
    access.upsert_user('ed@agency.example', 'editor', actor='admin@x')
    rows = access.list_audit()
    self.assertTrue(rows)
    self.assertEqual(rows[0]['action'], 'admin_user_upsert')
    self.assertEqual(rows[0]['actor'], 'admin@x')


class ContentSecurityPolicyTest(unittest.TestCase):

  def tearDown(self):
    main.app.config['AUTH_BYPASS'] = False

  def test_policy_allows_self_avatars_and_google_signin(self):
    policy = app_security.content_security_policy({})
    self.assertIn("default-src 'self'", policy)
    self.assertIn("script-src 'self' 'unsafe-inline' 'unsafe-eval'", policy)
    self.assertIn('img-src', policy)
    self.assertIn('https://*.googleusercontent.com', policy)
    self.assertIn('https://accounts.google.com', policy)
    self.assertIn('https://oauth2.googleapis.com', policy)
    self.assertIn("object-src 'none'", policy)
    self.assertIn("frame-ancestors 'self'", policy)
    self.assertNotIn("frame-ancestors 'none'", policy)
    self.assertNotIn('cdn.jsdelivr', policy)
    self.assertNotIn('googletagmanager', policy)

  def test_gtag_origins_only_when_gtag_id_set(self):
    policy = app_security.content_security_policy({'GTAG_ID': 'G-TEST'})
    self.assertIn('https://www.googletagmanager.com', policy)
    self.assertIn('https://www.google-analytics.com', policy)

  def test_receiver_origin_is_added_to_pixel_directives(self):
    env = {'RECEIVER_URL': 'https://recv.example/pixel'}
    self.assertEqual(
        app_security.receiver_origin(env), 'https://recv.example')
    policy = app_security.content_security_policy(env)
    self.assertIn('img-src', policy)
    self.assertRegex(policy, r'img-src [^;]*https://recv\.example')
    self.assertRegex(policy, r'connect-src [^;]*https://recv\.example')
    self.assertRegex(policy, r'frame-src [^;]*https://recv\.example')
    empty = app_security.content_security_policy({})
    self.assertNotIn('recv.example', empty)
    self.assertEqual(app_security.receiver_origin({}), '')
    self.assertEqual(
        app_security.receiver_origin({'RECEIVER_URL': 'not-a-url'}), '')

  def test_login_sends_enforced_csp(self):
    main.app.config['AUTH_BYPASS'] = False
    main.app.config['GOOGLE_OAUTH_CLIENT_ID'] = ''
    response = main.app.test_client().get('/login')
    self.assertEqual(response.status_code, 200)
    csp = response.headers.get('Content-Security-Policy', '')
    self.assertIn("default-src 'self'", csp)
    self.assertIn('https://*.googleusercontent.com', csp)
    self.assertIn('https://accounts.google.com', csp)
    self.assertIn("frame-ancestors 'self'", csp)
    self.assertIsNone(response.headers.get('Content-Security-Policy-Report-Only'))
    self.assertIn(b'Brandometer2', response.data)

  def test_report_only_escape_hatch(self):
    main.app.config['AUTH_BYPASS'] = False
    main.app.config['GOOGLE_OAUTH_CLIENT_ID'] = ''
    with mock.patch.dict(os.environ, {'CSP_REPORT_ONLY': '1'}):
      response = main.app.test_client().get('/login')
    self.assertTrue(
        response.headers.get('Content-Security-Policy-Report-Only'))
    self.assertIsNone(response.headers.get('Content-Security-Policy'))
    self.assertIn(
        "default-src 'self'",
        response.headers.get('Content-Security-Policy-Report-Only'))
