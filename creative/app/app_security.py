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
"""Basic auth, Secret Manager, and App Engine runtime guards."""
import hmac
import logging
import os

from flask import Response
from flask import request

DEFAULT_SECRET_KEY = 'dev-only-not-for-production'
SECRET_AUTH_USERNAME = 'brandometer-auth-username'
SECRET_AUTH_PASSWORD = 'brandometer-auth-password'
SECRET_SECRET_KEY = 'brandometer-secret-key'

_log = logging.getLogger(__name__)
_secret_cache = {}


def running_on_app_engine(environ=None):
  env = environ if environ is not None else os.environ
  return bool((env.get('GAE_ENV') or '').strip())


def disable_basic_auth_requested(environ=None):
  env = environ if environ is not None else os.environ
  return (env.get('DISABLE_BASIC_AUTH') or '').strip().lower() in (
      '1', 'true', 'yes', 'on')


def _from_secret_manager(secret_id, project_id):
  if not secret_id or not project_id:
    return None
  cached = _secret_cache.get(secret_id)
  if cached is not None:
    return cached
  try:
    from google.cloud import secretmanager
  except ImportError:
    return None
  try:
    client = secretmanager.SecretManagerServiceClient()
    name = 'projects/%s/secrets/%s/versions/latest' % (project_id, secret_id)
    payload = client.access_secret_version(name=name).payload.data.decode('utf-8')
  except Exception:
    _log.debug('secret_manager_miss secret_id=%s', secret_id, exc_info=True)
    return None
  _secret_cache[secret_id] = payload
  return payload


def load_secret(env_key, secret_id, environ=None, default=None):
  """Env first (local / secret_environment_variables), then Secret Manager."""
  env = environ if environ is not None else os.environ
  value = env.get(env_key)
  if value is not None and str(value) != '':
    return value
  project_id = env.get('PROJECT_ID') or env.get('GOOGLE_CLOUD_PROJECT')
  loaded = _from_secret_manager(secret_id, project_id)
  if loaded is not None and loaded != '':
    return loaded
  return default


def configure_app(app, environ=None):
  env = environ if environ is not None else os.environ
  app.config['SECRET_KEY'] = load_secret(
      'SECRET_KEY', SECRET_SECRET_KEY, environ=env, default=DEFAULT_SECRET_KEY)
  app.config['BASIC_AUTH_USERNAME'] = load_secret(
      'AUTH_USERNAME', SECRET_AUTH_USERNAME, environ=env, default='') or ''
  app.config['BASIC_AUTH_PASSWORD'] = load_secret(
      'AUTH_PASSWORD', SECRET_AUTH_PASSWORD, environ=env, default='') or ''
  app.config['BASIC_AUTH_FORCE'] = not disable_basic_auth_requested(env)
  app.config['SESSION_COOKIE_HTTPONLY'] = True
  app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
  app.config['SESSION_COOKIE_SECURE'] = running_on_app_engine(env)
  app.config.setdefault('WTF_CSRF_TIME_LIMIT', None)
  apply_runtime_guards(app, environ=env)
  return app


def apply_runtime_guards(app, environ=None):
  """Refuse insecure production settings. No-op off App Engine."""
  env = environ if environ is not None else os.environ
  if not running_on_app_engine(env):
    return
  if disable_basic_auth_requested(env):
    raise RuntimeError(
        'DISABLE_BASIC_AUTH is not allowed when GAE_ENV is set')
  secret = app.config.get('SECRET_KEY')
  if not secret or secret == DEFAULT_SECRET_KEY:
    raise RuntimeError(
        'Refusing to start on App Engine with the default SECRET_KEY')


def credentials_match(username, password, expected_user, expected_pass):
  """Timing-safe compare. Missing expected values never authenticate."""
  got_user = username if isinstance(username, str) else ''
  got_pass = password if isinstance(password, str) else ''
  want_user = expected_user if isinstance(expected_user, str) else ''
  want_pass = expected_pass if isinstance(expected_pass, str) else ''
  if not want_user or not want_pass:
    return False
  return (
      hmac.compare_digest(got_user, want_user)
      and hmac.compare_digest(got_pass, want_pass))


def challenge_response():
  return Response(
      status=401,
      headers={'WWW-Authenticate': 'Basic realm="Brandometer"'})


def install_basic_auth(app):
  """Replace Flask-BasicAuth with a timing-safe before_request hook."""

  @app.before_request
  def require_basic_auth():
    if request.endpoint == 'static':
      return None
    if not app.config.get('BASIC_AUTH_FORCE'):
      return None
    auth = request.authorization
    if auth is None or (auth.type or '').lower() != 'basic':
      return challenge_response()
    if not credentials_match(
        auth.username, auth.password,
        app.config.get('BASIC_AUTH_USERNAME'),
        app.config.get('BASIC_AUTH_PASSWORD')):
      return challenge_response()
    return None
