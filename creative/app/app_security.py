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


def _from_secret_manager(secret_id, project_id, required=False):
  """Load a Secret Manager version. Cached at module level for the process."""
  if not secret_id or not project_id:
    if required:
      raise RuntimeError(
          'Missing project id while loading Secret Manager secret %s' % secret_id)
    return None
  cached = _secret_cache.get(secret_id)
  if cached is not None:
    return cached
  try:
    from google.cloud import secretmanager
  except ImportError as exc:
    _log.error(
        'google-cloud-secret-manager is not installed; cannot load %s',
        secret_id)
    if required:
      raise RuntimeError(
          'Cannot load secret %s: google-cloud-secret-manager is missing' %
          secret_id) from exc
    return None
  name = 'projects/%s/secrets/%s/versions/latest' % (project_id, secret_id)
  try:
    client = secretmanager.SecretManagerServiceClient()
    payload = client.access_secret_version(name=name).payload.data.decode('utf-8')
  except Exception as exc:
    _log.error(
        'Failed to load secret %s from Secret Manager (project %s): %s',
        secret_id, project_id, exc)
    if required:
      raise RuntimeError(
          'Missing required secret %s in Secret Manager (project %s)' %
          (secret_id, project_id)) from exc
    return None
  if payload is None or payload == '':
    _log.error('Secret %s in project %s is empty', secret_id, project_id)
    if required:
      raise RuntimeError(
          'Required secret %s in Secret Manager is empty (project %s)' %
          (secret_id, project_id))
    return None
  _secret_cache[secret_id] = payload
  return payload


def load_secret(env_key, secret_id, environ=None, default=None, required=False):
  """Env first (local), then Secret Manager. Fail fast when required."""
  env = environ if environ is not None else os.environ
  value = env.get(env_key)
  if value is not None and str(value) != '':
    return value
  project_id = env.get('PROJECT_ID') or env.get('GOOGLE_CLOUD_PROJECT')
  loaded = _from_secret_manager(secret_id, project_id, required=required)
  if loaded is not None and loaded != '':
    return loaded
  if required:
    raise RuntimeError(
        'Missing required secret %s (env %s, project %s)' % (
            secret_id, env_key, project_id or '(unset)'))
  return default


def configure_app(app, environ=None):
  env = environ if environ is not None else os.environ
  on_gae = running_on_app_engine(env)
  app.config['SECRET_KEY'] = load_secret(
      'SECRET_KEY', SECRET_SECRET_KEY, environ=env,
      default=DEFAULT_SECRET_KEY, required=on_gae)
  app.config['GOOGLE_OAUTH_CLIENT_ID'] = load_secret(
      'GOOGLE_OAUTH_CLIENT_ID', SECRET_OAUTH_CLIENT_ID, environ=env,
      default='', required=on_gae) or ''
  app.config['GOOGLE_OAUTH_CLIENT_SECRET'] = load_secret(
      'GOOGLE_OAUTH_CLIENT_SECRET', SECRET_OAUTH_CLIENT_SECRET,
      environ=env, default='', required=on_gae) or ''
  app.config['RECEIVER_HMAC_SECRET'] = load_secret(
      'RECEIVER_HMAC_SECRET', SECRET_RECEIVER_HMAC, environ=env,
      default='', required=on_gae) or ''
  app.config['OAUTH_REDIRECT_URI'] = (env.get('OAUTH_REDIRECT_URI') or '').strip()
  app.config['BOOTSTRAP_ADMIN_EMAIL'] = (env.get('BOOTSTRAP_ADMIN_EMAIL') or '').strip()
  app.config['AUTH_BYPASS'] = disable_basic_auth_requested(env)
  app.config['SESSION_COOKIE_HTTPONLY'] = True
  app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
  app.config['SESSION_COOKIE_SECURE'] = on_gae
  if on_gae:
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
