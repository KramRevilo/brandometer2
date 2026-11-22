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
import math
import unittest

import pandas
import reporting


class ReportingMathTest(unittest.TestCase):

  def test_parse_response_skips_empty_tokens(self):
    self.assertEqual(reporting.parse_response('1:A|2:B|3:C'), {
        1: 'A', 2: 'B', 3: 'C'
    })
    self.assertEqual(reporting.parse_response('1:A|2:B||4:D|'), {
        1: 'A', 2: 'B', 4: 'D'
    })
    self.assertEqual(reporting.parse_response('1:|2:B'), {2: 'B'})
    self.assertEqual(reporting.parse_response(None), {})
    self.assertEqual(reporting.completeness('1:A|2:B'), 2)

  def test_segment_role_uses_stored_seg_values(self):
    self.assertEqual(reporting.segment_role('default_control'), 'control')
    self.assertEqual(reporting.segment_role('default_expose'), 'expose')
    self.assertEqual(reporting.segment_role('expose'), 'expose')
    self.assertEqual(reporting.segment_role('CONTROL_MALE'), 'control')
    self.assertEqual(reporting.segment_role(''), 'other')
    self.assertEqual(reporting.segment_role('seg1'), 'other')
    cells = [
        {'id': 'north', 'label': 'North', 'role': 'control'},
        {'id': 'hold_pool', 'label': 'Hold', 'role': 'holdout'},
    ]
    self.assertEqual(reporting.segment_role('north', cells), 'control')
    self.assertEqual(reporting.segment_role('hold_pool', cells), 'holdout')

  def test_wilson_interval_50_of_100(self):
    lo, hi = reporting.wilson_interval(50, 100)
    self.assertAlmostEqual(lo, 0.403832, places=4)
    self.assertAlmostEqual(hi, 0.596168, places=4)
    self.assertTrue(lo < 0.5 < hi)
    margin = reporting.wilson_margin(50, 100)
    self.assertAlmostEqual((hi - lo) / 2.0, margin, places=6)
    nan_lo, nan_hi = reporting.wilson_interval(0, 0)
    self.assertTrue(math.isnan(nan_lo))
    self.assertTrue(math.isnan(nan_hi))
    self.assertTrue(math.isnan(reporting.wilson_margin(0, 0)))

  def test_two_proportion_pvalue_detects_difference(self):
    p_sig = reporting.two_proportion_pvalue(60, 100, 40, 100)
    self.assertGreater(p_sig, 0.001)
    self.assertLess(p_sig, 0.01)
    p_same = reporting.two_proportion_pvalue(50, 100, 50, 100)
    self.assertAlmostEqual(p_same, 1.0, places=6)
    self.assertTrue(math.isnan(reporting.two_proportion_pvalue(1, 10, 0, 0)))
    z = reporting.two_proportion_z(60, 100, 40, 100)
    self.assertGreater(z, 0)
    self.assertAlmostEqual(
        reporting.two_proportion_pvalue(60, 100, 40, 100),
        math.erfc(abs(z) / math.sqrt(2.0)), places=12)

  def test_lift_ratio_undefined_when_control_is_zero(self):
    self.assertEqual(reporting.lift_ratio(0.4, 0.2), 1.0)
    self.assertTrue(math.isnan(reporting.lift_ratio(0.4, 0.0)))
    self.assertTrue(math.isnan(reporting.lift_ratio(0.4, float('nan'))))

  def test_holm_adjust_monotone_and_skips_nan(self):
    adjusted = reporting.holm_adjust([0.01, 0.04, 0.03])
    self.assertAlmostEqual(adjusted[0], 0.03)
    self.assertAlmostEqual(adjusted[1], 0.06)
    self.assertAlmostEqual(adjusted[2], 0.06)
    with_nan = reporting.holm_adjust([0.01, float('nan'), 0.04])
    self.assertAlmostEqual(with_nan[0], 0.02)
    self.assertTrue(math.isnan(with_nan[1]))
    self.assertAlmostEqual(with_nan[2], 0.04)
    self.assertEqual(reporting.holm_adjust([]), [])
    self.assertTrue(math.isnan(reporting.holm_adjust([None])[0]))


class ConsolidationTest(unittest.TestCase):

  def test_consolidate_keeps_most_complete_then_latest_per_bomid(self):
    t1 = datetime.datetime(2026, 11, 1, 10, 0, 0)
    t2 = datetime.datetime(2026, 11, 1, 10, 1, 0)
    t3 = datetime.datetime(2026, 11, 1, 10, 2, 0)
    df = pandas.DataFrame({
        'CreatedAt': [t1, t2, t3],
        'Segmentation': ['seg1', 'seg1', 'seg1'],
        'Response': ['1:A', '1:A|2:B', '1:A|2:B'],
        'BomID': ['b1', 'b1', 'b1'],
    })
    out = reporting.consolidate_frame(df)
    self.assertEqual(len(out), 1)
    self.assertEqual(out.iloc[0]['Response'], '1:A|2:B')
    self.assertEqual(out.iloc[0]['CreatedAt'], t3)

  def test_consolidate_duplicate_respondent_id_from_retry_pixels(self):
    t1 = datetime.datetime(2026, 11, 1, 10, 0, 0)
    t2 = datetime.datetime(2026, 11, 1, 10, 0, 1)
    df = pandas.DataFrame({
        'CreatedAt': [t1, t2],
        'Segmentation': ['default_expose', 'default_expose'],
        'Response': ['1:A', '1:A'],
        'BomID': ['b1', 'b1'],
        'RespondentID': ['rid-1', 'rid-1'],
    })
    out = reporting.consolidate_frame(df)
    self.assertEqual(len(out), 1)
    self.assertEqual(out.iloc[0]['RespondentID'], 'rid-1')

  def test_consolidate_blank_bomid_stays_as_individual_rows(self):
    t1 = datetime.datetime(2026, 11, 1)
    df = pandas.DataFrame({
        'CreatedAt': [t1, t1],
        'Segmentation': ['seg1', 'seg1'],
        'Response': ['1:A', '1:B'],
        'BomID': ['', None],
    })
    out = reporting.consolidate_frame(df)
    self.assertEqual(len(out), 2)

  def test_consolidate_without_bomid_column_is_noop(self):
    df = pandas.DataFrame({
        'CreatedAt': [datetime.datetime(2026, 11, 1)] * 2,
        'Segmentation': ['seg1', 'seg1'],
        'Response': ['1:A', '1:A|2:B'],
    })
    out = reporting.consolidate_frame(df)
    self.assertEqual(len(out), 2)

  def test_consolidate_empty_frame(self):
    df = pandas.DataFrame(columns=['CreatedAt', 'Segmentation', 'Response', 'BomID'])
    out = reporting.consolidate_frame(df)
    self.assertTrue(out.empty)


class BuildReportTest(unittest.TestCase):

  def test_build_report_lift_and_track(self):
    t = datetime.datetime(2026, 11, 18, 12, 0, 0)
    df = pandas.DataFrame({
        'CreatedAt': [t, t, t, t],
        'Segmentation': [
            'default_control', 'default_control',
            'default_expose', 'default_expose'
        ],
        'Response': ['1:A', '1:B', '1:A', '1:A'],
        'BomID': ['c1', 'c2', 'e1', 'e2'],
    })
    survey = {
        'question1': 'Aware?',
        'answer1a': 'Yes',
        'answer1b': 'No',
        'surveytype': 'brand_lift',
    }
    lift = reporting.build_report(df, survey, is_lift=True)
    self.assertEqual(lift['n_total'], 4)
    self.assertTrue(lift['has_control'])
    self.assertTrue(lift['has_expose'])
    self.assertTrue(lift['warning_n_small'])
    self.assertEqual(lift['questions'][0]['text'], 'Aware?')
    yes = lift['questions'][0]['answers'][0]
    self.assertEqual(yes['id'], 'A')
    self.assertEqual(yes['k_control'], 1)
    self.assertEqual(yes['k_expose'], 2)
    self.assertEqual(yes['lift'], 1.0)
    self.assertIn('pvalue_adjusted', yes)
    self.assertTrue(lift['questions'][0]['warning_n_small'])
    self.assertGreaterEqual(lift['n_tests'], 2)
    self.assertIn('Holm', lift['stats_notes']['multiple_comparison'])
    self.assertTrue(lift['daily'])

    track = reporting.build_report(df, survey, is_lift=False)
    self.assertFalse(track['warning_n_small'])
    self.assertIsNone(track['empty_reason'])

  def test_build_report_empty_and_missing_control(self):
    empty = reporting.build_report(
        pandas.DataFrame(columns=['CreatedAt', 'Segmentation', 'Response']),
        {}, is_lift=True)
    self.assertEqual(empty['empty_reason'], 'no_data')

    t = datetime.datetime(2026, 11, 18)
    df = pandas.DataFrame({
        'CreatedAt': [t],
        'Segmentation': ['default_expose'],
        'Response': ['1:A'],
        'BomID': ['e1'],
    })
    report = reporting.build_report(
        df, {'question1': 'Q', 'answer1a': 'Yes'}, is_lift=True)
    self.assertEqual(report['empty_reason'], 'no_control')
    self.assertTrue(report['has_expose'])
    self.assertEqual(report['n_total'], 1)

  def test_breakouts_by_size_and_date_include_lift(self):
    t1 = datetime.datetime(2026, 11, 18, 12, 0, 0)
    t2 = datetime.datetime(2026, 11, 19, 12, 0, 0)
    df = pandas.DataFrame({
        'CreatedAt': [t1, t1, t2, t2],
        'Segmentation': [
            'default_control', 'default_expose',
            'default_control', 'default_expose',
        ],
        'Response': ['1:A', '1:A', '1:B', '1:A'],
        'BomID': ['c1', 'e1', 'c2', 'e2'],
        'CreativeSize': ['300x250', '300x250', '160x600', '160x600'],
        'PlacementID': ['p1', 'p1', 'p2', 'p2'],
        'SiteID': ['site-a', 'site-a', 'site-b', 'site-b'],
        'AdCreativeID': ['cr-a', 'cr-a', 'cr-b', 'cr-b'],
    })
    survey = {
        'question1': 'Aware?',
        'answer1a': 'Yes',
        'answer1b': 'No',
        'surveytype': 'brand_lift',
    }
    report = reporting.build_report(df, survey, is_lift=True)
    keys = [dim['key'] for dim in report['breakouts']]
    self.assertEqual(
        keys, ['size', 'placement', 'site', 'creative', 'date', 'segment'])
    site = [dim for dim in report['breakouts'] if dim['key'] == 'site'][0]
    self.assertEqual(
        [sl['value'] for sl in site['slices']], ['site-a', 'site-b'])
    size = [dim for dim in report['breakouts'] if dim['key'] == 'size'][0]
    self.assertEqual([sl['value'] for sl in size['slices']], ['160x600', '300x250'])
    by_size = {sl['value']: sl for sl in size['slices']}
    yes_300 = [
        a for a in by_size['300x250']['questions'][0]['answers'] if a['id'] == 'A'
    ][0]
    self.assertEqual(yes_300['k_control'], 1)
    self.assertEqual(yes_300['k_expose'], 1)
    self.assertEqual(yes_300['lift'], 0.0)
    csv_text = reporting.breakouts_to_csv(report)
    self.assertIn('dimension,slice,question_index', csv_text)
    self.assertIn('Size,300x250,1,Aware?,A,Yes', csv_text)
    self.assertIn('overall,all,', csv_text)
    self.assertIn('Date,2026-11-18,', csv_text)
    self.assertIn('pvalue_adjusted', csv_text)
    yes_300_adj = yes_300['pvalue_adjusted']
    self.assertFalse(math.isnan(yes_300_adj))
    size_dim = [dim for dim in report['breakouts'] if dim['key'] == 'size'][0]
    self.assertGreaterEqual(size_dim['n_tests'], 1)

  def test_breakouts_skip_blank_only_dimensions(self):
    t = datetime.datetime(2026, 11, 18)
    df = pandas.DataFrame({
        'CreatedAt': [t, t],
        'Segmentation': ['default_control', 'default_expose'],
        'Response': ['1:A', '1:A'],
        'BomID': ['c1', 'e1'],
        'CreativeSize': ['300x250', '300x250'],
        'PlacementID': ['', ''],
        'SiteID': ['', ''],
        'AdCreativeID': [None, ''],
    })
    report = reporting.build_report(
        df, {'question1': 'Q', 'answer1a': 'Yes'}, is_lift=True)
    keys = [dim['key'] for dim in report['breakouts']]
    self.assertIn('size', keys)
    self.assertIn('date', keys)
    self.assertNotIn('placement', keys)
    self.assertNotIn('site', keys)
    self.assertNotIn('creative', keys)

  def test_breakouts_creative_version_unknown_label(self):
    t = datetime.datetime(2026, 11, 18)
    df = pandas.DataFrame({
        'CreatedAt': [t, t, t, t],
        'Segmentation': [
            'default_control', 'default_expose',
            'default_control', 'default_expose',
        ],
        'Response': ['1:A', '1:A', '1:B', '1:A'],
        'BomID': ['c1', 'e1', 'c2', 'e2'],
        'CreativeVersion': [2, 2, None, None],
    })
    report = reporting.build_report(
        df, {'question1': 'Q', 'answer1a': 'Yes', 'answer1b': 'No'},
        is_lift=True)
    version = [dim for dim in report['breakouts'] if dim['key'] == 'version'][0]
    labels = [sl['value'] for sl in version['slices']]
    self.assertEqual(labels, ['2', reporting.UNKNOWN_VERSION_LABEL])
    csv_text = reporting.breakouts_to_csv(report)
    self.assertIn('Creative version,2,', csv_text)
    self.assertIn('Creative version,Unknown / pre-version,', csv_text)
