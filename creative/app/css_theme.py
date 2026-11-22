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
"""Parse and generate the theme block stored in custom_css."""
import re

THEME_START = '/* BV2_THEME_START */'
THEME_END = '/* BV2_THEME_END */'

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
    'answer_bg': '#ffc800',
    'answer_color': '#1a1400',
    'font_family': "'Open Sans', sans-serif",
    'font_size': '13px',
    'bg_image': '',
    'accent': '#ffc800',
    'panel': 'rgba(0, 0, 0, 0.35)',
    'bg_pattern': 'none',
}


def _preset(preset_id, label, bg, accent, text, button_bg, button_text,
            pattern='none', font_size='13'):
  return {
      'id': preset_id,
      'label': label,
      'bg': bg,
      'accent': accent,
      'question_color': text,
      'answer_bg': button_bg,
      'answer_bg_opacity': 100,
      'answer_color': button_text,
      'font_family': "'Open Sans', sans-serif",
      'font_size': font_size,
      'bg_image': '',
      'panel': 'rgba(0, 0, 0, 0.42)',
      'bg_pattern': pattern,
      'swatch': [bg, accent, button_bg],
  }


_STRIPES_HAZARD = (
    'repeating-linear-gradient(45deg,#000000 0 12px,#FFD000 12px 24px)')
_STRIPES_NEON = (
    'repeating-linear-gradient(45deg,rgba(17,255,0,0.18) 0 10px,transparent 10px 20px)')
_CHECK_LIME = 'repeating-conic-gradient(#000000 0% 25%, #B8FF00 0% 50%)'
_CHECK_MAGENTA = 'repeating-conic-gradient(#120012 0% 25%, #FF00AA 0% 50%)'
_DOTS_WHITE = (
    'radial-gradient(#FFFFFF 1.15px, transparent 1.4px)')
_DOTS_YELLOW = (
    'radial-gradient(#FFE600 1.15px, transparent 1.4px)')


STYLE_PRESET_GROUPS = [
    {
        'id': 'classic',
        'label': 'Classic',
        'presets': [
            _preset('classic', 'Classic green', '#008000', '#FFC800', '#FFFFFF',
                    '#FFC800', '#1A1400'),
            _preset('dark', 'Dark', '#1A1A1A', '#F5F5F5', '#F5F5F5',
                    '#FFFFFF', '#1A1A1A'),
            _preset('contrast', 'High contrast', '#000000', '#FFFF00', '#FFFF00',
                    '#FFFFFF', '#000000', font_size='14'),
            _preset('ocean', 'Ocean', '#0B3D91', '#E8F4FF', '#FFFFFF',
                    '#FFFFFF', '#0B3D91'),
        ],
    },
    {
        'id': 'loud',
        'label': 'Loud solids',
        'presets': [
            _preset('electric-lime', 'Electric lime', '#111111', '#11FF00',
                    '#C6FF00', '#11FF00', '#111111'),
            _preset('neon-magenta', 'Neon magenta', '#120012', '#FF00AA',
                    '#FF7AD4', '#FF00AA', '#120012'),
            _preset('hot-pink', 'Hot pink punch', '#1A0010', '#FF1493',
                    '#FF1493', '#FF1493', '#1A0010'),
            _preset('safety-orange', 'Safety orange', '#1A0A00', '#FF5A00',
                    '#FF5A00', '#FF5A00', '#1A0A00'),
            _preset('school-bus', 'School bus yellow', '#FFD000', '#1A1400',
                    '#1A1400', '#1A1400', '#FFD000'),
            _preset('cyber-yellow', 'Cyber yellow', '#000000', '#FFE600',
                    '#FFE600', '#FFE600', '#000000'),
            _preset('electric-cyan', 'Electric cyan', '#001018', '#00E5FF',
                    '#00E5FF', '#00E5FF', '#001018'),
            _preset('chartreuse', 'Chartreuse shock', '#B6FF00', '#111111',
                    '#111111', '#111111', '#B6FF00'),
            _preset('fire-engine', 'Fire-engine red', '#D00000', '#FFD000',
                    '#FFFFFF', '#FFD000', '#111111'),
        ],
    },
    {
        'id': 'complementary',
        'label': 'Complementary',
        'presets': [
            _preset('royal-blue', 'Royal blue shock', '#000C24', '#FFB000',
                    '#66B3FF', '#FFB000', '#000C24'),
            _preset('ultraviolet', 'Ultraviolet', '#0A0018', '#7A00FF',
                    '#E0C2FF', '#7A00FF', '#FFFFFF'),
            _preset('crimson', 'Crimson flare', '#140004', '#E0002A',
                    '#FFFFFF', '#FFD000', '#140004'),
            _preset('lime-magenta', 'Lime and magenta', '#051405', '#FF00E5',
                    '#B8FF00', '#FF00E5', '#FFFFFF'),
            _preset('navy-orange', 'Navy and orange', '#001A4D', '#FF6A00',
                    '#FFFFFF', '#FF6A00', '#001A4D'),
            _preset('blood-cyan', 'Blood red and cyan', '#3B0000', '#00FFF0',
                    '#00FFF0', '#00FFF0', '#3B0000'),
            _preset('purple-yellow', 'Purple and yellow', '#3B0066', '#FFE600',
                    '#FFE600', '#FFE600', '#3B0066'),
        ],
    },
    {
        'id': 'patterns',
        'label': 'Patterns',
        'presets': [
            _preset('hazard', 'Hazard stripes', '#000000', '#FFD000', '#FFD000',
                    '#FFD000', '#000000', pattern=_STRIPES_HAZARD),
            _preset('neon-stripes', 'Neon green stripes', '#0A0A0A', '#11FF00',
                    '#C6FF00', '#11FF00', '#0A0A0A', pattern=_STRIPES_NEON),
            _preset('lime-checkers', 'Lime checkers', '#000000', '#B8FF00',
                    '#B8FF00', '#B8FF00', '#000000', pattern=_CHECK_LIME),
            _preset('magenta-checkers', 'Magenta checkers', '#120012', '#FF00AA',
                    '#FF7AD4', '#FF00AA', '#120012', pattern=_CHECK_MAGENTA),
            _preset('white-dots', 'White dots on navy', '#001F4D', '#FFFFFF',
                    '#FFFFFF', '#FFFFFF', '#001F4D', pattern=_DOTS_WHITE),
            _preset('yellow-dots', 'Yellow dots on black', '#000000', '#FFE600',
                    '#FFE600', '#FFE600', '#000000', pattern=_DOTS_YELLOW),
        ],
    },
]

STYLE_PRESETS = [
    preset for group in STYLE_PRESET_GROUPS for preset in group['presets']
]

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


def sanitize_user_css(css):
  """Strip HTML/CSS constructs that can break out of a <style> tag.

  Removes ``</style``, ``<``, ``@import``, and ``url(javascript:``. Remaining
  CSS is safe to emit in a style element without Jinja |safe on raw input.
  """
  text = '' if css is None else str(css)
  text = re.sub(r'</style', '', text, flags=re.IGNORECASE)
  text = text.replace('<', '')
  text = re.sub(r'@import', '', text, flags=re.IGNORECASE)
  text = re.sub(r'url\s*\(\s*javascript\s*:', '', text, flags=re.IGNORECASE)
  return text


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


def _pattern_value(value):
  raw = (value or '').strip()
  if not raw or raw.lower() == 'none':
    return 'none'
  if 'url(' in raw.lower() or 'javascript:' in raw.lower():
    return 'none'
  return raw


def generate_theme_block(theme):
  """Return the theme block for picker values."""
  t = dict(DEFAULT_THEME)
  t.update(theme or {})
  image_value = _css_image_value(t.get('bg_image') or '')
  pattern_value = _pattern_value(t.get('bg_pattern') or 'none')
  if 'conic-gradient' in pattern_value:
    pattern_size = '16px 16px'
  elif 'radial-gradient' in pattern_value:
    pattern_size = '10px 10px'
  else:
    pattern_size = 'auto'
  panel = t.get('panel') or DEFAULT_THEME['panel']
  accent = t.get('accent') or t.get('answer_bg') or DEFAULT_THEME['accent']
  return '\n'.join([
      THEME_START,
      ':root {',
      '  --bv2-bg: %s;' % t['bg'],
      '  --bv2-question-color: %s;' % t['question_color'],
      '  --bv2-answer-bg: %s;' % t['answer_bg'],
      '  --bv2-answer-color: %s;' % t['answer_color'],
      '  --bv2-font-family: %s;' % t['font_family'],
      '  --bv2-font-size: %s;' % t['font_size'],
      '  --bv2-bg-image: %s;' % image_value,
      '  --bv2-bg-pattern: %s;' % pattern_value,
      '  --bv2-bg-pattern-size: %s;' % pattern_size,
      '  --bv2-panel: %s;' % panel,
      '  --bv2-accent: %s;' % accent,
      '}',
      '#master_container {',
      '  background-color: var(--bv2-bg);',
      '  background-image: var(--bv2-bg-image), var(--bv2-bg-pattern);',
      '  background-size: cover, var(--bv2-bg-pattern-size);',
      '  background-position: center, 0 0;',
      '}',
      '.Qbox {',
      '  color: var(--bv2-question-color);',
      '  font-family: var(--bv2-font-family);',
      '  font-size: var(--bv2-font-size);',
      '  background-color: var(--bv2-panel);',
      '}',
      '.Abox {',
      '  background-color: var(--bv2-answer-bg);',
      '  border: 1px solid rgba(0, 0, 0, 0.35);',
      '  border-radius: 5px;',
      '  margin: 0;',
      '  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.18);',
      '}',
      '.AText, #next_button {',
      '  color: var(--bv2-answer-color);',
      '  font-family: var(--bv2-font-family);',
      '}',
      '.AText {',
      '  font-size: var(--bv2-font-size);',
      '}',
      '#next_button {',
      '  background-color: var(--bv2-accent);',
      '  padding: 3px 15px;',
      '  border: 1px solid rgba(0, 0, 0, 0.28);',
      '  border-radius: 4px;',
      '  display: inline-block;',
      '}',
      '#ad_text {',
      '  font-family: Arial, Helvetica, sans-serif;',
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
      r'--bv2-' + re.escape(name) + r'\s*:\s*([^;]+);', block)
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
      'panel': 'panel',
      'accent': 'accent',
  }
  for css_name, key in mapping.items():
    value = _var(block, css_name)
    if value:
      theme[key] = value
  image = _var(block, 'bg-image')
  if image is not None:
    theme['bg_image'] = _image_url_from_css_value(image)
  pattern = _var(block, 'bg-pattern')
  if pattern is not None:
    theme['bg_pattern'] = pattern
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

  Known theme-block values fill the pickers. Everything else, including
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
