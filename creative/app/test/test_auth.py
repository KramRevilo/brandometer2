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

import unittest
from unittest import mock

from flask import Flask

import app_security
import main


class AuthAndRedirectTest(unittest.TestCase):

  def tearDown(self):
    main.app.config['BASIC_AUTH_FORCE'] = True

  def test_root_redirect_is_relative_when_auth_disabled(self):
    main.app.config['BASIC_AUTH_FORCE'] = False
    client = main.app.test_client()
    response = client.get('/', follow_redirects=False)
    self.assertEqual(response.status_code, 302)
    self.assertEqual(response.headers['Location'], '/index')
    self.assertNotIn('://', response.headers['Location'])

  def test_root_requires_basic_auth_by_default(self):
    main.app.config['BASIC_AUTH_FORCE'] = True
    client = main.app.test_client()
    response = client.get('/', follow_redirects=False)
    self.assertEqual(response.status_code, 401)

  def test_wrong_password_is_rejected(self):
    main.app.config['BASIC_AUTH_FORCE'] = True
    main.app.config['BASIC_AUTH_USERNAME'] = 'mark'
    main.app.config['BASIC_AUTH_PASSWORD'] = 'secret'
    client = main.app.test_client()
    response = client.get(
        '/', headers={'Authorization': 'Basic bWFyazp3cm9uZw=='})
    self.assertEqual(response.status_code, 401)

  def test_matching_credentials_pass_timing_safe_check(self):
    self.assertTrue(app_security.credentials_match('mark', 'pw', 'mark', 'pw'))
    self.assertFalse(app_security.credentials_match('mark', 'no', 'mark', 'pw'))
    self.assertFalse(app_security.credentials_match('mark', 'pw', '', 'pw'))
    self.assertFalse(app_security.credentials_match('mark', 'pw', 'mark', ''))

  def test_app_engine_refuses_default_secret_and_disabled_auth(self):
    app = Flask('guard-test')
    app.config['SECRET_KEY'] = app_security.DEFAULT_SECRET_KEY
    with self.assertRaises(RuntimeError):
      app_security.apply_runtime_guards(
          app, environ={'GAE_ENV': 'standard'})
    app.config['SECRET_KEY'] = 'not-the-default'
    with self.assertRaises(RuntimeError):
      app_security.apply_runtime_guards(
          app, environ={'GAE_ENV': 'standard', 'DISABLE_BASIC_AUTH': '1'})
    app_security.apply_runtime_guards(
        app, environ={'GAE_ENV': 'standard'})

  def test_load_secret_prefers_env(self):
    value = app_security.load_secret(
        'AUTH_USERNAME', app_security.SECRET_AUTH_USERNAME,
        environ={'AUTH_USERNAME': 'from-env', 'PROJECT_ID': 'p'})
    self.assertEqual(value, 'from-env')

  def test_session_cookie_secure_only_on_app_engine(self):
    app = Flask('cookie-test')
    with mock.patch.object(app_security, 'load_secret', side_effect=lambda *a, **k: {
        'SECRET_KEY': 'k', 'AUTH_USERNAME': 'u', 'AUTH_PASSWORD': 'p'
    }.get(a[0], k.get('default'))):
      app_security.configure_app(app, environ={})
    self.assertFalse(app.config['SESSION_COOKIE_SECURE'])
    self.assertEqual(app.config['SESSION_COOKIE_SAMESITE'], 'Lax')
    self.assertTrue(app.config['SESSION_COOKIE_HTTPONLY'])
    app2 = Flask('cookie-gae')
    with mock.patch.object(app_security, 'load_secret', side_effect=lambda *a, **k: {
        'SECRET_KEY': 'k', 'AUTH_USERNAME': 'u', 'AUTH_PASSWORD': 'p'
    }.get(a[0], k.get('default'))):
      app_security.configure_app(app2, environ={'GAE_ENV': 'standard'})
    self.assertTrue(app2.config['SESSION_COOKIE_SECURE'])
