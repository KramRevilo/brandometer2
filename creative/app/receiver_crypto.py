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
"""HMAC helpers for signed receiver pixels and daily IP hashes."""
import datetime
import hashlib
import hmac
import os

SECRET_RECEIVER_HMAC = 'brandometer-receiver-hmac'
SECRET_IP_HMAC = 'brandometer-ip-hmac'


def survey_token(survey_id, secret):
  """Per-survey HMAC-SHA256 hex digest. Empty secret or id yields ''."""
  if not secret or not survey_id:
    return ''
  return hmac.new(
      _as_bytes(secret), _as_bytes(survey_id), hashlib.sha256).hexdigest()


def token_is_valid(survey_id, token, secret):
  expected = survey_token(survey_id, secret)
  got = token if isinstance(token, str) else ''
  if not expected or not got:
    return False
  return hmac.compare_digest(got, expected)


def utc_day_key(secret, when=None):
  """HMAC(master, YYYY-MM-DD UTC) used as the same-day IP hashing key."""
  when = when or datetime.datetime.now(datetime.timezone.utc)
  day = when.astimezone(datetime.timezone.utc).strftime('%Y-%m-%d')
  return hmac.new(_as_bytes(secret), day.encode('utf-8'), hashlib.sha256).digest()


def hash_ip(ip_address, secret, when=None):
  """HMAC-SHA256 of the IP keyed by the daily-rotated key. Not reversible."""
  ip = '' if ip_address is None else str(ip_address)
  if not secret:
    return ''
  day_key = utc_day_key(secret, when=when)
  return hmac.new(day_key, ip.encode('utf-8'), hashlib.sha256).hexdigest()


def load_receiver_secret(environ=None):
  env = environ if environ is not None else os.environ
  return (env.get('RECEIVER_HMAC_SECRET') or '').strip()


def load_ip_secret(environ=None):
  env = environ if environ is not None else os.environ
  return (env.get('IP_HMAC_SECRET') or '').strip()


def _as_bytes(value):
  if isinstance(value, bytes):
    return value
  return str(value).encode('utf-8')
