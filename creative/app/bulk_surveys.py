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
"""Bulk-create surveys from a CSV. Editor role only; preview then commit."""
import csv
import io
import json

import ad_macros
import brand
import creative_size
from forms import ANSWER_LETTERS
from forms import ANSWERS_SHUFFLED
from forms import BRAND_LIFT
from forms import BRAND_TRACK
from forms import DEFAULT_CSS
from forms import NEXT_END
from forms import RESPONSES_AT_END
from forms import RESPONSES_IMMEDIATELY

MAX_ROWS = 50
MAX_BYTES = 256 * 1024

LANGUAGE_CODES = (
    'en', 'ar', 'bn', 'cs', 'da', 'de', 'el', 'es', 'fa', 'fi', 'fr', 'gu',
    'he', 'hi', 'hu', 'id', 'it', 'ja', 'kn', 'ko', 'ml', 'mr', 'ms', 'nl',
    'no', 'pl', 'pt', 'ru', 'sv', 'ta', 'te', 'th', 'tl', 'tr', 'uk', 'ur',
    'vi', 'zh')

TEMPLATE_COLUMNS = (
    'surveyname',
    'displayname',
    'client',
    'agency',
    'campaign_id',
    'placement_id',
    'ad_server',
    'surveytype',
    'language',
    'responsetype',
    'creativesize',
    'badge_icon',
    'badge_text',
    'badge_name',
) + tuple(
    item
    for q in range(1, 6)
    for item in (
        ['question%s' % q] +
        ['answer%s%s' % (q, letter) for letter in ANSWER_LETTERS]
    )
)

EXAMPLE_ROW = {
    'surveyname': 'Acme lift 300x250',
    'displayname': 'Acme cola lift',
    'client': 'Acme',
    'agency': 'Example Media',
    'campaign_id': '',
    'placement_id': '',
    'ad_server': 'cm360',
    'surveytype': 'brand_lift',
    'language': 'en',
    'responsetype': 'end',
    'creativesize': '300x250',
    'badge_icon': 'B',
    'badge_text': '',
    'badge_name': 'Example Media',
    'question1': 'Which cola did you see advertised recently?',
    'answer1a': 'Example Cola',
    'answer1b': 'Other Cola',
}


def template_csv():
  buf = io.StringIO()
  writer = csv.DictWriter(buf, fieldnames=TEMPLATE_COLUMNS)
  writer.writeheader()
  writer.writerow({key: EXAMPLE_ROW.get(key, '') for key in TEMPLATE_COLUMNS})
  return buf.getvalue().encode('utf-8-sig')


def _cell(row, key):
  if not row:
    return ''
  for candidate in (key, key.lower(), key.replace('_', '')):
    if candidate in row and row[candidate] is not None:
      return str(row[candidate]).strip()
  return ''


def _parse_surveytype(raw):
  text = (raw or '').strip().lower().replace(' ', '_')
  if text in ('', 'brand_track', 'track', 'brandtrack'):
    return BRAND_TRACK, None
  if text in ('brand_lift', 'lift', 'brandlift'):
    return BRAND_LIFT, None
  return None, 'surveytype must be brand_track or brand_lift (got %s).' % raw


def _parse_responsetype(raw):
  text = (raw or '').strip().lower()
  if text in ('', 'end', 'at end', RESPONSES_AT_END.lower()):
    return RESPONSES_AT_END, None
  if text in (
      'each', 'immediately', 'after each', RESPONSES_IMMEDIATELY.lower()):
    return RESPONSES_IMMEDIATELY, None
  return None, 'responsetype must be end or each.'


def _parse_sizes(raw):
  text = (raw or '').replace('×', 'x').replace(';', ',')
  parts = [
      part.strip().lower().replace(' ', '')
      for part in text.split(',') if part.strip()
  ]
  if not parts:
    return [creative_size.DEFAULT_SIZE], None
  keys = []
  unknown = []
  for part in parts:
    if part in creative_size.SIZES:
      if part not in keys:
        keys.append(part)
    else:
      unknown.append(part)
  if unknown:
    return [], 'Unknown creative size(s): %s.' % ', '.join(unknown)
  return keys, None


def _parse_ad_server(raw):
  text = (raw or '').strip().lower()
  if not text:
    return ad_macros.DEFAULT_AD_SERVER, None
  if text in ad_macros.PRESETS:
    return text, None
  return None, 'ad_server must be cm360, dv360, gam, or generic.'


def _row_empty(row):
  return not any((value or '').strip() for value in (row or {}).values())


def validate_row(row, line_number):
  """Return {line, surveyname, ok, errors, payload}."""
  errors = []
  surveyname = _cell(row, 'surveyname')
  if not surveyname:
    errors.append('surveyname is required.')
  question1 = _cell(row, 'question1')
  if not question1:
    errors.append('question1 is required.')
  answer1a = _cell(row, 'answer1a')
  answer1b = _cell(row, 'answer1b')
  if not answer1a or not answer1b:
    errors.append('answer1a and answer1b are required.')

  surveytype, type_error = _parse_surveytype(_cell(row, 'surveytype'))
  if type_error:
    errors.append(type_error)
  responsetype, response_error = _parse_responsetype(_cell(row, 'responsetype'))
  if response_error:
    errors.append(response_error)
  sizes, size_error = _parse_sizes(_cell(row, 'creativesize'))
  if size_error:
    errors.append(size_error)
  ad_server, ad_error = _parse_ad_server(_cell(row, 'ad_server'))
  if ad_error:
    errors.append(ad_error)
  language = (_cell(row, 'language') or 'en').lower()
  if language not in LANGUAGE_CODES:
    errors.append('language must be one of the editor language codes.')

  payload = {
      'surveyname': surveyname,
      'displayname': _cell(row, 'displayname'),
      'client': _cell(row, 'client'),
      'agency': _cell(row, 'agency'),
      'campaign_id': _cell(row, 'campaign_id'),
      'placement_id': _cell(row, 'placement_id'),
      'ad_server': ad_server or ad_macros.DEFAULT_AD_SERVER,
      'surveytype': surveytype or BRAND_TRACK,
      'language': language if language in LANGUAGE_CODES else 'en',
      'responsetype': responsetype or RESPONSES_AT_END,
      'creativesize': sizes or [creative_size.DEFAULT_SIZE],
      'badge_icon': _cell(row, 'badge_icon') or brand.DEFAULT_BADGE_ICON,
      'badge_text': _cell(row, 'badge_text'),
      'badge_name': _cell(row, 'badge_name'),
      'custom_css': DEFAULT_CSS,
  }
  for q in range(1, 6):
    payload['question%s' % q] = _cell(row, 'question%s' % q)
    payload['question%stype' % q] = 'SINGLE_OPTION'
    payload['question%sorder' % q] = ANSWERS_SHUFFLED
    for letter in ANSWER_LETTERS:
      payload['answer%s%s' % (q, letter)] = _cell(
          row, 'answer%s%s' % (q, letter))
      payload['answer%s%snext' % (q, letter)] = NEXT_END
  for q in range(2, 6):
    qtext = payload.get('question%s' % q) or ''
    if qtext and (not payload.get('answer%sa' % q) or not payload.get('answer%sb' % q)):
      errors.append(
          'question%s has text so answer%sa and answer%sb are required.' % (
              q, q, q))

  limit = creative_size.max_answers(payload.get('creativesize'))
  extra = []
  for q in range(1, 6):
    for letter in ANSWER_LETTERS[limit:]:
      if payload.get('answer%s%s' % (q, letter)):
        extra.append('Q%s %s' % (q, letter.upper()))
  if extra:
    errors.append(
        'Answers F–H need every size to be 160×600 or 300×600 (%s).' %
        ', '.join(extra))

  return {
      'line': line_number,
      'surveyname': surveyname,
      'ok': not errors,
      'errors': errors,
      'payload': payload if not errors else None,
  }


def parse_csv(raw):
  """Parse CSV bytes or text. Returns (rows, file_errors)."""
  if raw is None:
    return [], ['Upload a CSV file.']
  if isinstance(raw, bytes):
    if len(raw) > MAX_BYTES:
      return [], ['CSV is larger than %s KB.' % (MAX_BYTES // 1024)]
    text = raw.decode('utf-8-sig', errors='replace')
  else:
    text = str(raw)
    if len(text.encode('utf-8')) > MAX_BYTES:
      return [], ['CSV is larger than %s KB.' % (MAX_BYTES // 1024)]
  try:
    reader = csv.DictReader(io.StringIO(text))
  except csv.Error as exc:
    return [], ['Could not parse CSV: %s' % exc]
  if not reader.fieldnames:
    return [], ['CSV has no header row.']
  fieldnames = [str(name or '').strip().lower() for name in reader.fieldnames]
  if 'surveyname' not in fieldnames:
    return [], ['CSV must include a surveyname column.']
  rows = []
  file_errors = []
  try:
    for index, row in enumerate(reader, start=2):
      if index - 1 > MAX_ROWS:
        file_errors.append(
            'Only the first %s data rows are imported.' % MAX_ROWS)
        break
      normalised = {}
      for key, value in (row or {}).items():
        normalised[str(key or '').strip().lower()] = value
      if _row_empty(normalised):
        continue
      rows.append(validate_row(normalised, index))
  except csv.Error as exc:
    return rows, ['Could not parse CSV: %s' % exc]
  if not rows and not file_errors:
    file_errors.append('CSV has no survey rows.')
  return rows, file_errors


def dumps_payloads(rows):
  payloads = [row['payload'] for row in rows if row.get('ok') and row.get('payload')]
  return json.dumps(payloads, ensure_ascii=True)


def loads_payloads(raw):
  try:
    data = json.loads(raw or '[]')
  except (TypeError, ValueError):
    return [], ['Could not read the previewed surveys. Upload the CSV again.']
  if not isinstance(data, list):
    return [], ['Could not read the previewed surveys. Upload the CSV again.']
  if len(data) > MAX_ROWS:
    return [], ['Too many surveys in this batch (max %s).' % MAX_ROWS]
  rows = []
  for index, payload in enumerate(data, start=1):
    if not isinstance(payload, dict):
      rows.append({
          'line': index,
          'surveyname': '',
          'ok': False,
          'errors': ['Invalid survey payload.'],
          'payload': None,
      })
      continue
    flat = {str(key): ('' if value is None else value) for key, value in payload.items()}
    if isinstance(flat.get('creativesize'), list):
      flat['creativesize'] = ','.join(str(item) for item in flat['creativesize'])
    rows.append(validate_row(flat, index))
  return rows, []
