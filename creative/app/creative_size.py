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
"""Supported display creative sizes (300x250 default, 160x600)."""
import re

DEFAULT_SIZE = '300x250'
SIZE_START = '/* SONAR_SIZE_START */'
SIZE_END = '/* SONAR_SIZE_END */'

SIZES = {
    '300x250': {
        'key': '300x250',
        'width': 300,
        'height': 250,
        'label': '300×250',
        'qbox_width': 274,
        'thankyou_width': 300,
        'thankyou_top': 100,
        'ad_background_width': 299,
    },
    '160x600': {
        'key': '160x600',
        'width': 160,
        'height': 600,
        'label': '160×600',
        'qbox_width': 134,
        'thankyou_width': 160,
        'thankyou_top': 240,
        'ad_background_width': 159,
    },
}

SIZE_CHOICES = [
    ('300x250', '300×250'),
    ('160x600', '160×600'),
]

_SIZE_BLOCK_RE = re.compile(
    re.escape(SIZE_START) + r'.*?' + re.escape(SIZE_END),
    re.DOTALL)


def resolve(value=None):
  """Return a size dict. Missing/unknown values become 300x250."""
  if isinstance(value, dict):
    if value.get('key') in SIZES and 'width' in value and 'height' in value:
      return dict(value)
    key = value.get('creativesize')
  else:
    key = value
  key = str(key or DEFAULT_SIZE).strip()
  return dict(SIZES.get(key, SIZES[DEFAULT_SIZE]))


def ad_size_meta(size):
  spec = resolve(size)
  return 'width=%s,height=%s' % (spec['width'], spec['height'])


def overlay_css(size):
  spec = resolve(size)
  return '\n'.join([
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
      SIZE_END,
  ])


def apply_overlay(css, size):
  """Replace any previous size block and append the overlay for this size."""
  base = _SIZE_BLOCK_RE.sub('', css or '').rstrip()
  block = overlay_css(size)
  if base:
    return base + '\n\n' + block + '\n'
  return block + '\n'
