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

import unittest

import css_theme
from forms import DEFAULT_CSS


class CssThemeTest(unittest.TestCase):

  def test_generate_parse_round_trip(self):
    theme = {
        'bg': '#123456',
        'question_color': '#abcdef',
        'answer_bg': 'rgba(10, 20, 30, 0.4)',
        'answer_color': '#ffffff',
        'font_family': 'Georgia, serif',
        'font_size': '16px',
        'bg_image': 'https://example.com/bg.png',
    }
    extra = '.foo { color: pink; }\n#next_button { top: 4px; }'
    combined = css_theme.combine_css(theme, extra)
    parsed = css_theme.parse_theme_css(combined)

    self.assertTrue(parsed['had_theme_block'])
    self.assertEqual(parsed['theme']['bg'], '#123456')
    self.assertEqual(parsed['theme']['question_color'], '#abcdef')
    self.assertEqual(parsed['theme']['answer_bg'], 'rgba(10, 20, 30, 0.4)')
    self.assertEqual(parsed['theme']['answer_color'], '#ffffff')
    self.assertEqual(parsed['theme']['font_family'], 'Georgia, serif')
    self.assertEqual(parsed['theme']['font_size'], '16px')
    self.assertEqual(parsed['theme']['bg_image'], 'https://example.com/bg.png')
    self.assertIn('.foo { color: pink; }', parsed['extra'])
    self.assertIn('#next_button { top: 4px; }', parsed['extra'])
    self.assertNotIn(css_theme.THEME_START, parsed['extra'])

  def test_old_freeform_css_is_preserved(self):
    custom = DEFAULT_CSS + '\n.custom-rule { outline: 2px solid orange; }\n'
    parsed = css_theme.parse_theme_css(custom)

    self.assertFalse(parsed['had_theme_block'])
    self.assertEqual(parsed['theme']['bg'], '#008000')
    self.assertEqual(parsed['theme']['question_color'], '#ffffff')
    self.assertIn('.custom-rule { outline: 2px solid orange; }', parsed['extra'])
    self.assertIn('.Qbox', parsed['extra'])

    combined = css_theme.combine_css(parsed['theme'], parsed['extra'])
    self.assertIn('.custom-rule { outline: 2px solid orange; }', combined)
    self.assertIn('.Qbox', combined)
    self.assertIn(css_theme.THEME_START, combined)

    again = css_theme.parse_theme_css(combined)
    self.assertIn('.custom-rule { outline: 2px solid orange; }', again['extra'])
    self.assertNotIn(css_theme.THEME_START, again['extra'])

  def test_combine_does_not_duplicate_theme_block(self):
    first = css_theme.combine_css(css_theme.DEFAULT_THEME, DEFAULT_CSS)
    second = css_theme.combine_css(
        css_theme.DEFAULT_THEME, first)
    self.assertEqual(second.count(css_theme.THEME_START), 1)
    self.assertEqual(second.count(css_theme.THEME_END), 1)

  def test_javascript_url_is_rejected(self):
    block = css_theme.generate_theme_block({
        'bg_image': 'javascript:alert(1)'
    })
    self.assertIn('--sonar-bg-image: none;', block)
    self.assertNotIn('javascript:', block)

  def test_normalize_named_and_rgb_colors(self):
    self.assertEqual(css_theme.normalize_color('white'), '#ffffff')
    self.assertEqual(css_theme.normalize_color('#08F'), '#0088ff')
    self.assertEqual(css_theme.normalize_color('rgb(0, 128, 0)'), '#008000')

  def test_live_preview_script_fits_creative_in_iframe(self):
    with open('static/survey-editor.js', encoding='utf-8') as handle:
      source = handle.read()
    self.assertIn('overflow:hidden!important', source)
    self.assertIn('margin:0!important', source)
    self.assertIn('box-sizing:border-box', source)
    self.assertIn('currentSize', source)
    self.assertIn('px!important', source)
    self.assertIn('applyPreset', source)
    self.assertIn("['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']", source)
    self.assertIn('syncNextTargets', source)
    self.assertIn('End survey', source)
