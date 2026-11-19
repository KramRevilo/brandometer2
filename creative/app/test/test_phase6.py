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

import os
import unittest
from unittest import mock
import zipfile

import pandas

import brand
import creative_size
import css_theme
import reporting
import survey_service

import main


class SizeCatalogTest(unittest.TestCase):

  def test_new_sizes_and_no_leaderboard_or_mobile(self):
    keys = list(creative_size.SIZES)
    self.assertEqual(keys, ['300x250', '160x600', '300x600', '336x280', '970x250'])
    self.assertNotIn('728x90', keys)
    self.assertNotIn('320x50', keys)
    self.assertNotIn('320x100', keys)
    self.assertEqual(creative_size.SIZES['970x250']['layout'], 'wide')
    self.assertEqual(creative_size.SIZES['300x600']['layout'], 'tall')

  def test_selected_keys_legacy_string_and_list(self):
    self.assertEqual(creative_size.selected_keys({'creativesize': '160x600'}),
                     ['160x600'])
    self.assertEqual(
        creative_size.selected_keys({'creativesizes': ['300x250', '970x250']}),
        ['300x250', '970x250'])
    self.assertEqual(creative_size.selected_keys('nope'), ['300x250'])
    payload, keys = creative_size.persist_sizes({'creativesize': ['336x280']})
    self.assertEqual(keys, ['336x280'])
    self.assertEqual(payload['creativesize'], '336x280')
    self.assertEqual(payload['creativesizes'], ['336x280'])

  def test_max_answers_tall_only_when_all_sizes_are_tall(self):
    self.assertEqual(creative_size.max_answers(['160x600']), 8)
    self.assertEqual(creative_size.max_answers(['160x600', '300x600']), 8)
    self.assertEqual(creative_size.max_answers(['160x600', '300x250']), 5)
    self.assertEqual(creative_size.max_answers(['970x250']), 5)

  def test_inner_zip_name_is_at_most_50_chars(self):
    name = creative_size.inner_zip_basename(
        '20261119', 'a-very-long-survey-name-that-must-truncate',
        '970x250', 'default_control')
    self.assertLessEqual(len(name), 50)
    self.assertTrue(name.endswith('.zip'))
    self.assertIn('970x250', name)

  def test_layout_fix_overrides_fixed_atext_height(self):
    css = creative_size.apply_overlay(
        '.AText { height: 27px; line-height: 27px; }', '300x250')
    self.assertIn('SONAR_LAYOUT_START', css)
    self.assertGreater(css.rfind('height: auto !important'), css.find('height: 27px'))
    self.assertIn('overflow-wrap: anywhere', css)
    self.assertIn('word-break: break-word', css)
    self.assertIn('width: 100% !important', css)


class ZipAndHtmlTest(unittest.TestCase):

  @mock.patch.object(survey_service.survey_collection, 'add_version')
  def test_multi_size_zip_has_one_html5_zip_per_size(self, _version_mock):
    with main.app.app_context():
      filename, data = survey_service.zip_file('sid', {
        'surveyname': 'pack',
        'question1': 'Q',
        'answer1a': 'A',
        'answer1b': 'B',
        'creativesize': ['300x250', '970x250'],
    })
    self.assertIn('_sizes.zip', filename)
    outer = zipfile.ZipFile(data)
    names = sorted(outer.namelist())
    self.assertEqual(len(names), 2)
    self.assertTrue(all(name.endswith('.zip') for name in names))
    self.assertTrue(all(len(os.path.basename(name)) <= 50 for name in names))
    self.assertTrue(any('300x250' in name for name in names))
    self.assertTrue(any('970x250' in name for name in names))
    for name in names:
      inner_bytes = outer.read(name)
      inner = zipfile.ZipFile(__import__('io').BytesIO(inner_bytes))
      inner_names = inner.namelist()
      self.assertEqual(inner_names, ['index.html'])
      html = inner.read('index.html').decode('utf-8')
      self.assertNotIn('.zip', html)
      if '970x250' in name:
        self.assertIn('width=970,height=250', html)
        self.assertIn('layout-wide', html)
      else:
        self.assertIn('width=300,height=250', html)
      self.assertIn('brand-badge', html)
      self.assertIn('Survey Type Brandometer Ad - powered by Google', html)
      self.assertIn('option_container_7', html)
      self.assertIn('SONAR_LAYOUT_START', html)
      self.assertLess(len(inner_bytes), 5 * 1024 * 1024)

  def test_html_includes_badge_and_eight_slots(self):
    with main.app.app_context():
      html = survey_service.get_html_template('sid', {
          'surveyname': 'Sky',
          'question1': 'Q',
          'answer1a': 'A',
          'answer1h': 'H',
          'creativesize': '300x600',
      }, '', size='300x600')
    self.assertIn('width=300,height=600', html)
    self.assertIn('layout-tall', html)
    self.assertIn('option_container_7', html)
    self.assertIn('brand-badge', html)
    json = survey_service.get_question_json({
        'question1': 'Q',
        'answer1a': 'A',
        'answer1h': 'H',
    })
    ids = [opt['id'] for opt in json[0]['options']]
    self.assertEqual(ids, ['A', 'H'])


class PresetAndBrandTest(unittest.TestCase):

  def test_preset_groups_and_classic_first(self):
    groups = [g['id'] for g in css_theme.STYLE_PRESET_GROUPS]
    self.assertEqual(groups, ['classic', 'loud', 'complementary', 'patterns'])
    self.assertEqual(css_theme.STYLE_PRESETS[0]['id'], 'classic')
    self.assertEqual(len(css_theme.STYLE_PRESETS), 26)
    hazard = [p for p in css_theme.STYLE_PRESETS if p['id'] == 'hazard'][0]
    self.assertIn('repeating-linear-gradient', hazard['bg_pattern'])
    block = css_theme.generate_theme_block({
        'bg': '#000000',
        'bg_pattern': hazard['bg_pattern'],
        'question_color': '#FFD000',
        'answer_bg': '#FFD000',
        'answer_color': '#000000',
        'font_family': 'Arial, sans-serif',
        'font_size': '13px',
    })
    self.assertIn('--sonar-bg-pattern:', block)
    self.assertIn('--sonar-panel:', block)
    self.assertNotIn('url(', hazard['bg_pattern'])

  def test_brand_name_env_and_badge_letter(self):
    with mock.patch.dict(os.environ, {}, clear=False):
      os.environ.pop('APP_BRAND_NAME', None)
      os.environ.pop('APP_BRAND_BADGE_LETTER', None)
      self.assertEqual(brand.brand_name(), 'Brandometer')
      self.assertEqual(brand.badge_letter(), 'B')
      self.assertIn('Brandometer', brand.badge_tooltip())
    with mock.patch.dict(os.environ, {
        'APP_BRAND_NAME': 'AcmeAds',
        'APP_BRAND_BADGE_LETTER': 'Q',
    }):
      self.assertEqual(brand.brand_name(), 'AcmeAds')
      self.assertEqual(brand.badge_letter(), 'Q')

  def test_navbar_uses_brand_name(self):
    main.app.config['BASIC_AUTH_FORCE'] = False
    client = main.app.test_client()
    with mock.patch.object(
        survey_service, 'identity_suggestions',
        return_value={'clients': [], 'agencies': []}):
      response = client.get('/survey/create')
    self.assertIn(b'Brandometer', response.data)
    self.assertNotIn(b'>Sonar</a>', response.data)
    main.app.config['BASIC_AUTH_FORCE'] = True

  def test_reporting_includes_answer_h(self):
    df = pandas.DataFrame({
        'CreatedAt': pandas.to_datetime(['2026-11-19'] * 2),
        'Segmentation': ['', ''],
        'Response': ['1:A', '1:H'],
        'BomID': ['a', 'b'],
    })
    report = reporting.build_report(df, {
        'question1': 'Q',
        'answer1a': 'Yes',
        'answer1h': 'Eighth',
    }, is_lift=False)
    ids = [ans['id'] for ans in report['questions'][0]['answers']]
    self.assertEqual(ids, ['A', 'H'])
    self.assertEqual(report['questions'][0]['answers'][1]['text'], 'Eighth')
