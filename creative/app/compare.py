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
"""Multi-study compare page model (excludes Type=test)."""
import math
import re

import reporting

COMPARE_MAX_IDS = 30
_ID_RE = re.compile(r'^[A-Za-z0-9._\-]+$')


def parse_ids(raw, limit=COMPARE_MAX_IDS):
  """Ordered unique survey ids from a comma/space query string, capped."""
  seen = set()
  out = []
  text = str(raw or '')
  for token in re.split(r'[,+\s]+', text):
    token = token.strip()
    if not token or not _ID_RE.fullmatch(token) or token in seen:
      continue
    seen.add(token)
    out.append(token)
    if len(out) >= int(limit):
      break
  return out


def ids_query(ids):
  return ','.join(parse_ids(ids if isinstance(ids, str) else ','.join(ids or [])))


def _q1_a(report):
  for question in (report or {}).get('questions') or []:
    if question.get('index') != 1:
      continue
    for answer in question.get('answers') or []:
      if answer.get('id') == 'A':
        return answer, question
  questions = (report or {}).get('questions') or []
  if questions:
    answers = questions[0].get('answers') or []
    if answers:
      return answers[0], questions[0]
  return None, None


def _finite(value):
  try:
    number = float(value)
  except (TypeError, ValueError):
    return None
  if math.isnan(number) or not math.isfinite(number):
    return None
  return number


def _label(survey, survey_id):
  survey = survey or {}
  return (survey.get('displayname') or survey.get('surveyname') or survey_id)


def study_row(survey_id, survey, report):
  survey = survey or {}
  report = report or {}
  answer, question = _q1_a(report)
  answer = answer or {}
  is_lift = bool(report.get('is_lift') or survey.get('surveytype') == 'brand_lift')
  n_total = int(report.get('n_total') or 0)
  control_n = int(report.get('control_n') or 0)
  expose_n = int(report.get('expose_n') or 0)
  min_n = int(report.get('min_n') or reporting.MIN_N)
  lift = _finite(answer.get('lift')) if is_lift else None
  seq = report.get('sequential') or {}
  progress = _finite(seq.get('progress'))
  if progress is None and is_lift and min_n:
    progress = min(control_n / float(min_n), expose_n / float(min_n)) if (
        control_n or expose_n) else None
  below = bool(
      is_lift and (control_n < min_n or expose_n < min_n) and n_total)
  return {
      'id': survey_id,
      'label': _label(survey, survey_id),
      'client': (survey.get('client') or '').strip() or 'Unknown',
      'surveytype': survey.get('surveytype') or '',
      'is_lift': is_lift,
      'n_total': n_total,
      'control_n': control_n,
      'expose_n': expose_n,
      'min_n': min_n,
      'lift': lift,
      'pvalue': _finite(answer.get('pvalue')),
      'p_control': _finite(answer.get('p_control')),
      'p_expose': _finite(answer.get('p_expose')),
      'q1_text': (question or {}).get('text') or '',
      'answer_text': answer.get('text') or 'A',
      'progress': progress,
      'below_min_n': below,
      'empty_reason': report.get('empty_reason'),
      'daily': list(report.get('daily') or []),
  }


def group_by_client(rows):
  groups = {}
  order = []
  for row in rows:
    key = row['client']
    if key not in groups:
      groups[key] = {
          'client': key,
          'n_studies': 0,
          'lifts': [],
          'n_total': 0,
      }
      order.append(key)
    groups[key]['n_studies'] += 1
    groups[key]['n_total'] += row['n_total']
    if row['is_lift'] and row['lift'] is not None:
      groups[key]['lifts'].append(row['lift'])
  out = []
  for key in order:
    group = groups[key]
    lifts = group['lifts']
    group['mean_lift'] = (sum(lifts) / len(lifts)) if lifts else None
    out.append(group)
  return out


def chart_payload(rows):
  """JSON-serializable datasets for Chart.js (no NaN)."""
  lift_rows = [row for row in rows if row['is_lift']]
  lift_by_study = {
      'labels': [row['label'] for row in lift_rows],
      'ids': [row['id'] for row in lift_rows],
      'clients': [row['client'] for row in lift_rows],
      'values': [row['lift'] if row['lift'] is not None else None
                 for row in lift_rows],
      'below_min_n': [row['below_min_n'] for row in lift_rows],
  }
  clients = group_by_client(lift_rows)
  lift_by_client = {
      'labels': [group['client'] for group in clients],
      'values': [group['mean_lift'] for group in clients],
      'n_studies': [group['n_studies'] for group in clients],
  }
  dates = sorted({
      point.get('date') for row in rows for point in row['daily']
      if point.get('date')
  })
  daily = {
      'labels': dates,
      'datasets': [],
  }
  for row in rows:
    by_date = {}
    for point in row['daily']:
      day = point.get('date')
      if not day:
        continue
      by_date[day] = by_date.get(day, 0) + int(point.get('count') or 0)
    daily['datasets'].append({
        'label': row['label'],
        'id': row['id'],
        'data': [by_date.get(day, 0) for day in dates],
    })
  sample = {
      'labels': [row['label'] for row in rows],
      'n_total': [row['n_total'] for row in rows],
      'control_n': [row['control_n'] for row in rows],
      'expose_n': [row['expose_n'] for row in rows],
      'min_n': [row['min_n'] for row in rows],
      'progress': [
          None if row['progress'] is None else round(row['progress'] * 100, 1)
          for row in rows
      ],
      'is_lift': [row['is_lift'] for row in rows],
  }
  return {
      'lift_by_study': lift_by_study,
      'lift_by_client': lift_by_client,
      'daily': daily,
      'sample': sample,
  }


def build(studies):
  """studies: list of (survey_id, survey_dict, report_dict)."""
  rows = [study_row(sid, survey, report) for sid, survey, report in studies]
  truncated = len(studies) >= COMPARE_MAX_IDS
  return {
      'rows': rows,
      'clients': group_by_client(rows),
      'charts': chart_payload(rows),
      'n_studies': len(rows),
      'max_ids': COMPARE_MAX_IDS,
      'truncated': truncated,
      'min_n': reporting.MIN_N,
      'has_lift': any(row['is_lift'] for row in rows),
  }
