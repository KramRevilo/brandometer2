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
import csv
import io
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


BREAKOUT_DIMS = (
    ('size', 'CreativeSize', 'Size'),
    ('placement', 'PlacementID', 'Placement'),
    ('creative', 'AdCreativeID', 'Creative ID'),
    ('version', 'CreativeVersion', 'Creative version'),
    ('date', '_date', 'Date'),
    ('segment', 'Segmentation', 'Segment'),
)
UNKNOWN_VERSION_LABEL = 'Unknown / pre-version'

BREAKOUT_CSV_HEADERS = (
    'dimension', 'slice', 'question_index', 'question', 'answer_id', 'answer',
    'n_answered', 'k', 'p', 'ci_lo', 'ci_hi',
    'n_control', 'k_control', 'p_control', 'ci_control_lo', 'ci_control_hi',
    'n_expose', 'k_expose', 'p_expose', 'ci_expose_lo', 'ci_expose_hi',
    'lift', 'pvalue', 'warning_n_small',
)


def _cell_text(value):
  if value is None or isinstance(value, bool):
    return ''
  if isinstance(value, float) and math.isnan(value):
    return ''
  if isinstance(value, float) and value.is_integer():
    return str(int(value))
  if isinstance(value, int):
    return str(value)
  text = str(value).strip()
  if text.lower() in ('nan', 'none', '<na>'):
    return ''
  if text.endswith('.0') and text[:-2].lstrip('-').isdigit():
    return text[:-2]
  return text


def _display_slice(value, blank='(blank)'):
  return value if value else blank


def question_stats(work, survey_info):
  """Answer distributions + lift for one already-sliced respondent frame."""
  survey_info = survey_info or {}
  questions = []
  if work is None or work.empty:
    return questions
  parsed_list = list(work['_parsed']) if '_parsed' in work.columns else []
  for q in range(1, 6):
    text = survey_info.get('question' + str(q)) or ''
    if not text and not any(q in parsed for parsed in parsed_list):
      continue
    labels = {}
    for letter in 'abcdefgh':
      label = survey_info.get('answer' + str(q) + letter) or ''
      if label:
        labels[letter.upper()] = label
    seen = set(labels)
    for parsed in parsed_list:
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
    n_answered = 0
    for _, row in work.iterrows():
      if q not in row['_parsed']:
        continue
      n_answered += 1
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
      k_total = 0
      for _, row in work.iterrows():
        if row['_parsed'].get(q) != answer_id:
          continue
        k_total += 1
        seg = '' if pd.isna(row['Segmentation']) else str(row['Segmentation'])
        counts[seg] = counts.get(seg, 0) + 1
        if row['role'] == 'control':
          k_control += 1
        elif row['role'] == 'expose':
          k_expose += 1
      p_all = (k_total / n_answered) if n_answered else float('nan')
      p_control = (k_control / n_control) if n_control else float('nan')
      p_expose = (k_expose / n_expose) if n_expose else float('nan')
      ci_all = wilson_interval(k_total, n_answered)
      ci_control = wilson_interval(k_control, n_control)
      ci_expose = wilson_interval(k_expose, n_expose)
      answers.append({
          'id': answer_id,
          'text': labels.get(answer_id, answer_id),
          'counts': counts,
          'total': sum(counts.values()),
          'k': k_total,
          'p': p_all,
          'ci': ci_all,
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
    questions.append({
        'index': q,
        'text': text or ('Question %s' % q),
        'answers': answers,
        'n_by_segment': n_by_segment,
        'n_answered': n_answered,
        'n_control': n_control,
        'n_expose': n_expose,
    })
  return questions


def _slice_summary(work, survey_info, value, blank='(blank)'):
  roles = work['role'] if 'role' in work.columns else pd.Series(dtype=str)
  control_n = int((roles == 'control').sum())
  expose_n = int((roles == 'expose').sum())
  return {
      'value': _display_slice(value, blank=blank),
      'n': int(len(work)),
      'control_n': control_n,
      'expose_n': expose_n,
      'warning_n_small': control_n < MIN_N or expose_n < MIN_N,
      'has_control': control_n > 0,
      'has_expose': expose_n > 0,
      'questions': question_stats(work, survey_info),
  }


def build_breakouts(work, survey_info, is_lift=False):
  """Per-dimension slices with the same lift / CI math as the overall report."""
  del is_lift  # lift columns are always computed; UI hides them for Track
  if work is None or work.empty:
    return []
  breakouts = []
  for key, column, label in BREAKOUT_DIMS:
    if column not in work.columns:
      continue
    values = {_cell_text(v) for v in work[column].tolist()}
    nonempty = sorted(v for v in values if v)
    ordered = nonempty + ([''] if '' in values else [])
    if not nonempty:
      continue
    slices = []
    blanked = work[column].map(_cell_text)
    for value in ordered:
      slice_df = work.loc[blanked == value]
      if slice_df.empty:
        continue
      slices.append(_slice_summary(
          slice_df, survey_info, value,
          blank=UNKNOWN_VERSION_LABEL if key == 'version' else '(blank)'))
    if slices:
      breakouts.append({
          'key': key,
          'label': label,
          'slices': slices,
      })
  return breakouts


def _csv_num(value):
  if value is None:
    return ''
  if isinstance(value, float) and math.isnan(value):
    return ''
  if isinstance(value, float):
    return '%.6f' % value
  return str(value)


def _csv_answer_row(dimension, slice_value, question, answer, warning_n_small):
  ci = answer.get('ci') or (float('nan'), float('nan'))
  ci_c = answer.get('ci_control') or (float('nan'), float('nan'))
  ci_e = answer.get('ci_expose') or (float('nan'), float('nan'))
  return {
      'dimension': dimension,
      'slice': slice_value,
      'question_index': question['index'],
      'question': question['text'],
      'answer_id': answer['id'],
      'answer': answer['text'],
      'n_answered': question.get('n_answered', 0),
      'k': answer.get('k', answer.get('total', 0)),
      'p': _csv_num(answer.get('p')),
      'ci_lo': _csv_num(ci[0]),
      'ci_hi': _csv_num(ci[1]),
      'n_control': question.get('n_control', 0),
      'k_control': answer.get('k_control', 0),
      'p_control': _csv_num(answer.get('p_control')),
      'ci_control_lo': _csv_num(ci_c[0]),
      'ci_control_hi': _csv_num(ci_c[1]),
      'n_expose': question.get('n_expose', 0),
      'k_expose': answer.get('k_expose', 0),
      'p_expose': _csv_num(answer.get('p_expose')),
      'ci_expose_lo': _csv_num(ci_e[0]),
      'ci_expose_hi': _csv_num(ci_e[1]),
      'lift': _csv_num(answer.get('lift')),
      'pvalue': _csv_num(answer.get('pvalue')),
      'warning_n_small': '1' if warning_n_small else '0',
  }


def breakout_csv_rows(report):
  """Flat rows for overall + every breakout slice."""
  report = report or {}
  rows = []
  overall_warning = bool(report.get('warning_n_small'))
  for question in report.get('questions') or []:
    for answer in question.get('answers') or []:
      rows.append(_csv_answer_row(
          'overall', 'all', question, answer, overall_warning))
  for dim in report.get('breakouts') or []:
    for sl in dim.get('slices') or []:
      warning = bool(sl.get('warning_n_small'))
      for question in sl.get('questions') or []:
        for answer in question.get('answers') or []:
          rows.append(_csv_answer_row(
              dim['label'], sl['value'], question, answer, warning))
  return rows


def breakouts_to_csv(report):
  buf = io.StringIO()
  writer = csv.DictWriter(buf, fieldnames=list(BREAKOUT_CSV_HEADERS))
  writer.writeheader()
  for row in breakout_csv_rows(report):
    writer.writerow(row)
  return buf.getvalue()


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
      'breakouts': [],
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

  report['questions'] = question_stats(work, survey_info)
  report['breakouts'] = build_breakouts(work, survey_info, is_lift=is_lift)
  return report
