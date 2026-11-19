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
from flask import stream_with_context
from flask import url_for
from flask_basicauth import BasicAuth

# local file imports
import brand
import creative_size
import css_theme
import forms
from forms import DEFAULT_CSS
import survey_service
from forms import RESPONSES_AT_END

# Project setup. Overridden per request by APP_BRAND_NAME (default Brandometer).
title = brand.DEFAULT_BRAND_NAME
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-only-not-for-production')
app.config['BASIC_AUTH_USERNAME'] = os.environ.get('AUTH_USERNAME')
app.config['BASIC_AUTH_PASSWORD'] = os.environ.get('AUTH_PASSWORD')
basic_auth = BasicAuth(app)
# Cloud Shell Web Preview (and similar proxies) cannot complete the browser
# basic-auth challenge. Set DISABLE_BASIC_AUTH=1 for local/proxy use only.
# Never set this in App Engine / ./deploy.
_disable_basic_auth = os.environ.get('DISABLE_BASIC_AUTH', '').strip().lower()
app.config['BASIC_AUTH_FORCE'] = _disable_basic_auth not in (
    '1', 'true', 'yes', 'on')

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
  }


def _index_query(show_archived, page=None, filters=None):
  args = {}
  if show_archived:
    args['archived'] = 1
  if page:
    args['page'] = page
  filters = filters or {}
  for key in ('q', 'client', 'agency', 'year', 'size'):
    value = (filters.get(key) or '').strip()
    if value:
      args[key] = value
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


@app.route('/index')
def index():
  request_started = time.perf_counter()
  show_archived = _truthy_arg(request.args.get('archived'))
  filters = _filter_args()
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
      size=filters['size'])
  _log_index_timing('filter', filter_started, n=len(surveys))

  def index_query(archived_flag, page=None):
    return _index_query(archived_flag, page, filters)

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
      stats_ids=','.join(survey_ids),
      index_query=index_query,
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
  """Load count / last-response / status cells (BQ, cached) after the list paints."""
  started = time.perf_counter()
  survey_ids = [sid for sid in request.args.get('ids', '').split(',') if sid]
  stat_array = survey_service.build_stat_array(survey_ids)
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


def _render_editor(form, page_title, survey_id=None, versions=None):
  ctx = _editor_context(form)
  suggestions = survey_service.identity_suggestions()
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
      client_suggestions=suggestions.get('clients') or [],
      agency_suggestions=suggestions.get('agencies') or [],
      preset_groups=ctx.get('preset_groups') or [],
      size_choices=ctx.get('size_choices') or creative_size.SIZE_CHOICES,
      layout_fix_css=ctx.get('layout_fix_css') or '',
      size_overlay_css=ctx.get('size_overlay_css') or {},
      badge_icons=ctx.get('badge_icons') or brand.badge_icon_list(),
      badge_text_max=ctx.get('badge_text_max') or brand.BADGE_TEXT_MAX,
      badge_text_default=ctx.get('badge_text_default') or brand.badge_tooltip())


@app.route('/survey/create', methods=['GET', 'POST'])
def create():
  """Survey creation."""
  form = forms.QuestionForm()
  if form.validate_on_submit():
    survey_service.create(form)
    return redirect(url_for('index'))
  return _render_editor(form, 'Create survey')


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
    custom_css = creative_size.apply_overlay(custom_css, size)

    return render_template(
        'creative.html',
        survey=survey_info,
        survey_id=survey_id,
        manual_responses=True,
        show_back_button=True,
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
        thankyou_text=survey_service.get_thank_you_text(survey_info),
        next_text=survey_service.get_next_text(survey_info),
        comment_text=survey_service.get_comment_text(survey_info),
        **brand.badge_render_vars(survey_info))
  else:
    flash('Survey not found')
    return redirect(url_for('index'))


@app.route('/survey/delete', methods=['GET', 'DELETE'])
def delete():
  """Delete survey."""
  if request.method == 'GET':
    docref_id = request.args.get('survey_id')
    survey_service.delete_by_id(docref_id)
    flash(f'Survey \'{docref_id}\' deleted')
  return redirect(url_for('index'))


@app.route('/survey/copy', methods=['GET'])
def copy_survey():
  """Copy a survey and open the new document in the editor."""
  survey_id = request.args.get('survey_id')
  new_ref = survey_service.copy_by_id(survey_id)
  if new_ref is None:
    flash('Survey not found')
    return redirect(url_for('index'))
  flash(f'Copied as {new_ref.id}')
  return redirect(url_for('edit', survey_id=new_ref.id))


@app.route('/survey/archive', methods=['GET'])
def archive():
  """Archive or restore a survey."""
  survey_id = request.args.get('survey_id')
  archived = request.args.get('archived', '1').strip().lower() in (
      '1', 'true', 'yes', 'on')
  survey_service.set_archived(survey_id, archived)
  flash('Survey archived' if archived else 'Survey restored')
  if request.args.get('view') == 'archived':
    return redirect(url_for('index', archived=1))
  return redirect(url_for('index'))


@app.route('/survey/edit', methods=['POST', 'PUT', 'GET'])
def edit():
  """Edit Survey."""
  # Create form object
  form = forms.QuestionForm()

  # Get info about survey from Firebase
  docref_id = request.args.get('survey_id')
  edit_doc = survey_service.get_doc_by_id(docref_id)

  # Set the form data according to what was loaded from Firebase
  if request.method == 'GET':
    survey_service.set_form_data(form, edit_doc)

  # present page, gather entries upon submission
  if form.validate_on_submit():
    survey_service.update_by_id(docref_id, form)
    return redirect(url_for('index'))
  versions = []
  if edit_doc and getattr(edit_doc, 'exists', False):
    versions = survey_service.list_versions(docref_id)
  return _render_editor(
      form, 'Edit survey', survey_id=docref_id, versions=versions)


@app.route('/survey/download_zip/<string:survey_id>', methods=['GET'])
def download_zip(survey_id):
  """Download zip of survey creative(s) and snapshot a version."""
  survey_doc = survey_service.get_doc_by_id(survey_id)

  # this is the standard survey
  filename, data = survey_service.zip_file(survey_id, survey_doc.to_dict())

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
  snapshot = survey_service.get_version(survey_id, version)
  if not snapshot:
    flash('Version not found')
    return redirect(url_for('edit', survey_id=survey_id))
  filename, data = survey_service.zip_file(
      survey_id, snapshot, record_version=False)
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
        title=page_title)
  else:
    flash('Survey not found')
    return redirect(url_for('index'))


@app.context_processor
def inject_receiver_params():
  return {
      'receiver_url': os.environ.get('RECEIVER_URL') or '',
      'gtag_id': os.environ.get('GTAG_ID') or '',
      'brand_name': brand.brand_name(),
      'badge_letter': brand.badge_letter(),
      'badge_tooltip': brand.badge_tooltip(),
  }


@app.template_filter('get_all_question_text')
def get_all_question_text(survey):
  return survey_service.get_all_question_text(survey.to_dict())


@app.template_filter('survey_label')
def survey_label_filter(survey):
  return survey_service.survey_label(survey)


@app.template_filter('survey_identity_line')
def survey_identity_line_filter(survey):
  return survey_service.survey_identity_line(survey)


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
