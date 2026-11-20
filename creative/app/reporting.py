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
"""Response consolidation and honest reporting math (Wilson CI, z-test)."""
import math
import re

import pandas as pd

import respondent

# Warn when a lift arm has fewer than this many respondents who answered.
MIN_N = 30
Z_95 = 1.959963984540054  # inverse Phi(0.975)

_ANSWER_TOKEN = re.compile(r'(?:^|\|)([1-5]):([^|]*)')


def parse_response(response):
  """Parse '1:A|2:B|3:C' into {1: 'A', 2: 'B', 3: 'C'}. Empty tokens are skipped."""
  parsed = {}
  if response is None or (isinstance(response, float) and math.isnan(response)):
    return parsed
  text = str(response)
  for match in _ANSWER_TOKEN.finditer(text):
    answer = match.group(2).strip()
    if answer:
      parsed[int(match.group(1))] = answer
  return parsed


def completeness(response):
  return len(parse_response(response))


def segment_role(seg):
  """Map a stored seg value to control, expose, or other. Does not rename it."""
  text = str(seg or '').strip().lower()
  if 'control' in text:
    return 'control'
  if 'expos' in text:
    return 'expose'
  return 'other'


def consolidate_frame(df):
  """Keep one row per respondent: the most complete response, then the latest.

  Session key is COALESCE(RespondentID, BomID). Blank IDs stay as individual
  respondents (typical of old 'submit at end' rows with no BomID).
  """
  if df is None or df.empty:
    return df
  out = df.copy()
  if 'BomID' not in out.columns and 'RespondentID' not in out.columns:
    return out
  out['_complete'] = out['Response'].map(completeness)
  out['_session'] = respondent.session_keys(out)
  sort_cols = ['_complete']
  ascending = [False]
  if 'CreatedAt' in out.columns:
    sort_cols.append('CreatedAt')
    ascending.append(False)
  out = out.sort_values(sort_cols, ascending=ascending, kind='mergesort')
  out = out.drop_duplicates('_session', keep='first')
  return out.drop(columns=['_complete', '_session'])


def wilson_interval(successes, n, z=Z_95):
  """Wilson score 95% CI for a binomial proportion. Returns (lo, hi)."""
  if n is None or n <= 0:
    return (float('nan'), float('nan'))
  successes = max(0, min(int(successes), int(n)))
  n = float(n)
  p = successes / n
  z2 = z * z
  denom = 1.0 + z2 / n
  center = (p + z2 / (2.0 * n)) / denom
  margin = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n) / denom
  return (max(0.0, center - margin), min(1.0, center + margin))


def two_proportion_pvalue(successes_a, n_a, successes_b, n_b):
  """Two-sided two-proportion z-test p-value (pooled)."""
  if not n_a or not n_b:
    return float('nan')
  p_a = successes_a / float(n_a)
  p_b = successes_b / float(n_b)
  p_pool = (successes_a + successes_b) / float(n_a + n_b)
  se = math.sqrt(p_pool * (1.0 - p_pool) * (1.0 / n_a + 1.0 / n_b))
  if se == 0:
    return 1.0 if p_a == p_b else 0.0
  z = (p_a - p_b) / se
  return math.erfc(abs(z) / math.sqrt(2.0))


def lift_ratio(p_expose, p_control):
  if p_control is None or p_control == 0 or (
      isinstance(p_control, float) and math.isnan(p_control)):
    return float('nan')
  return (p_expose - p_control) / p_control


def build_report(df, survey_info, is_lift=False):
  """Build the reporting page model from consolidated response rows."""
  survey_info = survey_info or {}
  raw_n = 0 if df is None or df.empty else len(df)
  consolidated = consolidate_frame(df)
  n_total = 0 if consolidated is None or consolidated.empty else len(consolidated)

  report = {
      'is_lift': bool(is_lift),
      'n_raw': raw_n,
      'n_total': n_total,
      'min_n': MIN_N,
      'warning_n_small': False,
      'has_control': False,
      'has_expose': False,
      'segments': [],
      'daily': [],
      'questions': [],
      'empty_reason': None,
      'control_n': 0,
      'expose_n': 0,
  }
  if n_total == 0:
    report['empty_reason'] = 'no_data'
    return report

  work = consolidated.copy()
  work['role'] = work['Segmentation'].map(segment_role)
  work['_parsed'] = work['Response'].map(parse_response)
  if 'CreatedAt' in work.columns:
    dates = pd.to_datetime(work['CreatedAt'], errors='coerce')
    work['_date'] = dates.dt.strftime('%Y-%m-%d')
  else:
    work['_date'] = ''

  segments = [
      str(s) for s in work['Segmentation'].fillna('').unique().tolist()
  ]
  report['segments'] = segments
  report['has_control'] = bool((work['role'] == 'control').any())
  report['has_expose'] = bool((work['role'] == 'expose').any())
  report['control_n'] = int((work['role'] == 'control').sum())
  report['expose_n'] = int((work['role'] == 'expose').sum())
  if is_lift:
    report['warning_n_small'] = (
        report['control_n'] < MIN_N or report['expose_n'] < MIN_N)
    if not report['has_control'] and not report['has_expose']:
      report['empty_reason'] = 'no_control_or_expose'
    elif not report['has_control']:
      report['empty_reason'] = 'no_control'
    elif not report['has_expose']:
      report['empty_reason'] = 'no_expose'

  daily = (
      work.groupby(['_date', 'Segmentation'], dropna=False)
      .size()
      .reset_index(name='count'))
  report['daily'] = [
      {
          'date': row['_date'] or '',
          'segment': '' if pd.isna(row['Segmentation']) else str(row['Segmentation']),
          'count': int(row['count']),
      }
      for row in daily.to_dict('records')
      if row['_date']
  ]

  for q in range(1, 6):
    text = survey_info.get('question' + str(q)) or ''
    if not text and not any(q in parsed for parsed in work['_parsed']):
      continue
    labels = {}
    for letter in 'abcdefgh':
      label = survey_info.get('answer' + str(q) + letter) or ''
      if label:
        labels[letter.upper()] = label
    seen = set(labels)
    for parsed in work['_parsed']:
      token = parsed.get(q)
      if token:
        seen.add(token)
    answer_ids = []
    for letter in 'ABCDEFGH':
      if letter in seen:
        answer_ids.append(letter)
    for token in sorted(seen):
      if token not in answer_ids:
        answer_ids.append(token)

    n_by_segment = {}
    n_control = 0
    n_expose = 0
    for _, row in work.iterrows():
      if q not in row['_parsed']:
        continue
      seg = '' if pd.isna(row['Segmentation']) else str(row['Segmentation'])
      n_by_segment[seg] = n_by_segment.get(seg, 0) + 1
      if row['role'] == 'control':
        n_control += 1
      elif row['role'] == 'expose':
        n_expose += 1

    answers = []
    for answer_id in answer_ids:
      counts = {}
      k_control = 0
      k_expose = 0
      for _, row in work.iterrows():
        if row['_parsed'].get(q) != answer_id:
          continue
        seg = '' if pd.isna(row['Segmentation']) else str(row['Segmentation'])
        counts[seg] = counts.get(seg, 0) + 1
        if row['role'] == 'control':
          k_control += 1
        elif row['role'] == 'expose':
          k_expose += 1
      p_control = (k_control / n_control) if n_control else float('nan')
      p_expose = (k_expose / n_expose) if n_expose else float('nan')
      ci_control = wilson_interval(k_control, n_control)
      ci_expose = wilson_interval(k_expose, n_expose)
      answers.append({
          'id': answer_id,
          'text': labels.get(answer_id, answer_id),
          'counts': counts,
          'total': sum(counts.values()),
          'k_control': k_control,
          'k_expose': k_expose,
          'p_control': p_control,
          'p_expose': p_expose,
          'ci_control': ci_control,
          'ci_expose': ci_expose,
          'lift': lift_ratio(p_expose, p_control),
          'pvalue': two_proportion_pvalue(
              k_expose, n_expose, k_control, n_control),
      })
    report['questions'].append({
        'index': q,
        'text': text or ('Question %s' % q),
        'answers': answers,
        'n_by_segment': n_by_segment,
        'n_control': n_control,
        'n_expose': n_expose,
    })
  return report
