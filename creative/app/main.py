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
"""Import of required packages/libraries."""

# OS imports
import datetime
import io
import logging
import math
import os
import time

# Flask imports
from flask import flash
from flask import Flask
from flask import redirect
from flask import render_template
from flask import request
from flask import Response
from flask import send_file
from flask import send_from_directory
from flask import stream_with_context
from flask import url_for
from flask_wtf.csrf import CSRFProtect
from markupsafe import Markup

# local file imports
import app_security
import brand
import bulk_surveys
import ui_help
import creative_size
import css_theme
import forms
from forms import DEFAULT_CSS
import google_auth
import reporting_views
import sample_size
import survey_collection
import survey_service
from forms import RESPONSES_AT_END

# Project setup. Overridden per request by APP_BRAND_NAME (default Brandometer2).
title = brand.DEFAULT_BRAND_NAME
app = Flask(__name__)
app_security.configure_app(app)
google_auth.init_app(app)
csrf = CSRFProtect(app)
# Cloud Shell Web Preview cannot complete Google Sign-In when the preview
# hostname is not on the OAuth client. Set DISABLE_BASIC_AUTH=1 for local/proxy
# use only. Never set this in App Engine / ./deploy. GAE_ENV refuses that bypass.

def _truthy_arg(value):
  return (value or '').strip().lower() in ('1', 'true', 'yes', 'on')


def _page_arg(value):
  try:
    return int(value)
  except (TypeError, ValueError):
    return 1


def flask_port():
  """Local `python main.py` port. Cloud Shell Web Preview is stuck on 8080."""
  raw = os.environ.get('PORT', '8080')
  try:
    return int(raw)
  except (TypeError, ValueError):
    return 8080


_index_log = logging.getLogger(__name__)


def _filter_args():
  return {
      'q': (request.args.get('q') or '').strip(),
      'client': (request.args.get('client') or '').strip(),
      'agency': (request.args.get('agency') or '').strip(),
      'year': (request.args.get('year') or '').strip(),
      'size': (request.args.get('size') or '').strip(),
      'created_by': (request.args.get('created_by') or '').strip(),
  }


def _sort_args():
  return survey_service.parse_sort(
      request.args.get('sort'), request.args.get('dir'))


def _index_query(
    show_archived, page=None, filters=None, sort=None, direction=None):
  args = {}
  if show_archived:
    args['archived'] = 1
  if page:
    args['page'] = page
  filters = filters or {}
  for key in ('q', 'client', 'agency', 'year', 'size', 'created_by'):
    value = (filters.get(key) or '').strip()
    if value:
      args[key] = value
  sort, direction = survey_service.parse_sort(sort, direction)
  if (sort != survey_service.DEFAULT_SORT_KEY
      or direction != survey_service.DEFAULT_SORT_DIR):
    args['sort'] = sort
    args['dir'] = direction
  return args


def _log_index_timing(part, started, **fields):
  extra = ' '.join('%s=%s' % (key, value) for key, value in fields.items())
  _index_log.debug(
      'index.%s_ms=%.1f %s',
      part, (time.perf_counter() - started) * 1000, extra.strip())


@app.route('/')
def root():
  # Path-only Location so Cloud Shell / reverse proxies do not flip http/https.
  return redirect('/index')


@app.route('/favicon.ico')
def favicon():
  """Local /favicon.ico. App Engine serves the same file via app.yaml."""
  return send_from_directory(
      os.path.dirname(os.path.abspath(__file__)),
      'favicon.ico',
      mimetype='image/vnd.microsoft.icon',
      max_age=86400)


@app.route('/index')
def index():
  request_started = time.perf_counter()
  show_archived = _truthy_arg(request.args.get('archived'))
  filters = _filter_args()
  sort_key, sort_dir = _sort_args()
  list_started = time.perf_counter()
  surveys = survey_service.list_surveys(include_archived=show_archived)
  _log_index_timing(
      'firestore_list', list_started, n=len(surveys),
      cache='n/a')
  filter_options = survey_service.homepage_filter_options(surveys)
  unfiltered_count = len(surveys)
  filter_started = time.perf_counter()
  surveys = survey_service.apply_homepage_filters(
      surveys,
      q=filters['q'],
      client=filters['client'],
      agency=filters['agency'],
      year=filters['year'],
      size=filters['size'],
      created_by=filters['created_by'])
  surveys = survey_service.sort_surveys(surveys, sort_key, sort_dir)
  _log_index_timing('filter', filter_started, n=len(surveys))

  def index_query(archived_flag, page=None, sort=None, direction=None):
    return _index_query(
        archived_flag, page, filters,
        sort=sort_key if sort is None else sort,
        direction=sort_dir if direction is None else direction)

  def sort_query(column):
    if column == sort_key:
      nxt = 'asc' if sort_dir == 'desc' else 'desc'
    elif column == 'created_at':
      nxt = 'desc'
    else:
      nxt = 'asc'
    return _index_query(show_archived, None, filters, sort=column, direction=nxt)

  page_surveys, pager = survey_service.paginate_surveys(
      surveys,
      page=_page_arg(request.args.get('page')),
      page_size=survey_service.HOMEPAGE_PAGE_SIZE)
  survey_ids = [survey.id for survey in page_surveys]
  # Do not wait on BigQuery. Count/last/status cells load via htmx on page load.
  render_started = time.perf_counter()
  html = render_template(
      'index.html',
      all_surveys=page_surveys,
      stats_by_id={},
      stats_pending=True,
      show_archived=show_archived,
      pager=pager,
      stats_poll_seconds=survey_service.STATS_POLL_SECONDS,
      stats_timeout_ms=survey_service.STATS_PARTIAL_TIMEOUT_MS,
      stats_ids=','.join(survey_ids),
      index_query=index_query,
      sort_query=sort_query,
      sort_key=sort_key,
      sort_dir=sort_dir,
      filters=filters,
      filter_options=filter_options,
      size_choices=creative_size.SIZE_CHOICES,
      filters_active=any(filters.values()),
      unfiltered_count=unfiltered_count,
      title=brand.brand_name())
  _log_index_timing('render', render_started, n=len(page_surveys))
  _log_index_timing(
      'request', request_started, n=len(page_surveys), bq='deferred')
  return html


@app.route('/index/stats-partial')
def index_stats_partial():
  """Load count / last-received-days / status cells (BQ, cached) after the list paints.

  Always 200 with OOB cells so htmx can swap. BigQuery errors become an
  unavailable row (—) instead of a 500 that would leave Loading… forever.
  """
  started = time.perf_counter()
  survey_ids = [sid for sid in request.args.get('ids', '').split(',') if sid]
  try:
    stat_array = survey_service.build_stat_array(survey_ids)
  except Exception as exc:
    _index_log.exception(
        'index.stats_partial_error n_ids=%d type=%s error=%r',
        len(survey_ids), type(exc).__name__, exc)
    stat_array = survey_service.unavailable_stat_array(survey_ids)
  _index_log.debug(
      'index.stats_partial_ms=%.1f n_ids=%d',
      (time.perf_counter() - started) * 1000, len(survey_ids))
  return render_template('stats_partial.html', stat_array=stat_array)


def _editor_context(form):
  parsed = css_theme.parse_theme_css(form.custom_css.data or DEFAULT_CSS)
  return {
      'theme': parsed['theme'],
      'extra_css': parsed['extra'],
      'font_choices': css_theme.FONT_CHOICES,
      'presets': css_theme.STYLE_PRESETS,
      'preset_groups': css_theme.STYLE_PRESET_GROUPS,
      'size_choices': creative_size.SIZE_CHOICES,
      'layout_fix_css': creative_size.layout_fix_css(),
      'size_overlay_css': {
          key: creative_size.overlay_css(key) for key in creative_size.SIZES
      },
      'badge_icons': brand.badge_icon_list(),
      'badge_text_max': brand.BADGE_TEXT_MAX,
      'badge_text_default': brand.badge_tooltip(),
  }


def _render_editor(form, page_title, survey_id=None, versions=None,
                   last_update_time=''):
  ctx = _editor_context(form)
  suggestions = survey_service.identity_suggestions()
  payload = brand.persist_badge(dict(form.data or {}))
  payload, _ = creative_size.persist_sizes(payload)
  try:
    qa_findings = survey_service.html5_qa_for_survey(survey_id, payload)
  except Exception:
    logging.exception('html5_qa_for_survey failed')
    qa_findings = []
  return render_template(
      'questions.html',
      title=page_title,
      form=form,
      theme=ctx['theme'],
      extra_css=ctx['extra_css'],
      font_choices=ctx['font_choices'],
      presets=ctx['presets'],
      survey_id=survey_id,
      versions=versions or [],
      last_update_time=last_update_time or '',
      client_suggestions=suggestions.get('clients') or [],
      agency_suggestions=suggestions.get('agencies') or [],
      preset_groups=ctx.get('preset_groups') or [],
      size_choices=ctx.get('size_choices') or creative_size.SIZE_CHOICES,
      layout_fix_css=ctx.get('layout_fix_css') or '',
      size_overlay_css=ctx.get('size_overlay_css') or {},
      badge_icons=ctx.get('badge_icons') or brand.badge_icon_list(),
      badge_text_max=ctx.get('badge_text_max') or brand.BADGE_TEXT_MAX,
      badge_text_default=ctx.get('badge_text_default') or brand.badge_tooltip(),
      qa_findings=qa_findings)


@app.route('/survey/create', methods=['GET', 'POST'])
def create():
  """Survey creation."""
  google_auth.require_editor()
  form = forms.QuestionForm()
  if form.validate_on_submit():
    survey_service.create(form)
    return redirect(url_for('index'))
  return _render_editor(form, 'Create survey')


@app.route('/survey/bulk/template.csv', methods=['GET'])
def bulk_template():
  """CSV header + one example row for bulk survey create."""
  google_auth.require_editor()
  return send_file(
      io.BytesIO(bulk_surveys.template_csv()),
      mimetype='text/csv',
      as_attachment=True,
      download_name='survey_bulk_template.csv')


@app.route('/survey/bulk', methods=['GET', 'POST'])
def bulk_create():
  """Preview and commit a CSV of new surveys. Editor / admin only."""
  google_auth.require_editor()
  rows = None
  file_errors = []
  valid_count = 0
  payloads_json = ''
  if request.method == 'POST':
    action = (request.form.get('action') or 'preview').strip().lower()
    if action == 'commit':
      rows, file_errors = bulk_surveys.loads_payloads(
          request.form.get('payloads_json'))
      created = []
      for row in rows:
        if not row.get('ok') or not row.get('payload'):
          continue
        ref = survey_service.create_from_payload(
            row['payload'], flash_created=False)
        created.append((row.get('surveyname') or ref.id, ref.id))
      if created:
        flash(
            'Created %s survey(s): %s' % (
                len(created),
                ', '.join('%s (%s)' % item for item in created)),
            'success')
        return redirect(url_for('index'))
      if not file_errors:
        file_errors = ['No valid surveys to create. Fix the CSV and preview again.']
    else:
      uploaded = request.files.get('csv_file')
      raw = uploaded.read() if uploaded and uploaded.filename else None
      rows, file_errors = bulk_surveys.parse_csv(raw)
    valid_count = len([row for row in (rows or []) if row.get('ok')])
    payloads_json = bulk_surveys.dumps_payloads(rows or [])
  return render_template(
      'bulk_create.html',
      title='Bulk create surveys',
      rows=rows,
      file_errors=file_errors,
      valid_count=valid_count,
      payloads_json=payloads_json,
      max_rows=bulk_surveys.MAX_ROWS)


@app.route('/survey/preview/<string:survey_id>', methods=['GET'])
def preview(survey_id):
  """Survey preview."""
  survey_doc = survey_service.get_doc_by_id(survey_id)
  if survey_doc.exists:
    survey_info = survey_doc.to_dict()

    if 'custom_css' in survey_info:
        custom_css = survey_info['custom_css']
    else:
        custom_css = DEFAULT_CSS

    if 'responsetype' in survey_info:
        response_type = survey_info['responsetype']
    else:
        response_type = RESPONSES_AT_END

    preview_sizes = creative_size.selected_keys(survey_info)
    size = creative_size.resolve_preview(survey_info, request.args.get('size'))
    custom_css = Markup(creative_size.apply_overlay(
        css_theme.sanitize_user_css(custom_css), size))
    embed = (request.args.get('embed') or '').strip() == '1'

    return render_template(
        'creative.html',
        survey=survey_info,
        survey_id=survey_id,
        manual_responses=True,
        show_back_button=not embed,
        embed=embed,
        preview_sizes=preview_sizes,
        all_question_json=survey_service.get_question_json(survey_info),
        seg='preview',
        custom_css=custom_css,
        response_type=response_type,
        creative_width=size['width'],
        creative_height=size['height'],
        size_key=size['key'],
        size_layout=size.get('layout') or 'stack',
        ad_size_meta=creative_size.ad_size_meta(size),
        # Do not post preview answers to BigQuery.
        receiver_url='',
        receiver_token='',
        thankyou_text=survey_service.get_thank_you_text(survey_info),
        next_text=survey_service.get_next_text(survey_info),
        comment_text=survey_service.get_comment_text(survey_info),
        **brand.badge_render_vars(survey_info))
  else:
    flash('Survey not found')
    return redirect(url_for('index'))


@app.route('/survey/delete', methods=['POST'])
def delete():
  """Delete survey."""
  google_auth.require_editor()
  docref_id = request.form.get('survey_id') or request.args.get('survey_id')
  survey_service.delete_by_id(docref_id)
  flash(f'Survey \'{docref_id}\' deleted')
  return redirect(url_for('index'))


@app.route('/survey/copy', methods=['POST'])
def copy_survey():
  """Copy a survey and open the new document in the editor."""
  google_auth.require_editor()
  survey_id = request.form.get('survey_id') or request.args.get('survey_id')
  new_ref = survey_service.copy_by_id(survey_id)
  if new_ref is None:
    flash('Survey not found')
    return redirect(url_for('index'))
  flash(f'Copied as {new_ref.id}')
  return redirect(url_for('edit', survey_id=new_ref.id))


@app.route('/survey/archive', methods=['POST'])
def archive():
  """Archive or restore a survey."""
  google_auth.require_editor()
  survey_id = request.form.get('survey_id') or request.args.get('survey_id')
  archived_raw = request.form.get('archived', request.args.get('archived', '1'))
  archived = (archived_raw or '1').strip().lower() in (
      '1', 'true', 'yes', 'on')
  survey_service.set_archived(survey_id, archived)
  flash('Survey archived' if archived else 'Survey restored')
  view = request.form.get('view') or request.args.get('view')
  if view == 'archived':
    return redirect(url_for('index', archived=1))
  return redirect(url_for('index'))


@app.route('/survey/edit', methods=['POST', 'PUT', 'GET'])
def edit():
  """Edit Survey."""
  google_auth.require_editor()
  # Create form object
  form = forms.QuestionForm()

  # Get info about survey from Firebase
  docref_id = request.args.get('survey_id')
  edit_doc = survey_service.get_doc_by_id(docref_id)

  # Set the form data according to what was loaded from Firebase
  if request.method == 'GET':
    survey_service.set_form_data(form, edit_doc)

  last_update_time = ''
  if request.method == 'GET' and edit_doc and getattr(edit_doc, 'exists', False):
    last_update_time = survey_collection.encode_update_time(edit_doc)
  elif request.method != 'GET':
    last_update_time = request.form.get('last_update_time') or ''

  # present page, gather entries upon submission
  if form.validate_on_submit():
    try:
      survey_service.update_by_id(
          docref_id, form, last_update_time=last_update_time)
      return redirect(url_for('index'))
    except survey_collection.SurveyConflictError:
      flash('Someone else saved this survey, reload', 'warning')
      current = survey_service.get_doc_by_id(docref_id)
      if current and getattr(current, 'exists', False):
        survey_service.set_form_data(form, current)
        last_update_time = survey_collection.encode_update_time(current)
      versions = survey_service.list_versions(docref_id)
      body = _render_editor(
          form, 'Edit survey', survey_id=docref_id, versions=versions,
          last_update_time=last_update_time)
      return body, 409
  versions = []
  if edit_doc and getattr(edit_doc, 'exists', False):
    versions = survey_service.list_versions(docref_id)
  return _render_editor(
      form, 'Edit survey', survey_id=docref_id, versions=versions,
      last_update_time=last_update_time)


@app.route('/survey/download_zip/<string:survey_id>', methods=['GET'])
def download_zip(survey_id):
  """Download zip of survey creative(s) and snapshot a version."""
  google_auth.require_editor()
  survey_doc = survey_service.get_doc_by_id(survey_id)

  # this is the standard survey
  filename, data = survey_service.zip_file(survey_id, survey_doc.to_dict())
  survey_service.flash_zip_html5_qa(data)
  return send_file(
      data,
      mimetype='application/zip',
      etag=False,
      max_age=0,
      last_modified=datetime.datetime.now(),
      as_attachment=True,
      download_name=filename)


@app.route(
    '/survey/download_zip/<string:survey_id>/version/<int:version>',
    methods=['GET'])
def download_zip_version(survey_id, version):
  """Re-zip a stored snapshot. Does not write a new version."""
  google_auth.require_editor()
  snapshot = survey_service.get_version(survey_id, version)
  if not snapshot:
    flash('Version not found')
    return redirect(url_for('edit', survey_id=survey_id))
  filename, data = survey_service.zip_file(
      survey_id, snapshot, record_version=False)
  survey_service.flash_zip_html5_qa(data)
  return send_file(
      data,
      mimetype='application/zip',
      etag=False,
      max_age=0,
      last_modified=datetime.datetime.now(),
      as_attachment=True,
      download_name=filename)


@app.route('/survey/download_responses/<string:survey_id>', methods=['GET'])
def download_responses(survey_id):
  """Download survey responses as a streamed CSV (chunked, not one string)."""
  return Response(
      stream_with_context(survey_service.iter_response_csv(survey_id)),
      mimetype='text/csv',
      headers={'Content-disposition': 'attachment; filename=surveydata.csv'})


@app.route('/survey/download_responses_context/<string:survey_id>', methods=['GET'])
def download_responses_context(survey_id):
  """Download survey responses with question text as a streamed CSV."""
  return Response(
      stream_with_context(
          survey_service.iter_response_csv(survey_id, with_context=True)),
      mimetype='text/csv',
      headers={
          'Content-disposition':
              'attachment; filename=surveydata_context.csv'
      })


@app.route('/survey/download_breakouts/<string:survey_id>', methods=['GET'])
def download_breakouts(survey_id):
  """Download size/placement/site/creative/date/segment lift breakouts as CSV."""
  return Response(
      survey_service.download_breakouts(survey_id),
      mimetype='text/csv',
      headers={
          'Content-disposition':
              'attachment; filename=survey_breakouts.csv'
      })


@app.route('/survey/download_bulk_upload/<string:survey_id>', methods=['GET'])
def download_bulk_upload(survey_id):
  """CM360/DV360 bulk-upload CSVs (sidecar files; no API)."""
  google_auth.require_editor()
  survey_doc = survey_service.get_doc_by_id(survey_id)
  if not survey_doc or not getattr(survey_doc, 'exists', False):
    flash('Survey not found')
    return redirect(url_for('index'))
  filename, payload = survey_service.bulk_upload_payload(
      survey_id, survey_doc.to_dict() or {})
  return send_file(
      io.BytesIO(payload),
      mimetype='application/zip',
      as_attachment=True,
      download_name=filename)


@app.route('/survey/download_tags/<string:survey_id>', methods=['GET'])
def download_tags(survey_id):
  """Trafficking tag sheet (CSV or XLSX) for one survey."""
  google_auth.require_editor()
  survey_doc = survey_service.get_doc_by_id(survey_id)
  if not survey_doc or not getattr(survey_doc, 'exists', False):
    flash('Survey not found')
    return redirect(url_for('index'))
  fmt = (request.args.get('format') or 'csv').strip().lower()
  filename, payload, mime = survey_service.tag_sheet_payload(
      survey_id, survey_doc.to_dict() or {}, fmt=fmt)
  return send_file(
      io.BytesIO(payload),
      mimetype=mime,
      as_attachment=True,
      download_name=filename)


def _planner_raw_from_request():
  keys = (
      'baseline', 'mde_mode', 'mde_relative', 'mde_absolute', 'confidence',
      'power', 'comparisons', 'response_rate', 'control_share')
  raw = {}
  for key in keys:
    value = request.values.get(key)
    if value is not None and str(value).strip() != '':
      raw[key] = value
  return raw


@app.route('/survey/sample-size', methods=['GET', 'POST'])
@app.route('/survey/sample-size/<string:survey_id>', methods=['GET', 'POST'])
def sample_size_planner(survey_id=None):
  """Brand Lift sample-size planner. Viewers read; editors may save on a survey."""
  survey = None
  stored = None
  if survey_id:
    survey_doc = survey_service.get_doc_by_id(survey_id)
    if not survey_doc or not getattr(survey_doc, 'exists', False):
      flash('Survey not found')
      return redirect(url_for('index'))
    survey = survey_doc.to_dict() or {}
    stored = survey.get('sample_plan') if isinstance(survey.get('sample_plan'), dict) else None

  if request.method == 'POST':
    google_auth.require_editor()
    if not survey_id:
      flash('Save a survey first, then attach a sample plan to it.')
      return redirect(url_for('sample_size_planner'))
    computed = sample_size.compute(_planner_raw_from_request())
    if computed['result'].get('error'):
      flash(computed['result']['error'])
      return redirect(url_for('sample_size_planner', survey_id=survey_id))
    survey_service.save_sample_plan(
        survey_id, sample_size.storage_payload(
            computed['inputs'], computed['result']))
    flash('Sample plan saved on this survey. The report uses it for sequential status.')
    return redirect(url_for('sample_size_planner', survey_id=survey_id))

  raw = _planner_raw_from_request()
  if not raw and stored:
    raw = stored
  computed = sample_size.compute(raw)
  title = 'Sample-size planner'
  if survey:
    title = 'Sample size · %s' % (
        survey.get('displayname') or survey.get('surveyname') or survey_id)
  return render_template(
      'sample_size.html',
      title=title,
      survey=survey,
      survey_id=survey_id,
      stored=stored,
      inputs=computed['inputs'],
      result=computed['result'],
      table=computed['table'],
      defaults=sample_size.DEFAULTS,
      confidence_choices=sample_size.CONFIDENCE_CHOICES,
      power_choices=sample_size.POWER_CHOICES,
      min_n=30)


@app.route('/survey/reporting/<string:survey_id>', methods=['GET'])
def reporting(survey_id):
  """Survey reporting (Brand Lift with CIs; Brand Track distributions)."""
  survey_doc = survey_service.get_doc_by_id(survey_id)

  if survey_doc.exists:
    survey_info = survey_doc.to_dict()
    report = survey_service.get_report(survey_id)
    page_title = (
        'Brand Lift stats' if survey_service.is_brand_lift(survey_info)
        else 'Survey stats')
    return render_template(
        'reporting.html',
        report=report,
        survey=survey_info,
        survey_id=survey_id,
        looker_studio_url=reporting_views.looker_studio_url(
            os.environ.get('PROJECT_ID'), survey_id=survey_id),
        title=page_title)
  else:
    flash('Survey not found')
    return redirect(url_for('index'))


@app.errorhandler(403)
def forbidden(_error):
  return render_template('403.html', title='Not allowed'), 403


@app.context_processor
def inject_receiver_params():
  ctx = google_auth.login_context()
  ctx.update({
      'receiver_url': os.environ.get('RECEIVER_URL') or '',
      'gtag_id': os.environ.get('GTAG_ID') or '',
      'brand_name': brand.brand_name(),
      'badge_letter': brand.badge_letter(),
      'badge_tooltip': brand.badge_tooltip(),
      'ui_help': ui_help.ENTRIES,
  })
  return ctx


@app.template_filter('get_all_question_text')
def get_all_question_text(survey):
  return survey_service.get_all_question_text(survey.to_dict())


@app.template_filter('survey_label')
def survey_label_filter(survey):
  return survey_service.survey_label(survey)


@app.template_filter('survey_identity_line')
def survey_identity_line_filter(survey):
  return survey_service.survey_identity_line(survey)


@app.template_filter('created_at_display')
def created_at_display_filter(survey):
  return survey_service.created_at_display(survey)


@app.template_filter('created_at_title')
def created_at_title_filter(survey):
  return survey_service.created_at_title(survey)


@app.template_filter('created_by_display')
def created_by_display_filter(survey):
  return survey_service.created_by_display(survey)


@app.template_filter('compact_count')
def compact_count_filter(item):
  return survey_service.compact_count(item)


@app.template_filter('sizes_compact')
def sizes_compact_filter(keys):
  return survey_service.sizes_compact(keys)


@app.template_filter('format_percentage')
def format_percentage(num):
  if num is None or (isinstance(num, float) and math.isnan(num)):
    return '—'
  return '{:.2%}'.format(num)


@app.template_filter('format_pvalue')
def format_pvalue(num):
  if num is None or (isinstance(num, float) and math.isnan(num)):
    return '—'
  if num < 0.001:
    return '< 0.001'
  return '{:.3f}'.format(num)


@app.template_filter('is_brand_lift')
def is_brand_lift_filter(survey):
  return survey_service.is_brand_lift(survey)


@app.template_filter('survey_size_keys')
def survey_size_keys_filter(survey):
  return survey_service.survey_size_keys(survey)


@app.template_filter('has_reporting')
def has_reporting(survey):
  """Stats are available for Brand Lift and Brand Track."""
  return True


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=flask_port(), debug=True)
