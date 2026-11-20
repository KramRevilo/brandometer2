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

import math
import unittest

import numpy
import pandas
import datetime

import reporting
import sequential
import sample_size


class SequentialBoundaryTest(unittest.TestCase):

  def test_of_bound_matches_z_at_t1_and_doubles_at_t025(self):
    alpha = 0.05
    z = sample_size.norm_ppf(0.975)
    self.assertAlmostEqual(sequential.obrien_fleming_bound(alpha, 1.0), z, places=5)
    self.assertAlmostEqual(
        sequential.obrien_fleming_bound(alpha, 0.25), 2.0 * z, places=5)

  def test_not_enough_below_min_n(self):
    got = sequential.evaluate(10, 20, 12, 20, plan=None, alpha=0.05)
    self.assertEqual(got['status'], sequential.STATUS_NOT_ENOUGH)
    self.assertIn('n<30', got['label'])

  def test_futility_at_planned_end_when_z_small(self):
    plan = {
        'n_control': 80, 'n_expose': 80, 'confidence': 0.95, 'comparisons': 1,
        'baseline': 0.2, 'mde_relative': 0.1, 'power': 0.8,
        'control_share': 0.5, 'response_rate': 0.01, 'mde_mode': 'relative',
        'mde_absolute': 0.05,
    }
    got = sequential.evaluate(40, 80, 41, 80, plan=plan)
    self.assertEqual(got['method'], sequential.METHOD_OF)
    self.assertAlmostEqual(got['t'], 1.0, places=6)
    self.assertEqual(got['status'], sequential.STATUS_FUTILITY)

  def test_positive_crosses_of_boundary(self):
    plan = {
        'n_control': 80, 'n_expose': 80, 'confidence': 0.95, 'comparisons': 1,
        'baseline': 0.2, 'mde_relative': 0.1, 'power': 0.8,
        'control_share': 0.5, 'response_rate': 0.01, 'mde_mode': 'relative',
        'mde_absolute': 0.05,
    }
    got = sequential.evaluate(20, 80, 60, 80, plan=plan)
    self.assertEqual(got['status'], sequential.STATUS_POSITIVE)
    self.assertGreater(got['z'], got['bound'])

  def test_attach_sets_overall_from_question1_answer_a(self):
    t = datetime.datetime(2026, 11, 18)
    rows = []
    for i in range(40):
      rows.append({
          'CreatedAt': t, 'Segmentation': 'default_control',
          'Response': '1:A' if i < 10 else '1:B', 'BomID': 'c%s' % i,
      })
    for i in range(40):
      rows.append({
          'CreatedAt': t, 'Segmentation': 'default_expose',
          'Response': '1:A' if i < 30 else '1:B', 'BomID': 'e%s' % i,
      })
    df = pandas.DataFrame(rows)
    survey = {
        'question1': 'Aware?', 'answer1a': 'Yes', 'answer1b': 'No',
        'surveytype': 'brand_lift',
        'sample_plan': {
            'baseline': 0.2, 'mde_mode': 'relative', 'mde_relative': 0.1,
            'confidence': 0.95, 'power': 0.8, 'comparisons': 1,
            'response_rate': 0.01, 'control_share': 0.5,
            'n_control': 200, 'n_expose': 200,
        },
    }
    report = reporting.build_report(df, survey, is_lift=True)
    self.assertIn('sequential', report)
    self.assertEqual(report['sequential']['method'], sequential.METHOD_OF)
    self.assertLess(report['sequential']['progress'], 1.0)
    yes = report['questions'][0]['answers'][0]
    self.assertEqual(yes['id'], 'A')
    self.assertIn('sequential', yes)
    csv_text = reporting.breakouts_to_csv(report)
    self.assertIn('sequential_status', csv_text)
    self.assertIn('conclusive_positive', csv_text)
    overall_line = [
        line for line in csv_text.splitlines() if line.startswith('overall,all,1,')
        and ',A,Yes,' in line][0]
    self.assertTrue(overall_line.endswith('conclusive_positive') or
                    'conclusive_positive' in overall_line)

  def test_no_plan_uses_always_valid(self):
    got = sequential.evaluate(20, 40, 22, 40, plan=None, alpha=0.05)
    self.assertEqual(got['method'], sequential.METHOD_AV)
    self.assertEqual(got['status'], sequential.STATUS_COLLECTING)
    self.assertGreater(got['bound'], sample_size.norm_ppf(0.975))


class SequentialTypeITest(unittest.TestCase):

  def test_obrien_fleming_type_i_at_or_below_alpha(self):
    rng = numpy.random.default_rng(20261120)
    alpha = 0.05
    n_plan = 100
    looks = (30, 50, 75, 100)
    p = 0.25
    trials = 1200
    rejections = 0
    plan = {
        'n_control': n_plan, 'n_expose': n_plan, 'confidence': 0.95,
        'comparisons': 1, 'baseline': p, 'mde_relative': 0.1, 'power': 0.8,
        'control_share': 0.5, 'response_rate': 0.01, 'mde_mode': 'relative',
        'mde_absolute': 0.05,
    }
    for _ in range(trials):
      k_c = 0
      k_e = 0
      crossed = False
      prev = 0
      for look in looks:
        add = look - prev
        k_c += int(rng.binomial(add, p))
        k_e += int(rng.binomial(add, p))
        prev = look
        got = sequential.evaluate(k_c, look, k_e, look, plan=plan, alpha=alpha)
        if got['status'] in (
            sequential.STATUS_POSITIVE, sequential.STATUS_NEGATIVE):
          crossed = True
          break
      if crossed:
        rejections += 1
    rate = rejections / float(trials)
    self.assertLessEqual(rate, alpha + 0.03, msg='OF type I=%s' % rate)

  def test_always_valid_type_i_at_or_below_alpha(self):
    rng = numpy.random.default_rng(7)
    alpha = 0.05
    looks = list(range(30, 160, 10))
    p = 0.3
    trials = 800
    rejections = 0
    for _ in range(trials):
      k_c = 0
      k_e = 0
      prev = 0
      crossed = False
      for look in looks:
        add = look - prev
        k_c += int(rng.binomial(add, p))
        k_e += int(rng.binomial(add, p))
        prev = look
        got = sequential.evaluate(k_c, look, k_e, look, plan=None, alpha=alpha)
        if got['status'] in (
            sequential.STATUS_POSITIVE, sequential.STATUS_NEGATIVE):
          crossed = True
          break
      if crossed:
        rejections += 1
    rate = rejections / float(trials)
    self.assertLessEqual(rate, alpha + 0.02, msg='AV type I=%s' % rate)
