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

import creative_size
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
    self.assertIn('--bv2-bg-image: none;', block)
    self.assertNotIn('javascript:', block)

  def test_theme_and_layout_style_separate_answer_boxes(self):
    block = css_theme.generate_theme_block(css_theme.DEFAULT_THEME)
    self.assertIn('border: 1px solid rgba(0, 0, 0, 0.35)', block)
    self.assertIn('padding: 3px 15px', block)
    self.assertIn('#ad_text {', block)
    layout = creative_size.layout_fix_css()
    self.assertIn('gap: 6px', layout)
    self.assertIn('border: 1px solid rgba(0, 0, 0, 0.35)', layout)
    self.assertIn('#next_button {', layout)
    self.assertIn('Arial, Helvetica, sans-serif', layout)

  def test_generated_theme_uses_bv2_variables_and_sentinels(self):
    block = css_theme.generate_theme_block(css_theme.DEFAULT_THEME)
    self.assertTrue(block.startswith(css_theme.THEME_START))
    self.assertIn('/* BV2_THEME_START */', block)
    self.assertIn('/* BV2_THEME_END */', block)
    for name in (
        '--bv2-bg:', '--bv2-question-color:', '--bv2-answer-bg:',
        '--bv2-answer-color:', '--bv2-font-family:', '--bv2-font-size:',
        '--bv2-bg-image:', '--bv2-bg-pattern:', '--bv2-bg-pattern-size:',
        '--bv2-panel:', '--bv2-accent:',
        'var(--bv2-bg)', 'var(--bv2-accent)',
    ):
      self.assertIn(name, block)

  def test_normalize_named_and_rgb_colors(self):
    self.assertEqual(css_theme.normalize_color('white'), '#ffffff')
    self.assertEqual(css_theme.normalize_color('#08F'), '#0088ff')
    self.assertEqual(css_theme.normalize_color('rgb(0, 128, 0)'), '#008000')

  def test_sanitize_user_css_strips_style_breakout_and_import(self):
    dirty = '</style><script>alert(1)</script> @import url("x"); url(javascript:alert(1)); .A { color: red; }'
    clean = css_theme.sanitize_user_css(dirty)
    self.assertNotIn('</style', clean.lower())
    self.assertNotIn('<', clean)
    self.assertNotIn('@import', clean.lower())
    self.assertNotIn('javascript:', clean.lower())
    self.assertIn('.A { color: red; }', clean)

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
    self.assertIn('/* BV2_THEME_START */', source)
    self.assertIn('--bv2-bg:', source)
    self.assertIn('var(--bv2-accent)', source)
    self.assertIn('border: 1px solid rgba(0, 0, 0, 0.35)', source)
    self.assertIn('#next_button', source)
