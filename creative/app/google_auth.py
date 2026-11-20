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
"""Google Sign-In (OIDC) via Authlib. Shared Basic Auth is retired in prod."""
import logging

from flask import abort
from flask import current_app
from flask import flash
from flask import has_request_context
from flask import redirect
from flask import render_template
from flask import request
from flask import session
from flask import url_for

import access
import brand

_log = logging.getLogger(__name__)
_oauth = None

PUBLIC_ENDPOINTS = frozenset({
    'login',
    'login_google',
    'auth_callback',
    'logout',
    'static',
})


def picture_url(value):
  """HTTPS photo URL from Google userinfo, or empty. Existing sessions omit it."""
  url = (value or '').strip()
  if url.startswith('https://'):
    return url
  return ''


def avatar_initial(user):
  """First letter of name, else email, else '?'."""
  if not user:
    return '?'
  for source in (user.get('name'), user.get('email')):
    text = (source or '').strip()
    if text:
      return text[0].upper()
  return '?'


def avatar_label(user):
  """Accessible name for the navbar avatar control."""
  if not user:
    return ''
  email = (user.get('email') or '').strip()
  name = (user.get('name') or '').strip()
  if name and email and name != email:
    return '%s (%s)' % (name, email)
  return name or email


def current_user():
  """Signed-in user dict, a local-dev admin when AUTH_BYPASS, or None."""
  try:
    bypass = current_app.config.get('AUTH_BYPASS')
  except Exception:
    bypass = False
  if bypass:
    name = 'Local dev'
    role = 'admin'
    picture = ''
    if has_request_context():
      name = session.get('user_name') or name
      role = session.get('user_role') or role
      picture = picture_url(session.get('user_picture'))
    user = {
        'email': access.actor_email(),
        'name': name,
        'role': role,
        'picture': picture,
    }
    user['initial'] = avatar_initial(user)
    user['label'] = avatar_label(user)
    return user
  if not has_request_context():
    return None
  email = session.get('user_email')
  if not email:
    return None
  user = {
      'email': email,
      'name': session.get('user_name') or email,
      'role': session.get('user_role') or 'editor',
      'picture': picture_url(session.get('user_picture')),
  }
  user['initial'] = avatar_initial(user)
  user['label'] = avatar_label(user)
  return user


def is_admin():
  user = current_user()
  return bool(user and user.get('role') == 'admin')


def require_admin():
  if not is_admin():
    abort(403)


def accept_google_identity(userinfo, environ=None):
  """Validate Google OIDC claims and return (user_dict, error_message)."""
  info = userinfo or {}
  email = access.normalize_email(info.get('email'))
  verified = info.get('email_verified')
  email_verified = verified is True or str(verified).lower() == 'true'
  hd = info.get('hd')
  if not email_verified:
    return None, 'Google did not verify that email address'
  role = access.resolve_role(email, True, hd, environ=environ)
  if not role:
    return None, 'That Google account is not allowed to use this app'
  return {
      'email': email,
      'name': (info.get('name') or email).strip(),
      'role': role,
      'hd': hd or '',
      'picture': picture_url(info.get('picture')),
  }, None


def _store_user(user):
  session['user_email'] = user['email']
  session['user_name'] = user.get('name') or user['email']
  session['user_role'] = user['role']
  picture = picture_url(user.get('picture'))
  if picture:
    session['user_picture'] = picture
  else:
    session.pop('user_picture', None)
  session.permanent = True


def _clear_user():
  session.pop('user_email', None)
  session.pop('user_name', None)
  session.pop('user_role', None)
  session.pop('user_picture', None)
  session.pop('next', None)


def _redirect_uri():
  configured = (current_app.config.get('OAUTH_REDIRECT_URI') or '').strip()
  if configured:
    return configured
  return url_for('auth_callback', _external=True)


def init_oauth(app):
  """Register the Google OIDC client when a client id is configured."""
  global _oauth
  client_id = app.config.get('GOOGLE_OAUTH_CLIENT_ID')
  client_secret = app.config.get('GOOGLE_OAUTH_CLIENT_SECRET')
  if not client_id or not client_secret:
    _oauth = None
    return None
  from authlib.integrations.flask_client import OAuth
  oauth = OAuth(app)
  oauth.register(
      name='google',
      client_id=client_id,
      client_secret=client_secret,
      server_metadata_url=(
          'https://accounts.google.com/.well-known/openid-configuration'),
      client_kwargs={'scope': 'openid email profile'},
  )
  _oauth = oauth
  return oauth


def init_app(app):
  init_oauth(app)
  install_login(app)
  register_routes(app)
  return app


def install_login(app):
  @app.before_request
  def require_login():
    if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
      return None
    if request.endpoint == 'static':
      return None
    if app.config.get('AUTH_BYPASS'):
      return None
    if session.get('user_email'):
      return None
    session['next'] = request.full_path if request.query_string else request.path
    return redirect(url_for('login'))


def register_routes(app):
  @app.route('/login')
  def login():
    if current_user() and not app.config.get('AUTH_BYPASS'):
      return redirect(url_for('index'))
    if app.config.get('AUTH_BYPASS'):
      return redirect(url_for('index'))
    return render_template(
        'login.html',
        title='Sign in',
        brand_name=brand.brand_name(),
        oauth_configured=bool(app.config.get('GOOGLE_OAUTH_CLIENT_ID')))

  @app.route('/auth/google')
  def login_google():
    if app.config.get('AUTH_BYPASS'):
      return redirect(url_for('index'))
    if _oauth is None:
      flash('Google Sign-In is not configured', 'error')
      return redirect(url_for('login'))
    return _oauth.google.authorize_redirect(_redirect_uri())

  @app.route('/auth/callback')
  def auth_callback():
    if _oauth is None:
      flash('Google Sign-In is not configured', 'error')
      return redirect(url_for('login'))
    try:
      token = _oauth.google.authorize_access_token()
    except Exception:
      _log.exception('google_oauth_callback_failed')
      flash('Google Sign-In failed. Try again.', 'error')
      return redirect(url_for('login'))
    userinfo = (token or {}).get('userinfo') or {}
    user, error = accept_google_identity(userinfo)
    if error:
      flash(error, 'error')
      return redirect(url_for('login'))
    _store_user(user)
    nxt = session.pop('next', None) or url_for('index')
    if not isinstance(nxt, str) or not nxt.startswith('/'):
      nxt = url_for('index')
    return redirect(nxt)

  @app.route('/logout', methods=['GET', 'POST'])
  def logout():
    _clear_user()
    flash('Signed out')
    return redirect(url_for('login'))

  @app.route('/admin', methods=['GET', 'POST'])
  def admin():
    require_admin()
    error = None
    if request.method == 'POST':
      action = (request.form.get('action') or '').strip()
      try:
        if action == 'add_user':
          access.upsert_user(
              request.form.get('email'), request.form.get('role') or 'editor')
          flash('User saved')
        elif action == 'delete_user':
          access.delete_user(request.form.get('email'))
          flash('User removed')
        elif action == 'add_domain':
          access.add_domain(request.form.get('domain'))
          flash('Domain allowed')
        elif action == 'remove_domain':
          access.remove_domain(request.form.get('domain'))
          flash('Domain removed')
        else:
          error = 'Unknown action'
      except access.AccessError as exc:
        error = str(exc)
        flash(error, 'error')
      if error is None and action:
        return redirect(url_for('admin'))
    return render_template(
        'admin.html',
        title='Admin',
        users=access.list_users(),
        domains=access.allowed_domains(),
        audit=access.list_audit(80),
        bootstrap_admin=access.bootstrap_admin_email(),
        google_domain=access.GOOGLE_DOMAIN)


def login_context():
  user = current_user()
  return {
      'current_user': user,
      'is_admin': bool(user and user.get('role') == 'admin'),
  }
