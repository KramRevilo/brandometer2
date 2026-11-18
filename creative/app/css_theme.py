# Copyright 2023 Google LLC
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
"""Parse and generate the Sonar theme block stored in custom_css."""
import re

THEME_START = '/* SONAR_THEME_START */'
THEME_END = '/* SONAR_THEME_END */'

FONT_CHOICES = [
    ("'Open Sans', sans-serif", 'Open Sans'),
    ('Arial, Helvetica, sans-serif', 'Arial'),
    ('Helvetica, Arial, sans-serif', 'Helvetica'),
    ('Verdana, Geneva, sans-serif', 'Verdana'),
    ('Tahoma, Geneva, sans-serif', 'Tahoma'),
    ('Trebuchet MS, Helvetica, sans-serif', 'Trebuchet MS'),
    ('Georgia, serif', 'Georgia'),
    ("'Times New Roman', Times, serif", 'Times New Roman'),
    ("'Courier New', Courier, monospace", 'Courier New'),
    ('system-ui, sans-serif', 'System UI'),
]

DEFAULT_THEME = {
    'bg': '#008000',
    'question_color': '#ffffff',
    'answer_bg': 'rgba(255, 255, 255, 0.149)',
    'answer_color': '#ffffff',
    'font_family': "'Open Sans', sans-serif",
    'font_size': '13px',
    'bg_image': '',
}

_NAMED_COLORS = {
    'white': '#ffffff',
    'black': '#000000',
    'beige': '#f5f5dc',
    'red': '#ff0000',
    'green': '#008000',
    'blue': '#0000ff',
    'navy': '#000080',
    'teal': '#008080',
    'silver': '#c0c0c0',
    'gray': '#808080',
    'grey': '#808080',
    'maroon': '#800000',
    'purple': '#800080',
    'olive': '#808000',
    'lime': '#00ff00',
    'aqua': '#00ffff',
    'orange': '#ffa500',
}

_THEME_BLOCK_RE = re.compile(
    re.escape(THEME_START) + r'.*?' + re.escape(THEME_END),
    re.DOTALL)


def strip_theme_block(css):
  if not css:
    return ''
  return _THEME_BLOCK_RE.sub('', css).strip()


def _sanitize_url(url):
  if not url:
    return ''
  cleaned = url.strip().strip('\'"')
  cleaned = cleaned.replace('\\', '').replace(')', '').replace('(', '')
  if cleaned.lower().startswith(('https://', 'http://', '//')):
    return cleaned
  return ''


def _css_image_value(url):
  safe = _sanitize_url(url)
  if not safe:
    return 'none'
  return 'url("%s")' % safe.replace('"', '')


def generate_theme_block(theme):
  """Return the SONAR_THEME block for picker values."""
  t = dict(DEFAULT_THEME)
  t.update(theme or {})
  image_value = _css_image_value(t.get('bg_image') or '')
  return '\n'.join([
      THEME_START,
      ':root {',
      '  --sonar-bg: %s;' % t['bg'],
      '  --sonar-question-color: %s;' % t['question_color'],
      '  --sonar-answer-bg: %s;' % t['answer_bg'],
      '  --sonar-answer-color: %s;' % t['answer_color'],
      '  --sonar-font-family: %s;' % t['font_family'],
      '  --sonar-font-size: %s;' % t['font_size'],
      '  --sonar-bg-image: %s;' % image_value,
      '}',
      '#master_container {',
      '  background-color: var(--sonar-bg);',
      '  background-image: var(--sonar-bg-image);',
      '  background-size: cover;',
      '  background-position: center;',
      '}',
      '.Qbox {',
      '  color: var(--sonar-question-color);',
      '  font-family: var(--sonar-font-family);',
      '  font-size: var(--sonar-font-size);',
      '}',
      '.Abox {',
      '  background-color: var(--sonar-answer-bg);',
      '}',
      '.AText, #next_button {',
      '  color: var(--sonar-answer-color);',
      '  font-family: var(--sonar-font-family);',
      '}',
      '.AText {',
      '  font-size: var(--sonar-font-size);',
      '}',
      THEME_END,
  ])


def combine_css(theme, extra_css):
  extra = strip_theme_block(extra_css or '')
  block = generate_theme_block(theme)
  if extra:
    return extra.rstrip() + '\n\n' + block + '\n'
  return block + '\n'


def _var(block, name):
  match = re.search(
      r'--sonar-' + re.escape(name) + r'\s*:\s*([^;]+);', block)
  if not match:
    return None
  return match.group(1).strip()


def _image_url_from_css_value(value):
  if not value or value.strip().lower() == 'none':
    return ''
  match = re.search(r'url\(\s*[\'"]?([^\'")]+)[\'"]?\s*\)', value, re.I)
  if not match:
    return ''
  return _sanitize_url(match.group(1))


def parse_theme_block(block):
  theme = dict(DEFAULT_THEME)
  mapping = {
      'bg': 'bg',
      'question-color': 'question_color',
      'answer-bg': 'answer_bg',
      'answer-color': 'answer_color',
      'font-family': 'font_family',
      'font-size': 'font_size',
  }
  for css_name, key in mapping.items():
    value = _var(block, css_name)
    if value:
      theme[key] = value
  image = _var(block, 'bg-image')
  if image is not None:
    theme['bg_image'] = _image_url_from_css_value(image)
  return theme


def _rule_body(css, selector):
  pattern = re.compile(
      re.escape(selector) + r'\s*\{([^{}]*)\}', re.I | re.DOTALL)
  match = pattern.search(css or '')
  if not match:
    return ''
  return match.group(1)


def _declaration(body, property_name):
  match = re.search(
      r'(?:^|;)\s*' + re.escape(property_name) + r'\s*:\s*([^;]+);',
      ';' + (body or ''),
      re.I)
  if not match:
    return None
  return match.group(1).strip()


def normalize_color(value):
  """Return a CSS color string suitable for pickers when possible."""
  if not value:
    return value
  raw = value.strip()
  lower = raw.lower()
  if lower in _NAMED_COLORS:
    return _NAMED_COLORS[lower]
  hex_match = re.fullmatch(r'#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})', raw)
  if hex_match:
    hex_value = hex_match.group(1)
    if len(hex_value) == 3:
      hex_value = ''.join(ch * 2 for ch in hex_value)
    return '#' + hex_value.lower()
  rgb = re.fullmatch(
      r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([0-9.]+))?\s*\)',
      raw, re.I)
  if rgb:
    red, green, blue = (int(rgb.group(i)) for i in (1, 2, 3))
    alpha = rgb.group(4)
    if alpha is None or float(alpha) >= 0.999:
      return '#%02x%02x%02x' % (red, green, blue)
    return 'rgba(%d, %d, %d, %s)' % (red, green, blue, alpha)
  return raw


def parse_legacy_theme(css):
  """Best-effort picker values from pre-theme custom_css."""
  theme = dict(DEFAULT_THEME)
  master = _rule_body(css, '#master_container')
  qbox = _rule_body(css, '.Qbox')
  abox = _rule_body(css, '.Abox')
  atext = _rule_body(css, '.AText')
  bg = _declaration(master, 'background-color')
  if bg:
    theme['bg'] = normalize_color(bg) or bg
  image = _declaration(master, 'background-image')
  if image:
    theme['bg_image'] = _image_url_from_css_value(image)
  q_color = _declaration(qbox, 'color')
  if q_color:
    theme['question_color'] = normalize_color(q_color) or q_color
  font_family = _declaration(qbox, 'font-family') or _declaration(atext, 'font-family')
  if font_family:
    theme['font_family'] = font_family
  font_size = _declaration(qbox, 'font-size') or _declaration(atext, 'font-size')
  if font_size:
    theme['font_size'] = font_size
  answer_bg = _declaration(abox, 'background-color')
  if answer_bg:
    theme['answer_bg'] = normalize_color(answer_bg) or answer_bg
  answer_color = _declaration(atext, 'color')
  if answer_color:
    theme['answer_color'] = normalize_color(answer_color) or answer_color
  return theme


def parse_theme_css(css):
  """Split custom_css into picker theme values and leftover extra CSS.

  Known SONAR_THEME values fill the pickers. Everything else, including
  old free-form rules, is returned as extra so it is not dropped.
  """
  css = css or ''
  match = _THEME_BLOCK_RE.search(css)
  if match:
    extra = strip_theme_block(css)
    theme = parse_theme_block(match.group(0))
    return {'theme': theme, 'extra': extra, 'had_theme_block': True}
  return {
      'theme': parse_legacy_theme(css),
      'extra': css.strip(),
      'had_theme_block': False,
  }
