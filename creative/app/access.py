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
"""Allowed users, allowed domains, and a simple audit log in Firestore."""
import logging
import os
import re

import survey_collection

_log = logging.getLogger(__name__)

USERS_COLLECTION = 'AccessUsers'
CONFIG_COLLECTION = 'AccessConfig'
CONFIG_DOC = 'settings'
AUDIT_COLLECTION = 'AuditLog'
GOOGLE_DOMAIN = 'google.com'
ROLES = ('admin', 'editor')
_EMAIL_RE = re.compile(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$')


class AccessError(Exception):
  """Raised for invalid admin mutations."""


def normalize_email(email):
  return (email or '').strip().lower()


def email_domain(email):
  email = normalize_email(email)
  if email.count('@') != 1:
    return ''
  local, domain = email.split('@')
  if not local or not domain:
    return ''
  return domain


def is_valid_email(email):
  return bool(_EMAIL_RE.fullmatch(normalize_email(email)))


def is_valid_domain(domain):
  text = (domain or '').strip().lower().lstrip('@')
  if not text or '@' in text or text.startswith('.'):
    return False
  return bool(re.fullmatch(r'[a-z0-9.\-]+\.[a-z]{2,}', text))


def bootstrap_admin_email(environ=None):
  env = environ if environ is not None else os.environ
  return normalize_email(env.get('BOOTSTRAP_ADMIN_EMAIL'))


def actor_email():
  """Email of the signed-in user, or local-dev when auth is bypassed."""
  try:
    from flask import current_app
    from flask import has_request_context
    from flask import session
    if has_request_context():
      if current_app.config.get('AUTH_BYPASS'):
        return normalize_email(session.get('user_email')) or 'local-dev'
      return normalize_email(session.get('user_email')) or 'unknown'
  except Exception:
    pass
  return 'local-dev'


def _db():
  return survey_collection.get_db()


def _users():
  return _db().collection(USERS_COLLECTION)


def _config_ref():
  return _db().collection(CONFIG_COLLECTION).document(CONFIG_DOC)


def _audit():
  return _db().collection(AUDIT_COLLECTION)


def get_settings():
  try:
    snap = _config_ref().get()
  except Exception:
    _log.debug('access_settings_unavailable', exc_info=True)
    return {'domains': []}
  if not getattr(snap, 'exists', False):
    return {'domains': []}
  data = snap.to_dict() or {}
  domains = []
  for item in data.get('domains') or []:
    if is_valid_domain(item):
      domains.append((item or '').strip().lower().lstrip('@'))
  return {'domains': sorted(set(domains))}


def allowed_domains():
  return get_settings().get('domains') or []


def list_users():
  users = []
  try:
    stream = _users().stream()
  except Exception:
    _log.debug('access_users_unavailable', exc_info=True)
    return users
  for doc in stream:
    data = doc.to_dict() or {}
    email = normalize_email(data.get('email') or doc.id)
    role = data.get('role') if data.get('role') in ROLES else 'editor'
    users.append({
        'email': email,
        'role': role,
        'created_at': data.get('created_at') or '',
        'created_by': data.get('created_by') or '',
    })
  users.sort(key=lambda item: item['email'])
  return users


def get_user(email):
  email = normalize_email(email)
  if not email:
    return None
  try:
    snap = _users().document(email).get()
  except Exception:
    _log.debug('access_user_unavailable', exc_info=True)
    return None
  if not getattr(snap, 'exists', False):
    return None
  data = snap.to_dict() or {}
  role = data.get('role') if data.get('role') in ROLES else 'editor'
  return {'email': email, 'role': role}


def _admin_count(except_email=None):
  except_email = normalize_email(except_email)
  n = 0
  for user in list_users():
    if user['role'] == 'admin' and user['email'] != except_email:
      n += 1
  if bootstrap_admin_email() and bootstrap_admin_email() != except_email:
    # Bootstrap can always sign back in as admin even if not listed.
    n = max(n, 1)
  return n


def upsert_user(email, role, actor=None):
  email = normalize_email(email)
  role = (role or '').strip().lower()
  if not is_valid_email(email):
    raise AccessError('Enter a valid email address')
  if role not in ROLES:
    raise AccessError('Role must be admin or editor')
  existing = get_user(email)
  if existing and existing['role'] == 'admin' and role != 'admin':
    if _admin_count(except_email=email) < 1 and email != bootstrap_admin_email():
      raise AccessError('Cannot demote the last admin')
  now = survey_collection.utc_now_iso()
  payload = {
      'email': email,
      'role': role,
      'updated_at': now,
      'updated_by': actor or actor_email(),
  }
  if not existing:
    payload['created_at'] = now
    payload['created_by'] = actor or actor_email()
  _users().document(email).set(payload, merge=True)
  write_audit(
      'admin_user_upsert', actor or actor_email(),
      detail='%s (%s)' % (email, role))
  return payload


def delete_user(email, actor=None):
  email = normalize_email(email)
  existing = get_user(email)
  if not existing:
    raise AccessError('User not found')
  if existing['role'] == 'admin' and _admin_count(except_email=email) < 1:
    if email != bootstrap_admin_email():
      raise AccessError('Cannot remove the last admin')
  _users().document(email).delete()
  write_audit('admin_user_delete', actor or actor_email(), detail=email)
  return existing


def set_domains(domains, actor=None):
  cleaned = []
  for item in domains or []:
    if not is_valid_domain(item):
      raise AccessError('Invalid domain: %s' % item)
    cleaned.append((item or '').strip().lower().lstrip('@'))
  cleaned = sorted(set(cleaned))
  _config_ref().set({
      'domains': cleaned,
      'updated_at': survey_collection.utc_now_iso(),
      'updated_by': actor or actor_email(),
  }, merge=True)
  write_audit(
      'admin_domains', actor or actor_email(),
      detail=','.join(cleaned) or '(none)')
  return cleaned


def add_domain(domain, actor=None):
  if not is_valid_domain(domain):
    raise AccessError('Enter a valid domain (example.com)')
  domain = domain.strip().lower().lstrip('@')
  domains = allowed_domains()
  if domain not in domains:
    domains.append(domain)
  return set_domains(domains, actor=actor)


def remove_domain(domain, actor=None):
  domain = (domain or '').strip().lower().lstrip('@')
  domains = [item for item in allowed_domains() if item != domain]
  return set_domains(domains, actor=actor)


def google_identity_ok(email, email_verified, hd):
  """True for a verified Google-issued @google.com identity."""
  if email_verified is not True:
    return False
  if email_domain(email) != GOOGLE_DOMAIN:
    return False
  hosted = (hd or '').strip().lower()
  # Google Workspace sets hd=google.com. Missing hd still requires verified email.
  return hosted in ('', GOOGLE_DOMAIN)


def resolve_role(email, email_verified, hd, environ=None):
  """Return 'admin' or 'editor', or None if the identity is not allowed."""
  if email_verified is not True:
    return None
  email = normalize_email(email)
  if not is_valid_email(email):
    return None
  bootstrap = bootstrap_admin_email(environ)
  if bootstrap and email == bootstrap:
    try:
      upsert_user(email, 'admin', actor='bootstrap')
    except Exception:
      _log.debug('bootstrap_upsert_failed', exc_info=True)
    return 'admin'
  listed = get_user(email)
  if listed:
    return listed['role']
  if google_identity_ok(email, email_verified, hd):
    return 'editor'
  domain = email_domain(email)
  if domain and domain in allowed_domains():
    return 'editor'
  return None


def write_audit(action, actor, survey_id='', detail=''):
  payload = {
      'action': action,
      'actor': actor or actor_email(),
      'survey_id': survey_id or '',
      'detail': (detail or '')[:500],
      'created_at': survey_collection.utc_now_iso(),
  }
  try:
    _audit().document().set(payload)
  except Exception:
    _log.exception('audit_write_failed action=%s', action)
  return payload


def list_audit(limit=100):
  rows = []
  try:
    stream = _audit().stream()
  except Exception:
    _log.debug('audit_list_unavailable', exc_info=True)
    return rows
  for doc in stream:
    data = doc.to_dict() or {}
    data['id'] = doc.id
    rows.append(data)
  rows.sort(key=lambda item: item.get('created_at') or '', reverse=True)
  return rows[:limit]
