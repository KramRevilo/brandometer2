# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Generator tests for tools/seed_demo_data.py (Firestore/BQ mocked)."""
import datetime
import importlib.util
import io
import os
import re
import threading
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

import pandas
import reporting
from mockfirestore import MockFirestore

import css_theme
import main
import survey_service

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
NOW = datetime.datetime(2026, 11, 22, 16, 0, 0, tzinfo=datetime.timezone.utc)


def _load_seed():
  import sys
  path = os.path.join(_ROOT, 'tools', 'seed_demo_data.py')
  spec = importlib.util.spec_from_file_location('seed_demo_data', path)
  module = importlib.util.module_from_spec(spec)
  sys.modules['seed_demo_data'] = module
  spec.loader.exec_module(module)
  return module


class SeedDemoDataTest(unittest.TestCase):

  @classmethod
  def setUpClass(cls):
    cls.mod = _load_seed()
    cls.world = cls.mod.generate_world(cls.mod.DEFAULT_COUNT, 1, now=NOW)

  def test_default_count_covers_four_homepage_pages(self):
    self.assertGreaterEqual(self.mod.DEFAULT_COUNT, 200)
    self.assertGreaterEqual(self.world.count, 200)
    self.assertGreaterEqual(self.world.count, 4 * 50)
    self.assertEqual(len(self.world.surveys), self.mod.DEFAULT_COUNT)
    self.assertLessEqual(self.world.n_rows, 400000)
    self.assertGreater(self.world.n_rows, 1000)

  def test_determinism(self):
    again = self.mod.generate_world(self.mod.DEFAULT_COUNT, 1, now=NOW)
    other = self.mod.generate_world(self.mod.DEFAULT_COUNT, 2, now=NOW)
    ids_a = [s.id for s in self.world.surveys]
    ids_b = [s.id for s in again.surveys]
    ids_c = [s.id for s in other.surveys]
    self.assertEqual(ids_a, ids_b)
    self.assertNotEqual(ids_a, ids_c)
    self.assertEqual(
        [s.doc['displayname'] for s in self.world.surveys],
        [s.doc['displayname'] for s in again.surveys])
    self.assertEqual(
        [s.doc['custom_css'] for s in self.world.surveys],
        [s.doc['custom_css'] for s in again.surveys])
    self.assertEqual(self.world.n_rows, again.n_rows)
    self.assertNotEqual(
        [s.doc['custom_css'] for s in self.world.surveys],
        [s.doc['custom_css'] for s in other.surveys])

  def test_ids_and_docs_are_tagged(self):
    for spec in self.world.surveys:
      self.assertTrue(self.mod.is_demo_survey_id(spec.id))
      self.assertTrue(spec.id.startswith('demo_1_'))
      self.assertIs(spec.doc['demo_seed'], True)
      self.assertEqual(spec.doc['demo_batch'], 'demo-1')
      self.assertTrue(spec.doc['created_by'].endswith('.example'))
      self.assertIn('@', spec.doc['created_by'])
      self.assertTrue(spec.audit.get('demo_seed'))
      self.assertEqual(spec.audit['survey_id'], spec.id)

  def test_themes_vary_across_the_batch(self):
    backgrounds = {spec.theme['bg'].lower() for spec in self.world.surveys}
    css_blocks = {spec.doc['custom_css'] for spec in self.world.surveys}
    self.assertGreaterEqual(len(backgrounds), 12, backgrounds)
    self.assertGreaterEqual(len(css_blocks), 20)
    classic = css_theme.DEFAULT_THEME['bg'].lower()
    self.assertTrue(
        any(bg != classic for bg in backgrounds),
        'seeded surveys should not all use classic green')
    self.assertTrue(
        all('BV2_THEME_START' in spec.doc['custom_css']
            for spec in self.world.surveys))
    self.assertTrue(
        all('--bv2-accent:' in spec.doc['custom_css']
            for spec in self.world.surveys))

  def test_every_agency_client_has_a_brand_palette(self):
    names = {client[0] for agency in self.mod.AGENCIES for client in agency['clients']}
    self.assertEqual(names, set(self.mod.CLIENT_BRANDS))
    for spec in self.world.surveys:
      parsed = css_theme.parse_theme_css(spec.doc['custom_css'])
      self.assertTrue(parsed['had_theme_block'], spec.id)
      self.assertEqual(
          parsed['theme']['bg'].lower(), spec.theme['bg'].lower(), spec.id)

  def test_per_client_theme_consistency_and_campaign_variation(self):
    by_client = {}
    for spec in self.world.surveys:
      by_client.setdefault(spec.doc['client'], []).append(spec)
    for client, specs in by_client.items():
      allowed = self.mod.brand_backgrounds(client)
      used = {spec.theme['bg'].lower() for spec in specs}
      self.assertTrue(used <= allowed, '%s extra %s' % (client, used - allowed))
      self.assertGreaterEqual(len(specs), 8, client)
      self.assertGreaterEqual(len(used), 2, client)
      fonts = {spec.theme['font_family'] for spec in specs}
      self.assertTrue(fonts, client)

  def test_theme_contrast_meets_wcag_aa(self):
    self.assertGreaterEqual(self.mod.WCAG_AA_CONTRAST, 4.5)
    for spec in self.world.surveys:
      for label, fg, bg in self.mod.theme_contrast_pairs(spec.theme):
        ratio = self.mod.contrast_ratio(fg, bg)
        self.assertGreaterEqual(
            ratio, self.mod.WCAG_AA_CONTRAST,
            '%s %s %s on %s ratio=%.2f' % (spec.id, label, fg, bg, ratio))
    for client, brand in self.mod.CLIENT_BRANDS.items():
      for i, entry in enumerate(brand['campaigns']):
        theme = self.mod.resolve_campaign(entry)
        self.assertTrue(
            self.mod.theme_meets_aa(theme),
            '%s campaign %s' % (client, i))

  def test_apply_overwrites_existing_demo_themes(self):
    fs = MockFirestore()
    sid = self.world.surveys[0].id
    fs.collection('Surveys').document(sid).set({
        'surveyname': 'old-green',
        'demo_seed': True,
        'demo_batch': 'demo-1',
        'custom_css': (
            'body { margin: 0; display: block; }\n'
            '#master_container { background-color:#008000; }'),
    })
    self.mod.apply_firestore(fs, self.world)
    data = fs.collection('Surveys').document(sid).get().to_dict()
    self.assertIn('BV2_THEME_START', data['custom_css'])
    self.assertIn('--bv2-bg:', data['custom_css'])
    parsed = css_theme.parse_theme_css(data['custom_css'])
    self.assertTrue(parsed['had_theme_block'])
    self.assertEqual(
        parsed['theme']['bg'].lower(),
        self.world.surveys[0].theme['bg'].lower())
    self.assertNotEqual(
        data['custom_css'].strip(),
        '#master_container { background-color:#008000; }')

  def test_demo_surveys_set_agency_badge_names(self):
    names = {spec.doc['badge_name'] for spec in self.world.surveys}
    agencies = {spec.doc['agency'] for spec in self.world.surveys}
    self.assertEqual(names, agencies)
    self.assertTrue(any(spec.doc['badge_icon'] == 'Name' for spec in self.world.surveys))
    self.assertNotIn('Dentsu', {spec.doc['badge_icon'] for spec in self.world.surveys})

  def test_no_real_agency_or_brand_names(self):
    blob = ' '.join(
        spec.doc['agency'] + ' ' + spec.doc['client'] + ' ' + spec.doc['displayname']
        for spec in self.world.surveys).lower()
    for banned in (
        'dentsu', 'wpp', 'omnicom', 'publicis', 'ipg', 'havas',
        'coca-cola', 'coke', 'nike', 'adidas', 'apple', 'google',
        'ford', 'toyota', 'mcdonald', 'walmart'):
      self.assertNotIn(banned, blob)
    names = {a['name'] for a in self.mod.AGENCIES}
    self.assertGreaterEqual(len(names), 3)
    self.assertLessEqual(len(names), 5)
    self.assertIn('Northline Media', names)

  def test_status_matches_last_days(self):
    seen = set()
    for spec in self.world.surveys:
      self.assertEqual(
          spec.expected_status, self.mod.classify_status(spec.last_days))
      seen.add(spec.expected_status)
      if spec.expected_status == 'No data':
        self.assertFalse(spec.counts)
        self.assertEqual(spec.n_rows, 0)
      else:
        self.assertTrue(spec.counts)
        self.assertGreater(sum(spec.counts.values()), 0)
      if spec.expected_status == 'Active':
        self.assertLessEqual(spec.last_days, 3)
      elif spec.expected_status == 'Stale':
        self.assertGreater(spec.last_days, 3)
        self.assertLessEqual(spec.last_days, 7)
      elif spec.expected_status == 'Timed out':
        self.assertGreater(spec.last_days, 7)
    self.assertTrue({'Active', 'No data', 'Timed out'} <= seen)

  def test_creators_stay_with_their_agency_clients(self):
    domain_by_agency = {a['name']: a['domain'] for a in self.mod.AGENCIES}
    for spec in self.world.surveys:
      domain = domain_by_agency[spec.doc['agency']]
      self.assertTrue(spec.doc['created_by'].endswith('@' + domain))

  def test_purge_sql_targets_only_tagged_rows(self):
    sql = self.mod.bq_purge_sql('brandometer2.responses.responses')
    self.assertIn('STARTS_WITH(ID, "demo_")', sql)
    self.assertIn('STARTS_WITH(RandomTimeStamp, "demo_seed:")', sql)
    self.assertIn('INTERVAL 800 DAY', sql)
    self.assertNotIn('RandomTimeStamp = "', sql)
    self.assertNotIn('DELETE FROM `brandometer2.responses.responses`\nWHERE TRUE', sql)
    scoped = self.mod.bq_purge_sql(
        'brandometer2.responses.responses', batch='i18n')
    self.assertIn('RandomTimeStamp = "demo_seed:i18n"', scoped)
    self.assertIn('STARTS_WITH(ID, "demo_")', scoped)
    with self.assertRaises(ValueError):
      self.mod.bq_purge_sql('p.t.t', batch='i18n"; DROP TABLE x; --')

  def test_is_demo_bq_row(self):
    self.assertTrue(self.mod.is_demo_bq_row({
        'ID': 'demo_1_0003',
        'RandomTimeStamp': 'demo_seed:demo-1',
        'RespondentID': 'demo_demo_1_0003_000001',
    }))
    self.assertFalse(self.mod.is_demo_bq_row({
        'ID': 'prod-survey',
        'RandomTimeStamp': 'abc',
        'RespondentID': 'person-1',
    }))

  def test_generated_rows_match_plan_and_tag(self):
    spec = next(
        s for s in self.world.surveys
        if s.counts and sum(s.counts.values()) <= 80 and s.n_questions == 1)
    rows = list(self.mod.iter_response_rows(self.world, spec))
    self.assertTrue(rows)
    self.assertTrue(all(self.mod.is_demo_bq_row(row) for row in rows))
    complete = [row for row in rows if row['Response'].count(':') >= spec.n_questions]
    by_seg = {}
    for row in complete:
      by_seg.setdefault(row['Segmentation'], set()).add(row['BomID'])
    for seg, n in spec.counts.items():
      self.assertEqual(len(by_seg.get(seg, ())), n, seg)

  def test_reporting_accepts_seeded_lift_shape(self):
    spec = next(
        s for s in self.world.surveys
        if s.doc['surveytype'] == 'brand_lift' and sum(s.counts.values()) >= 80)
    rows = list(self.mod.iter_response_rows(self.world, spec))
    frame = pandas.DataFrame(rows)
    frame['CreatedAt'] = pandas.to_datetime(frame['CreatedAt'])
    report = reporting.build_report(frame, spec.doc, is_lift=True)
    self.assertGreaterEqual(report['n_total'], 80)
    self.assertTrue(report['has_control'] or report['has_expose'])
    self.assertTrue(report['questions'])
    self.assertIsNone(report.get('empty_reason'))

  def test_seeded_rows_produce_stats_and_ignore_demo_timestamp(self):
    spec = next(
        s for s in self.world.surveys
        if s.doc['surveytype'] == 'brand_lift'
        and s.expected_status == 'Active'
        and sum(s.counts.values()) >= 80)
    rows = list(self.mod.iter_response_rows(self.world, spec))
    self.assertTrue(rows)
    self.assertTrue(all(
        isinstance(row['RandomTimeStamp'], str)
        and row['RandomTimeStamp'].startswith('demo_seed:')
        for row in rows))
    self.assertNotIn('RandomTimeStamp', survey_service._RESPONSE_SELECT)
    import inspect
    counts_src = inspect.getsource(survey_service._fetch_all_response_counts)
    self.assertNotIn('RandomTimeStamp', counts_src)
    frame = pandas.DataFrame(rows)
    frame['CreatedAt'] = pandas.to_datetime(frame['CreatedAt'])
    report = reporting.build_report(frame, spec.doc, is_lift=True)
    self.assertGreaterEqual(report['n_total'], 80)
    counts = self.mod.counts_frame_from_world(self.world, ids=[spec.id])
    stats = survey_service.build_stat_array([spec.id], counts_df=counts)
    compact = survey_service.compact_count(stats[0])
    self.assertIn('C ', compact['text'])
    self.assertIn('E ', compact['text'])
    self.assertEqual(stats[0]['status'], 'Active')
    self.assertFalse(stats[0]['unavailable'])

  def test_firestore_apply_and_purge_only_tagged(self):
    fs = MockFirestore()
    fs.collection('Surveys').document('keep-me').set({
        'surveyname': 'production', 'demo_seed': False,
    })
    written = self.mod.apply_firestore(fs, self.world)
    self.assertEqual(written, self.world.count)
    first = fs.collection('Surveys').document(self.world.surveys[0].id).get()
    self.assertTrue(first.exists)
    self.assertTrue(first.to_dict()['demo_seed'])
    planned = self.mod.purge_firestore(fs, dry_run=True)
    self.assertEqual(planned['surveys'], self.world.count)
    deleted = self.mod.purge_firestore(fs, dry_run=False)
    self.assertEqual(deleted['surveys'], self.world.count)
    self.assertFalse(
        fs.collection('Surveys').document(self.world.surveys[0].id).get().exists)
    keep = fs.collection('Surveys').document('keep-me').get()
    self.assertTrue(keep.exists)
    self.assertEqual(keep.to_dict()['surveyname'], 'production')

  def test_apply_bigquery_uses_load_job_not_streaming(self):
    client = mock.Mock()
    client.query.return_value.result.return_value = None
    load = mock.Mock()
    load.errors = None
    client.load_table_from_file.return_value = load
    tiny = self.mod.generate_world(self.mod.DEFAULT_COUNT, 1, now=NOW)
    tiny.surveys = [s for s in tiny.surveys if s.n_rows and s.n_rows <= 40][:3]
    tiny.n_rows = sum(s.n_rows for s in tiny.surveys)
    n = self.mod.apply_bigquery(client, 'p.responses.responses', tiny)
    self.assertGreater(n, 0)
    client.query.assert_called()
    sql = client.query.call_args[0][0]
    self.assertIn('STARTS_WITH(ID, "demo_")', sql)
    self.assertIn('RandomTimeStamp = "demo_seed:demo-1"', sql)
    self.assertTrue(client.load_table_from_file.called)
    client.insert_rows_json.assert_not_called()
    load.result.assert_called()

  def test_cli_rejects_small_count(self):
    code = self.mod.main(['--project', 'brandometer2', '--count', '10'])
    self.assertEqual(code, 2)

  def test_cli_purge_requires_batch_or_all(self):
    buf = io.StringIO()
    with redirect_stdout(buf):
      code = self.mod.main(['--project', 'brandometer2', '--purge'])
    self.assertEqual(code, 2)
    both = self.mod.main(
        ['--project', 'brandometer2', '--purge', '--batch', 'i18n', '--all'])
    self.assertEqual(both, 2)

  def test_cli_dry_run_prints_summary(self):
    buf = io.StringIO()
    with redirect_stdout(buf):
      code = self.mod.main(
          ['--project', 'brandometer2', '--seed', '1', '--count', '220'])
    text = buf.getvalue()
    self.assertEqual(code, 0)
    self.assertIn('Dry run', text)
    self.assertIn('Estimated BigQuery rows', text)
    self.assertIn('WARNING', text)
    self.assertIn('Northline Media', text)
    self.assertIn('Themes:', text)
    self.assertIn('BV2_THEME', text)
    self.assertGreaterEqual(self.world.n_rows, 1000)

  def test_active_surveys_cover_four_pages(self):
    active = [s for s in self.world.surveys if not s.doc['archived']]
    self.assertGreaterEqual(len(active), 200)

  def test_row_plan_matches_yielded_rows(self):
    for spec in self.world.surveys[:30]:
      n = sum(1 for _ in self.mod.iter_response_rows(self.world, spec))
      self.assertEqual(n, spec.n_rows, spec.id)

  def test_apply_is_idempotent_on_mock_firestore(self):
    fs = MockFirestore()
    fs.collection('Surveys').document('keep-me').set({'surveyname': 'production'})
    self.mod.apply_firestore(fs, self.world)
    self.mod.apply_firestore(fs, self.world)
    ids = [doc.id for doc in fs.collection('Surveys').stream()]
    self.assertEqual(len(ids), self.world.count + 1)
    self.assertIn('keep-me', ids)
    self.assertEqual(len([i for i in ids if i.startswith('demo_')]), self.world.count)

  def test_homepage_and_report_routes_accept_seeded_shape(self):
    main.app.config['AUTH_BYPASS'] = True
    main.app.config['WTF_CSRF_ENABLED'] = False
    self.addCleanup(lambda: main.app.config.update(
        AUTH_BYPASS=False, WTF_CSRF_ENABLED=True))
    docs = self.mod.mock_survey_docs(self.world)

    def list_side(include_archived=False):
      if include_archived:
        return [d for d in docs if d.to_dict().get('archived') is True]
      return [d for d in docs if d.to_dict().get('archived') is not True]

    spec = next(
        s for s in self.world.surveys
        if s.doc['surveytype'] == 'brand_lift' and sum(s.counts.values()) >= 80)
    rows = list(self.mod.iter_response_rows(self.world, spec))
    frame = pandas.DataFrame(rows)
    frame['CreatedAt'] = pandas.to_datetime(frame['CreatedAt'])
    counts = self.mod.counts_frame_from_world(self.world)
    survey_service.clear_stats_cache()
    client = main.app.test_client()
    with mock.patch.object(survey_service, 'list_surveys', side_effect=list_side), \
         mock.patch.object(survey_service, 'get_response_counts', return_value=counts), \
         mock.patch.object(
             survey_service, 'get_doc_by_id',
             return_value=next(d for d in docs if d.id == spec.id)), \
         mock.patch.object(
             survey_service, 'get_survey_responses', return_value=frame):
      home = client.get('/index')
      self.assertEqual(home.status_code, 200)
      html = home.data.decode('utf-8')
      self.assertIn('Page 1 of', html)
      pages = int(html.split('Page 1 of ')[1].split('<')[0].strip())
      self.assertGreaterEqual(pages, 4)
      self.assertIn('Northline Media', html)
      first_id = list_side(False)
      first_id = survey_service.sort_surveys(first_id, 'created_at', 'desc')[0].id
      stats = client.get('/index/stats-partial?ids=%s' % first_id)
      self.assertEqual(stats.status_code, 200)
      self.assertIn('id="count-%s"' % first_id, stats.data.decode('utf-8'))
      self.assertNotIn('Loading', stats.data.decode('utf-8'))
      report = client.get('/survey/reporting/%s' % spec.id)
      self.assertEqual(report.status_code, 200)
      self.assertIn(spec.doc['question1'].encode(), report.data)

  def test_i18n_scenario_covers_rtl_ltr_sizes_and_long_thankyou(self):
    world = self.mod.generate_i18n_world(now=NOW, seed=1)
    self.assertEqual(world.batch, 'i18n')
    self.assertEqual(world.count, 6)
    codes = [s.doc['language'] for s in world.surveys]
    self.assertEqual(codes, ['en', 'ja', 'zh', 'ar', 'he', 'de'])
    self.assertEqual(
        {s.id for s in world.surveys},
        {'demo_i18n_en', 'demo_i18n_ja', 'demo_i18n_zh',
         'demo_i18n_ar', 'demo_i18n_he', 'demo_i18n_de'})
    for spec in world.surveys:
      self.assertIs(spec.doc['demo_seed'], True)
      self.assertEqual(spec.doc['demo_batch'], 'i18n')
      self.assertEqual(spec.doc['creativesizes'], ['300x250', '160x600'])
      self.assertTrue(spec.doc['thankyou_text'])
      self.assertGreaterEqual(len(spec.doc['thankyou_text']), 20)
      self.assertEqual(spec.doc['surveytype'], 'brand_track')
      lang, direction = survey_service.html_lang_dir(spec.doc)
      self.assertEqual(lang, spec.doc['language'])
      if spec.doc['language'] in ('ar', 'he'):
        self.assertEqual(direction, 'rtl')
      else:
        self.assertEqual(direction, 'ltr')
      self.assertEqual(
          survey_service.get_thank_you_text(spec.doc),
          spec.doc['thankyou_text'])
    en = next(s for s in world.surveys if s.doc['language'] == 'en')
    self.assertIn('appreciate', en.doc['thankyou_text'].lower())
    rows = list(self.mod.iter_response_rows(world, en))
    self.assertTrue(rows)
    self.assertTrue(all(
        row['RandomTimeStamp'] == 'demo_seed:i18n' for row in rows))
    self.assertTrue(all(self.mod.is_demo_bq_row(row) for row in rows))

  def test_homepage_and_i18n_batches_coexist(self):
    fs = MockFirestore()
    fs.collection('Surveys').document('keep-me').set({'surveyname': 'production'})
    tiny = self.mod.generate_world(self.mod.DEFAULT_COUNT, 1, now=NOW)
    tiny.surveys = tiny.surveys[:4]
    tiny.count = 4
    tiny.n_rows = sum(s.n_rows for s in tiny.surveys)
    i18n = self.mod.generate_i18n_world(now=NOW, seed=1)
    self.mod.apply_firestore(fs, tiny)
    self.mod.apply_firestore(fs, i18n)
    ids = [doc.id for doc in fs.collection('Surveys').stream()]
    self.assertIn('keep-me', ids)
    self.assertIn(tiny.surveys[0].id, ids)
    self.assertIn('demo_i18n_ar', ids)
    planned = self.mod.purge_firestore(fs, dry_run=True, batch='i18n')
    self.assertEqual(planned['surveys'], 6)
    deleted = self.mod.purge_firestore(fs, dry_run=False, batch='i18n')
    self.assertEqual(deleted['surveys'], 6)
    self.assertTrue(
        fs.collection('Surveys').document(tiny.surveys[0].id).get().exists)
    self.assertFalse(
        fs.collection('Surveys').document('demo_i18n_en').get().exists)
    self.assertTrue(fs.collection('Surveys').document('keep-me').get().exists)

  def test_cli_i18n_dry_run_and_ignores_homepage_min_count(self):
    buf = io.StringIO()
    with redirect_stdout(buf):
      code = self.mod.main(
          ['--project', 'brandometer2', '--scenario', 'i18n', '--count', '10'])
    text = buf.getvalue()
    self.assertEqual(code, 0)
    self.assertIn('Dry run', text)
    self.assertIn('batch i18n', text)
    self.assertIn('demo_i18n_ar', text)
    self.assertIn('Harbor Grocer', text)


def _playwright_or_skip():
  try:
    from playwright.sync_api import sync_playwright
    return sync_playwright
  except ImportError:
    raise unittest.SkipTest('playwright is not installed')


def _start_app(app):
  from werkzeug.serving import make_server
  server = make_server('127.0.0.1', 0, app, threaded=True)
  thread = threading.Thread(target=server.serve_forever, daemon=True)
  thread.start()
  port = server.server_port
  for _ in range(50):
    import urllib.request
    try:
      urllib.request.urlopen('http://127.0.0.1:%s/index' % port, timeout=1)
      break
    except Exception:
      time.sleep(0.1)
  return server, port


class SeededHomepageBrowserTest(unittest.TestCase):

  @classmethod
  def setUpClass(cls):
    cls.mod = _load_seed()
    cls.world = cls.mod.generate_world(cls.mod.DEFAULT_COUNT, 1, now=NOW)
    cls.docs = cls.mod.mock_survey_docs(cls.world)
    cls.counts = cls.mod.counts_frame_from_world(cls.world)

  def setUp(self):
    super().setUp()
    main.app.config['AUTH_BYPASS'] = True
    main.app.config['WTF_CSRF_ENABLED'] = False
    docs = self.docs

    def list_side(include_archived=False):
      if include_archived:
        return [d for d in docs if d.to_dict().get('archived') is True]
      return [d for d in docs if d.to_dict().get('archived') is not True]

    self._list = mock.patch.object(
        survey_service, 'list_surveys', side_effect=list_side)
    self._counts = mock.patch.object(
        survey_service, 'get_response_counts', return_value=self.counts)
    self._list.start()
    self._counts.start()
    self.addCleanup(self._list.stop)
    self.addCleanup(self._counts.stop)
    survey_service.clear_stats_cache()

  def tearDown(self):
    main.app.config['AUTH_BYPASS'] = False
    main.app.config['WTF_CSRF_ENABLED'] = True
    super().tearDown()

  def test_seeded_list_has_four_plus_pages(self):
    sync_playwright = _playwright_or_skip()
    server, port = _start_app(main.app)
    base = 'http://127.0.0.1:%s' % port
    try:
      with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1400, 'height': 900})
        page.goto(base + '/index', wait_until='networkidle')
        page.wait_for_selector('#mainTable tbody tr')
        pager = page.locator('.pagination').inner_text()
        match = re.search(r'Page 1 of (\d+)', pager)
        self.assertIsNotNone(match, pager)
        self.assertGreaterEqual(int(match.group(1)), 4)
        rows = page.locator('#mainTable tbody tr').count()
        self.assertEqual(rows, 50)
        self.assertIn('Northline Media', page.locator('#mainTable').inner_text())
        first_id = page.evaluate(
            """() => {
              const el = document.querySelector('#mainTable [id^="count-"]');
              return el ? el.id.slice(6) : '';
            }""")
        self.assertTrue(first_id)
        page.wait_for_function(
            """(id) => {
              const el = document.getElementById('count-' + id);
              return el && el.textContent.indexOf('Loading') === -1;
            }""",
            arg=first_id)
        self.assertNotIn('Loading', page.locator('#count-%s' % first_id).inner_text())
        page.locator('.pagination >> text=Next').click()
        page.wait_for_function(
            "() => document.body.innerText.indexOf('Page 2 of') !== -1")
        page.locator('.pagination >> text=Next').click()
        page.wait_for_function(
            "() => document.body.innerText.indexOf('Page 3 of') !== -1")
        page.locator('.pagination >> text=Next').click()
        page.wait_for_function(
            "() => document.body.innerText.indexOf('Page 4 of') !== -1")
        self.assertGreaterEqual(
            page.locator('#mainTable tbody tr').count(), 1)
        browser.close()
    finally:
      server.shutdown()

