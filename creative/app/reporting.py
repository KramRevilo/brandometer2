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

import cells as cells_mod
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


def segment_role(seg, cells=None):
  """Map a stored seg value to control, expose, holdout, or other.

  When the survey stores cells, the matching cell id wins. Surveys without
  cells keep the substring fallback (control / expos in the string).
  """
  return cells_mod.role_for_seg(seg, cells)


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


def wilson_margin(successes, n, z=Z_95):
  """Half-width of the Wilson score interval before clipping to [0, 1]."""
  if n is None or n <= 0:
    return float('nan')
  successes = max(0, min(int(successes), int(n)))
  n = float(n)
  p = successes / n
  z2 = z * z
  denom = 1.0 + z2 / n
  return z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n) / denom


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
  margin = wilson_margin(successes, n, z=z)
  return (max(0.0, center - margin), min(1.0, center + margin))


def two_proportion_z(successes_a, n_a, successes_b, n_b):
  """Pooled two-proportion z for p_a − p_b (expose − control when a is expose)."""
  if not n_a or not n_b:
    return float('nan')
  p_a = successes_a / float(n_a)
  p_b = successes_b / float(n_b)
  p_pool = (successes_a + successes_b) / float(n_a + n_b)
  se = math.sqrt(p_pool * (1.0 - p_pool) * (1.0 / n_a + 1.0 / n_b))
  if se == 0:
    if p_a == p_b:
      return 0.0
    return float('inf') if p_a > p_b else float('-inf')
  return (p_a - p_b) / se


def two_proportion_pvalue(successes_a, n_a, successes_b, n_b):
  """Two-sided two-proportion z-test p-value (pooled)."""
  z = two_proportion_z(successes_a, n_a, successes_b, n_b)
  if z is None or (isinstance(z, float) and math.isnan(z)):
    return float('nan')
  if not math.isfinite(z):
    return 0.0
  return math.erfc(abs(z) / math.sqrt(2.0))


def lift_ratio(p_expose, p_control):
  if p_control is None or p_control == 0 or (
      isinstance(p_control, float) and math.isnan(p_control)):
    return float('nan')
  return (p_expose - p_control) / p_control


def holm_adjust(pvalues):
  """Holm–Bonferroni adjusted p-values. NaN / None are skipped (not tests).

  Sort p1 ≤ p2 ≤ … ≤ pm, then p'_k = min(1, max_{j≤k} (m−j+1)·p_j).
  """
  n = len(pvalues or [])
  adjusted = [float('nan')] * n
  indexed = []
  for i, raw in enumerate(pvalues or []):
    if raw is None:
      continue
    try:
      p = float(raw)
    except (TypeError, ValueError):
      continue
    if math.isnan(p):
      continue
    indexed.append((i, max(0.0, min(1.0, p))))
  m = len(indexed)
  if not m:
    return adjusted
  indexed.sort(key=lambda item: item[1])
  running = 0.0
  for rank, (i, p) in enumerate(indexed):
    adj = min(1.0, p * (m - rank))
    if adj < running:
      adj = running
    running = adj
    adjusted[i] = adj
  return adjusted


def _finite_pvalue(value):
  if value is None:
    return False
  try:
    p = float(value)
  except (TypeError, ValueError):
    return False
  return not math.isnan(p)


def apply_holm_to_questions(questions):
  """Attach pvalue_adjusted on every answer. Returns the Holm family size."""
  answers = []
  for question in questions or []:
    answers.extend(question.get('answers') or [])
  raw = [answer.get('pvalue') for answer in answers]
  adjusted = holm_adjust(raw)
  for answer, adj in zip(answers, adjusted):
    answer['pvalue_adjusted'] = adj
  return sum(1 for value in raw if _finite_pvalue(value))


def _q1_a_counts(work, mask):
  n = k = 0
  if work is None or work.empty:
    return n, k
  for _, row in work.loc[mask].iterrows():
    parsed = row.get('_parsed') or {}
    if 1 not in parsed:
      continue
    n += 1
    if parsed.get(1) == 'A':
      k += 1
  return n, k


def cell_comparisons(work, survey_info):
  """Each extra expose cell vs pooled control (Q1 answer A), Holm across cells.

  Primary sequential / Result still pool every control vs every expose.
  Holdout and other cells are omitted. One expose cell is the primary arm,
  so this list is empty unless there are additional expose cells.
  """
  cells = cells_mod.normalize((survey_info or {}).get('cells'))
  extra = cells_mod.primary_cells(cells)[2]
  if work is None or work.empty or not extra:
    return []
  control_mask = work['role'] == 'control'
  n_c, k_c = _q1_a_counts(work, control_mask)
  rows = []
  for cell in extra:
    expose_mask = work['Segmentation'].fillna('').astype(str) == cell['id']
    n_e, k_e = _q1_a_counts(work, expose_mask)
    p_c = (k_c / n_c) if n_c else float('nan')
    p_e = (k_e / n_e) if n_e else float('nan')
    rows.append({
        'id': cell['id'],
        'label': cell['label'],
        'n_control': n_c,
        'n_expose': n_e,
        'k_control': k_c,
        'k_expose': k_e,
        'p_control': p_c,
        'p_expose': p_e,
        'lift': lift_ratio(p_e, p_c),
        'pvalue': two_proportion_pvalue(k_e, n_e, k_c, n_c),
        'pvalue_adjusted': float('nan'),
        'warning_n_small': n_c < MIN_N or n_e < MIN_N,
    })
  adjusted = holm_adjust([row['pvalue'] for row in rows])
  for row, adj in zip(rows, adjusted):
    row['pvalue_adjusted'] = adj
  return rows


BREAKOUT_DIMS = (
    ('size', 'CreativeSize', 'Size'),
    ('placement', 'PlacementID', 'Placement'),
    ('site', 'SiteID', 'Site'),
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
    'lift', 'pvalue', 'pvalue_adjusted', 'warning_n_small',
    'sequential_status',
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
          'pvalue_adjusted': float('nan'),
      })
    questions.append({
        'index': q,
        'text': text or ('Question %s' % q),
        'answers': answers,
        'n_by_segment': n_by_segment,
        'n_answered': n_answered,
        'n_control': n_control,
        'n_expose': n_expose,
        'warning_n_small': n_control < MIN_N or n_expose < MIN_N,
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
      family_questions = []
      for sl in slices:
        family_questions.extend(sl.get('questions') or [])
      n_tests = apply_holm_to_questions(family_questions)
      breakouts.append({
          'key': key,
          'label': label,
          'slices': slices,
          'n_tests': n_tests,
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
      'pvalue_adjusted': _csv_num(answer.get('pvalue_adjusted')),
      'warning_n_small': '1' if warning_n_small else '0',
      'sequential_status': (
          ((answer.get('sequential') or {}).get('status')) or ''),
  }


def breakout_csv_rows(report):
  """Flat rows for overall + every breakout slice."""
  report = report or {}
  rows = []
  overall_warning = bool(report.get('warning_n_small'))
  for question in report.get('questions') or []:
    warning = overall_warning or bool(question.get('warning_n_small'))
    for answer in question.get('answers') or []:
      rows.append(_csv_answer_row(
          'overall', 'all', question, answer, warning))
  for dim in report.get('breakouts') or []:
    for sl in dim.get('slices') or []:
      slice_warning = bool(sl.get('warning_n_small'))
      for question in sl.get('questions') or []:
        warning = slice_warning or bool(question.get('warning_n_small'))
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
      'n_tests': 0,
      'cell_comparisons': [],
      'cells': cells_mod.normalize(survey_info.get('cells')),
      'stats_notes': {
          'ci': 'Wilson score 95% CI on each arm (not Wald).',
          'test': 'Two-sided two-proportion z-test with pooled standard error.',
          'multiple_comparison': (
              'Holm–Bonferroni within the overall table (all answers) and '
              'separately within each breakout dimension (all slices × answers). '
              'Additional expose cells vs pooled control are a third family. '
              'Unadjusted p-values are still shown.'),
          'min_n': MIN_N,
      },
  }
  if n_total == 0:
    report['empty_reason'] = 'no_data'
    return report

  work = consolidated.copy()
  survey_cells = cells_mod.normalize(survey_info.get('cells'))
  work['role'] = work['Segmentation'].map(
      lambda seg: cells_mod.lift_role(seg, survey_cells))
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
  report['n_tests'] = apply_holm_to_questions(report['questions'])
  if is_lift:
    report['cell_comparisons'] = cell_comparisons(work, survey_info)
  report['breakouts'] = build_breakouts(work, survey_info, is_lift=is_lift)
  if is_lift:
    import sequential as sequential_mod
    sequential_mod.attach_to_report(report, survey_info.get('sample_plan'))
  return report
