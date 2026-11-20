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
"""Group-sequential Brand Lift status (Lan-DeMets O'Brien-Fleming, or always-valid).

When a sample plan from the planner is stored, peeking uses an O'Brien-Fleming
boundary at information fraction t = I / I_plan, with I = 1/(1/n_c + 1/n_e).
At t = 1 the bound equals the usual two-sided z critical value, so the
fixed-horizon test and the sequential call agree at the planned end.

With no plan, an always-valid Robbins-style mixture bound is used so the type I
error stays at or below alpha under repeated looks. Futility is only declared
when a plan exists and t has reached 1 without crossing efficacy.
"""
import math

import reporting
import sample_size

STATUS_NOT_ENOUGH = 'not_enough'
STATUS_COLLECTING = 'collecting'
STATUS_POSITIVE = 'conclusive_positive'
STATUS_NEGATIVE = 'conclusive_negative'
STATUS_FUTILITY = 'conclusive_futility'

STATUS_LABELS = {
    STATUS_NOT_ENOUGH: 'Not enough data (n<30)',
    STATUS_COLLECTING: 'Collecting',
    STATUS_POSITIVE: 'Conclusive: positive lift',
    STATUS_NEGATIVE: 'Conclusive: negative lift',
    STATUS_FUTILITY: 'Conclusive: no meaningful lift / futility',
}

METHOD_OF = 'obrien_fleming'
METHOD_AV = 'always_valid'


def information(n_control, n_expose):
  n_c = float(n_control or 0)
  n_e = float(n_expose or 0)
  if n_c <= 0 or n_e <= 0:
    return 0.0
  return 1.0 / (1.0 / n_c + 1.0 / n_e)


def obrien_fleming_bound(alpha, t):
  """Continuous OF / Lan-DeMets bound for a N(0,1) z-statistic at info t."""
  if t <= 0:
    return float('inf')
  z = sample_size.norm_ppf(1.0 - float(alpha) / 2.0)
  return z / math.sqrt(min(1.0, float(t)))


def always_valid_bound(alpha, n_total):
  """Robbins mixture bound: |Z| >= sqrt(2 log(1/α) + log n), n = n_c + n_e."""
  alpha = max(1e-12, min(0.5, float(alpha)))
  n = max(2.0, float(n_total or 2))
  return math.sqrt(2.0 * math.log(1.0 / alpha) + math.log(n))


def planned_ns(plan):
  if not plan:
    return None, None
  n_c = plan.get('n_control')
  n_e = plan.get('n_expose')
  try:
    n_c = int(n_c)
    n_e = int(n_e)
  except (TypeError, ValueError):
    return None, None
  if n_c < reporting.MIN_N or n_e < reporting.MIN_N:
    return None, None
  return n_c, n_e


def evaluate(k_control, n_control, k_expose, n_expose, plan=None, alpha=None):
  """Sequential status for one two-proportion comparison."""
  n_c = int(n_control or 0)
  n_e = int(n_expose or 0)
  min_n = reporting.MIN_N
  plan_c, plan_e = planned_ns(plan)
  has_plan = plan_c is not None
  if alpha is None:
    if plan:
      alpha = sample_size.alpha_for_plan(sample_size.parse_inputs(plan))
    else:
      alpha = 0.05
  method = METHOD_OF if has_plan else METHOD_AV
  info = information(n_c, n_e)
  if has_plan:
    t = info / information(plan_c, plan_e) if information(plan_c, plan_e) else 0.0
    t = max(0.0, min(1.0, t))
    bound = obrien_fleming_bound(alpha, t) if t > 0 else float('inf')
  else:
    t = None
    bound = always_valid_bound(alpha, n_c + n_e)
  z = reporting.two_proportion_z(k_expose, n_e, k_control, n_c)
  if n_c < min_n or n_e < min_n:
    status = STATUS_NOT_ENOUGH
  elif not math.isfinite(z):
    status = STATUS_COLLECTING
  elif abs(z) >= bound:
    status = STATUS_POSITIVE if z > 0 else STATUS_NEGATIVE
  elif has_plan and t >= 1.0:
    status = STATUS_FUTILITY
  else:
    status = STATUS_COLLECTING
  progress = t if has_plan else None
  return {
      'status': status,
      'label': STATUS_LABELS[status],
      'z': z,
      'bound': bound,
      't': t,
      'progress': progress,
      'method': method,
      'alpha': alpha,
      'n_control': n_c,
      'n_expose': n_e,
      'n_control_plan': plan_c,
      'n_expose_plan': plan_e,
      'has_plan': has_plan,
  }


def _question_status(question):
  """Question-level: answer A (first answer) is the planned positive metric."""
  answers = question.get('answers') or []
  if not answers:
    return None
  primary = None
  for answer in answers:
    if answer.get('id') == 'A':
      primary = answer
      break
  if primary is None:
    primary = answers[0]
  return primary.get('sequential')


def attach_to_report(report, plan=None):
  """Fill sequential fields on a Brand Lift report. No-op for Brand Track."""
  report = report or {}
  if not report.get('is_lift'):
    return report
  stored = plan if isinstance(plan, dict) and plan else None
  parsed = sample_size.parse_inputs(stored) if stored else None
  n_tests = max(1, int(report.get('n_tests') or 1))
  if parsed:
    comparisons = parsed['comparisons']
    # Sequential alpha uses the planned family size, not the realised n_tests,
    # so the bound matches the sample-size page the editor saved.
    seq_plan = dict(parsed)
    if stored:
      seq_plan['n_control'] = stored.get('n_control')
      seq_plan['n_expose'] = stored.get('n_expose')
    alpha = sample_size.alpha_for_plan(parsed)
  else:
    comparisons = n_tests
    seq_plan = None
    alpha = 0.05 / float(comparisons)

  overall = None
  for question in report.get('questions') or []:
    for answer in question.get('answers') or []:
      answer['sequential'] = evaluate(
          answer.get('k_control'), question.get('n_control'),
          answer.get('k_expose'), question.get('n_expose'),
          plan=seq_plan, alpha=alpha)
    question['sequential'] = _question_status(question)
    if overall is None and question.get('sequential'):
      overall = dict(question['sequential'])

  if overall is None:
    overall = evaluate(
        0, report.get('control_n'), 0, report.get('expose_n'),
        plan=seq_plan, alpha=alpha)
  overall['comparisons'] = comparisons
  overall['method_label'] = (
      "O'Brien-Fleming (Lan-DeMets) vs the saved sample plan"
      if overall.get('has_plan') else
      'Always-valid confidence sequence (no sample plan saved)')
  overall['fixed_horizon_note'] = (
      'Fixed-horizon p-values and Wilson CIs are only valid at the planned '
      'end. Sequential status is safe to check anytime.')
  report['sequential'] = overall
  return report
