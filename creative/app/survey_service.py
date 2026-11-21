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

"""Various imports to be used for survey functionalites."""
import datetime
import io
import logging
import math
import os
import re
import threading
import time
import zipfile
import access
import brand
import css_theme
import receiver_crypto
from flask import flash
from flask import render_template
from markupsafe import Markup
from google.api_core.exceptions import NotFound
from google.cloud import bigquery
from google.cloud import bigquery_storage
import numpy as np
import pandas as pd
import creative_size
import ad_macros
import bulk_upload
import html5_qa
import reporting
import respondent
import survey_collection
from forms import ANSWER_LETTERS
from forms import BRAND_LIFT
from forms import BRAND_TRACK
from forms import DEFAULT_CSS
from forms import RESPONSES_AT_END

UNKNOWN_YEAR = 'unknown'
UNKNOWN_CREATOR = 'unknown'
DEFAULT_SORT_KEY = 'created_at'
DEFAULT_SORT_DIR = 'desc'
SORT_KEYS = (
    'created_at', 'name', 'id', 'client', 'agency', 'created_by', 'sizes',
)
_IDENTITY_KEYS = (
    'client', 'agency', 'campaign_id', 'placement_id', 'ad_server')
_FORM_META_KEYS = ('csrf_token', 'submit', 'last_update_time')

# Homepage status chips. Active <= 3 days, Stale <= 7, Timed out after that.
# 2022 backlog (yellow at 7 days). Previously Stale ran through 14 days.
STATUS_ACTIVE_DAYS = 3
STATUS_STALE_DAYS = 7
# Homepage list page size. Not an env var — change this constant to retune.
HOMEPAGE_PAGE_SIZE = 50
STATS_POLL_SECONDS = 30
_DEFAULT_STATS_CACHE_SECONDS = 90
_DEFAULT_STATS_LOOKBACK_DAYS = 400
_MRC_INIT = 999999999

_log = logging.getLogger(__name__)
_stats_lock = threading.Lock()
_stats_cache = {'by_id': {}, 'expires_at': 0.0}

_bq_client = None
_bqstorage_client = None


def _get_bq_client(project_id=None):
  """Return a BigQuery client, created on first use."""
  global _bq_client
  if _bq_client is None:
    _bq_client = bigquery.Client(project=project_id or os.environ.get('PROJECT_ID'))
  return _bq_client


def _get_bqstorage_client():
  """Return a BigQuery Storage client, created on first use."""
  global _bqstorage_client
  if _bqstorage_client is None:
    _bqstorage_client = bigquery_storage.BigQueryReadClient()
  return _bqstorage_client


_EMPTY_RESPONSES_COLUMNS = [
    'CreatedAt', 'Segmentation', 'Response', 'BomID',
    'RespondentID', 'RespondentIDSource',
    'CampaignID', 'PlacementID', 'SiteID', 'AdCreativeID',
    'CreativeSize', 'CreativeVersion',
]
CSV_CHUNK_ROWS = 500
_RESPONSE_SELECT = """
        SELECT CreatedAt, Segmentation, Response, BomID,
               RespondentID, RespondentIDSource,
               CampaignID, PlacementID, SiteID, AdCreativeID,
               CreativeSize, CreativeVersion
        FROM `{table}`
        WHERE ID = @survey_id
    """
_EMPTY_COUNTS_COLUMNS = [
    'ID', 'Segmentation', 'max_date', 'days_since_response', 'response_count'
]


def _empty_frame(columns):
  return pd.DataFrame(columns=columns)


def _concat_frames(frames, **kwargs):
  """pd.concat that drops empty frames so pandas does not FutureWarning."""
  kept = [frame for frame in frames if frame is not None and not frame.empty]
  if not kept:
    if frames:
      return frames[0]
    return pd.DataFrame()
  if len(kept) == 1:
    out = kept[0]
    if kwargs.get('ignore_index'):
      return out.reset_index(drop=True)
    return out
  return pd.concat(kept, **kwargs)


def _query_to_dataframe(query, job_config=None, client=None, empty_columns=None):
  """Run a BigQuery SQL job. Missing tables return an empty frame, not an error."""
  empty = _empty_frame(empty_columns or _EMPTY_RESPONSES_COLUMNS)
  project_id = os.environ.get('PROJECT_ID')
  if client is None:
    client = _get_bq_client(project_id)
  try:
    if job_config is None:
      query_job = client.query(query)
    else:
      query_job = client.query(query, job_config=job_config)
    bqstorageclient = _get_bqstorage_client()
    return query_job.result().to_dataframe(bqstorage_client=bqstorageclient)
  except NotFound:
    return empty

def get_all():
  return survey_collection.get_all()


def get_doc_by_id(survey_id):
  return survey_collection.get_doc_by_id(survey_id)


def get_by_id(survey_id):
  return survey_collection.get_by_id(survey_id)


def delete_by_id(survey_id):
  actor = access.actor_email()
  result = survey_collection.delete_by_id(survey_id)
  access.write_audit('delete', actor, survey_id=survey_id)
  return result


def is_archived(survey):
  data = survey.to_dict() if hasattr(survey, 'to_dict') else (survey or {})
  return data.get('archived') is True


def _survey_data(survey):
  if hasattr(survey, 'to_dict'):
    return survey.to_dict() or {}
  return survey or {}


def parse_created_at(value):
  """Parse stored created_at to aware UTC datetime, or None."""
  if value is None or value == '':
    return None
  if isinstance(value, datetime.datetime):
    if value.tzinfo is None:
      return value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)
  text = str(value).strip()
  if not text:
    return None
  if text.endswith('Z'):
    text = text[:-1] + '+00:00'
  try:
    parsed = datetime.datetime.fromisoformat(text)
  except ValueError:
    return None
  if parsed.tzinfo is None:
    parsed = parsed.replace(tzinfo=datetime.timezone.utc)
  return parsed.astimezone(datetime.timezone.utc)


def created_year(survey):
  """Calendar year of created_at, or None when missing/unparseable (unknown)."""
  data = _survey_data(survey)
  parsed = parse_created_at(data.get('created_at'))
  if parsed is None:
    raw = data.get('created_at')
    if raw is None or raw == '':
      return None
    text = str(raw).strip()
    if len(text) >= 4 and text[:4].isdigit():
      year = int(text[:4])
      if 1990 <= year <= 2100:
        return str(year)
    return None
  return str(parsed.year)


def created_at_display(survey):
  """YYYY-MM-DD for the table, or empty when unknown."""
  parsed = parse_created_at(_survey_data(survey).get('created_at'))
  if parsed is None:
    return ''
  return parsed.strftime('%Y-%m-%d')


def created_at_title(survey):
  parsed = parse_created_at(_survey_data(survey).get('created_at'))
  if parsed is None:
    return ''
  return parsed.strftime('%Y-%m-%dT%H:%M:%SZ')


def created_by_email(survey):
  return (_survey_data(survey).get('created_by') or '').strip()


def created_by_display(survey):
  return created_by_email(survey) or 'Unknown'


_GENERIC_SEGMENTS = frozenset(('', 'survey', 'unnamed', '<unnamed>', 'default'))
_SEGMENT_SHORT = {
    'default_control': 'C',
    'default_expose': 'E',
    'control': 'C',
    'expose': 'E',
    'exposed': 'E',
}


def short_segment_label(name):
  """One-letter (or short) label for a homepage count segment."""
  text = (name or '').strip()
  key = text.lower()
  if key in _SEGMENT_SHORT:
    return _SEGMENT_SHORT[key]
  if 'control' in key:
    return 'C'
  if 'expos' in key:
    return 'E'
  if not text:
    return '?'
  token = re.split(r'[\s_]+', text)[-1] or text
  if len(token) <= 3:
    return token[:1].upper() + token[1:]
  return token[:1].upper()


def compact_count(item):
  """One-line count cell: {'text', 'title'}.

  Brand Lift control/expose becomes 'C 40 · E 42'. A single generic segment
  (survey / unnamed / default) is just the number. Full labels stay in title.
  """
  empty = {'text': '', 'title': ''}
  if not item:
    return empty
  segs = item.get('stats') if isinstance(item, dict) else None
  if not segs:
    return empty
  full = []
  shorts = []
  for seg in segs:
    name = (seg.get('Segmentation') or '').strip()
    label = name or 'Unnamed'
    raw = seg.get('response_count')
    try:
      count = int(raw)
    except (TypeError, ValueError):
      count = raw
    full.append('%s: %s' % (label, count))
    shorts.append((short_segment_label(name), count, name.lower()))
  title = ' · '.join(full)
  if len(shorts) == 1:
    short, count, key = shorts[0]
    if key in _GENERIC_SEGMENTS:
      return {'text': str(count), 'title': title}
    return {'text': '%s %s' % (short, count), 'title': title}
  text = ' · '.join('%s %s' % (short, count) for short, count, _ in shorts)
  return {'text': text, 'title': title}


def sizes_compact(keys):
  """First size plus '+N' when there are more. Title is the full list."""
  keys = list(keys or [])
  if not keys:
    return {'text': '', 'title': ''}
  labels = [str(key).replace('x', '×') for key in keys]
  title = ', '.join(labels)
  if len(labels) == 1:
    return {'text': labels[0], 'title': title}
  return {
      'text': '%s +%d' % (labels[0], len(labels) - 1),
      'title': title,
  }


def survey_identity_line(survey):
  data = _survey_data(survey)
  parts = []
  client = (data.get('client') or '').strip()
  agency = (data.get('agency') or '').strip()
  if client:
    parts.append(client)
  if agency:
    parts.append(agency)
  return ' · '.join(parts)


def homepage_filter_options(surveys):
  clients = set()
  agencies = set()
  years = set()
  creators = set()
  has_unknown_year = False
  has_unknown_creator = False
  for survey in surveys:
    data = _survey_data(survey)
    client = (data.get('client') or '').strip()
    agency = (data.get('agency') or '').strip()
    creator = (data.get('created_by') or '').strip()
    if client:
      clients.add(client)
    if agency:
      agencies.add(agency)
    if creator:
      creators.add(creator)
    else:
      has_unknown_creator = True
    year = created_year(data)
    if year:
      years.add(year)
    else:
      has_unknown_year = True
  return {
      'clients': sorted(clients, key=lambda value: (value.lower(), value)),
      'agencies': sorted(agencies, key=lambda value: (value.lower(), value)),
      'creators': sorted(creators, key=lambda value: (value.lower(), value)),
      'years': sorted(years, reverse=True),
      'has_unknown_year': has_unknown_year,
      'has_unknown_creator': has_unknown_creator,
  }


def survey_size_keys(survey):
  """Configured creative sizes for a survey doc or dict. Legacy docs get 300x250."""
  return creative_size.selected_keys(_survey_data(survey))


def apply_homepage_filters(
    surveys, q='', client='', agency='', year='', size='', created_by=''):
  """Filter in Python so Firestore stays a single select() of list fields."""
  q = (q or '').strip().lower()
  client = (client or '').strip()
  agency = (agency or '').strip()
  year = (year or '').strip()
  size = (size or '').strip()
  created_by = (created_by or '').strip()
  matched = []
  for survey in surveys:
    data = _survey_data(survey)
    if client and (data.get('client') or '').strip() != client:
      continue
    if agency and (data.get('agency') or '').strip() != agency:
      continue
    if created_by:
      creator = (data.get('created_by') or '').strip()
      if created_by == UNKNOWN_CREATOR:
        if creator:
          continue
      elif creator != created_by:
        continue
    if year:
      survey_year = created_year(data)
      if year == UNKNOWN_YEAR:
        if survey_year is not None:
          continue
      elif survey_year != year:
        continue
    if size and size not in survey_size_keys(data):
      continue
    if q:
      name = (data.get('surveyname') or '')
      display = (data.get('displayname') or '')
      if q not in name.lower() and q not in display.lower():
        continue
    matched.append(survey)
  return matched


def parse_sort(sort_key, direction):
  key = (sort_key or DEFAULT_SORT_KEY).strip().lower()
  if key not in SORT_KEYS:
    key = DEFAULT_SORT_KEY
  direction = (direction or DEFAULT_SORT_DIR).strip().lower()
  if direction not in ('asc', 'desc'):
    direction = DEFAULT_SORT_DIR
  return key, direction


def sort_surveys(surveys, sort_key=DEFAULT_SORT_KEY, direction=DEFAULT_SORT_DIR):
  """Sort the homepage list. Missing created_at / created_by always sort last."""
  key, direction = parse_sort(sort_key, direction)
  reverse = direction == 'desc'

  def _text(value):
    return (value or '').strip().lower()

  def _missing_last(value):
    text = _text(value)
    if not text:
      return (1, '')
    return (0, text)

  def sort_item(survey):
    data = _survey_data(survey)
    sid = getattr(survey, 'id', '') or ''
    if key == 'created_at':
      parsed = parse_created_at(data.get('created_at'))
      if parsed is None:
        stamp = (1, 0.0)
      else:
        stamp = (0, -parsed.timestamp() if reverse else parsed.timestamp())
      return stamp + (sid,)
    if key == 'name':
      label = _text(data.get('displayname') or data.get('surveyname'))
      return ((1, '') if not label else (0, label), sid)
    if key == 'id':
      return (_text(sid),)
    if key == 'client':
      return (_missing_last(data.get('client')), sid)
    if key == 'agency':
      return (_missing_last(data.get('agency')), sid)
    if key == 'created_by':
      return (_missing_last(data.get('created_by')), sid)
    if key == 'sizes':
      sizes = survey_size_keys(data)
      return (_missing_last(','.join(sizes)), sid)
    return (sid,)

  if key == 'created_at':
    return sorted(surveys, key=sort_item)
  if key in ('name', 'client', 'agency', 'created_by', 'sizes'):
    return sorted(surveys, key=sort_item, reverse=reverse)
  return sorted(surveys, key=sort_item, reverse=reverse)


def identity_suggestions():
  """Distinct client/agency values for editor datalists."""
  clients = set()
  agencies = set()
  try:
    docs = survey_collection.get_all(survey_collection.IDENTITY_SUGGESTION_FIELDS)
  except Exception:
    return {'clients': [], 'agencies': []}
  for doc in docs:
    data = _survey_data(doc)
    client = (data.get('client') or '').strip()
    agency = (data.get('agency') or '').strip()
    if client:
      clients.add(client)
    if agency:
      agencies.add(agency)
  return {
      'clients': sorted(clients, key=lambda value: (value.lower(), value)),
      'agencies': sorted(agencies, key=lambda value: (value.lower(), value)),
  }


def _strip_identity(data):
  payload = dict(data or {})
  for key in _FORM_META_KEYS:
    payload.pop(key, None)
  for key in _IDENTITY_KEYS:
    if key in payload and payload[key] is not None:
      payload[key] = str(payload[key]).strip()
  return payload


def list_surveys(include_archived=False):
  surveys = list(survey_collection.get_all(survey_collection.LIST_FIELDS))
  if include_archived:
    surveys = [survey for survey in surveys if is_archived(survey)]
  else:
    surveys = [survey for survey in surveys if not is_archived(survey)]
  return surveys


def paginate_surveys(surveys, page=1, page_size=HOMEPAGE_PAGE_SIZE):
  """Slice surveys into a page. Out-of-range pages clamp to the last page."""
  surveys = list(surveys)
  total = len(surveys)
  try:
    page = int(page)
  except (TypeError, ValueError):
    page = 1
  try:
    page_size = int(page_size)
  except (TypeError, ValueError):
    page_size = HOMEPAGE_PAGE_SIZE
  page_size = max(1, page_size)
  total_pages = max(1, math.ceil(total / page_size)) if total else 1
  page = max(1, min(page, total_pages))
  start = (page - 1) * page_size
  page_items = surveys[start:start + page_size]
  return page_items, {
      'page': page,
      'page_size': page_size,
      'total': total,
      'total_pages': total_pages,
      'has_prev': page > 1,
      'has_next': page < total_pages,
  }


def build_stat_array(survey_ids, counts_df=None):
  """Per-survey count / last-response / status from the (cached) BQ summary."""
  if counts_df is None:
    counts_df = get_response_counts(survey_ids)
  stat_array = []
  for survey_id in survey_ids:
    df = counts_df.loc[counts_df['ID'] == survey_id]
    segmentation_rows = df.to_dict()
    most_recent_change = _MRC_INIT
    segs = []
    for x in segmentation_rows.get('ID', {}):
      days = segmentation_rows['days_since_response'][x]
      segs.append({
          'Segmentation': segmentation_rows['Segmentation'][x],
          'response_count': segmentation_rows['response_count'][x],
          'days_since_response': days,
      })
      if days < most_recent_change:
        most_recent_change = days
    if most_recent_change == _MRC_INIT:
      days_since = None
      last_change_display = ''
    else:
      days_since = most_recent_change
      last_change_display = most_recent_change
    status_text, status_label = classify_status(days_since)
    stat_array.append({
        'id': survey_id,
        'stats': segs,
        'last_change': last_change_display,
        'status': status_text,
        'status_label': status_label,
    })
  return stat_array


def set_archived(survey_id, archived):
  actor = access.actor_email()
  result = survey_collection.set_archived(survey_id, archived, actor=actor)
  access.write_audit(
      'archive' if archived else 'restore', actor, survey_id=survey_id)
  return result


def copy_by_id(survey_id):
  actor = access.actor_email()
  result = survey_collection.copy(survey_id, actor=actor)
  if result is not None:
    access.write_audit(
        'copy', actor, survey_id=survey_id, detail=result.id)
  return result


def is_brand_lift(survey):
  if hasattr(survey, 'to_dict'):
    data = survey.to_dict() or {}
  elif isinstance(survey, dict):
    data = survey
  else:
    data = {}
  return data.get('surveytype') == BRAND_LIFT


def survey_label(survey):
  data = survey.to_dict() if hasattr(survey, 'to_dict') else (survey or {})
  data = data or {}
  return data.get('displayname') or data.get('surveyname') or getattr(
      survey, 'id', '')


def classify_status(days_since_response):
  """Return (label, Bootstrap 5 text-bg-*) for homepage badges.

  days_since_response is None when the survey has no BQ rows.
  """
  if days_since_response is None:
    return 'No data', 'secondary'
  if days_since_response <= STATUS_ACTIVE_DAYS:
    return 'Active', 'success'
  if days_since_response <= STATUS_STALE_DAYS:
    return 'Stale', 'warning'
  return 'Timed out', 'danger'


def create_from_payload(data, flash_created=True):
  """Persist a survey dict (editor form or bulk CSV)."""
  payload = brand.persist_badge(_strip_identity(dict(data or {})))
  payload, _ = creative_size.persist_sizes(payload)
  payload['archived'] = False
  actor = access.actor_email()
  now = survey_collection.utc_now_iso()
  if not payload.get('created_at'):
    payload['created_at'] = now
  payload['created_by'] = actor
  payload['updated_at'] = now
  payload['updated_by'] = actor
  doc_ref = survey_collection.create(payload)
  name = payload.get('surveyname') or doc_ref.id
  access.write_audit(
      'create', actor, survey_id=doc_ref.id, detail=name)
  if flash_created:
    flash('%s created as %s' % (name, doc_ref.id))
  return doc_ref


def create(form):
  return create_from_payload(dict(form.data), flash_created=True)


def save_sample_plan(survey_id, plan):
  """Store planner inputs (and planned n) without rewriting the rest of the survey."""
  payload = {'sample_plan': dict(plan or {})}
  actor = access.actor_email()
  payload['updated_at'] = survey_collection.utc_now_iso()
  payload['updated_by'] = actor
  survey_collection.update_by_id(survey_id, payload)
  access.write_audit(
      'sample_plan', actor, survey_id=survey_id,
      detail='n_control=%s n_expose=%s' % (
          payload['sample_plan'].get('n_control'),
          payload['sample_plan'].get('n_expose')))
  return payload['sample_plan']


def update_by_id(survey_id, form, last_update_time=None):
  data, _ = creative_size.persist_sizes(
      brand.persist_badge(_strip_identity(form.data)))
  actor = access.actor_email()
  data['updated_at'] = survey_collection.utc_now_iso()
  data['updated_by'] = actor
  data.pop('created_by', None)
  data.pop('created_at', None)
  edit_doc = survey_collection.update_by_id(
      survey_id, data, last_update_time=last_update_time)
  access.write_audit(
      'edit', actor, survey_id=survey_id, detail=form.surveyname.data)
  flash(f'{form.surveyname.data} updated')
  return edit_doc


def set_form_data(form, edit_doc):
  edit_doc_dict = edit_doc.to_dict()

  for key, value in edit_doc_dict.items():
    if key in form:
      form[key].data = edit_doc.get(key,)
  if 'creativesize' in form:
    form['creativesize'].data = creative_size.selected_keys(edit_doc_dict)


def zip_file(survey_id, survey_dict, record_version=True):
  """Outer ZIP of one HTML5 inner ZIP per size (and per Brand Lift segment)."""
  when = datetime.datetime.now()
  current_datetime = when.strftime('%Y%m%d')
  surveyname = (survey_dict.get('surveyname') or 'survey').replace(' ', '-')
  size_keys = creative_size.selected_keys(survey_dict)
  survey_type = survey_dict.get('surveytype', BRAND_TRACK)
  if survey_type == BRAND_LIFT:
    seg_types = ['default_control', 'default_expose']
  else:
    seg_types = ['']

  if 'responsetype' not in survey_dict:
    survey_dict['responsetype'] = RESPONSES_AT_END

  # Snapshot first so the HTML can bake the same version into the signed pixel.
  creative_version = None
  if record_version:
    snapshot = survey_collection.add_version(
        survey_id, survey_dict, actor=access.actor_email())
    creative_version = receiver_crypto.parse_creative_version(
        (snapshot or {}).get('version'))
  else:
    creative_version = receiver_crypto.parse_creative_version(
        (survey_dict or {}).get('version'))

  template_zips = []
  for size_key in size_keys:
    prefix = current_datetime + '_' + surveyname + '_' + size_key
    template_zips.extend(
        write_html_template(
            survey_id, survey_dict, prefix, seg_types, size_key=size_key,
            creative_version=creative_version))
  findings = []
  receiver_url = os.environ.get('RECEIVER_URL') or ''
  for inner in template_zips:
    inner_name = os.path.basename(inner.filename)
    findings.extend(html5_qa.check_inner_zip(
        inner.filename, filename=inner_name,
        size_key=html5_qa.size_key_from_filename(inner_name),
        receiver_url=receiver_url))
  outer_name = creative_size.outer_zip_basename(
      current_datetime, surveyname, size_keys)
  outer_stem = outer_name[:-4] if outer_name.endswith('.zip') else outer_name
  extra_files = [('html5_qa.txt', html5_qa.format_report(findings))]
  extra_files.extend(bulk_upload.sidecar_files(
      survey_id, survey_dict, when=when, creative_version=creative_version))
  combined_zip = zip_dir(
      outer_stem, template_zips, extra_files=extra_files)

  with open(combined_zip.filename, 'rb') as file:
    file_data = io.BytesIO(file.read())

  delete_tmp_zip_files([combined_zip] + template_zips)

  return os.path.basename(combined_zip.filename), file_data


def zip_dir(filename, template_zips, extra_files=None):
  with zipfile.ZipFile('/tmp/' + filename + '.zip', 'w',
                       zipfile.ZIP_DEFLATED) as zipdir:
    for inner in template_zips:
      zipdir.write(inner.filename, arcname=os.path.basename(inner.filename))
    for name, content in extra_files or []:
      zipdir.writestr(name, content)
  return zipdir


def write_html_template(survey_id, survey_dict, prefix_filename, seg_types,
                        size_key=None, creative_version=None):
  template_zips = []
  date_stamp = datetime.datetime.now().strftime('%Y%m%d')
  surveyname = (survey_dict.get('surveyname') or 'survey').replace(' ', '-')
  resolved_key = size_key or creative_size.resolve(survey_dict)['key']

  for seg_type in seg_types:
    file_suffix = seg_type if seg_type else 'creative'
    inner_name = creative_size.inner_zip_basename(
        date_stamp, surveyname, resolved_key, file_suffix)
    # Tests pass a prefix like test_prefix; honour it when it is not a dated name.
    if prefix_filename and not re.match(r'^\d{8}_', prefix_filename or ''):
      path = '/tmp/' + prefix_filename + '_' + file_suffix + '.zip'
    else:
      path = '/tmp/' + inner_name
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zip_write_file:
      zip_write_file.writestr(
          'index.html',
          get_html_template(
              survey_id, survey_dict, seg_type, size=resolved_key,
              creative_version=creative_version))
      template_zips.append(zip_write_file)

  return template_zips


def get_html_template(survey_id, survey_dict, seg_type, size=None,
                      creative_version=None):
  if 'custom_css' in survey_dict:
    custom_css = survey_dict['custom_css']
  else:
    custom_css = DEFAULT_CSS
  spec = creative_size.resolve(size or survey_dict)
  custom_css = Markup(creative_size.apply_overlay(
      css_theme.sanitize_user_css(custom_css), spec))

  receiver_url = os.environ.get('RECEIVER_URL') or ''
  hmac_secret = ''
  try:
    from flask import current_app
    hmac_secret = current_app.config.get('RECEIVER_HMAC_SECRET') or ''
  except Exception:
    hmac_secret = os.environ.get('RECEIVER_HMAC_SECRET') or ''
  creative_version = receiver_crypto.parse_creative_version(creative_version)
  receiver_token = receiver_crypto.survey_token(
      survey_id, hmac_secret, version=creative_version)
  macro_vars = ad_macros.render_vars(survey_dict)
  return render_template(
      'creative.html',
      survey=survey_dict,
      survey_id=survey_id,
      show_back_button=False,
      response_type=survey_dict.get('responsetype', RESPONSES_AT_END),
      all_question_json=get_question_json(survey_dict),
      seg=seg_type,
      custom_css=custom_css,
      creative_width=spec['width'],
      creative_height=spec['height'],
      size_key=spec['key'],
      size_layout=spec.get('layout') or 'stack',
      ad_size_meta=creative_size.ad_size_meta(spec),
      thankyou_text=get_thank_you_text(survey_dict),
      next_text=get_next_text(survey_dict),
      comment_text=get_comment_text(survey_dict),
      brand_name=brand.brand_name(),
      receiver_url=receiver_url,
      receiver_token=receiver_token,
      creative_version=creative_version,
      **macro_vars,
      **brand.badge_render_vars(survey_dict))


def html5_qa_for_survey(survey_id, survey_dict):
  """IAB/CM360/DV360 warnings for each selected size (HTML, not a zip)."""
  survey_dict = dict(survey_dict or {})
  size_keys = creative_size.selected_keys(survey_dict)
  receiver_url = os.environ.get('RECEIVER_URL') or ''
  findings = []
  seen = set()
  for size_key in size_keys:
    html = get_html_template(survey_id or 'draft', survey_dict, '', size=size_key)
    for item in html5_qa.check_html(
        html, size_key=size_key, target=size_key, receiver_url=receiver_url):
      key = (item.get('code'), item.get('message'), item.get('target'))
      if key in seen:
        continue
      seen.add(key)
      findings.append(item)
  return findings


def flash_zip_html5_qa(data):
  """Flash HTML5 spec warnings from html5_qa.txt in an outer zip BytesIO."""
  try:
    data.seek(0)
    with zipfile.ZipFile(data) as zf:
      if 'html5_qa.txt' not in zf.namelist():
        return
      report = zf.read('html5_qa.txt').decode('utf-8', 'replace')
  except Exception:
    return
  finally:
    try:
      data.seek(0)
    except Exception:
      pass
  count = report.count('[warning]') + report.count('[error]')
  if count:
    flash(
        'HTML5 spec: %s warning(s). See html5_qa.txt inside the zip.' % count,
        'warning')


def delete_tmp_zip_files(zipfiles):
  for zipfile in zipfiles:
    os.remove(zipfile.filename)


def get_all_question_text(survey):
  all_question_text = []
  for i in range(1, 6):
    question_text = survey.get('question' + str(i), '')
    if question_text:
      all_question_text.append(question_text)
  return all_question_text


def get_question_json(survey):
  """Retrieving questions from survey in JSON format.

  Answers a–e with empty text are skipped so 2–5 option questions all work.
  Missing next values default to 'end'.
  """
  all_question_json = []
  for i in range(1, 6):
    question_text = survey.get('question' + str(i), '')
    if not question_text:
      continue
    options = []
    next_question = {}
    question_type = survey.get('question' + str(i) + 'type')
    answers_order = survey.get('question' + str(i) + 'order')
    question = {
        'id': i,
        'type': question_type,
        'text': question_text,
        'options': options,
        'answersOrder': answers_order,
        'next_question': next_question
    }
    for j in ANSWER_LETTERS:
      answer_text = survey.get('answer' + str(i) + j, '')
      if answer_text:
        answer_id = j.capitalize()
        options.append({'id': answer_id, 'role': 'option', 'text': answer_text})
        next_question[answer_id] = (
            survey.get('answer' + str(i) + j + 'next', '') or 'end')
    all_question_json.append(question)
  return all_question_json


def list_versions(survey_id):
  return survey_collection.list_versions(survey_id)


def get_version(survey_id, version):
  return survey_collection.get_version(survey_id, version)


def fetch_survey_response_rows(surveyid, client=None):
  """All response rows for one survey. Parameterized by ID.

  Includes BomID plus nullable RespondentID / RespondentIDSource.
  """
  table_id = os.environ.get('TABLE_ID')
  query = _RESPONSE_SELECT.format(table=table_id)
  return get_survey_responses(surveyid, query, client=client)


def get_report(surveyid, client=None):
  """Honest in-app report: consolidated respondents, distributions, optional lift."""
  survey_doc = get_doc_by_id(surveyid)
  survey_info = {}
  is_lift = False
  if survey_doc and getattr(survey_doc, 'exists', False):
    survey_info = survey_doc.to_dict() or {}
    is_lift = is_brand_lift(survey_info)
  df = fetch_survey_response_rows(surveyid, client=client)
  return reporting.build_report(df, survey_info, is_lift=is_lift)


def get_brand_lift_results(surveyid):
  """Legacy lift matrices (expose/control proportions + lift).

  Used by tests and as a thin adapter. The reporting page uses get_report.
  Segment roles come from the stored seg values (control / expos), not a
  hardcoded rename of default_*.
  """
  df = fetch_survey_response_rows(surveyid)
  df = reporting.consolidate_frame(df)
  if df.empty or not df['Response'].any():
    return []
  df = df.copy()
  roles = df['Segmentation'].map(reporting.segment_role)
  df['Segmentation'] = [
      role if role != 'other' else seg
      for role, seg in zip(roles, df['Segmentation'])
  ]
  if df['Response'].any():
    responselist = df['Response'].str.split(pat=('|'), expand=True)
  else:
    responselist = pd.DataFrame()
  columns = list(responselist)
  for i in columns:
    responselist[i] = responselist[i].str.slice(start=2)
  df = _concat_frames([df, responselist], axis=1)
  df = df.drop(columns=['CreatedAt', 'Response', 'BomID'], errors='ignore')

  output = []
  for i in range(len(df.columns) - 1):
    # aggregate count
    pivot = df.pivot_table(
        index='Segmentation', columns=i, aggfunc=len, fill_value=0)
    # rearrange rows
    pivot = pivot.reindex(['expose', 'control'])
    # convert count to percentages
    pivot = pivot.div(pivot.sum(axis=1), axis=0)

    # compute brand lift
    matrix = pivot.to_numpy()
    lift = []
    for col in matrix.T:
      control = col[1]
      if control == 0 or np.isnan(control):
        lift.append(np.nan)
      else:
        lift.append((col[0] - control) / control)

    # append brand lift to matrix
    matrix = np.vstack([matrix, lift])
    output.append(matrix)
  return output


def get_survey_responses(surveyid, query, client=None):
  """Get data from survey"""
  job_config = bigquery.QueryJobConfig(
      query_parameters=[bigquery.ScalarQueryParameter(
          'survey_id','STRING',surveyid)])
  return _query_to_dataframe(
      query, job_config=job_config, client=client,
      empty_columns=_EMPTY_RESPONSES_COLUMNS)


def get_survey_responses_context(surveyid, client=None):
  """Get data from survey (same rows as fetch_survey_response_rows)."""
  return fetch_survey_response_rows(surveyid, client=client)

def stats_cache_seconds():
  raw = os.environ.get('STATS_CACHE_SECONDS', str(_DEFAULT_STATS_CACHE_SECONDS))
  try:
    return max(0, int(raw))
  except (TypeError, ValueError):
    return _DEFAULT_STATS_CACHE_SECONDS


def stats_lookback_days():
  """CreatedAt partition window for homepage counts. 0 disables the filter."""
  raw = os.environ.get('STATS_LOOKBACK_DAYS', str(_DEFAULT_STATS_LOOKBACK_DAYS))
  try:
    return max(0, int(raw))
  except (TypeError, ValueError):
    return _DEFAULT_STATS_LOOKBACK_DAYS


def shared_stats_cache_enabled():
  """Firestore L2 for homepage counts. Off when STATS_SHARED_CACHE=0."""
  raw = os.environ.get('STATS_SHARED_CACHE', '1')
  return str(raw).strip().lower() not in ('0', 'false', 'no', 'off')


def _l2_available():
  return shared_stats_cache_enabled() and survey_collection._db is not None


def _counts_frame_from_rows(rows):
  if not rows:
    return _empty_counts_frame()
  frame = pd.DataFrame(list(rows))
  for col in _EMPTY_COUNTS_COLUMNS:
    if col not in frame.columns:
      frame[col] = '' if col in ('ID', 'Segmentation', 'max_date') else 0
  return frame[_EMPTY_COUNTS_COLUMNS]


def _counts_rows_from_frame(frame, survey_id):
  if frame is None or frame.empty:
    return []
  rows = []
  for rec in frame.to_dict('records'):
    max_date = rec.get('max_date')
    if max_date is None or (
        isinstance(max_date, float) and math.isnan(max_date)):
      max_text = ''
    elif hasattr(max_date, 'isoformat') and not isinstance(max_date, str):
      max_text = max_date.isoformat()
      if 'T' in max_text:
        max_text = max_text.split('T', 1)[0]
    else:
      max_text = str(max_date)
    seg = rec.get('Segmentation')
    if seg is None or (isinstance(seg, float) and math.isnan(seg)):
      seg = ''
    try:
      days = int(rec.get('days_since_response') or 0)
    except (TypeError, ValueError):
      days = 0
    try:
      count = int(rec.get('response_count') or 0)
    except (TypeError, ValueError):
      count = 0
    rows.append({
        'ID': str(rec.get('ID') or survey_id or ''),
        'Segmentation': str(seg),
        'max_date': max_text,
        'days_since_response': days,
        'response_count': count,
    })
  return rows


def _l2_get(survey_ids):
  if not _l2_available():
    return {}
  try:
    stored = survey_collection.read_stats_cache(survey_ids)
  except Exception:
    _log.debug('stats.l2_get_failed', exc_info=True)
    return {}
  out = {}
  for sid, rows in (stored or {}).items():
    out[sid] = _counts_frame_from_rows(rows)
  return out


def _l2_put(frames_by_id, ttl):
  if not _l2_available() or ttl <= 0:
    return
  expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
      seconds=int(ttl))
  payload = {}
  for sid, frame in (frames_by_id or {}).items():
    payload[sid] = _counts_rows_from_frame(frame, sid)
  try:
    survey_collection.write_stats_cache(payload, expires)
  except Exception:
    _log.debug('stats.l2_put_failed', exc_info=True)


def clear_stats_cache():
  with _stats_lock:
    _stats_cache['by_id'] = {}
    _stats_cache['expires_at'] = 0.0


def _empty_counts_frame():
  return _empty_frame(_EMPTY_COUNTS_COLUMNS)


def _fetch_all_response_counts(survey_ids=None):
  """Homepage counts: one respondent per COALESCE(RespondentID, BomID).

  Restricted to the given survey IDs (current homepage page) and, when
  STATS_LOOKBACK_DAYS > 0, a CreatedAt partition window so BigQuery can prune.
  """
  ids = [sid for sid in (survey_ids or []) if sid]
  if not ids:
    _log.debug('stats.bq_ms=0.0 cache=skip n_ids=0')
    return _empty_counts_frame()
  table_id = os.environ.get('TABLE_ID')
  lookback = stats_lookback_days()
  session_key = respondent.SESSION_KEY_SQL
  partition = ''
  if lookback > 0:
    partition = (
        'AND CreatedAt >= DATETIME_SUB(CURRENT_DATETIME(), '
        'INTERVAL @lookback_days DAY)')
  query = f"""
    WITH numbered AS (
      SELECT
        ID,
        Segmentation,
        CreatedAt,
        Response,
        BomID,
        RespondentID,
        ARRAY_LENGTH(REGEXP_EXTRACT_ALL(IFNULL(Response, ''), r'[1-5]:[^|]+')) AS n_answers,
        ROW_NUMBER() OVER () AS row_id
      FROM `{table_id}`
      WHERE ID IN UNNEST(@survey_ids)
        {partition}
    ),
    keyed AS (
      SELECT
        *,
        {session_key} AS session_key
      FROM numbered
    ),
    best AS (
      SELECT * EXCEPT(rn) FROM (
        SELECT *,
          ROW_NUMBER() OVER (
            PARTITION BY ID, session_key
            ORDER BY n_answers DESC, CreatedAt DESC
          ) AS rn
        FROM keyed
      )
      WHERE rn = 1
    )
    SELECT
      ID,
      Segmentation,
      EXTRACT(DATE FROM MAX(CreatedAt)) AS max_date,
      DATE_DIFF(CURRENT_DATE(), EXTRACT(DATE FROM MAX(CreatedAt)), DAY) AS days_since_response,
      COUNT(*) AS response_count
    FROM best
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
  params = [
      bigquery.ArrayQueryParameter('survey_ids', 'STRING', ids),
  ]
  if lookback > 0:
    params.append(
        bigquery.ScalarQueryParameter('lookback_days', 'INT64', lookback))
  job_config = bigquery.QueryJobConfig(query_parameters=params)
  started = time.perf_counter()
  df = _query_to_dataframe(
      query, job_config=job_config, empty_columns=_EMPTY_COUNTS_COLUMNS)
  _log.debug(
      'stats.bq_ms=%.1f cache=miss n_ids=%d lookback_days=%d',
      (time.perf_counter() - started) * 1000, len(ids), lookback)
  return df


def get_response_counts(survey_ids=None):
  """Homepage BQ summary for the given survey IDs.

  L1 is in-process per instance. L2 is Firestore collection StatsCache with a
  logical expires_at TTL (STATS_CACHE_SECONDS, default 90). Set 0 to disable
  both caches. STATS_SHARED_CACHE=0 keeps L1 only. Stale values up to the TTL
  are acceptable. L2 is skipped until a Firestore client already exists so
  unit tests without a mock db never open a real client.
  """
  ids = []
  for sid in survey_ids or []:
    if sid and sid not in ids:
      ids.append(sid)
  if not ids:
    return _empty_counts_frame()
  ttl = stats_cache_seconds()
  if ttl <= 0:
    return _fetch_all_response_counts(ids)
  now = time.monotonic()
  with _stats_lock:
    if now >= _stats_cache['expires_at']:
      _stats_cache['by_id'] = {}
    by_id = _stats_cache['by_id']
    missing = [sid for sid in ids if sid not in by_id]
    if not missing:
      _log.debug('stats.bq_ms=0.0 cache=l1 n_ids=%d', len(ids))
      frames = [by_id[sid] for sid in ids]
    else:
      frames = None
  if frames is None:
    l2_hits = _l2_get(missing)
    still = [sid for sid in missing if sid not in l2_hits]
    fetched_by_id = {}
    if still:
      fetched = _fetch_all_response_counts(still)
      empty = _empty_counts_frame()
      for sid in still:
        if fetched is None or fetched.empty or 'ID' not in fetched.columns:
          fetched_by_id[sid] = empty
        else:
          slice_df = fetched.loc[fetched['ID'] == sid]
          fetched_by_id[sid] = slice_df if not slice_df.empty else empty
      _l2_put(fetched_by_id, ttl)
    elif l2_hits:
      _log.debug('stats.bq_ms=0.0 cache=l2 n_ids=%d', len(ids))
    with _stats_lock:
      by_id = _stats_cache['by_id']
      for sid, frame in l2_hits.items():
        by_id[sid] = frame
      for sid, frame in fetched_by_id.items():
        by_id[sid] = frame
      _stats_cache['expires_at'] = time.monotonic() + ttl
      frames = [by_id[sid] for sid in ids if sid in by_id]
  if not frames:
    return _empty_counts_frame()
  combined = _concat_frames(frames, ignore_index=True)
  if combined is None or combined.empty:
    return _empty_counts_frame()
  return combined


def get_all_response_counts(survey_ids=None):
  """Back-compat wrapper. Pass survey IDs; an empty list does not scan BigQuery."""
  return get_response_counts(survey_ids)


def _segmentation_csv_column(surveyid):
  survey_doc = get_doc_by_id(surveyid)
  if survey_doc and getattr(survey_doc, 'exists', False):
    if is_brand_lift(survey_doc.to_dict() or {}):
      return 'Control/Expose'
  return 'Segment'


def _response_columns_for_csv(df, question_names):
  if df.empty or not df['Response'].any():
    return pd.DataFrame()
  responselist = df['Response'].str.split(pat=('|'), expand=True)
  for i in list(responselist):
    responselist[i] = responselist[i].str.slice(start=2)
  rename = {}
  defaults = ['Response 1', 'Response 2', 'Response 3', 'Response 4',
              'Response 5']
  for i, default in enumerate(defaults):
    if i in responselist.columns:
      rename[i] = question_names[i] if i < len(question_names) else default
  return responselist.rename(columns=rename).reset_index(drop=True)


def _csv_dataframe(surveyid, with_context=False):
  """Consolidated response table ready for CSV. One row per respondent."""
  df = reporting.consolidate_frame(fetch_survey_response_rows(surveyid))
  question_names = [
      'Response 1', 'Response 2', 'Response 3', 'Response 4', 'Response 5'
  ]
  survey_info = {}
  survey_doc = get_doc_by_id(surveyid)
  if survey_doc and getattr(survey_doc, 'exists', False):
    survey_info = survey_doc.to_dict() or {}
    if with_context:
      question_names = [
          survey_info.get('question1') or question_names[0],
          survey_info.get('question2') or question_names[1],
          survey_info.get('question3') or question_names[2],
          survey_info.get('question4') or question_names[3],
          survey_info.get('question5') or question_names[4],
      ]
  if with_context:
    segment_col = 'Control/Expose' if is_brand_lift(survey_info) else 'Segment'
  else:
    segment_col = _segmentation_csv_column(surveyid)
  outputdf = pd.DataFrame({'Date': [], segment_col: []})
  if not df.empty:
    outputdf['Date'] = df['CreatedAt'].values
    outputdf[segment_col] = df['Segmentation'].values
    for src, dest in (
        ('CampaignID', 'Campaign ID'),
        ('PlacementID', 'Placement ID'),
        ('SiteID', 'Site ID'),
        ('AdCreativeID', 'Creative ID'),
        ('CreativeSize', 'Size'),
        ('CreativeVersion', 'Creative version'),
    ):
      if src in df.columns:
        if src == 'CreativeVersion':
          series = df[src].map(reporting._cell_text)
        else:
          series = df[src].fillna('').astype(str)
      else:
        series = pd.Series([''] * len(df), index=df.index)
      fallback = ''
      if dest == 'Campaign ID':
        fallback = (survey_info.get('campaign_id') or '').strip()
      elif dest == 'Placement ID':
        fallback = (survey_info.get('placement_id') or '').strip()
      if fallback:
        series = series.where(series.str.strip() != '', fallback)
      outputdf[dest] = series.values
  responselist = _response_columns_for_csv(df, question_names)
  if not responselist.empty:
    outputdf = _concat_frames(
        [outputdf.reset_index(drop=True), responselist], axis=1)
  return outputdf


def iter_response_csv(surveyid, with_context=False, chunksize=CSV_CHUNK_ROWS):
  """Yield CSV chunks so downloads are not built as one in-memory string."""
  outputdf = _csv_dataframe(surveyid, with_context=with_context)
  try:
    chunksize = max(1, int(chunksize))
  except (TypeError, ValueError):
    chunksize = CSV_CHUNK_ROWS
  if outputdf.empty:
    yield outputdf.to_csv(index=False)
    return
  header = True
  for start in range(0, len(outputdf), chunksize):
    chunk = outputdf.iloc[start:start + chunksize]
    yield chunk.to_csv(index=False, header=header)
    header = False


def download_responses(surveyid):
  """Download survey responses in a CSV format file."""
  return ''.join(iter_response_csv(surveyid, with_context=False))


def download_responses_with_context(surveyid):
  """Download survey responses in a CSV format file."""
  return ''.join(iter_response_csv(surveyid, with_context=True))


def download_breakouts(surveyid, client=None):
  """CSV of overall + per-slice lift / CIs (size, placement, site, creative, date, segment)."""
  report = get_report(surveyid, client=client)
  return reporting.breakouts_to_csv(report)


#def get_thank_you_text(survey):
#  """Multi-language support input for thank you text."""
#  if survey.get('language') == 'ms':
#    thankyou_text = 'Terima Kasih'
#  elif survey.get('language') == 'zh':
#    thankyou_text = '谢谢'
#  elif survey.get('language') == 'ja':
#    thankyou_text = 'ありがとうございました'
#  elif survey.get('language') == 'ko':
#    thankyou_text = '고맙습니다'
#  elif survey.get('language') == 'fr':
#    thankyou_text = 'Merci'
#  elif survey.get('language') == 'es':
#    thankyou_text = 'Gracias'
#  else:
#    thankyou_text = 'Thank You'
#  return thankyou_text


def get_thank_you_text(survey):
  """Multi-language support input for thank you text."""

  language_codes = {
    'ms': 'Terima Kasih',
    'zh': '谢谢',
    'ja': 'ありがとうございました',
    'ko': '고맙습니다',
    'fr': 'Merci',
    'es': 'Gracias',
    'de': 'Danke',
    'it': 'Grazie',
    'pt': 'Obrigado',
    'ru': 'Спасибо',
    'ar': 'شكرا',
    'hi': 'धन्यवाद',
    'tr': 'Teşekkür ederim',
    'vi': 'Cảm ơn',
    'pl': 'Dziękuję',
    'id': 'Terima kasih',
    'th': 'ขอบคุณ',
    'tl': 'Salamat',
    'nl': 'Dankjewel',
    'da': 'Tak',
    'fi': 'Kiitos',
    'el': 'Ευχαριστώ',
    'he': 'תודה',
    'sv': 'Tack',
    'hu': 'Köszönet',
    'cs': 'Děkuji',
    'no': 'Takk',
    'uk': 'Дякую',
    'fa': 'متشکرم',
    'ur': 'شکریہ',
    'ml': 'നന്ദി',
    'ta': 'நன்றி',
    'te': 'ధన్యవాదాలు',
    'kn': 'ಧನ್ಯವಾದಗಳು',
    'gu': 'ધન્યવાદ',
    'mr': 'धन्यवाद',
    'bn': 'ধন্যবাদ'
  }

  language_code = survey.get('language')
  thankyou_text = language_codes.get(language_code) or 'Thank You'
  return thankyou_text

# def get_next_text(survey):
#   """Multi-language support input for next text."""
#   if survey.get('language') == 'ms':
#     next_text = 'Next'
#   elif survey.get('language') == 'zh':
#     next_text = '下一个'
#   elif survey.get('language') == 'ja':
#     next_text = '次へ'
#   elif survey.get('language') == 'ko':
#     next_text = '다음에'
#   elif survey.get('language') == 'fr':
#     next_text = 'Suivante'
#   elif survey.get('language') == 'es':
#     next_text = 'Próxima'
#   else:
#     next_text = 'Next'
#   return next_text

def get_next_text(survey):
  """Multi-language support input for next text."""

  language_codes = {
    'ms': 'Berikutnya',
    'zh': '下一个',
    'ja': '次へ',
    'ko': '다음에',
    'fr': 'Suivante',
    'es': 'Próxima',
    'de': 'Weiter',
    'it': 'Avanti',
    'pt': 'Próximo',
    'ru': 'Следующий',
    'ar': 'التالي',
    'hi': 'अगला',
    'tr': 'Sonraki',
    'vi': 'Kế tiếp',
    'pl': 'Następny',
    'id': 'Berikutnya',
    'th': 'ถัดไป',
    'tl': 'Susunod',
    'nl': 'Volgende',
    'da': 'Næste',
    'fi': 'Seuraava',
    'el': 'Επόμενο',
    'he': 'הבא',
    'sv': 'Nästa',
    'hu': 'Következő',
    'cs': 'Další',
    'no': 'Neste',
    'uk': 'Наступний',
    'fa': 'بعد',
    'ur': 'اگلے',
    'ml': 'അടുത്തത്',
    'ta': 'அடுத்த',
    'te': 'తర్వాత',
    'kn': 'ಮುಂದಿನ',
    'gu': 'આગળ',
    'mr': 'पुढील',
    'bn': 'পরবর্তী'
  }

  language_code = survey.get('language')
  next_text = language_codes.get(language_code) or 'Next'
  return next_text


# def get_comment_text(survey):
#   """Multi-language support input for comment text."""
#   if survey.get('language') == 'ms':
#     comment_text = 'Pilih semua yang berkenaan'
#   elif survey.get('language') == 'zh':
#     comment_text = '选择所有适用的'
#   elif survey.get('language') == 'ja':
#     comment_text = '当てはまるもの全て選択'
#   elif survey.get('language') == 'ko':
#     comment_text = '적용 가능한 모든 항목을 선택하십시오'
#   elif survey.get('language') == 'fr':
#     comment_text = "Choisissez tout ce qui s'applique"
#   elif survey.get('language') == 'es':
#     comment_text = 'Elige todas las aplicables'
#   else:
#     comment_text = 'Choose all applicable'
#   return comment_text


def get_comment_text(survey):
  """Multi-language support input for comment text."""

  language_codes = {
    'ms': 'Pilih semua yang berkenaan',
    'zh': '选择所有适用的',
    'ja': '当てはまるもの全て選択',
    'ko': '적용 가능한 모든 항목을 선택하십시오',
    'fr': "Choisissez tout ce qui s'applique",
    'es': 'Elige todas las aplicables',
    'de': 'Wählen Sie alle zutreffenden aus.',
    'it': 'Seleziona tutte le opzioni applicabili.',
    'pt': 'Escolha todas as opções aplicáveis.',
    'ru': 'Выберите все подходящие.',
    'ar': 'اختر كل ما ينطبق.',
    'hi': 'सभी लागू विकल्प चुनें.',
    'tr': 'Uygun olan tüm seçenekleri seçin.',
    'vi': 'Chọn tất cả các tùy chọn áp dụng.',
    'pl': 'Wybierz wszystkie odpowiednie opcje.',
    'id': 'Pilih semua opsi yang berlaku.',
    'th': 'เลือกตัวเลือกทั้งหมดที่ใช้ได้',
    'tl': 'Piliin ang lahat ng naaangkop na opsyon.',
    'nl': 'Selecteer alle van toepassing zijnde opties.',
    'da': 'Vælg alle relevante muligheder.',
    'fi': 'Valitse kaikki soveltuvat vaihtoehdot.',
    'el': 'Επιλέξτε όλες τις σχετικές επιλογές.',
    'he': 'בחר את כל האפשרויות הרלוונטיות.',
    'sv': 'Välj alla relevanta alternativ.',
    'hu': 'Válassza ki az összes releváns lehetőséget.',
    'cs': 'Vyberte všechny relevantní možnosti.',
    'no': 'Velg alle relevante alternativer.',
    'uk': 'Виберіть усі відповідні варіанти.',
    'fa': 'همه گزینه های مربوطه را انتخاب کنید.',
    'ur': 'تمام متعلقہ اختیارات کا انتخاب کریں۔',
    'ml': 'എല്ലാ ബാധകമായ ഓപ്ഷനുകളും തിരഞ്ഞെടുക്കുക.',
    'ta': 'அனைத்து பொருத்தமான விருப்பங்களையும் தேர்வு செய்யவும்.',
    'te': 'అన్ని వర్తించే ఎంపికలను ఎంచుకోండి.',
    'kn': 'ಎಲ್ಲಾ ಅನ್ವಯಿಸುವ ಆಯ್ಕೆಗಳನ್ನು ಆರಿಸಿ.',
    'gu': '모든 해당 옵션을 선택하세요.',
    'mr': 'सर्व लागू पर्याय निवडा.',
    'bn': 'সभी প্রযোজ্য বিকল্পগুলি নির্বাচন করুন।'
  }

  language_code = survey.get('language')
  comment_text = language_codes.get(language_code) or 'Choose all applicable'
  return comment_text


def bulk_upload_payload(survey_id, survey):
  """Sidecar CM360/DV360 bulk-upload CSVs (no API, no credentials)."""
  version = None
  try:
    version = survey_collection.peek_next_version(survey_id)
  except Exception:
    version = None
  return bulk_upload.download_zip(
      survey_id, survey, creative_version=version)


def tag_sheet_payload(survey_id, survey, fmt='csv'):
  """CSV or XLSX bytes plus a download filename."""
  version = None
  try:
    version = survey_collection.peek_next_version(survey_id)
  except Exception:
    version = None
  headers, rows = ad_macros.tag_sheet_matrix(
      survey_id, survey, creative_version=version)
  slug = (survey.get('surveyname') or survey_id or 'survey').replace(' ', '-')
  fmt = (fmt or 'csv').strip().lower()
  if fmt == 'xlsx':
    return (
        '%s_tag_sheet.xlsx' % slug,
        ad_macros.xlsx_bytes(headers, rows),
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
  return (
      '%s_tag_sheet.csv' % slug,
      ad_macros.csv_bytes(headers, rows),
      'text/csv',
  )
