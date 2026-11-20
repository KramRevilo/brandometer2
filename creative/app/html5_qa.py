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
"""IAB / CM360 / DV360 HTML5 zip checks. Warnings never block a download."""
import io
import os
import re
import zipfile

import creative_size

# IAB HTML5 display: initial load budget. Polite/host-initiated cap is 2.2 MB.
IAB_INITIAL_BYTES = 200 * 1024
IAB_POLITE_BYTES = int(2.2 * 1024 * 1024)
# Campaign Manager 360 HTML5 creative max (standard display).
CM360_MAX_BYTES = 10 * 1024 * 1024
CM360_MAX_FILES = 100
IAB_MAX_FILES = 10
INNER_NAME_MAX = creative_size.INNER_ZIP_NAME_MAX

_URL_RE = re.compile(
    r"""(?:url\(\s*['"]?|href\s*=\s*['"]|src\s*=\s*['"]|@import\s+['"]?)"""
    r"""(https?://[^)'"\s>]+)""",
    re.I)
_BARE_HTTP_RE = re.compile(r'https?://[^\s\'"<>)]+', re.I)
_AD_SIZE_RE = re.compile(
    r'<meta\s+name=["\']ad\.size["\']\s+content=["\']width=(\d+),height=(\d+)["\']',
    re.I)
_CLICKTAG_RE = re.compile(r'\bvar\s+clickTag\b')
_FETCH_RE = re.compile(r'\b(?:fetch|XMLHttpRequest|navigator\.sendBeacon)\s*\(')

_MACRO_MARKERS = ('%', '${', '%%')
_ALLOWED_CLICK_HOSTS = (
    'www.google.com',
    'google.com',
)


def _finding(level, code, message, target=''):
  item = {'level': level, 'code': code, 'message': message}
  if target:
    item['target'] = target
  return item


def _is_macro(url):
  text = url or ''
  return any(marker in text for marker in _MACRO_MARKERS)


def _host(url):
  match = re.match(r'https?://([^/:]+)', url or '', re.I)
  return (match.group(1).lower() if match else '')


def _allowed_url(url, allowed_hosts):
  if not url:
    return True
  if _is_macro(url):
    return True
  lowered = url.lower()
  if lowered.startswith('data:') or lowered.startswith('blob:'):
    return True
  host = _host(url)
  if host in allowed_hosts or host in _ALLOWED_CLICK_HOSTS:
    return True
  if host.endswith('.googleusercontent.com'):
    return True
  return False


def _allowed_hosts(receiver_url='', extra_urls=None):
  hosts = set()
  for candidate in [receiver_url] + list(extra_urls or []):
    host = _host(candidate or '')
    if host:
      hosts.add(host)
  env_receiver = os.environ.get('RECEIVER_URL') or ''
  host = _host(env_receiver)
  if host:
    hosts.add(host)
  return hosts


def check_html(html, size_key=None, target='', receiver_url='', extra_urls=None):
  """Inspect a creative index.html. Returns a list of finding dicts."""
  findings = []
  text = html if isinstance(html, str) else (html or b'').decode('utf-8', 'replace')
  label = target or (size_key or 'creative')
  spec = creative_size.resolve(size_key) if size_key else None

  if not _CLICKTAG_RE.search(text):
    findings.append(_finding(
        'warning', 'clickTag',
        'No `var clickTag` (IAB/CM360 HTML5 click-through).', label))

  ad_size = _AD_SIZE_RE.search(text)
  if not ad_size:
    findings.append(_finding(
        'warning', 'ad.size',
        'Missing <meta name="ad.size" content="width=W,height=H">.', label))
  elif spec:
    got_w, got_h = int(ad_size.group(1)), int(ad_size.group(2))
    if got_w != spec['width'] or got_h != spec['height']:
      findings.append(_finding(
          'warning', 'ad.size.mismatch',
          'ad.size is %sx%s but this zip is labelled %s.' % (
              got_w, got_h, spec['key']),
          label))

  if spec:
    width_rule = 'width: %spx' % spec['width']
    height_rule = 'height: %spx' % spec['height']
    if width_rule not in text or height_rule not in text:
      findings.append(_finding(
          'warning', 'size.css',
          '#master_container CSS should be %s×%s.' % (
              spec['width'], spec['height']),
          label))

  allowed = _allowed_hosts(receiver_url, extra_urls)
  urls = set(_URL_RE.findall(text))
  for match in _BARE_HTTP_RE.findall(text):
    urls.add(match)
  for url in sorted(urls):
    if _allowed_url(url, allowed):
      continue
    findings.append(_finding(
        'warning', 'external',
        'External request %s (IAB/CM360 HTML5 should be self-contained).' % url,
        label))

  if _FETCH_RE.search(text):
    findings.append(_finding(
        'warning', 'xhr',
        'fetch/XHR/sendBeacon in the creative can fail CM360 backup/preview.',
        label))

  html_bytes = len(text.encode('utf-8'))
  if html_bytes > IAB_INITIAL_BYTES:
    findings.append(_finding(
        'warning', 'iab.initial',
        'HTML is %s bytes (IAB initial-load budget is %s KB).' % (
            html_bytes, IAB_INITIAL_BYTES // 1024),
        label))
  return findings


def check_inner_zip(payload, filename='', size_key=None, receiver_url='',
                    extra_urls=None):
  """Inspect one HTML5 inner zip (bytes, path, or ZipFile)."""
  findings = []
  label = os.path.basename(filename) if filename else (size_key or 'inner.zip')
  if filename and len(os.path.basename(filename)) > INNER_NAME_MAX:
    findings.append(_finding(
        'warning', 'filename',
        'Inner zip filename is %s characters (CM360 limit is %s).' % (
            len(os.path.basename(filename)), INNER_NAME_MAX),
        label))

  zf, closer = _open_zip(payload)
  try:
    names = zf.namelist()
    raw_size = _zip_payload_size(payload)
    if raw_size > CM360_MAX_BYTES:
      findings.append(_finding(
          'warning', 'cm360.size',
          'Inner zip is %s bytes (CM360 HTML5 max is 10 MB).' % raw_size,
          label))
    elif raw_size > IAB_POLITE_BYTES:
      findings.append(_finding(
          'warning', 'iab.polite',
          'Inner zip is %s bytes (IAB polite/host-initiated cap is 2.2 MB).' %
          raw_size,
          label))
    elif raw_size > IAB_INITIAL_BYTES:
      findings.append(_finding(
          'warning', 'iab.initial',
          'Inner zip is %s bytes (IAB initial-load budget is 200 KB).' %
          raw_size,
          label))
    if len(names) > CM360_MAX_FILES:
      findings.append(_finding(
          'warning', 'cm360.files',
          '%s files in the zip (CM360 max is %s).' % (
              len(names), CM360_MAX_FILES),
          label))
    elif len(names) > IAB_MAX_FILES:
      findings.append(_finding(
          'warning', 'iab.files',
          '%s files in the zip (IAB HTML5 commonly caps host-initiated files at %s).' % (
              len(names), IAB_MAX_FILES),
          label))
    nested = [name for name in names if name.lower().endswith('.zip')]
    if nested:
      findings.append(_finding(
          'warning', 'nested.zip',
          'Nested zip inside HTML5 creative: %s.' % ', '.join(nested),
          label))
    html_names = [
        name for name in names
        if os.path.basename(name).lower() == 'index.html']
    if not html_names:
      findings.append(_finding(
          'warning', 'index.html',
          'HTML5 zip has no index.html.', label))
    else:
      html = zf.read(html_names[0])
      findings.extend(check_html(
          html, size_key=size_key, target=label,
          receiver_url=receiver_url, extra_urls=extra_urls))
  finally:
    if closer:
      zf.close()
  return findings


def check_outer_zip(payload, receiver_url=''):
  findings = []
  zf, closer = _open_zip(payload)
  try:
    for name in zf.namelist():
      if not name.lower().endswith('.zip'):
        continue
      size_key = size_key_from_filename(name)
      findings.extend(check_inner_zip(
          zf.read(name), filename=name, size_key=size_key,
          receiver_url=receiver_url))
  finally:
    if closer:
      zf.close()
  return findings


def format_report(findings):
  if not findings:
    return (
        'HTML5 spec QA (IAB display / CM360 / DV360)\n'
        'No warnings.\n'
        'Checks: zip size, file count, index.html, ad.size vs labelled size, '
        'clickTag, no nested zip, no unexpected external requests.\n')
  lines = [
      'HTML5 spec QA (IAB display / CM360 / DV360)',
      'Warnings do not block the download. Fix before trafficking if listed.',
      '',
  ]
  for item in findings:
    target = item.get('target') or ''
    prefix = '[%s] %s' % (item['level'], item['code'])
    if target:
      prefix += ' (%s)' % target
    lines.append('%s: %s' % (prefix, item['message']))
  return '\n'.join(lines) + '\n'


def size_key_from_filename(name):
  base = os.path.basename(name or '')
  for key in creative_size.SIZES:
    if key in base:
      return key
  return None


def _open_zip(payload):
  if isinstance(payload, zipfile.ZipFile):
    return payload, False
  if hasattr(payload, 'read'):
    position = payload.tell() if hasattr(payload, 'tell') else None
    data = payload.read()
    if position is not None:
      payload.seek(position)
    return zipfile.ZipFile(io.BytesIO(data)), True
  if isinstance(payload, (bytes, bytearray)):
    return zipfile.ZipFile(io.BytesIO(payload)), True
  return zipfile.ZipFile(payload), True


def _zip_payload_size(payload):
  if isinstance(payload, (bytes, bytearray)):
    return len(payload)
  if isinstance(payload, zipfile.ZipFile):
    try:
      return os.path.getsize(payload.filename)
    except Exception:
      return sum(info.file_size for info in payload.infolist())
  if hasattr(payload, 'read'):
    position = payload.tell() if hasattr(payload, 'tell') else None
    data = payload.read()
    if position is not None:
      payload.seek(position)
    return len(data)
  try:
    return os.path.getsize(payload)
  except OSError:
    return 0
