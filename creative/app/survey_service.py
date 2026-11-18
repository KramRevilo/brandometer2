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
import math
import os
import threading
import time
import zipfile
from flask import flash
from flask import render_template
from google.api_core.exceptions import NotFound
from google.cloud import bigquery
from google.cloud import bigquery_storage
import numpy as np
import pandas as pd
import creative_size
import reporting
import survey_collection
from forms import ANSWER_LETTERS
from forms import BRAND_LIFT
from forms import BRAND_TRACK
from forms import DEFAULT_CSS
from forms import RESPONSES_AT_END

# Homepage status chips. Active <= 3 days, Stale <= 7, Timed out after that.
# 2022 backlog (yellow at 7 days). Previously Stale ran through 14 days.
STATUS_ACTIVE_DAYS = 3
STATUS_STALE_DAYS = 7
HOMEPAGE_PAGE_SIZE = 50
STATS_POLL_SECONDS = 30
_DEFAULT_STATS_CACHE_SECONDS = 90
_MRC_INIT = 999999999

_stats_lock = threading.Lock()
_stats_cache = {'df': None, 'expires_at': 0.0}

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


_EMPTY_RESPONSES_COLUMNS = ['CreatedAt', 'Segmentation', 'Response', 'BomID']
CSV_CHUNK_ROWS = 500
_RESPONSE_SELECT = """
        SELECT CreatedAt, Segmentation, Response, BomID
        FROM `{table}`
        WHERE ID = @survey_id
    """
_EMPTY_COUNTS_COLUMNS = [
    'ID', 'Segmentation', 'max_date', 'days_since_response', 'response_count'
]


def _empty_frame(columns):
  return pd.DataFrame(columns=columns)


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
  return survey_collection.delete_by_id(survey_id)


def is_archived(survey):
  data = survey.to_dict() if hasattr(survey, 'to_dict') else (survey or {})
  return data.get('archived') is True


def list_surveys(include_archived=False):
  surveys = list(survey_collection.get_all(survey_collection.LIST_FIELDS))
  if include_archived:
    surveys = [survey for survey in surveys if is_archived(survey)]
  else:
    surveys = [survey for survey in surveys if not is_archived(survey)]
  surveys.sort(key=lambda s: (
      ((s.to_dict() or {}).get('displayname')
       or (s.to_dict() or {}).get('surveyname') or '').lower(),
      s.id,
  ))
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
    counts_df = get_all_response_counts()
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
  return survey_collection.set_archived(survey_id, archived)


def copy_by_id(survey_id):
  return survey_collection.copy(survey_id)


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


def create(form):
  data = dict(form.data)
  data['archived'] = False
  doc_ref = survey_collection.create(data)
  flash(f'{form.surveyname.data} created as {doc_ref.id}')
  return doc_ref


def update_by_id(survey_id, form):
  edit_doc = survey_collection.update_by_id(survey_id, form.data)
  flash(f'{form.surveyname.data} updated')
  return edit_doc


def set_form_data(form, edit_doc):
  edit_doc_dict = edit_doc.to_dict()

  for key, value in edit_doc_dict.items():
    if key in form:
      form[key].data = edit_doc.get(key,)


def zip_file(survey_id, survey_dict, record_version=True):
  """File download function."""
  # Make these use temp files in '/tmp/' to work around
  # App Engine read only filesystem

  # Prepare data
  current_datetime = datetime.datetime.now().strftime('%Y%m%d')
  surveyname = survey_dict['surveyname'].replace(' ', '-')
  size_key = creative_size.resolve(survey_dict)['key']
  prefix_filename = current_datetime + '_' + surveyname + '_' + size_key
  # Missing surveytype matches the form default (Brand Track): one creative.
  survey_type = survey_dict.get('surveytype', BRAND_TRACK)
  if survey_type == BRAND_LIFT:
    seg_types = ['default_control', 'default_expose']
  else:
    # Empty seg in the HTML; zip suffix is added separately so the file
    # is not named "..._.zip" and does not collide with the outer zip.
    seg_types = ['']

  # In order to make the responsetype backward compatible we need to support
  # surveys defined WITHOUT a responsetype and default them to RESPONSES_AT_END.
  # Check to see if there's a key for answer type 'responsetype' and, if not,
  # then this is an old survey. Insert a key:value pair for RESPONSES_AT_END.
  if 'responsetype' not in survey_dict:
    survey_dict['responsetype'] = RESPONSES_AT_END

  # create zip
  template_zips = write_html_template(survey_id, survey_dict, prefix_filename,
                                      seg_types)
  combined_zip = zip_dir(prefix_filename, template_zips)

  # make data response
  with open(combined_zip.filename, 'rb') as file:
    file_data = io.BytesIO(file.read())

  # clean up tmp files
  delete_tmp_zip_files([combined_zip] + template_zips)

  if record_version:
    survey_collection.add_version(survey_id, survey_dict)

  return os.path.basename(combined_zip.filename), file_data


def zip_dir(filename, template_zips):
  with zipfile.ZipFile('/tmp/' + filename + '.zip', 'w',
                       zipfile.ZIP_DEFLATED) as zipdir:
    for zip in template_zips:
      zipdir.write(zip.filename)
  return zipdir


def write_html_template(survey_id, survey_dict, prefix_filename, seg_types):
  template_zips = []

  for seg_type in seg_types:
    file_suffix = seg_type if seg_type else 'creative'
    dir_name = '/tmp/' + prefix_filename + '_' + file_suffix
    # write html file
    with zipfile.ZipFile(dir_name + '.zip', 'w',
                         zipfile.ZIP_DEFLATED) as zip_write_file:
      zip_write_file.writestr(
          'index.html', get_html_template(survey_id, survey_dict, seg_type))
      template_zips.append(zip_write_file)

  return template_zips


def get_html_template(survey_id, survey_dict, seg_type):
  if 'custom_css' in survey_dict:
    custom_css = survey_dict['custom_css']
  else:
    custom_css = DEFAULT_CSS
  size = creative_size.resolve(survey_dict)
  custom_css = creative_size.apply_overlay(custom_css, size)

  return render_template(
      'creative.html',
      survey=survey_dict,
      survey_id=survey_id,
      show_back_button=False,
      response_type=survey_dict.get('responsetype', RESPONSES_AT_END),
      all_question_json=get_question_json(survey_dict),
      seg=seg_type,
      custom_css=custom_css,
      creative_width=size['width'],
      creative_height=size['height'],
      ad_size_meta=creative_size.ad_size_meta(size),
      thankyou_text=get_thank_you_text(survey_dict),
      next_text=get_next_text(survey_dict),
      comment_text=get_comment_text(survey_dict))


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
  """All response rows for one survey. Parameterized by ID. Includes BomID."""
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
  df = pd.concat([df, responselist], axis=1)
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


def clear_stats_cache():
  with _stats_lock:
    _stats_cache['df'] = None
    _stats_cache['expires_at'] = 0.0


def _fetch_all_response_counts():
  """Homepage counts: one respondent per BomID (latest/most complete row).

  Surveys that submit after each question used to be counted once per
  question. Those homepage numbers will drop after this consolidation.
  Blank BomID rows (submit-at-end) stay as individual respondents.
  """
  table_id = os.environ.get('TABLE_ID')
  query = f"""
    WITH numbered AS (
      SELECT
        ID,
        Segmentation,
        CreatedAt,
        Response,
        BomID,
        ARRAY_LENGTH(REGEXP_EXTRACT_ALL(IFNULL(Response, ''), r'[1-5]:[^|]+')) AS n_answers,
        ROW_NUMBER() OVER () AS row_id
      FROM `{table_id}`
      WHERE ID IS NOT NULL
    ),
    keyed AS (
      SELECT
        *,
        IF(BomID IS NOT NULL AND TRIM(BomID) != '', TRIM(BomID),
           CONCAT('row:', CAST(row_id AS STRING))) AS session_key
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
  return _query_to_dataframe(
      query, empty_columns=_EMPTY_COUNTS_COLUMNS)


def get_all_response_counts():
  """Return the homepage BQ summary, cached in-process.

  Each App Engine instance has its own cache. Stale values up to
  STATS_CACHE_SECONDS (default 90) are acceptable; set 0 to disable.
  """
  ttl = stats_cache_seconds()
  if ttl <= 0:
    return _fetch_all_response_counts()
  now = time.monotonic()
  with _stats_lock:
    cached = _stats_cache['df']
    if cached is not None and now < _stats_cache['expires_at']:
      return cached
    df = _fetch_all_response_counts()
    _stats_cache['df'] = df
    _stats_cache['expires_at'] = time.monotonic() + ttl
    return df


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
  """Consolidated response table ready for CSV. One row per BomID."""
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
  responselist = _response_columns_for_csv(df, question_names)
  if not responselist.empty:
    outputdf = pd.concat(
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
