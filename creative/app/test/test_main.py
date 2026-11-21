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

import datetime
import os
import re
import time
import unittest
from unittest import mock

import pandas
import forms
import survey_collection
import survey_service

import main


_COUNTS_COLUMNS = [
    'ID', 'Segmentation', 'max_date', 'days_since_response', 'response_count'
]


class MainRoutesTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    main.app.config['AUTH_BYPASS'] = True
    main.app.config['WTF_CSRF_ENABLED'] = False
    self.client = main.app.test_client()
    survey_service.clear_stats_cache()
    self._suggestions = mock.patch.object(
        survey_service, 'identity_suggestions',
        return_value={'clients': ['Acme'], 'agencies': ['OMD']})
    self._suggestions.start()
    self.addCleanup(self._suggestions.stop)

  def tearDown(self):
    main.app.config['AUTH_BYPASS'] = False
    main.app.config['WTF_CSRF_ENABLED'] = True
    super().tearDown()

  def _survey(self, doc_id, data):
    doc = mock.Mock()
    doc.id = doc_id
    doc.to_dict.return_value = data
    doc.exists = True
    return doc

  @mock.patch.object(survey_service, 'get_response_counts')
  @mock.patch.object(survey_service, 'list_surveys')
  def test_index_lists_surveys_once(self, list_mock, counts_mock):
    list_mock.return_value = []
    counts_mock.return_value = pandas.DataFrame(columns=_COUNTS_COLUMNS)

    response = self.client.get('/index')

    self.assertEqual(response.status_code, 200)
    list_mock.assert_called_once_with(include_archived=False)
    self.assertIn(b'Show archived', response.data)
    self.assertIn(b'No surveys yet', response.data)
    self.assertIn(b'favicon.svg', response.data)
    self.assertIn(b'rel="apple-touch-icon"', response.data)

  @mock.patch.object(survey_service, 'get_response_counts')
  @mock.patch.object(survey_service, 'list_surveys')
  def test_index_show_archived(self, list_mock, counts_mock):
    list_mock.return_value = []
    counts_mock.return_value = pandas.DataFrame(columns=_COUNTS_COLUMNS)

    response = self.client.get('/index?archived=1')

    self.assertEqual(response.status_code, 200)
    list_mock.assert_called_once_with(include_archived=True)
    self.assertIn(b'Hide archived', response.data)

  @mock.patch.object(survey_service, 'get_response_counts')
  @mock.patch.object(survey_service, 'list_surveys')
  def test_index_status_chip_and_stats_for_track(
      self, list_mock, counts_mock):
    list_mock.return_value = [
        self._survey('s1', {
            'surveyname': 'Track one',
            'surveytype': 'brand_track',
            'question1': 'Q1',
        })
    ]
    counts_mock.return_value = pandas.DataFrame(columns=_COUNTS_COLUMNS)

    response = self.client.get('/index')

    self.assertEqual(response.status_code, 200)
    self.assertIn(b'Loading', response.data)
    self.assertNotIn(b'No data', response.data)
    self.assertIn(b'View survey stats', response.data)
    self.assertIn(b'Sizes', response.data)
    self.assertIn(b'300', response.data)
    self.assertIn(b'filter-size', response.data)
    counts_mock.assert_not_called()
    self.assertNotIn(b'View Brand Lift Stats', response.data)
    self.assertIn(b'Copy Survey', response.data)
    self.assertIn(b'Archive Survey', response.data)
    self.assertIn(b'each RespondentID (or BomID on older rows) as one respondent',
                  response.data)

  @mock.patch.object(survey_service, 'get_response_counts')
  @mock.patch.object(survey_service, 'list_surveys')
  def test_index_shows_stats_for_brand_lift(self, list_mock, counts_mock):
    list_mock.return_value = [
        self._survey('s2', {
            'surveyname': 'Lift one',
            'surveytype': 'brand_lift',
            'question1': 'Q1',
        })
    ]
    counts_mock.return_value = pandas.DataFrame({
        'ID': ['s2'],
        'Segmentation': ['default_expose'],
        'max_date': ['2026-11-18'],
        'days_since_response': [1],
        'response_count': [4],
    })

    response = self.client.get('/index')

    self.assertEqual(response.status_code, 200)
    self.assertIn(b'View Brand Lift Stats', response.data)
    self.assertIn(b'Loading', response.data)
    self.assertNotIn(b'text-bg-success', response.data)
    self.assertIn(b'vendor/htmx.min.js', response.data)
    self.assertIn(b'every 30s', response.data)
    self.assertIn(b'document.hidden', response.data)
    self.assertIn(b'hx-trigger="load, every', response.data)
    self.assertIn(b'/index/stats-partial', response.data)
    self.assertIn(b'X-CSRFToken', response.data)
    self.assertIn(b'method="post"', response.data)
    self.assertIn(b'Really delete?', response.data)
    counts_mock.assert_not_called()

  @mock.patch.object(survey_service, 'get_response_counts')
  @mock.patch.object(survey_service, 'list_surveys')
  def test_index_pagination_preserves_archived(
      self, list_mock, counts_mock):
    list_mock.return_value = [
        self._survey('s%s' % i, {
            'surveyname': 'Survey %s' % i,
            'surveytype': 'brand_track',
            'question1': 'Q',
            'archived': True,
        }) for i in range(5)
    ]
    counts_mock.return_value = pandas.DataFrame(columns=_COUNTS_COLUMNS)

    with mock.patch.object(survey_service, 'HOMEPAGE_PAGE_SIZE', 2):
      response = self.client.get('/index?archived=1&page=2')

    self.assertEqual(response.status_code, 200)
    list_mock.assert_called_once_with(include_archived=True)
    self.assertIn(b'Survey 2', response.data)
    self.assertNotIn(b'Survey 0', response.data)
    self.assertIn(b'archived=1', response.data)
    self.assertIn(b'page=1', response.data)
    self.assertIn(b'page=3', response.data)
    self.assertIn(b'Previous', response.data)
    self.assertIn(b'Next', response.data)

  @mock.patch.object(survey_service, 'get_response_counts')
  @mock.patch.object(survey_service, 'list_surveys')
  def test_index_filters_by_client_search_and_year(self, list_mock, counts_mock):
    list_mock.return_value = [
        self._survey('s1', {
            'surveyname': 'Alpha study',
            'displayname': 'Friendly A',
            'client': 'Acme',
            'agency': 'OMD',
            'created_at': '2026-02-01T00:00:00Z',
            'question1': 'Q',
        }),
        self._survey('s2', {
            'surveyname': 'Beta',
            'client': 'Other',
            'agency': 'WPP',
            'created_at': '2025-02-01T00:00:00Z',
            'question1': 'Q',
        }),
        self._survey('s3', {
            'surveyname': 'Gamma old',
            'client': 'Acme',
            'agency': 'OMD',
            'question1': 'Q',
        }),
    ]
    counts_mock.return_value = pandas.DataFrame(columns=_COUNTS_COLUMNS)

    by_client = self.client.get('/index?client=Acme')
    self.assertEqual(by_client.status_code, 200)
    self.assertIn(b'Friendly A', by_client.data)
    self.assertIn(b'Gamma old', by_client.data)
    self.assertNotIn(b'>Beta<', by_client.data)
    self.assertNotIn(b's2', by_client.data)
    self.assertIn(b'>Acme</td>', by_client.data)
    self.assertIn(b'>OMD</td>', by_client.data)
    self.assertNotIn('Acme · OMD'.encode('utf-8'), by_client.data)
    self.assertIn(b'All clients', by_client.data)
    self.assertIn(b'filter-created-by', by_client.data)
    self.assertIn(b'sort=name', by_client.data)
    self.assertIn(b'Created by', by_client.data)

    by_search = self.client.get('/index?q=friendly')
    self.assertIn(b'Friendly A', by_search.data)
    self.assertNotIn(b's2', by_search.data)
    self.assertNotIn(b'Gamma old', by_search.data)

    by_year = self.client.get('/index?year=unknown')
    self.assertIn(b'Gamma old', by_year.data)
    self.assertNotIn(b'Friendly A', by_year.data)
    self.assertNotIn(b's2', by_year.data)
    self.assertIn(b'Unknown', by_year.data)

    named = self.client.get('/index?sort=name&dir=asc')
    html = named.data.decode('utf-8')
    self.assertLess(html.find('Friendly A'), html.find('Gamma old'))
    self.assertIn('sort=name', html)
    self.assertIn('dir=desc', html)

    default = self.client.get('/index')
    default_html = default.data.decode('utf-8')
    self.assertLess(default_html.find('Friendly A'), default_html.find('Beta'))
    self.assertLess(default_html.find('Beta'), default_html.find('Gamma old'))

  @mock.patch.object(survey_service, 'get_response_counts')
  @mock.patch.object(survey_service, 'list_surveys')
  def test_index_pagination_preserves_filters_and_archive(
      self, list_mock, counts_mock):
    list_mock.return_value = [
        self._survey('s%s' % i, {
            'surveyname': 'Survey %s' % i,
            'client': 'Acme',
            'created_at': '2026-01-01T00:00:00Z',
            'question1': 'Q',
            'archived': True,
        }) for i in range(5)
    ]
    counts_mock.return_value = pandas.DataFrame(columns=_COUNTS_COLUMNS)

    with mock.patch.object(survey_service, 'HOMEPAGE_PAGE_SIZE', 2):
      response = self.client.get(
          '/index?archived=1&client=Acme&year=2026&q=Survey&page=2')

    self.assertEqual(response.status_code, 200)
    list_mock.assert_called_once_with(include_archived=True)
    self.assertIn(b'Survey 2', response.data)
    self.assertNotIn(b'Survey 0', response.data)
    self.assertIn(b'archived=1', response.data)
    self.assertIn(b'client=Acme', response.data)
    self.assertIn(b'year=2026', response.data)
    self.assertIn(b'q=Survey', response.data)
    self.assertIn(b'page=1', response.data)
    self.assertIn(b'page=3', response.data)

  def test_flask_port_defaults_to_8080(self):
    with mock.patch.dict(os.environ, {}, clear=False):
      os.environ.pop('PORT', None)
      self.assertEqual(main.flask_port(), 8080)
    with mock.patch.dict(os.environ, {'PORT': '9099'}):
      self.assertEqual(main.flask_port(), 9099)
    with mock.patch.dict(os.environ, {'PORT': 'nope'}):
      self.assertEqual(main.flask_port(), 8080)

  @mock.patch.object(survey_service, 'get_response_counts')
  @mock.patch.object(survey_service, 'list_surveys')
  def test_stats_partial_returns_oob_cells(self, list_mock, counts_mock):
    counts_mock.return_value = pandas.DataFrame({
        'ID': ['s1'],
        'Segmentation': ['default_expose'],
        'max_date': ['2026-11-18'],
        'days_since_response': [1],
        'response_count': [9],
    })

    response = self.client.get('/index/stats-partial?ids=s1')

    self.assertEqual(response.status_code, 200)
    list_mock.assert_not_called()
    self.assertIn(b'id="count-s1"', response.data)
    self.assertIn(b'id="last-s1"', response.data)
    self.assertIn(b'id="status-s1"', response.data)
    self.assertIn(b'hx-swap-oob="true"', response.data)
    self.assertIn(b'9', response.data)
    self.assertIn(b'Active', response.data)

  @mock.patch.object(survey_service, 'list_surveys')
  @mock.patch.object(survey_service, '_fetch_all_response_counts')
  def test_stats_partial_does_not_requery_bq_within_ttl(
      self, fetch_mock, list_mock):
    fetch_mock.return_value = pandas.DataFrame({
        'ID': ['s1'],
        'Segmentation': ['seg'],
        'max_date': ['2026-11-18'],
        'days_since_response': [1],
        'response_count': [4],
    })
    with mock.patch.dict(os.environ, {'STATS_CACHE_SECONDS': '90'}):
      self.client.get('/index/stats-partial?ids=s1')
      self.client.get('/index/stats-partial?ids=s1')
    self.assertEqual(fetch_mock.call_count, 1)
    list_mock.assert_not_called()

  @mock.patch.object(survey_service, 'get_response_counts')
  @mock.patch.object(survey_service, 'list_surveys')
  def test_index_filters_by_size_and_shows_chips_and_split_view(
      self, list_mock, counts_mock):
    list_mock.return_value = [
        self._survey('wide', {
            'surveyname': 'Wide pack',
            'creativesizes': ['300x250', '970x250'],
            'question1': 'Q',
        }),
        self._survey('tall', {
            'surveyname': 'Tall only',
            'creativesize': '160x600',
            'question1': 'Q',
        }),
        self._survey('legacy', {
            'surveyname': 'Legacy default',
            'question1': 'Q',
        }),
    ]
    counts_mock.return_value = pandas.DataFrame(columns=_COUNTS_COLUMNS)

    home = self.client.get('/index')
    self.assertEqual(home.status_code, 200)
    self.assertIn(b'filter-size', home.data)
    self.assertIn('300×250'.encode('utf-8'), home.data)
    self.assertIn('970×250'.encode('utf-8'), home.data)
    self.assertIn('160×600'.encode('utf-8'), home.data)
    self.assertIn(b'title="View Survey"', home.data)
    self.assertIn(b'aria-label="More actions"', home.data)
    self.assertIn(b'/survey/preview/wide?size=970x250', home.data)
    self.assertIn(b'/survey/preview/tall', home.data)
    self.assertNotIn(b'/survey/preview/tall?size=', home.data)
    self.assertNotIn(b'dropdown-toggle-split', home.data)
    counts_mock.assert_not_called()

    by_size = self.client.get('/index?size=970x250')
    self.assertIn(b'Wide pack', by_size.data)
    self.assertNotIn(b'Tall only', by_size.data)
    self.assertNotIn(b'Legacy default', by_size.data)
    self.assertIn(b'size=970x250', by_size.data)

    default_size = self.client.get('/index?size=300x250')
    self.assertIn(b'Wide pack', default_size.data)
    self.assertIn(b'Legacy default', default_size.data)
    self.assertNotIn(b'Tall only', default_size.data)

  @mock.patch.object(survey_service, 'get_response_counts')
  @mock.patch.object(survey_service, 'list_surveys')
  def test_index_pagination_preserves_size_filter(
      self, list_mock, counts_mock):
    list_mock.return_value = [
        self._survey('s%s' % i, {
            'surveyname': 'Billboard %s' % i,
            'creativesizes': ['970x250'],
            'question1': 'Q',
            'archived': True,
        }) for i in range(5)
    ]
    counts_mock.return_value = pandas.DataFrame(columns=_COUNTS_COLUMNS)

    with mock.patch.object(survey_service, 'HOMEPAGE_PAGE_SIZE', 2):
      response = self.client.get(
          '/index?archived=1&size=970x250&page=2')

    self.assertEqual(response.status_code, 200)
    self.assertIn(b'Billboard 2', response.data)
    self.assertNotIn(b'Billboard 0', response.data)
    self.assertIn(b'size=970x250', response.data)
    self.assertIn(b'archived=1', response.data)
    self.assertIn(b'page=1', response.data)
    self.assertIn(b'page=3', response.data)
    counts_mock.assert_not_called()

  @mock.patch.object(survey_service, '_fetch_all_response_counts')
  @mock.patch.object(survey_service, 'list_surveys')
  def test_index_renders_before_slow_bq_and_logs_timing(
      self, list_mock, fetch_mock):
    list_mock.return_value = [
        self._survey('s1', {'surveyname': 'Timed', 'question1': 'Q'})
    ]

    def slow_fetch(survey_ids=None):
      time.sleep(0.35)
      return pandas.DataFrame(columns=_COUNTS_COLUMNS)

    fetch_mock.side_effect = slow_fetch
    started = time.perf_counter()
    with self.assertLogs('main', level='DEBUG') as captured:
      response = self.client.get('/index')
    index_ms = (time.perf_counter() - started) * 1000
    self.assertEqual(response.status_code, 200)
    self.assertLess(index_ms, 250)
    fetch_mock.assert_not_called()
    joined = '\n'.join(captured.output)
    self.assertIn('index.firestore_list_ms=', joined)
    self.assertIn('index.filter_ms=', joined)
    self.assertIn('index.render_ms=', joined)
    self.assertIn('index.request_ms=', joined)
    self.assertIn('bq=deferred', joined)
    self.assertIn(b'hx-trigger="load, every', response.data)
    self.assertIn(b'Loading', response.data)

    started = time.perf_counter()
    stats = self.client.get('/index/stats-partial?ids=s1')
    stats_ms = (time.perf_counter() - started) * 1000
    self.assertEqual(stats.status_code, 200)
    self.assertGreaterEqual(stats_ms, 300)
    fetch_mock.assert_called_once_with(['s1'])

  @mock.patch.object(survey_service, '_fetch_all_response_counts')
  def test_stats_partial_queries_only_requested_ids(self, fetch_mock):
    fetch_mock.return_value = pandas.DataFrame(columns=_COUNTS_COLUMNS)
    with mock.patch.dict(os.environ, {'STATS_CACHE_SECONDS': '0'}):
      self.client.get('/index/stats-partial?ids=page-a,page-b')
    fetch_mock.assert_called_once_with(['page-a', 'page-b'])

  def test_create_page_uses_iframe_preview_and_bootstrap5(self):
    response = self.client.get('/survey/create')
    self.assertEqual(response.status_code, 200)
    self.assertIn(b'vendor/bootstrap.min.css', response.data)
    self.assertIn(b'navbar-toggler', response.data)
    self.assertNotIn(b'navbar-header', response.data)
    self.assertIn(b'Live preview', response.data)
    self.assertIn(b'HTML5 spec QA', response.data)
    self.assertIn(b'html5_qa.txt', response.data)
    self.assertIn(b'<iframe', response.data)
    self.assertIn(b':srcdoc="previewSrcdoc"', response.data)
    csp = response.headers.get('Content-Security-Policy', '')
    self.assertIn("script-src 'self' 'unsafe-inline' 'unsafe-eval'", csp)
    self.assertIn('https://*.googleusercontent.com', csp)
    self.assertIn(b'vendor/alpine.min.js', response.data)
    self.assertIn(b'Advanced (CSS)', response.data)
    self.assertIn(b'Display name', response.data)
    self.assertNotIn(b'refreshFromCssSample', response.data)
    self.assertIn(b'scrolling="no"', response.data)
    self.assertIn(b'width: 302px', response.data)
    self.assertIn(b'height: 252px', response.data)
    self.assertIn(b'creativesize', response.data)
    self.assertIn(b'160x600', response.data)
    self.assertIn(b'300x600', response.data)
    self.assertIn(b'970x250', response.data)
    self.assertIn(b'answer1e', response.data)
    self.assertIn(b'answer1h', response.data)
    self.assertIn(b'Add answer', response.data)
    self.assertIn(b'Classic green', response.data)
    self.assertIn(b'theme-preset', response.data)
    self.assertIn(b'Disclosure badge', response.data)
    self.assertIn(b'name="badge_icon"', response.data)
    self.assertIn(b'value="B2"', response.data)
    self.assertIn(b'value="Ad"', response.data)
    self.assertIn(b'value="Dentsu"', response.data)
    self.assertIn(b'Use default', response.data)
    self.assertIn(b'id="badge_text"', response.data)
    self.assertIn(b'Hazard stripes', response.data)
    self.assertIn(b'previewFrameStyle', response.data)
    self.assertIn(b'End survey', response.data)
    self.assertIn(b'name="answer1anext"', response.data)
    self.assertIn(b'nextIsInvalid', response.data)
    self.assertIn(b'name="client"', response.data)
    self.assertIn(b'name="agency"', response.data)
    self.assertIn(b'list="client-suggestions"', response.data)
    self.assertIn(b'list="agency-suggestions"', response.data)
    self.assertIn(b'Acme', response.data)
    self.assertIn(b'OMD', response.data)
    self.assertIn(b'name="campaign_id"', response.data)
    self.assertIn(b'name="placement_id"', response.data)
    self.assertIn(b'name="ad_server"', response.data)
    self.assertIn(b'Campaign Manager 360', response.data)

  @mock.patch.object(survey_service, 'copy_by_id')
  def test_copy_opens_editor(self, copy_mock):
    copy_mock.return_value = mock.Mock(id='new123')

    response = self.client.post(
        '/survey/copy', data={'survey_id': 'old'}, follow_redirects=False)

    self.assertEqual(response.status_code, 302)
    self.assertIn('/survey/edit', response.headers['Location'])
    self.assertIn('survey_id=new123', response.headers['Location'])

  def test_copy_get_is_not_allowed(self):
    response = self.client.get('/survey/copy?survey_id=old')
    self.assertEqual(response.status_code, 405)

  @mock.patch.object(survey_service, 'set_archived')
  def test_archive_redirects_home(self, archive_mock):
    response = self.client.post(
        '/survey/archive',
        data={'survey_id': 'abc', 'archived': '1'},
        follow_redirects=False)

    archive_mock.assert_called_once_with('abc', True)
    self.assertEqual(response.status_code, 302)

  @mock.patch.object(survey_service, 'set_archived')
  def test_unarchive_from_archived_view(self, archive_mock):
    response = self.client.post(
        '/survey/archive',
        data={'survey_id': 'abc', 'archived': '0', 'view': 'archived'},
        follow_redirects=False)

    archive_mock.assert_called_once_with('abc', False)
    self.assertIn('archived=1', response.headers['Location'])

  def test_delete_and_archive_get_are_not_allowed(self):
    self.assertEqual(self.client.get('/survey/delete?survey_id=abc').status_code, 405)
    self.assertEqual(
        self.client.get('/survey/archive?survey_id=abc&archived=1').status_code,
        405)

  @mock.patch.object(survey_service, 'delete_by_id')
  def test_delete_posts(self, delete_mock):
    response = self.client.post(
        '/survey/delete', data={'survey_id': 'abc'}, follow_redirects=False)
    delete_mock.assert_called_once_with('abc')
    self.assertEqual(response.status_code, 302)

  @mock.patch.object(survey_service, 'get_survey_responses')
  @mock.patch.object(survey_service, 'get_doc_by_id')
  def test_reporting_brand_track_shows_distributions(self, doc_mock, responses_mock):
    doc_mock.return_value = self._survey('abc', {
        'surveytype': 'brand_track',
        'surveyname': 'Track',
        'question1': 'Aware?',
        'answer1a': 'Yes',
        'answer1b': 'No',
    })
    t = datetime.datetime(2026, 11, 18, 12, 0, 0)
    responses_mock.return_value = pandas.DataFrame({
        'CreatedAt': [t, t],
        'Segmentation': ['', ''],
        'Response': ['1:A', '1:B'],
        'BomID': ['b1', 'b2'],
    })

    response = self.client.get('/survey/reporting/abc')

    self.assertEqual(response.status_code, 200)
    self.assertIn(b'Aware?', response.data)
    self.assertIn(b'Responses per day', response.data)
    self.assertIn(b'Answer distribution', response.data)
    self.assertNotIn(b'>Lift</th>', response.data)
    self.assertNotIn(b'two-proportion z-test', response.data)

  @mock.patch.object(survey_service, 'get_survey_responses')
  @mock.patch.object(survey_service, 'get_doc_by_id')
  def test_reporting_brand_lift_shows_ci_and_empty_control(
      self, doc_mock, responses_mock):
    doc_mock.return_value = self._survey('abc', {
        'surveytype': 'brand_lift',
        'surveyname': 'Lift',
        'question1': 'Aware?',
        'answer1a': 'Yes',
        'answer1b': 'No',
    })
    t = datetime.datetime(2026, 11, 18, 12, 0, 0)
    responses_mock.return_value = pandas.DataFrame({
        'CreatedAt': [t, t],
        'Segmentation': ['default_expose', 'default_expose'],
        'Response': ['1:A', '1:B'],
        'BomID': ['e1', 'e2'],
    })

    response = self.client.get('/survey/reporting/abc')

    self.assertEqual(response.status_code, 200)
    self.assertIn(b'No control segment', response.data)
    self.assertIn(b'Answer distribution', response.data)

  @mock.patch.object(survey_service, 'get_survey_responses')
  @mock.patch.object(survey_service, 'get_doc_by_id')
  def test_reporting_brand_lift_shows_wilson_and_small_n(
      self, doc_mock, responses_mock):
    doc_mock.return_value = self._survey('abc', {
        'surveytype': 'brand_lift',
        'surveyname': 'Lift',
        'question1': 'Aware?',
        'answer1a': 'Yes',
        'answer1b': 'No',
    })
    t = datetime.datetime(2026, 11, 18, 12, 0, 0)
    responses_mock.return_value = pandas.DataFrame({
        'CreatedAt': [t, t, t, t],
        'Segmentation': [
            'default_control', 'default_control',
            'default_expose', 'default_expose'
        ],
        'Response': ['1:A', '1:B', '1:A', '1:A'],
        'BomID': ['c1', 'c2', 'e1', 'e2'],
    })

    response = self.client.get('/survey/reporting/abc')

    self.assertEqual(response.status_code, 200)
    self.assertIn(b'>Lift</th>', response.data)
    self.assertIn(b'two-proportion z-test', response.data)
    self.assertIn(b'Sample is small', response.data)
    self.assertIn(b'Wilson 95%', response.data)
    self.assertIn(b'vendor/chart.umd.min.js', response.data)
    self.assertIn(b'Not enough data (n&lt;30)', response.data)
    self.assertIn(b'Sequential:', response.data)

  @mock.patch.object(survey_service, 'get_survey_responses')
  @mock.patch.object(survey_service, 'get_doc_by_id')
  def test_reporting_no_data_empty_state(self, doc_mock, responses_mock):
    doc_mock.return_value = self._survey('abc', {
        'surveytype': 'brand_lift',
        'surveyname': 'Lift',
        'question1': 'Aware?',
    })
    responses_mock.return_value = pandas.DataFrame({
        'CreatedAt': [],
        'Segmentation': [],
        'Response': [],
        'BomID': [],
    })

    response = self.client.get('/survey/reporting/abc')

    self.assertEqual(response.status_code, 200)
    self.assertIn(b'No responses yet', response.data)
    self.assertNotIn(b'Open in Looker Studio', response.data)

  @mock.patch.object(survey_service, 'get_survey_responses')
  @mock.patch.object(survey_service, 'get_doc_by_id')
  def test_reporting_looker_studio_link(self, doc_mock, responses_mock):
    doc_mock.return_value = self._survey('abc', {
        'surveytype': 'brand_track',
        'surveyname': 'Track',
        'question1': 'Aware?',
    })
    responses_mock.return_value = pandas.DataFrame({
        'CreatedAt': [],
        'Segmentation': [],
        'Response': [],
        'BomID': [],
    })
    with mock.patch.dict(os.environ, {'PROJECT_ID': 'brandometer2'}):
      response = self.client.get('/survey/reporting/abc')
    self.assertEqual(response.status_code, 200)
    self.assertIn(b'Open in Looker Studio', response.data)
    self.assertIn(b'lookerstudio.google.com/reporting/create', response.data)
    self.assertIn(b'brandometer_reporting', response.data)
    self.assertIn(b'deduped_responses', response.data)

  @mock.patch.object(survey_service, 'get_survey_responses')
  @mock.patch.object(survey_service, 'get_doc_by_id')
  def test_reporting_shows_size_breakouts(self, doc_mock, responses_mock):
    doc_mock.return_value = self._survey('abc', {
        'surveytype': 'brand_lift',
        'surveyname': 'Lift',
        'question1': 'Aware?',
        'answer1a': 'Yes',
        'answer1b': 'No',
    })
    t = datetime.datetime(2026, 11, 18, 12, 0, 0)
    responses_mock.return_value = pandas.DataFrame({
        'CreatedAt': [t, t, t, t],
        'Segmentation': [
            'default_control', 'default_control',
            'default_expose', 'default_expose',
        ],
        'Response': ['1:A', '1:B', '1:A', '1:A'],
        'BomID': ['c1', 'c2', 'e1', 'e2'],
        'CreativeSize': ['300x250', '160x600', '300x250', '160x600'],
        'PlacementID': ['p1', 'p1', 'p1', 'p1'],
        'AdCreativeID': ['cr1', 'cr1', 'cr1', 'cr1'],
    })
    response = self.client.get('/survey/reporting/abc')
    self.assertEqual(response.status_code, 200)
    self.assertIn(b'Breakouts', response.data)
    self.assertIn(b'300x250', response.data)
    self.assertIn(b'160x600', response.data)
    self.assertIn(b'Breakouts CSV', response.data)
    self.assertIn(b'/survey/download_breakouts/abc', response.data)

  @mock.patch.object(survey_service, 'download_breakouts', return_value='dimension,slice\nSize,300x250\n')
  def test_download_breakouts_csv(self, download_mock):
    response = self.client.get('/survey/download_breakouts/abc')
    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.mimetype, 'text/csv')
    self.assertIn(b'Size,300x250', response.data)
    download_mock.assert_called_once_with('abc')

  @mock.patch.object(survey_service, 'iter_response_csv')
  def test_download_responses_streams_chunks(self, iter_mock):
    iter_mock.return_value = iter(['Date,Segment\n', 'd1,seg1\n'])

    response = self.client.get('/survey/download_responses/abc')

    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.mimetype, 'text/csv')
    self.assertIn(b'Date,Segment', response.data)
    self.assertIn(b'd1,seg1', response.data)
    iter_mock.assert_called_once_with('abc')

  @mock.patch.object(survey_service, 'get_question_json', return_value=[])
  @mock.patch.object(survey_service, 'get_doc_by_id')
  def test_preview_does_not_post_to_receiver(self, doc_mock, _json_mock):
    doc_mock.return_value = self._survey('abc', {
        'surveyname': 'Track',
        'question1': 'Q1',
        'responsetype': 'Submit Responses at End of Survey',
    })

    response = self.client.get('/survey/preview/abc')

    self.assertEqual(response.status_code, 200)
    self.assertNotIn(b'?type=survey', response.data)
    self.assertNotIn(b'AW-968433116', response.data)
    self.assertNotIn(b'>Size:</span>', response.data)
    csp = response.headers.get('Content-Security-Policy', '')
    self.assertIn("default-src 'self'", csp)
    self.assertIn("'unsafe-inline'", csp)
    self.assertIsNone(response.headers.get('Content-Security-Policy-Report-Only'))
    self.assertIn(b'<script>', response.data)
    self.assertIn(b'brand-badge', response.data)

  @mock.patch.object(survey_service, 'get_question_json', return_value=[])
  @mock.patch.object(survey_service, 'get_doc_by_id')
  def test_preview_size_query_and_switcher(self, doc_mock, _json_mock):
    doc_mock.return_value = self._survey('abc', {
        'surveyname': 'Multi',
        'question1': 'Q1',
        'creativesizes': ['300x250', '970x250'],
        'responsetype': 'Submit Responses at End of Survey',
    })

    default = self.client.get('/survey/preview/abc')
    self.assertEqual(default.status_code, 200)
    self.assertIn(b'width=300,height=250', default.data)
    self.assertIn(b'>300', default.data)
    self.assertIn(b'/survey/preview/abc?size=970x250', default.data)

    requested = self.client.get('/survey/preview/abc?size=970x250')
    self.assertEqual(requested.status_code, 200)
    self.assertIn(b'width=970,height=250', requested.data)
    self.assertIn(b'/survey/preview/abc?size=300x250', requested.data)

    unknown = self.client.get('/survey/preview/abc?size=160x600')
    self.assertEqual(unknown.status_code, 200)
    self.assertIn(b'width=300,height=250', unknown.data)

  @mock.patch.object(survey_service, 'list_versions', return_value=[])
  @mock.patch.object(survey_service, 'get_doc_by_id')
  @mock.patch.object(survey_service, 'update_by_id')
  def test_edit_conflict_returns_409(self, update_mock, doc_mock, _versions):
    doc_mock.return_value = self._survey('abc', {
        'surveyname': 'Live',
        'question1': 'Q',
        'answer1a': 'A',
        'answer1b': 'B',
    })
    update_mock.side_effect = survey_collection.SurveyConflictError('stale')
    with mock.patch(
        'flask_wtf.FlaskForm.validate_on_submit', return_value=True):
      response = self.client.post(
          '/survey/edit?survey_id=abc',
          data={'surveyname': 'Live', 'question1': 'Q'})
    self.assertEqual(response.status_code, 409)
    self.assertIn(b'Someone else saved this survey, reload', response.data)
    self.assertIn(b'alert-warning', response.data)


class CsrfProtectionTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    main.app.config['AUTH_BYPASS'] = True
    main.app.config['WTF_CSRF_ENABLED'] = True
    self.client = main.app.test_client()
    self._suggestions = mock.patch.object(
        survey_service, 'identity_suggestions',
        return_value={'clients': [], 'agencies': []})
    self._suggestions.start()
    self._list = mock.patch.object(survey_service, 'list_surveys', return_value=[])
    self._list.start()

  def tearDown(self):
    self._suggestions.stop()
    self._list.stop()
    main.app.config['AUTH_BYPASS'] = False
    super().tearDown()

  def _token(self):
    page = self.client.get('/index')
    match = re.search(br'name="csrf-token" content="([^"]+)"', page.data)
    self.assertIsNotNone(match)
    return match.group(1).decode('utf-8')

  def test_delete_without_csrf_is_rejected(self):
    response = self.client.post('/survey/delete', data={'survey_id': 'x'})
    self.assertEqual(response.status_code, 400)

  @mock.patch.object(survey_service, 'delete_by_id')
  def test_delete_with_csrf_form_field(self, delete_mock):
    token = self._token()
    response = self.client.post(
        '/survey/delete',
        data={'survey_id': 'x', 'csrf_token': token},
        follow_redirects=False)
    self.assertEqual(response.status_code, 302)
    delete_mock.assert_called_once_with('x')

  @mock.patch.object(survey_service, 'delete_by_id')
  def test_delete_with_csrf_header(self, delete_mock):
    token = self._token()
    response = self.client.post(
        '/survey/delete',
        data={'survey_id': 'x'},
        headers={'X-CSRFToken': token},
        follow_redirects=False)
    self.assertEqual(response.status_code, 302)
    delete_mock.assert_called_once_with('x')

  def test_stats_partial_get_does_not_need_csrf(self):
    with mock.patch.object(
        survey_service, 'get_response_counts',
        return_value=pandas.DataFrame(columns=[
            'ID', 'Segmentation', 'max_date', 'days_since_response',
            'response_count'])):
      response = self.client.get('/index/stats-partial?ids=s1')
    self.assertEqual(response.status_code, 200)

  @mock.patch.object(survey_service, 'copy_by_id')
  def test_copy_without_csrf_is_rejected(self, copy_mock):
    response = self.client.post('/survey/copy', data={'survey_id': 'x'})
    self.assertEqual(response.status_code, 400)
    copy_mock.assert_not_called()

  @mock.patch.object(survey_service, 'set_archived')
  def test_archive_without_csrf_is_rejected(self, archive_mock):
    response = self.client.post(
        '/survey/archive', data={'survey_id': 'x', 'archived': '1'})
    self.assertEqual(response.status_code, 400)
    archive_mock.assert_not_called()
