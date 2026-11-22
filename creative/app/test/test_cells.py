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

import datetime
import unittest
from unittest import mock

import pandas

import cells
import reporting
import survey_service


class CellsModuleTest(unittest.TestCase):

  def test_defaults_match_today_zips(self):
    lift = cells.default_cells('brand_lift')
    self.assertEqual([c['id'] for c in lift], [
        'default_control', 'default_expose'])
    self.assertEqual([c['role'] for c in lift], ['control', 'expose'])
    self.assertEqual(cells.default_cells('brand_track'), [])
    self.assertEqual(cells.zip_seg_ids({'surveytype': 'brand_lift'}), [
        'default_control', 'default_expose'])
    self.assertEqual(cells.zip_seg_ids({'surveytype': 'brand_track'}), [''])

  def test_zip_uses_stored_cell_ids(self):
    survey = {
        'surveytype': 'brand_lift',
        'cells': [
            {'id': 'ctrl_a', 'label': 'Control A', 'role': 'control'},
            {'id': 'exp_a', 'label': 'Expose A', 'role': 'expose'},
            {'id': 'exp_b', 'label': 'Expose B', 'role': 'expose'},
            {'id': 'hold_a', 'label': 'Holdout', 'role': 'holdout'},
        ],
    }
    self.assertEqual(cells.zip_seg_ids(survey), [
        'ctrl_a', 'exp_a', 'exp_b', 'hold_a'])

  def test_validate_lift_needs_control_and_expose(self):
    errors = cells.validate(
        [{'id': 'only_c', 'label': 'C', 'role': 'control'}], 'brand_lift')
    self.assertTrue(any('expose' in err for err in errors))
    ok = cells.default_cells('brand_lift')
    self.assertEqual(cells.validate(ok, 'brand_lift'), [])

  def test_validate_rejects_bad_ids(self):
    errors = cells.validate(
        [{'id': 'bad id', 'label': 'X', 'role': 'other'}], 'brand_track')
    self.assertTrue(errors)

  def test_role_lookup_beats_substring_fallback(self):
    stored = [
        {'id': 'north', 'label': 'North', 'role': 'control'},
        {'id': 'south_control_lookalike', 'label': 'South', 'role': 'expose'},
        {'id': 'hold_pool', 'label': 'Hold', 'role': 'holdout'},
    ]
    self.assertEqual(cells.role_for_seg('north', stored), 'control')
    self.assertEqual(cells.role_for_seg('south_control_lookalike', stored), 'expose')
    self.assertEqual(cells.role_for_seg('hold_pool', stored), 'holdout')
    self.assertEqual(cells.lift_role('hold_pool', stored), 'other')
    self.assertEqual(cells.role_for_seg('default_control'), 'control')
    self.assertEqual(cells.role_for_seg('seg1'), 'other')

  def test_persist_applies_defaults_and_strips_json(self):
    lift = cells.persist({'surveytype': 'brand_lift', 'surveyname': 'x'})
    self.assertEqual(lift['cells'][0]['id'], 'default_control')
    self.assertNotIn('cells_json', lift)
    track = cells.persist({'surveytype': 'brand_track', 'cells_json': '[]'})
    self.assertEqual(track['cells'], [])

  def test_preview_seg_uses_requested_cell(self):
    survey = {
        'surveytype': 'brand_lift',
        'cells': cells.default_cells('brand_lift'),
    }
    self.assertEqual(
        cells.resolve_preview_seg(survey, 'default_expose'), 'default_expose')
    self.assertEqual(
        cells.resolve_preview_seg(survey, 'missing'), 'default_control')
    self.assertEqual(
        cells.resolve_preview_seg({'surveytype': 'brand_track'}, ''), 'preview')


class CellsReportTest(unittest.TestCase):

  def test_holdout_excluded_from_primary_lift(self):
    t = datetime.datetime(2026, 11, 18)
    df = pandas.DataFrame({
        'CreatedAt': [t] * 6,
        'Segmentation': [
            'ctrl', 'ctrl', 'exp', 'exp', 'hold', 'hold'],
        'Response': ['1:A', '1:B', '1:A', '1:A', '1:A', '1:A'],
        'BomID': ['c1', 'c2', 'e1', 'e2', 'h1', 'h2'],
    })
    survey = {
        'question1': 'Aware?',
        'answer1a': 'Yes',
        'answer1b': 'No',
        'surveytype': 'brand_lift',
        'cells': [
            {'id': 'ctrl', 'label': 'Control', 'role': 'control'},
            {'id': 'exp', 'label': 'Exposed', 'role': 'expose'},
            {'id': 'hold', 'label': 'Holdout', 'role': 'holdout'},
        ],
    }
    report = reporting.build_report(df, survey, is_lift=True)
    self.assertEqual(report['control_n'], 2)
    self.assertEqual(report['expose_n'], 2)
    self.assertEqual(report['n_total'], 6)
    self.assertFalse(report['cell_comparisons'])
    yes = report['questions'][0]['answers'][0]
    self.assertEqual(yes['k_control'], 1)
    self.assertEqual(yes['k_expose'], 2)

  def test_extra_expose_cells_holm(self):
    t = datetime.datetime(2026, 11, 18)
    segs = (['ctrl'] * 4) + (['exp_a'] * 4) + (['exp_b'] * 4)
    responses = (
        ['1:A', '1:B', '1:B', '1:B']
        + ['1:A', '1:A', '1:A', '1:B']
        + ['1:A', '1:A', '1:B', '1:B'])
    df = pandas.DataFrame({
        'CreatedAt': [t] * 12,
        'Segmentation': segs,
        'Response': responses,
        'BomID': ['r%s' % i for i in range(12)],
    })
    survey = {
        'question1': 'Aware?',
        'answer1a': 'Yes',
        'answer1b': 'No',
        'surveytype': 'brand_lift',
        'cells': [
            {'id': 'ctrl', 'label': 'Control', 'role': 'control'},
            {'id': 'exp_a', 'label': 'Expose A', 'role': 'expose'},
            {'id': 'exp_b', 'label': 'Expose B', 'role': 'expose'},
        ],
    }
    report = reporting.build_report(df, survey, is_lift=True)
    self.assertEqual(report['control_n'], 4)
    self.assertEqual(report['expose_n'], 8)
    self.assertEqual(len(report['cell_comparisons']), 1)
    extra = report['cell_comparisons'][0]
    self.assertEqual(extra['id'], 'exp_b')
    self.assertIn('pvalue_adjusted', extra)

  def test_substring_fallback_when_survey_has_no_cells(self):
    t = datetime.datetime(2026, 11, 18)
    df = pandas.DataFrame({
        'CreatedAt': [t, t],
        'Segmentation': ['default_control', 'default_expose'],
        'Response': ['1:A', '1:A'],
        'BomID': ['c1', 'e1'],
    })
    report = reporting.build_report(
        df, {'question1': 'Q', 'answer1a': 'Yes'}, is_lift=True)
    self.assertTrue(report['has_control'])
    self.assertTrue(report['has_expose'])


class CellsZipAndPreviewTest(unittest.TestCase):

  @mock.patch.object(survey_service.survey_collection, 'add_version')
  @mock.patch.object(survey_service, 'get_html_template', return_value='<html></html>')
  def test_zip_file_one_inner_per_cell(self, _html_mock, _version_mock):
    survey = {
        'surveyname': 'multi cell',
        'surveytype': 'brand_lift',
        'cells': [
            {'id': 'ctrl_a', 'label': 'C', 'role': 'control'},
            {'id': 'exp_a', 'label': 'E1', 'role': 'expose'},
            {'id': 'exp_b', 'label': 'E2', 'role': 'expose'},
        ],
    }
    _, data = survey_service.zip_file('sid', survey)
    import zipfile
    names = zipfile.ZipFile(data).namelist()
    zips = sorted(n for n in names if n.endswith('.zip'))
    self.assertEqual(len(zips), 3)
    joined = ' '.join(zips)
    self.assertIn('ctrl_a', joined)
    self.assertIn('exp_a', joined)
    self.assertIn('exp_b', joined)

  def test_headline_arms_use_cells_not_substring(self):
    item = {
        'stats': [
            {'Segmentation': 'north', 'response_count': 10, 'n_q1': 10, 'k_q1_a': 4},
            {'Segmentation': 'south_control_lookalike', 'response_count': 12,
             'n_q1': 12, 'k_q1_a': 8},
            {'Segmentation': 'hold_pool', 'response_count': 99, 'n_q1': 99, 'k_q1_a': 90},
        ]
    }
    cells_spec = [
        {'id': 'north', 'label': 'N', 'role': 'control'},
        {'id': 'south_control_lookalike', 'label': 'S', 'role': 'expose'},
        {'id': 'hold_pool', 'label': 'H', 'role': 'holdout'},
    ]
    arms = survey_service._headline_arms(item, cells_spec)
    self.assertEqual(arms['n_control'], 10)
    self.assertEqual(arms['n_expose'], 12)
    self.assertEqual(arms['n'], 10 + 12 + 99)
