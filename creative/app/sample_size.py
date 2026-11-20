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
"""Brand Lift sample-size planner (two-proportion z-test, MIN_N floor)."""
import math

import reporting

MIN_N = reporting.MIN_N

DEFAULTS = {
    'baseline': 0.20,
    'mde_mode': 'relative',
    'mde_relative': 0.10,
    'mde_absolute': 0.05,
    'confidence': 0.95,
    'power': 0.80,
    'comparisons': 1,
    'response_rate': 0.01,
    'control_share': 0.50,
}

RELATIVE_GRID = (0.05, 0.08, 0.10, 0.15, 0.20)
ABSOLUTE_GRID = (0.02, 0.03, 0.05, 0.08, 0.10)
CONFIDENCE_CHOICES = (0.90, 0.95, 0.99)
POWER_CHOICES = (0.80, 0.90)


def norm_cdf(z):
  return 0.5 * (1.0 + math.erf(float(z) / math.sqrt(2.0)))


def norm_ppf(p):
  """Inverse standard normal via bisection on erf. Matches reporting.Z_95."""
  p = float(p)
  if p <= 0.0:
    return float('-inf')
  if p >= 1.0:
    return float('inf')
  if abs(p - 0.5) < 1e-15:
    return 0.0
  lo, hi = -20.0, 20.0
  for _ in range(80):
    mid = 0.5 * (lo + hi)
    if norm_cdf(mid) < p:
      lo = mid
    else:
      hi = mid
  return 0.5 * (lo + hi)


def _clamp(value, lo, hi):
  return max(lo, min(hi, value))


def _as_float(value, default):
  try:
    if value is None or value == '':
      return float(default)
    return float(value)
  except (TypeError, ValueError):
    return float(default)


def _as_int(value, default):
  try:
    if value is None or value == '':
      return int(default)
    return int(float(value))
  except (TypeError, ValueError):
    return int(default)


def parse_inputs(raw=None):
  """Normalise planner fields from a form, query, or stored dict."""
  raw = raw or {}
  baseline = _as_float(raw.get('baseline'), DEFAULTS['baseline'])
  if baseline > 1.0:
    baseline = baseline / 100.0
  baseline = _clamp(baseline, 0.01, 0.99)

  mode = (raw.get('mde_mode') or DEFAULTS['mde_mode'] or 'relative').strip().lower()
  if mode not in ('relative', 'absolute'):
    mode = 'relative'

  mde_relative = _as_float(raw.get('mde_relative'), DEFAULTS['mde_relative'])
  if mde_relative > 1.0:
    mde_relative = mde_relative / 100.0
  mde_relative = _clamp(mde_relative, 0.005, 2.0)

  mde_absolute = _as_float(raw.get('mde_absolute'), DEFAULTS['mde_absolute'])
  if mde_absolute > 1.0:
    mde_absolute = mde_absolute / 100.0
  mde_absolute = _clamp(mde_absolute, 0.001, 0.90)

  confidence = _as_float(raw.get('confidence'), DEFAULTS['confidence'])
  if confidence > 1.0:
    confidence = confidence / 100.0
  confidence = _clamp(confidence, 0.80, 0.999)

  power = _as_float(raw.get('power'), DEFAULTS['power'])
  if power > 1.0:
    power = power / 100.0
  power = _clamp(power, 0.50, 0.99)

  comparisons = _clamp(_as_int(raw.get('comparisons'), DEFAULTS['comparisons']), 1, 100)

  response_rate = _as_float(raw.get('response_rate'), DEFAULTS['response_rate'])
  if response_rate > 1.0:
    response_rate = response_rate / 100.0
  response_rate = _clamp(response_rate, 0.0001, 1.0)

  control_share = _as_float(raw.get('control_share'), DEFAULTS['control_share'])
  if control_share > 1.0:
    control_share = control_share / 100.0
  control_share = _clamp(control_share, 0.05, 0.95)

  return {
      'baseline': baseline,
      'mde_mode': mode,
      'mde_relative': mde_relative,
      'mde_absolute': mde_absolute,
      'confidence': confidence,
      'power': power,
      'comparisons': comparisons,
      'response_rate': response_rate,
      'control_share': control_share,
  }


def expose_rate(baseline, mde_mode, mde_relative, mde_absolute):
  if mde_mode == 'absolute':
    return baseline + mde_absolute
  return baseline * (1.0 + mde_relative)


def alpha_for_plan(inputs):
  """Bonferroni / Holm first-step alpha so planning matches item 66."""
  alpha = 1.0 - float(inputs['confidence'])
  return alpha / float(max(1, int(inputs['comparisons'])))


def n_per_group_unpooled(p_control, p_expose, alpha, power, control_share):
  """Standard two-sided two-proportion sample size (unpooled H1, pooled H0).

  Allocation: n_control : n_expose = control_share : (1 - control_share).
  Returns (n_control, n_expose) before the MIN_N floor.
  """
  delta = p_expose - p_control
  if abs(delta) < 1e-12:
    return float('inf'), float('inf')
  if not (0.0 < p_control < 1.0) or not (0.0 < p_expose < 1.0):
    return float('inf'), float('inf')
  k = (1.0 - control_share) / control_share  # n_expose / n_control
  p_bar = (p_control + k * p_expose) / (1.0 + k)
  z_a = norm_ppf(1.0 - alpha / 2.0)
  z_b = norm_ppf(power)
  se_null = math.sqrt((1.0 + 1.0 / k) * p_bar * (1.0 - p_bar))
  se_alt = math.sqrt(
      p_control * (1.0 - p_control) + p_expose * (1.0 - p_expose) / k)
  n_control = ((z_a * se_null + z_b * se_alt) / delta) ** 2
  n_expose = k * n_control
  return n_control, n_expose


def required_n(inputs, p_expose=None):
  """Ceil + MIN_N floor. Returns a result dict or an error string."""
  p_c = inputs['baseline']
  p_e = p_expose if p_expose is not None else expose_rate(
      p_c, inputs['mde_mode'], inputs['mde_relative'], inputs['mde_absolute'])
  if p_e <= 0.0 or p_e >= 1.0:
    return {'error': 'Exposed rate must stay between 0 and 1. Lower the lift or baseline.'}
  if abs(p_e - p_c) < 1e-12:
    return {'error': 'Lift is zero — pick a minimum detectable lift.'}
  alpha = alpha_for_plan(inputs)
  n_c_raw, n_e_raw = n_per_group_unpooled(
      p_c, p_e, alpha, inputs['power'], inputs['control_share'])
  if not math.isfinite(n_c_raw) or not math.isfinite(n_e_raw):
    return {'error': 'Could not compute a sample size for these inputs.'}
  n_c = max(reporting.MIN_N, int(math.ceil(n_c_raw - 1e-9)))
  n_e = max(reporting.MIN_N, int(math.ceil(n_e_raw - 1e-9)))
  n_total = n_c + n_e
  rate = inputs['response_rate']
  imp_c = int(math.ceil(n_c / rate - 1e-9))
  imp_e = int(math.ceil(n_e / rate - 1e-9))
  relative = (p_e - p_c) / p_c if p_c else float('nan')
  absolute = p_e - p_c
  return {
      'error': None,
      'p_control': p_c,
      'p_expose': p_e,
      'relative_lift': relative,
      'absolute_lift': absolute,
      'alpha': alpha,
      'n_control': n_c,
      'n_expose': n_e,
      'n_total': n_total,
      'impressions_control': imp_c,
      'impressions_expose': imp_e,
      'impressions_total': imp_c + imp_e,
      'min_n_applied': n_c == reporting.MIN_N or n_e == reporting.MIN_N,
  }


def scenario_table(inputs):
  """A few lift values around the chosen MDE, same extras as the main plan."""
  mode = inputs['mde_mode']
  chosen = (
      inputs['mde_relative'] if mode == 'relative' else inputs['mde_absolute'])
  grid = RELATIVE_GRID if mode == 'relative' else ABSOLUTE_GRID
  values = sorted(set(list(grid) + [chosen]))
  rows = []
  for value in values:
    if mode == 'relative':
      p_e = expose_rate(inputs['baseline'], 'relative', value, 0.0)
    else:
      p_e = expose_rate(inputs['baseline'], 'absolute', 0.0, value)
    row = required_n(inputs, p_expose=p_e)
    row['grid_value'] = value
    row['is_selected'] = abs(value - chosen) < 1e-12
    rows.append(row)
  return rows


def compute(raw=None):
  inputs = parse_inputs(raw)
  result = required_n(inputs)
  return {
      'inputs': inputs,
      'result': result,
      'table': scenario_table(inputs),
  }


def storage_payload(inputs, result=None):
  """Persist inputs plus the n that sequential reporting should target."""
  result = result or required_n(inputs)
  payload = dict(inputs)
  if result.get('error'):
    payload['error'] = result['error']
    return payload
  payload.update({
      'n_control': result['n_control'],
      'n_expose': result['n_expose'],
      'n_total': result['n_total'],
      'impressions_total': result['impressions_total'],
      'p_expose': result['p_expose'],
      'relative_lift': result['relative_lift'],
      'absolute_lift': result['absolute_lift'],
      'alpha': result['alpha'],
  })
  return payload


def plan_from_survey(survey):
  stored = (survey or {}).get('sample_plan')
  if not isinstance(stored, dict) or not stored:
    return None
  return parse_inputs(stored)
