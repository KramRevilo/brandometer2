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
"""Supported display creative sizes. 300x250 is the default for old docs."""
import re

DEFAULT_SIZE = '300x250'
SIZE_START = '/* SONAR_SIZE_START */'
SIZE_END = '/* SONAR_SIZE_END */'
LAYOUT_START = '/* SONAR_LAYOUT_START */'
LAYOUT_END = '/* SONAR_LAYOUT_END */'
INNER_ZIP_NAME_MAX = 50
MAX_ANSWERS_DEFAULT = 5
MAX_ANSWERS_TALL = 8
TALL_KEYS = ('160x600', '300x600')

SIZES = {
    '300x250': {
        'key': '300x250',
        'width': 300,
        'height': 250,
        'label': '300×250',
        'layout': 'stack',
        'qbox_width': 274,
        'thankyou_width': 300,
        'thankyou_top': 100,
        'ad_background_width': 299,
        'max_answers': MAX_ANSWERS_DEFAULT,
    },
    '160x600': {
        'key': '160x600',
        'width': 160,
        'height': 600,
        'label': '160×600',
        'layout': 'tall',
        'qbox_width': 134,
        'thankyou_width': 160,
        'thankyou_top': 240,
        'ad_background_width': 159,
        'max_answers': MAX_ANSWERS_TALL,
    },
    '300x600': {
        'key': '300x600',
        'width': 300,
        'height': 600,
        'label': '300×600',
        'layout': 'tall',
        'qbox_width': 274,
        'thankyou_width': 300,
        'thankyou_top': 240,
        'ad_background_width': 299,
        'max_answers': MAX_ANSWERS_TALL,
    },
    '336x280': {
        'key': '336x280',
        'width': 336,
        'height': 280,
        'label': '336×280',
        'layout': 'stack',
        'qbox_width': 310,
        'thankyou_width': 336,
        'thankyou_top': 110,
        'ad_background_width': 335,
        'max_answers': MAX_ANSWERS_DEFAULT,
    },
    '970x250': {
        'key': '970x250',
        'width': 970,
        'height': 250,
        'label': '970×250',
        'layout': 'wide',
        'qbox_width': 220,
        'thankyou_width': 970,
        'thankyou_top': 80,
        'ad_background_width': 969,
        'max_answers': MAX_ANSWERS_DEFAULT,
    },
}

SIZE_CHOICES = [(spec['key'], spec['label']) for spec in SIZES.values()]

_SIZE_BLOCK_RE = re.compile(
    re.escape(SIZE_START) + r'.*?' + re.escape(SIZE_END),
    re.DOTALL)
_LAYOUT_BLOCK_RE = re.compile(
    re.escape(LAYOUT_START) + r'.*?' + re.escape(LAYOUT_END),
    re.DOTALL)


def selected_keys(value=None):
  """List of valid size keys. Accepts a survey dict, a string, or a list.

  Stored single `creativesize` values still work. Unknown keys are dropped.
  Empty input becomes 300x250.
  """
  raw = value
  if isinstance(value, dict):
    raw = value.get('creativesizes')
    if raw in (None, '', []):
      raw = value.get('creativesize')
  keys = []
  if isinstance(raw, (list, tuple)):
    items = list(raw)
  else:
    items = [part.strip() for part in str(raw or '').replace(';', ',').split(',')
             if part.strip()]
  for item in items:
    if isinstance(item, dict):
      item = item.get('key') or item.get('creativesize')
    key = str(item or '').strip()
    if key in SIZES and key not in keys:
      keys.append(key)
  return keys or [DEFAULT_SIZE]


def resolve_preview(survey, requested=None):
  """Size for the View Survey page. Unknown ?size= falls back to the first key."""
  keys = selected_keys(survey)
  req = str(requested or '').strip()
  if req in keys:
    return resolve(req)
  return resolve(keys[0])


def persist_sizes(data):
  """Write both creativesizes (list) and creativesize (compat string/list)."""
  payload = dict(data or {})
  keys = selected_keys(payload)
  payload['creativesizes'] = keys
  payload['creativesize'] = keys[0] if len(keys) == 1 else keys
  return payload, keys


def max_answers(value=None):
  """8 only when every selected size is tall (160x600 / 300x600)."""
  keys = selected_keys(value)
  if keys and all(key in TALL_KEYS for key in keys):
    return MAX_ANSWERS_TALL
  return MAX_ANSWERS_DEFAULT


def resolve(value=None):
  """Return a size dict. Missing/unknown values become 300x250."""
  if isinstance(value, dict):
    if value.get('key') in SIZES and 'width' in value and 'height' in value:
      return dict(value)
    keys = selected_keys(value)
    key = keys[0]
  else:
    keys = selected_keys(value)
    key = keys[0]
  return dict(SIZES.get(key, SIZES[DEFAULT_SIZE]))


def ad_size_meta(size):
  spec = resolve(size)
  return 'width=%s,height=%s' % (spec['width'], spec['height'])


def overlay_css(size):
  spec = resolve(size)
  lines = [
      SIZE_START,
      '#master_container {',
      '  width: %spx;' % spec['width'],
      '  height: %spx;' % spec['height'],
      '}',
      '.Qbox {',
      '  width: %spx;' % spec['qbox_width'],
      '}',
      '.thankyoucontainer {',
      '  width: %spx;' % spec['thankyou_width'],
      '  top: %spx;' % spec['thankyou_top'],
      '}',
      '#ad_background {',
      '  width: %spx;' % spec['ad_background_width'],
      '}',
  ]
  if spec['layout'] == 'wide':
    lines += [
        '#master_container.layout-wide #survey_container {',
        '  display: flex;',
        '  flex-direction: row;',
        '  align-items: stretch;',
        '  gap: 8px;',
        '  padding-right: 8px;',
        '}',
        '#master_container.layout-wide .Qbox {',
        '  flex: 0 0 %spx;' % spec['qbox_width'],
        '  height: auto;',
        '  min-height: 72px;',
        '  max-height: 200px;',
        '}',
        '#master_container.layout-wide .answers-grid {',
        '  flex: 1 1 auto;',
        '  display: grid;',
        '  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));',
        '  gap: 6px;',
        '  align-content: start;',
        '  min-width: 0;',
        '}',
        '#master_container.layout-wide .Abox {',
        '  margin: 0;',
        '}',
    ]
  if spec['width'] <= 160:
    lines += [
        '#master_container.size-160x600 .AText,',
        '#master_container.size-160x600 .Qbox {',
        '  font-size: 11px;',
        '}',
    ]
  if spec['layout'] == 'tall':
    lines += [
        '#master_container.layout-tall .Qbox {',
        '  height: auto;',
        '  min-height: 36px;',
        '}',
        '#master_container.layout-tall .answers-grid {',
        '  display: flex;',
        '  flex-direction: column;',
        '}',
    ]
  lines.append(SIZE_END)
  return '\n'.join(lines)


def layout_fix_css():
  """Always injected after survey CSS so wrap/box rules win over old custom_css."""
  return '\n'.join([
      LAYOUT_START,
      '#master_container, #master_container * {',
      '  box-sizing: border-box;',
      '}',
      '#master_container {',
      '  position: relative;',
      '  overflow: hidden;',
      '  padding-bottom: 24px;',
      '}',
      '#survey_container {',
      '  max-width: 100%;',
      '  overflow: hidden;',
      '}',
      '.Qbox {',
      '  max-width: 100%;',
      '  height: auto;',
      '  min-height: 36px;',
      '  background-color: var(--sonar-panel, rgba(0, 0, 0, 0.35));',
      '}',
      '.answers-grid {',
      '  width: 100%;',
      '  max-width: 100%;',
      '}',
      '.Abox {',
      '  width: 100% !important;',
      '  max-width: 100% !important;',
      '  box-sizing: border-box !important;',
      '  height: auto !important;',
      '  overflow: hidden;',
      '}',
      '.AText {',
      '  height: auto !important;',
      '  min-height: 27px;',
      '  line-height: 1.25 !important;',
      '  overflow-wrap: anywhere !important;',
      '  word-break: break-word !important;',
      '  white-space: normal !important;',
      '  padding: 4px 6px 4px 5px !important;',
      '}',
      '.brand-badge {',
      '  position: absolute;',
      '  left: 4px;',
      '  bottom: 3px;',
      '  width: 20px;',
      '  height: 20px;',
      '  padding: 0;',
      '  margin: 0;',
      '  border: 0;',
      '  background: transparent;',
      '  opacity: 0.42;',
      '  cursor: pointer;',
      '  z-index: 40;',
      '  pointer-events: auto;',
      '  line-height: 0;',
      '  filter: drop-shadow(0 0 1px #000) drop-shadow(0 0 1px #fff);',
      '}',
      '.brand-badge.badge-kind-letter {',
      '  width: 20px;',
      '  height: 20px;',
      '  max-width: 20px;',
      '}',
      '.brand-badge.badge-kind-pill,',
      '.brand-badge.badge-kind-wordmark {',
      '  width: auto;',
      '  height: 16px;',
      '  max-width: 70px;',
      '}',
      '.brand-badge-face {',
      '  display: inline-flex;',
      '  align-items: center;',
      '  justify-content: center;',
      '  box-sizing: border-box;',
      '  height: 16px;',
      '  max-width: 70px;',
      '  padding: 0 5px;',
      '  border: 1.2px solid #111;',
      '  border-radius: 4px;',
      '  background: linear-gradient(180deg, #ffffff 0%, #d0d0d0 45%, #6a6a6a 100%);',
      '  color: #111;',
      '  font-family: Georgia, "Times New Roman", serif;',
      '  font-weight: 700;',
      '  font-size: 9px;',
      '  line-height: 1;',
      '  letter-spacing: 0.02em;',
      '  white-space: nowrap;',
      '  overflow: hidden;',
      '  text-overflow: clip;',
      '  pointer-events: none;',
      '}',
      '.brand-badge.badge-kind-wordmark .brand-badge-face {',
      '  font-size: 8px;',
      '  padding: 0 4px;',
      '  letter-spacing: 0;',
      '}',
      '#master_container.size-160x600 .brand-badge.badge-kind-pill,',
      '#master_container.size-160x600 .brand-badge.badge-kind-wordmark {',
      '  max-width: 52px;',
      '  height: 14px;',
      '}',
      '#master_container.size-160x600 .brand-badge-face {',
      '  height: 14px;',
      '  max-width: 52px;',
      '  font-size: 7px;',
      '  padding: 0 3px;',
      '}',
      '.brand-badge:hover, .brand-badge:focus, .brand-badge.is-open {',
      '  opacity: 0.92;',
      '  outline: none;',
      '}',
      '.brand-badge-tip {',
      '  display: none;',
      '  position: absolute;',
      '  left: 0;',
      '  bottom: 100%;',
      '  margin-bottom: 2px;',
      '  min-width: 120px;',
      '  max-width: 150px;',
      '  padding: 4px 6px;',
      '  background: #111;',
      '  color: #fff;',
      '  font-size: 9px;',
      '  font-family: Arial, sans-serif;',
      '  line-height: 1.25;',
      '  text-align: left;',
      '  white-space: normal;',
      '  border-radius: 3px;',
      '  pointer-events: none;',
      '  z-index: 41;',
      '}',
      '.brand-badge:hover .brand-badge-tip,',
      '.brand-badge:focus .brand-badge-tip,',
      '.brand-badge.is-open .brand-badge-tip {',
      '  display: block;',
      '}',
      LAYOUT_END,
  ])


def apply_overlay(css, size):
  """Replace any previous size block and append the overlay for this size."""
  base = _SIZE_BLOCK_RE.sub('', css or '').rstrip()
  base = _LAYOUT_BLOCK_RE.sub('', base).rstrip()
  block = overlay_css(size)
  fix = layout_fix_css()
  parts = [part for part in (base, block, fix) if part]
  return '\n\n'.join(parts) + '\n'


def inner_zip_basename(date_stamp, surveyname, size_key, suffix):
  """HTML5 inner zip filename, <= 50 characters including .zip."""
  ext = '.zip'
  slug = re.sub(r'[^A-Za-z0-9-]+', '-', (surveyname or 'survey').replace(' ', '-'))
  slug = slug.strip('-') or 's'
  size_key = size_key if size_key in SIZES else DEFAULT_SIZE
  suffix = suffix or 'creative'
  fixed = len(date_stamp) + 1 + 1 + len(size_key) + 1 + len(suffix) + len(ext)
  max_slug = max(1, INNER_ZIP_NAME_MAX - fixed)
  slug = slug[:max_slug]
  name = '%s_%s_%s_%s%s' % (date_stamp, slug, size_key, suffix, ext)
  return name[:INNER_ZIP_NAME_MAX]


def outer_zip_basename(date_stamp, surveyname, size_keys):
  slug = re.sub(r'[^A-Za-z0-9-]+', '-', (surveyname or 'survey').replace(' ', '-'))
  slug = slug.strip('-') or 'survey'
  keys = selected_keys(size_keys)
  if len(keys) == 1:
    return '%s_%s_%s.zip' % (date_stamp, slug, keys[0])
  return '%s_%s_sizes.zip' % (date_stamp, slug)
