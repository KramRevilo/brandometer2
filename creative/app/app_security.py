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
"""Secret Manager, session cookies, and App Engine runtime guards."""
import logging
import os

DEFAULT_SECRET_KEY = 'dev-only-not-for-production'
SECRET_SECRET_KEY = 'brandometer-secret-key'
SECRET_OAUTH_CLIENT_ID = 'brandometer-oauth-client-id'
SECRET_OAUTH_CLIENT_SECRET = 'brandometer-oauth-client-secret'
SECRET_RECEIVER_HMAC = 'brandometer-receiver-hmac'

_log = logging.getLogger(__name__)
_secret_cache = {}


def running_on_app_engine(environ=None):
  env = environ if environ is not None else os.environ
  return bool((env.get('GAE_ENV') or '').strip())


def disable_basic_auth_requested(environ=None):
  """Local-dev login bypass (DISABLE_BASIC_AUTH=1). Refused when GAE_ENV is set."""
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
  app.config['GOOGLE_OAUTH_CLIENT_ID'] = load_secret(
      'GOOGLE_OAUTH_CLIENT_ID', SECRET_OAUTH_CLIENT_ID, environ=env, default='') or ''
  app.config['GOOGLE_OAUTH_CLIENT_SECRET'] = load_secret(
      'GOOGLE_OAUTH_CLIENT_SECRET', SECRET_OAUTH_CLIENT_SECRET,
      environ=env, default='') or ''
  app.config['RECEIVER_HMAC_SECRET'] = load_secret(
      'RECEIVER_HMAC_SECRET', SECRET_RECEIVER_HMAC, environ=env, default='') or ''
  app.config['OAUTH_REDIRECT_URI'] = (env.get('OAUTH_REDIRECT_URI') or '').strip()
  app.config['BOOTSTRAP_ADMIN_EMAIL'] = (env.get('BOOTSTRAP_ADMIN_EMAIL') or '').strip()
  app.config['AUTH_BYPASS'] = disable_basic_auth_requested(env)
  app.config['SESSION_COOKIE_HTTPONLY'] = True
  app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
  app.config['SESSION_COOKIE_SECURE'] = running_on_app_engine(env)
  if running_on_app_engine(env):
    app.config['PREFERRED_URL_SCHEME'] = 'https'
  else:
    # Authlib blocks http:// redirects unless this is set. Local and Cloud Shell
    # Web Preview are http-to-the-app (or http on 127.0.0.1). Never set on GAE.
    os.environ.setdefault('AUTHLIB_INSECURE_TRANSPORT', '1')
  app.config.setdefault('WTF_CSRF_TIME_LIMIT', None)
  apply_runtime_guards(app, environ=env)
  return app


def apply_runtime_guards(app, environ=None):
  """Refuse insecure production settings. No-op off App Engine."""
  env = environ if environ is not None else os.environ
  if not running_on_app_engine(env):
    return
  if disable_basic_auth_requested(env) or app.config.get('AUTH_BYPASS'):
    raise RuntimeError(
        'DISABLE_BASIC_AUTH is not allowed when GAE_ENV is set')
  secret = app.config.get('SECRET_KEY')
  if not secret or secret == DEFAULT_SECRET_KEY:
    raise RuntimeError(
        'Refusing to start on App Engine with the default SECRET_KEY')
  if not app.config.get('GOOGLE_OAUTH_CLIENT_ID') or not app.config.get(
      'GOOGLE_OAUTH_CLIENT_SECRET'):
    raise RuntimeError(
        'Refusing to start on App Engine without Google OAuth client id/secret')
  if not app.config.get('RECEIVER_HMAC_SECRET'):
    raise RuntimeError(
        'Refusing to start on App Engine without RECEIVER_HMAC_SECRET')
