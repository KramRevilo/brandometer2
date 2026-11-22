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
"""Product brand for the admin UI and the creative disclosure badge."""
import os
import re

DEFAULT_BRAND_NAME = 'Brandometer2'
DEFAULT_BADGE_ICON = 'B'
BADGE_TEXT_MAX = 120
BADGE_NAME_MAX = 40
BADGE_NAME_ICON = 'Name'

# Registry of disclosure-badge faces. Add new keys here (including an official
# uploaded SVG later via the reserved `svg` field). `kind` is `letter` (20×20
# bevelled square), `pill` (compact rounded-rect), `wordmark` (plain-text pill),
# or `svg` (trusted markup in `svg`).
BADGE_ICONS = {
    'B': {
        'id': 'B',
        'label': 'B',
        'kind': 'letter',
        'mark': None,
        'svg': None,
    },
    'B2': {
        'id': 'B2',
        'label': 'B2',
        'kind': 'pill',
        'mark': 'B2',
        'svg': None,
    },
    'Ad': {
        'id': 'Ad',
        'label': 'Ad',
        'kind': 'pill',
        'mark': 'Ad',
        'svg': None,
    },
    BADGE_NAME_ICON: {
        'id': BADGE_NAME_ICON,
        'label': 'Name',
        'kind': 'wordmark',
        'mark': 'Name',
        'svg': None,
    },
}


def brand_name():
  value = (os.environ.get('APP_BRAND_NAME') or DEFAULT_BRAND_NAME).strip()
  return value or DEFAULT_BRAND_NAME


def badge_letter():
  override = (os.environ.get('APP_BRAND_BADGE_LETTER') or '').strip()
  if override:
    return override[0].upper()
  name = brand_name()
  return name[0].upper() if name else 'B'


def badge_tooltip():
  override = (os.environ.get('APP_BRAND_BADGE_TOOLTIP') or '').strip()
  if override:
    return override
  return 'Survey Type %s Ad - powered by Google' % brand_name()


def badge_icon_list():
  return list(BADGE_ICONS.values())


def badge_icon_choices():
  return [(opt['id'], opt['label']) for opt in badge_icon_list()]


def resolve_badge_icon(value):
  key = (value or '').strip()
  if key in BADGE_ICONS:
    return dict(BADGE_ICONS[key])
  # Legacy wordmark ids (removed vendor labels) still render as Name.
  if key:
    return dict(BADGE_ICONS[BADGE_NAME_ICON])
  return dict(BADGE_ICONS[DEFAULT_BADGE_ICON])


def sanitize_badge_name(value):
  text = '' if value is None else str(value)
  text = re.sub(r'<[^>]*>', '', text)
  text = re.sub(r'[\x00-\x1f\x7f]', '', text)
  text = text.replace('<', '').replace('>', '')
  text = re.sub(r'\s+', ' ', text).strip()
  return text[:BADGE_NAME_MAX]


def resolve_badge_name(survey=None):
  data = survey if isinstance(survey, dict) else {}
  name = sanitize_badge_name(data.get('badge_name'))
  if name:
    return name
  return sanitize_badge_name(data.get('agency'))


def resolve_badge_text(value):
  text = (value or '').strip()
  if not text:
    return badge_tooltip()
  return text[:BADGE_TEXT_MAX]


def badge_for_survey(survey=None):
  """Resolved icon + tooltip for a survey dict (missing/blank = current defaults)."""
  data = survey if isinstance(survey, dict) else {}
  icon = resolve_badge_icon(data.get('badge_icon'))
  name = resolve_badge_name(data)
  if icon['kind'] == 'wordmark':
    mark = name or 'Ad'
  else:
    mark = icon.get('mark') or badge_letter()
  return {
      'id': icon['id'],
      'kind': icon['kind'],
      'label': icon['label'],
      'mark': mark,
      'svg': icon.get('svg'),
      'tooltip': resolve_badge_text(data.get('badge_text')),
      'name': name,
  }


def badge_render_vars(survey=None):
  spec = badge_for_survey(survey)
  return {
      'badge_icon': spec['id'],
      'badge_kind': spec['kind'],
      'badge_mark': spec['mark'],
      'badge_letter': spec['mark'] if spec['kind'] == 'letter' else badge_letter(),
      'badge_tooltip': spec['tooltip'],
      'badge_svg': spec.get('svg'),
  }


def persist_badge(data):
  """Normalise badge_icon / badge_text / badge_name on a survey payload."""
  payload = dict(data or {})
  payload['badge_icon'] = resolve_badge_icon(payload.get('badge_icon'))['id']
  text = (payload.get('badge_text') or '').strip()
  payload['badge_text'] = text[:BADGE_TEXT_MAX]
  name = sanitize_badge_name(payload.get('badge_name'))
  if not name:
    name = sanitize_badge_name(payload.get('agency'))
  payload['badge_name'] = name
  return payload
