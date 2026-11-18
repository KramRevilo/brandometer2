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
import os

# Flask imports
from flask import flash
from flask import Flask
from flask import redirect
from flask import render_template
from flask import request
from flask import Response
from flask import send_file
from flask import url_for
from flask_basicauth import BasicAuth
from flask_bootstrap import Bootstrap

# local file imports
import forms
from forms import DEFAULT_CSS
import survey_service
from forms import RESPONSES_AT_END

# Project setup
title = 'Sonar'
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-only-not-for-production')
Bootstrap(app)
app.config['BASIC_AUTH_USERNAME'] = os.environ.get('AUTH_USERNAME')
app.config['BASIC_AUTH_PASSWORD'] = os.environ.get('AUTH_PASSWORD')
basic_auth = BasicAuth(app)
# Cloud Shell Web Preview (and similar proxies) cannot complete the browser
# basic-auth challenge. Set DISABLE_BASIC_AUTH=1 for local/proxy use only.
# Never set this in App Engine / ./deploy.
_disable_basic_auth = os.environ.get('DISABLE_BASIC_AUTH', '').strip().lower()
app.config['BASIC_AUTH_FORCE'] = _disable_basic_auth not in (
    '1', 'true', 'yes', 'on')

# Used when a survey has no BigQuery rows yet.
MRC_INIT = 999999999


@app.route('/')
def root():
  # Path-only Location so Cloud Shell / reverse proxies do not flip http/https.
  return redirect('/index')


@app.route('/index')
def index():
  show_archived = request.args.get('archived', '').strip().lower() in (
      '1', 'true', 'yes', 'on')
  all_surveys = survey_service.list_surveys(include_archived=show_archived)
  stat_array = []
  tmp_stats = survey_service.get_all_response_counts()

  for survey in all_surveys:
    df = tmp_stats.loc[tmp_stats['ID'] == survey.id]
    segmentation_rows = df.to_dict()

    most_recent_change = MRC_INIT
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

    if most_recent_change == MRC_INIT:
      days_since = None
      last_change_display = ''
    else:
      days_since = most_recent_change
      last_change_display = most_recent_change

    status_text, status_label = survey_service.classify_status(days_since)
    stat_array.append({
        'id': survey.id,
        'stats': segs,
        'last_change': last_change_display,
        'status': status_text,
        'status_label': status_label,
    })

  return render_template(
      'index.html',
      all_surveys=all_surveys,
      stat_array=stat_array,
      show_archived=show_archived,
      title=title)


@app.route('/survey/create', methods=['GET', 'POST'])
def create():
  """Survey creation."""
  form = forms.QuestionForm()
  if form.validate_on_submit():
    survey_service.create(form)
    return redirect(url_for('index'))
  return render_template('questions.html', title='Survey Creation', form=form)


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

    return render_template(
        'creative.html',
        survey=survey_info,
        survey_id=survey_id,
        manual_responses=True,
        show_back_button=True,
        all_question_json=survey_service.get_question_json(survey_info),
        seg='preview',
        custom_css=custom_css,
        response_type=response_type,
        # Do not post preview answers to BigQuery.
        receiver_url='',
        thankyou_text=survey_service.get_thank_you_text(survey_info),
        next_text=survey_service.get_next_text(survey_info),
        comment_text=survey_service.get_comment_text(survey_info))
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
  return render_template('questions.html', form=form)


@app.route('/survey/download_zip/<string:survey_id>', methods=['GET'])
def download_zip(survey_id):
  """Download zip of survey creative(s)."""
  survey_doc = survey_service.get_doc_by_id(survey_id)

  # check the survey to see if it's of the type that needs an alternate creative
  # print(f'in ZIP handler - survey_doc: {survey_doc.to_dict()}')

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


@app.route('/survey/download_responses/<string:survey_id>', methods=['GET'])
def download_responses(survey_id):
  """Download survey responses."""
  if request.method == 'GET':
    csv = survey_service.download_responses(survey_id)
    return Response(
        csv,
        mimetype='text/csv',
        headers={'Content-disposition': 'attachment; filename=surveydata.csv'})


@app.route('/survey/download_responses_context/<string:survey_id>', methods=['GET'])
def download_responses_context(survey_id):
  """Download survey responses with context"""
  if request.method == 'GET':
    csv = survey_service.download_responses_with_context(survey_id)
    return Response(
        csv,
        mimetype='text/csv',
        headers={'Content-disposition': 'attachment; filename=surveydata_context.csv'})


@app.route('/survey/reporting/<string:survey_id>', methods=['GET'])
def reporting(survey_id):
  """Survey reporting."""
  survey_doc = survey_service.get_doc_by_id(survey_id)

  if survey_doc.exists:
    survey_info = survey_doc.to_dict()
    if not survey_service.is_brand_lift(survey_info):
      flash('Reporting is available for Brand Lift surveys only')
      return redirect(url_for('index'))
    results = survey_service.get_brand_lift_results(survey_id)
    return render_template(
        'reporting.html',
        results=results,
        survey=survey_info,
        survey_id=survey_id)
  else:
    flash('Survey not found')
    return redirect(url_for('index'))


@app.context_processor
def inject_receiver_params():
  return {
      'receiver_url': os.environ.get('RECEIVER_URL') or '',
      'gtag_id': os.environ.get('GTAG_ID') or '',
  }


@app.template_filter('get_all_question_text')
def get_all_question_text(survey):
  return survey_service.get_all_question_text(survey.to_dict())


@app.template_filter('format_percentage')
def format_percentage(num):
  return '{:.2%}'.format(num)


@app.template_filter('has_reporting')
def has_reporting(survey):
  """True only for Brand Lift surveys (stats / reporting)."""
  return survey_service.is_brand_lift(survey)


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
    # index()
