#!/usr/bin/env python3
"""Seed a local Flask app with sample data and capture README screenshots.

Uses MockFirestore (no GCP, no real client data) and patches BigQuery reads
with synthetic Brand Lift rows so the report page has CIs and a chart.

  pip install -r creative/app/requirements.txt -r tools/requirements-screenshots.txt
  python3 -m playwright install chromium
  python3 tools/capture_screenshots.py

Images land in docs/images/ as optimised PNG (desktop UI at 1400px wide;
creatives stay natural size).
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / 'creative' / 'app'
DEFAULT_OUT = ROOT / 'docs' / 'images'
DEFAULT_PORT = 43147
PORT = DEFAULT_PORT
UI_MAX_WIDTH = 1400
DESKTOP_WIDTH = 1400
ONLY_NAMES: set[str] | None = None


def _prepare_env() -> None:
  os.environ.setdefault('DISABLE_BASIC_AUTH', '1')
  os.environ.setdefault('PROJECT_ID', 'brandometer-docs')
  os.environ.setdefault('TABLE_ID', 'brandometer-docs.responses.responses')
  os.environ.setdefault('SECRET_KEY', 'docs-screenshots-not-a-secret')
  os.environ.setdefault('STATS_CACHE_SECONDS', '0')
  os.environ.setdefault('APP_BRAND_NAME', 'Brandometer2')
  # Dummy values so Secret Manager is never called and /login shows Sign in.
  os.environ.setdefault(
      'GOOGLE_OAUTH_CLIENT_ID',
      'docs-screenshots.apps.googleusercontent.com')
  os.environ.setdefault('GOOGLE_OAUTH_CLIENT_SECRET', 'docs-not-a-secret')
  os.environ.setdefault('RECEIVER_HMAC_SECRET', 'docs-hmac-not-a-secret')
  os.environ.setdefault('RECEIVER_URL', 'https://receiver.example/pixel')
  os.environ['PYTHONPATH'] = str(APP_DIR) + os.pathsep + os.environ.get(
      'PYTHONPATH', '')
  sys.path.insert(0, str(APP_DIR))


def _preset(preset_id: str) -> dict:
  import css_theme
  for item in css_theme.STYLE_PRESETS:
    if item['id'] == preset_id:
      return item
  raise KeyError(preset_id)


def _theme_css(preset_id: str) -> str:
  import css_theme
  from forms import DEFAULT_CSS
  return css_theme.combine_css(_preset(preset_id), DEFAULT_CSS)


def _survey(doc_id, **fields):
  now = '2026-11-18T12:00:00Z'
  sizes = fields.pop('sizes', ['300x250'])
  preset = fields.pop('preset', 'classic')
  answers = fields.pop('answers', ['Example Cola', 'Other Cola'])
  agency = fields.pop('agency', 'Example Media')
  payload = {
      'surveyname': fields.pop('surveyname', doc_id),
      'displayname': fields.pop('displayname', ''),
      'surveytype': fields.pop('surveytype', 'brand_track'),
      'archived': False,
      'created_at': now,
      'created_by': 'admin@example.com',
      'updated_at': now,
      'updated_by': 'admin@example.com',
      'client': fields.pop('client', 'Acme'),
      'agency': agency,
      'language': 'en',
      'responsetype': 'Submit Responses at End of Survey',
      'question1': fields.pop('question1', 'Which brand did you see?'),
      'question1type': 'SINGLE_OPTION',
      'question1order': 'ORDERED',
      'badge_icon': fields.pop('badge_icon', 'B'),
      'badge_name': fields.pop('badge_name', agency),
      'badge_text': '',
      'custom_css': _theme_css(preset),
      'creativesizes': sizes,
      'creativesize': sizes[0] if len(sizes) == 1 else sizes,
  }
  if payload['surveytype'] == 'brand_lift':
    payload['cells'] = [
        {'id': 'default_control', 'label': 'Control', 'role': 'control'},
        {'id': 'default_expose', 'label': 'Exposed', 'role': 'expose'},
        {'id': 'exp_b', 'label': 'Exposed B', 'role': 'expose'},
    ]
  letters = 'abcdefgh'
  for index, text in enumerate(answers):
    payload['answer1' + letters[index]] = text
    payload['answer1' + letters[index] + 'next'] = 'end'
  payload.update(fields)
  return doc_id, payload


def seed(fs) -> None:
  import access
  surveys = [
      _survey(
          'lift-demo',
          surveyname='cola-awareness-lift',
          displayname='Cola awareness (lift)',
          surveytype='brand_lift',
          sizes=['300x250', '336x280'],
          preset='classic',
          answers=['Example Cola', 'Other Cola', 'Store brand', 'Not sure'],
          question1='Which cola brand did you notice?',
          client='Acme',
          agency='Example Media',
          created_at='2026-11-18T12:00:00Z',
          created_by='editor@example.com',
          sample_plan={
              'baseline': 0.20,
              'mde_mode': 'relative',
              'mde_relative': 0.10,
              'mde_absolute': 0.05,
              'confidence': 0.95,
              'power': 0.80,
              'comparisons': 1,
              'response_rate': 0.01,
              'control_share': 0.50,
              'n_control': 200,
              'n_expose': 200,
              'n_total': 400,
          },
      ),
      _survey(
          'lift-small',
          surveyname='cola-awareness-small',
          displayname='Cola awareness (small n)',
          surveytype='brand_lift',
          sizes=['300x250'],
          preset='classic',
          answers=['Example Cola', 'Other Cola'],
          question1='Which cola brand did you notice?',
          client='Acme',
          agency='Example Media',
          created_at='2026-11-17T09:00:00Z',
          created_by='editor@example.com',
      ),
      _survey(
          'track-two',
          surveyname='snack-consideration-track',
          displayname='Snack consideration (2 answers)',
          sizes=['300x250'],
          preset='ocean',
          answers=['Yes', 'No'],
          question1='Would you consider this snack?',
          client='Northwind',
          agency='Harbour Ads',
          created_at='2026-11-16T15:30:00Z',
          created_by='admin@example.com',
      ),
      _survey(
          'tall-eight',
          surveyname='skyscraper-pack-track',
          displayname='Pack ranking (8 answers)',
          sizes=['160x600'],
          preset='hazard',
          answers=[
              'Citrus crunch', 'Berry blast', 'Cocoa chip', 'Mint snap',
              'Honey oat', 'Chilli lime', 'Vanilla bean', 'Not listed',
          ],
          question1='Which pack would you pick?',
          client='Northwind',
          agency='Harbour Ads',
          badge_icon='B2',
          created_at='2026-11-15T11:00:00Z',
          created_by='admin@example.com',
      ),
      _survey(
          'halfpage-dark',
          surveyname='halfpage-recall-track',
          displayname='Half-page recall (dark)',
          sizes=['300x600'],
          preset='dark',
          answers=['Saw it', 'Maybe', 'Did not see', 'Prefer not to say'],
          question1='Do you recall the ad?',
          client='Acme',
          agency='Example Media',
          created_at='2026-11-14T08:15:00Z',
          created_by='editor@example.com',
      ),
      _survey(
          'mrec-pink',
          surveyname='medium-rectangle-track',
          displayname='Medium rectangle (hot pink)',
          sizes=['336x280'],
          preset='hot-pink',
          answers=['Brand A', 'Brand B', 'Brand C', 'None of these'],
          question1='Which brand feels most familiar?',
          client='Contoso',
          agency='Pixel Shop',
          created_at='2026-11-12T16:45:00Z',
          created_by='viewer@example.com',
      ),
      _survey(
          'lift-coffee',
          surveyname='morning-blend-lift',
          displayname='Morning blend awareness',
          surveytype='brand_lift',
          sizes=['300x250'],
          preset='classic',
          answers=['House blend', 'Store brand', 'Not sure'],
          question1='Which coffee did you notice?',
          client='Acme',
          agency='Brightline',
          created_at='2026-11-18T10:00:00Z',
          created_by='editor@example.com',
          sample_plan={
              'n_control': 200, 'n_expose': 200, 'n_total': 400,
              'baseline': 0.18, 'mde_relative': 0.10, 'confidence': 0.95,
              'power': 0.80, 'comparisons': 1, 'response_rate': 0.01,
              'control_share': 0.50, 'mde_mode': 'relative',
              'mde_absolute': 0.05,
          },
      ),
      _survey(
          'track-maple',
          surveyname='maple-consideration-track',
          displayname='Maple syrup consideration',
          sizes=['300x250'],
          preset='ocean',
          answers=['Yes', 'No'],
          question1='Would you consider this syrup?',
          client='Acme',
          agency='Oak & Iron',
          created_at='2026-11-17T14:00:00Z',
          created_by='admin@example.com',
      ),
      _survey(
          'lift-cereal',
          surveyname='breakfast-cereal-lift',
          displayname='Breakfast cereal lift',
          surveytype='brand_lift',
          sizes=['300x250'],
          preset='classic',
          answers=['Crunch Co', 'Other', 'Not sure'],
          question1='Which cereal brand did you notice?',
          client='Acme',
          agency='Example Media',
          created_at='2026-11-16T09:30:00Z',
          created_by='editor@example.com',
      ),
      _survey(
          'track-tools',
          surveyname='workshop-tools-track',
          displayname='Workshop tools awareness',
          sizes=['300x250'],
          preset='ocean',
          answers=['Yes', 'No'],
          question1='Have you heard of this tool brand?',
          client='Acme',
          agency='Brightline',
          created_at='2026-11-18T08:00:00Z',
          created_by='editor@example.com',
      ),
      _survey(
          'lift-yogurt',
          surveyname='cultured-yogurt-lift',
          displayname='Cultured yogurt lift',
          surveytype='brand_lift',
          sizes=['336x280'],
          preset='classic',
          answers=['Dairy Co', 'Other', 'Not sure'],
          question1='Which yogurt did you notice?',
          client='Globex',
          agency='North Star',
          created_at='2026-11-13T11:00:00Z',
          created_by='admin@example.com',
      ),
      _survey(
          'track-auto',
          surveyname='city-commute-track',
          displayname='City commute consideration',
          sizes=['300x250'],
          preset='ocean',
          answers=['Yes', 'No'],
          question1='Would you consider this service?',
          client='Initech',
          agency='Fieldwork',
          created_at='2026-11-10T16:00:00Z',
          created_by='editor@example.com',
      ),
      _survey(
          'track-bank',
          surveyname='neighbourhood-bank-track',
          displayname='Neighbourhood bank track',
          sizes=['970x250'],
          preset='classic',
          answers=['Yes', 'No'],
          question1='Would you consider this bank?',
          client='Blue Harbor',
          agency='Oak & Iron',
          created_at='2026-11-11T12:00:00Z',
          created_by='admin@example.com',
      ),
      _survey(
          'track-travel',
          surveyname='weekend-travel-track',
          displayname='Weekend travel intent',
          sizes=['300x600'],
          preset='dark',
          answers=['Yes', 'Maybe', 'No'],
          question1='Planning a weekend trip?',
          client='Contoso',
          agency='Pixel Shop',
          created_at='2026-11-09T09:00:00Z',
          created_by='viewer@example.com',
      ),
      _survey(
          'lift-soap',
          surveyname='hand-soap-lift',
          displayname='Hand soap lift (small n)',
          surveytype='brand_lift',
          sizes=['300x250'],
          preset='classic',
          answers=['Foam Co', 'Other'],
          question1='Which soap brand did you notice?',
          client='Umbrella Foods',
          agency='Harbour Ads',
          created_at='2026-11-08T15:00:00Z',
          created_by='editor@example.com',
      ),
      _survey(
          'track-pet',
          surveyname='pet-treats-track',
          displayname='Pet treats track (no data)',
          sizes=['160x600'],
          preset='hazard',
          answers=['Yes', 'No'],
          question1='Would you buy these treats?',
          client='Maple Retail',
          agency='North Star',
          created_at='2026-11-07T10:00:00Z',
          created_by='admin@example.com',
      ),
      _survey(
          'track-retail',
          surveyname='aisle-endcap-track',
          displayname='Aisle endcap recall',
          sizes=['336x280'],
          preset='hot-pink',
          answers=['Saw it', 'Did not'],
          question1='Do you recall the endcap?',
          client='Globex',
          agency='Brightline',
          created_at='2026-11-06T13:00:00Z',
          created_by='editor@example.com',
      ),
      _survey(
          'lift-phone',
          surveyname='handset-launch-lift',
          displayname='Handset launch lift',
          surveytype='brand_lift',
          sizes=['300x250'],
          preset='classic',
          answers=['Pixel brand', 'Other', 'Not sure'],
          question1='Which handset brand did you notice?',
          client='Initech',
          agency='Example Media',
          created_at='2026-11-05T11:30:00Z',
          created_by='admin@example.com',
      ),
      _survey(
          'track-stream',
          surveyname='streaming-bundle-track',
          displayname='Streaming bundle consideration',
          sizes=['300x250'],
          preset='ocean',
          answers=['Yes', 'No'],
          question1='Would you consider this bundle?',
          client='Contoso',
          agency='Harbour Ads',
          created_at='2026-11-04T17:00:00Z',
          created_by='viewer@example.com',
      ),
      _survey(
          'track-air',
          surveyname='regional-air-track',
          displayname='Regional air consideration',
          sizes=['970x250'],
          preset='classic',
          answers=['Yes', 'No'],
          question1='Would you fly this airline?',
          client='Blue Harbor',
          agency='Fieldwork',
          created_at='2026-11-03T08:45:00Z',
          created_by='editor@example.com',
      ),
  ]
  for doc_id, payload in surveys:
    fs.collection('Surveys').document(doc_id).set(payload)

  access.upsert_user('admin@example.com', 'admin', actor='bootstrap')
  access.upsert_user('editor@example.com', 'editor', actor='admin@example.com')
  access.upsert_user('viewer@example.com', 'viewer', actor='admin@example.com')
  access.add_domain('agency.example', actor='admin@example.com', role='editor')
  access.add_domain('partner.example', actor='admin@example.com', role='viewer')
  access.write_audit(
      'create', 'editor@example.com', survey_id='lift-demo',
      detail='cola-awareness-lift')
  access.write_audit(
      'admin_user_upsert', 'admin@example.com',
      detail='viewer@example.com (viewer)')


def patch_bigquery() -> None:
  import pandas
  import survey_service

  now = datetime.datetime(2026, 11, 18, 12, 0, 0)
  counts_rows = [
      {
          'ID': 'lift-demo', 'Segmentation': 'default_control',
          'max_date': now, 'days_since_response': 1, 'response_count': 40,
          'n_q1': 40, 'k_q1_a': 26,
      },
      {
          'ID': 'lift-demo', 'Segmentation': 'default_expose',
          'max_date': now, 'days_since_response': 1, 'response_count': 42,
          'n_q1': 42, 'k_q1_a': 21,
      },
      {
          'ID': 'track-two', 'Segmentation': 'survey',
          'max_date': now, 'days_since_response': 2, 'response_count': 24,
          'n_q1': 24, 'k_q1_a': 12,
      },
      {
          'ID': 'tall-eight', 'Segmentation': 'survey',
          'max_date': now, 'days_since_response': 4, 'response_count': 18,
          'n_q1': 18, 'k_q1_a': 9,
      },
      {
          'ID': 'halfpage-dark', 'Segmentation': 'survey',
          'max_date': now, 'days_since_response': 8, 'response_count': 11,
          'n_q1': 11, 'k_q1_a': 5,
      },
      {
          'ID': 'mrec-pink', 'Segmentation': 'survey',
          'max_date': now, 'days_since_response': 1, 'response_count': 30,
          'n_q1': 30, 'k_q1_a': 15,
      },
      {
          'ID': 'lift-coffee', 'Segmentation': 'default_control',
          'max_date': now, 'days_since_response': 1, 'response_count': 36,
          'n_q1': 36, 'k_q1_a': 18,
      },
      {
          'ID': 'lift-coffee', 'Segmentation': 'default_expose',
          'max_date': now, 'days_since_response': 1, 'response_count': 38,
          'n_q1': 38, 'k_q1_a': 22,
      },
      {
          'ID': 'track-maple', 'Segmentation': 'survey',
          'max_date': now, 'days_since_response': 2, 'response_count': 44,
          'n_q1': 44, 'k_q1_a': 20,
      },
      {
          'ID': 'lift-cereal', 'Segmentation': 'default_control',
          'max_date': now, 'days_since_response': 1, 'response_count': 32,
          'n_q1': 32, 'k_q1_a': 14,
      },
      {
          'ID': 'lift-cereal', 'Segmentation': 'default_expose',
          'max_date': now, 'days_since_response': 1, 'response_count': 33,
          'n_q1': 33, 'k_q1_a': 19,
      },
      {
          'ID': 'track-tools', 'Segmentation': 'survey',
          'max_date': now, 'days_since_response': 0, 'response_count': 28,
          'n_q1': 28, 'k_q1_a': 11,
      },
      {
          'ID': 'lift-yogurt', 'Segmentation': 'default_control',
          'max_date': now, 'days_since_response': 5, 'response_count': 41,
          'n_q1': 41, 'k_q1_a': 20,
      },
      {
          'ID': 'lift-yogurt', 'Segmentation': 'default_expose',
          'max_date': now, 'days_since_response': 5, 'response_count': 40,
          'n_q1': 40, 'k_q1_a': 21,
      },
      {
          'ID': 'track-auto', 'Segmentation': 'survey',
          'max_date': now, 'days_since_response': 14, 'response_count': 22,
          'n_q1': 22, 'k_q1_a': 9,
      },
      {
          'ID': 'track-bank', 'Segmentation': 'survey',
          'max_date': now, 'days_since_response': 2, 'response_count': 420,
          'n_q1': 420, 'k_q1_a': 42,
      },
      {
          'ID': 'track-travel', 'Segmentation': 'survey',
          'max_date': now, 'days_since_response': 1, 'response_count': 55,
          'n_q1': 55, 'k_q1_a': 18,
      },
      {
          'ID': 'lift-soap', 'Segmentation': 'default_control',
          'max_date': now, 'days_since_response': 2, 'response_count': 12,
          'n_q1': 12, 'k_q1_a': 5,
      },
      {
          'ID': 'lift-soap', 'Segmentation': 'default_expose',
          'max_date': now, 'days_since_response': 2, 'response_count': 11,
          'n_q1': 11, 'k_q1_a': 6,
      },
      {
          'ID': 'track-retail', 'Segmentation': 'survey',
          'max_date': now, 'days_since_response': 6, 'response_count': 19,
          'n_q1': 19, 'k_q1_a': 8,
      },
      {
          'ID': 'lift-phone', 'Segmentation': 'default_control',
          'max_date': now, 'days_since_response': 4, 'response_count': 40,
          'n_q1': 40, 'k_q1_a': 18,
      },
      {
          'ID': 'lift-phone', 'Segmentation': 'default_expose',
          'max_date': now, 'days_since_response': 4, 'response_count': 41,
          'n_q1': 41, 'k_q1_a': 20,
      },
      {
          'ID': 'track-stream', 'Segmentation': 'survey',
          'max_date': now, 'days_since_response': 1, 'response_count': 61,
          'n_q1': 61, 'k_q1_a': 30,
      },
      {
          'ID': 'track-air', 'Segmentation': 'survey',
          'max_date': now, 'days_since_response': 20, 'response_count': 16,
          'n_q1': 16, 'k_q1_a': 7,
      },
  ]
  counts = pandas.DataFrame(counts_rows)

  def fake_counts(survey_ids=None, include_test=False):
    del include_test
    if not survey_ids:
      return counts
    return counts[counts['ID'].isin(list(survey_ids))].copy()

  lift_rows = []
  for i in range(40):
    lift_rows.append({
        'CreatedAt': now - datetime.timedelta(days=i % 10, hours=i % 12),
        'Segmentation': 'default_control',
        'Response': '1:A' if i % 3 else '1:B',
        'BomID': 'c-%02d' % i,
    })
  for i in range(42):
    lift_rows.append({
        'CreatedAt': now - datetime.timedelta(days=i % 10, hours=i % 12),
        'Segmentation': 'default_expose',
        'Response': '1:A' if i % 2 else '1:B',
        'BomID': 'e-%02d' % i,
    })
  lift_df = pandas.DataFrame(lift_rows)

  small_rows = []
  for i in range(8):
    small_rows.append({
        'CreatedAt': now - datetime.timedelta(hours=i),
        'Segmentation': 'default_control',
        'Response': '1:A' if i % 2 else '1:B',
        'BomID': 'sc-%02d' % i,
    })
  for i in range(8):
    small_rows.append({
        'CreatedAt': now - datetime.timedelta(hours=i),
        'Segmentation': 'default_expose',
        'Response': '1:A' if i % 3 else '1:B',
        'BomID': 'se-%02d' % i,
    })
  small_df = pandas.DataFrame(small_rows)

  def fake_rows(surveyid, client=None, include_test=False):
    del include_test
    if surveyid == 'lift-demo':
      return lift_df.copy()
    if surveyid == 'lift-small':
      return small_df.copy()
    n = 24
    rows = []
    for i in range(n):
      rows.append({
        'CreatedAt': now - datetime.timedelta(days=i % 7, hours=i % 12),
        'Segmentation': 'survey',
          'Response': '1:A' if i % 2 else '1:B',
          'BomID': 't-%s-%02d' % (surveyid, i),
      })
    return pandas.DataFrame(rows)

  def fake_rows_for_ids(survey_ids, client=None, include_test=False):
    out = {}
    for sid in survey_ids or []:
      out[sid] = fake_rows(sid, client=client, include_test=include_test)
    return out

  survey_service.get_response_counts = fake_counts
  survey_service.fetch_survey_response_rows = fake_rows
  survey_service.fetch_survey_response_rows_for_ids = fake_rows_for_ids
  survey_service.clear_stats_cache()


def install_firestore():
  from mockfirestore import MockFirestore
  import survey_collection

  fs = MockFirestore()

  def get_db():
    return fs

  def get_all(field_names=None):
    return fs.collection('Surveys').stream()

  survey_collection.get_db = get_db
  survey_collection._db = fs
  survey_collection._survey_collection = fs.collection('Surveys')
  survey_collection.get_all = get_all
  return fs


def session_cookie(app, role, email, name):
  client = app.test_client()
  with client.session_transaction() as sess:
    sess['user_email'] = email
    sess['user_name'] = name
    sess['user_role'] = role
  cookie = client.get_cookie('session')
  if cookie is None:
    raise RuntimeError('Flask session cookie was not set')
  return {'name': 'session', 'value': cookie.value, 'url': 'http://127.0.0.1:%s/' % PORT}


def start_app(app):
  from werkzeug.serving import make_server
  server = make_server('127.0.0.1', PORT, app, threaded=True)
  thread = threading.Thread(target=server.serve_forever, daemon=True)
  thread.start()
  for _ in range(50):
    import urllib.request
    try:
      urllib.request.urlopen('http://127.0.0.1:%s/login' % PORT, timeout=1)
      break
    except Exception:
      time.sleep(0.1)
  return server


def _optimize_png(path: Path, max_width: int | None) -> None:
  from PIL import Image
  image = Image.open(path)
  if max_width and image.width > max_width:
    ratio = max_width / float(image.width)
    image = image.resize(
        (max_width, max(1, int(image.height * ratio))), Image.Resampling.LANCZOS)
  if image.mode == 'RGBA':
    background = Image.new('RGB', image.size, (248, 249, 250))
    background.paste(image, mask=image.split()[-1])
    image = background
  elif image.mode != 'RGB':
    image = image.convert('RGB')
  image.save(path, format='PNG', optimize=True)


def capture(page, path: Path, *, full_page=True, clip=None, max_width=UI_MAX_WIDTH):
  if ONLY_NAMES and path.name not in ONLY_NAMES:
    return
  path.parent.mkdir(parents=True, exist_ok=True)
  page.screenshot(path=str(path), full_page=full_page, clip=clip)
  _optimize_png(path, None if clip else max_width)
  print('Wrote', path)


def wait_stats_ready(page, element_id='status-lift-demo'):
  page.wait_for_function(
      """(id) => {
        const el = document.getElementById(id);
        const text = (el && el.textContent) || '';
        return text.length > 0 && text.indexOf('Loading') === -1;
      }""",
      arg=element_id)


def assert_home_chrome(page):
  """Fail capture if the homepage is missing current list chrome.

  Guards against shipping screenshots from an older layout (no Status
  filter, no Result/Progress columns, fixed .container).
  """
  missing = page.evaluate(
      """() => {
        const need = [];
        if (!document.querySelector('select#filter-status')) {
          need.push('#filter-status');
        }
        if (!document.querySelector('select#filter-result')) {
          need.push('#filter-result');
        }
        if (!document.querySelector('#filter-include-test')) {
          need.push('#filter-include-test');
        }
        if (!document.querySelector('.container-fluid')) {
          need.push('.container-fluid');
        }
        if (!document.querySelector('#survey-table-wrap')) {
          need.push('#survey-table-wrap');
        }
        if (document.querySelector('.table-responsive #mainTable')) {
          need.push('unexpected .table-responsive around #mainTable');
        }
        if (!document.querySelector('#mainTable th.cell-result')) {
          need.push('Result header');
        }
        if (!document.querySelector('#mainTable th.cell-progress')) {
          need.push('Progress header');
        }
        if (!document.querySelector('#mainTable th.cell-status')) {
          need.push('Status header');
        }
        const labels = Array.from(
            document.querySelectorAll('#filter-status option'))
            .map(opt => opt.textContent.trim());
        for (const label of ['Active', 'Stale', 'Timed out', 'No data']) {
          if (labels.indexOf(label) === -1) need.push('status option ' + label);
        }
        return need;
      }""")
  if missing:
    raise RuntimeError(
        'Home chrome missing before capture: %s' % ', '.join(missing))


def run_browser(app, out: Path) -> None:
  from playwright.sync_api import sync_playwright

  base = 'http://127.0.0.1:%s' % PORT
  admin_cookie = session_cookie(
      app, 'admin', 'admin@example.com', 'Alex Admin')
  viewer_cookie = session_cookie(
      app, 'viewer', 'viewer@example.com', 'Vic Viewer')

  with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={'width': DESKTOP_WIDTH, 'height': 900},
        device_scale_factor=1)
    context.add_cookies([admin_cookie])
    page = context.new_page()

    page.goto(base + '/index', wait_until='networkidle')
    wait_stats_ready(page)
    assert_home_chrome(page)
    page.wait_for_timeout(200)
    capture(page, out / 'home.png')

    page.goto(base + '/index?client=Acme&size=300x250&status=active', wait_until='networkidle')
    page.wait_for_function(
        """() => {
          const sel = document.getElementById('filter-status');
          return sel && sel.value === 'active';
        }""")
    wait_stats_ready(page)
    assert_home_chrome(page)
    page.wait_for_timeout(200)
    capture(page, out / 'home-filters.png')

    page.goto(base + '/index?sort=progress&dir=desc', wait_until='networkidle')
    page.wait_for_selector('#mainTable')
    wait_stats_ready(page)
    assert_home_chrome(page)
    page.wait_for_timeout(200)
    capture(page, out / 'home-progress.png')

    page.set_viewport_size({'width': 800, 'height': 900})
    page.goto(base + '/index', wait_until='networkidle')
    page.wait_for_selector('#mainTable')
    wait_stats_ready(page)
    assert_home_chrome(page)
    page.wait_for_timeout(200)
    capture(page, out / 'home-narrow.png')

    page.set_viewport_size({'width': 1024, 'height': 900})
    page.goto(base + '/index', wait_until='networkidle')
    page.wait_for_selector('#mainTable')
    wait_stats_ready(page)
    assert_home_chrome(page)
    page.wait_for_timeout(200)
    capture(page, out / 'home-1024.png')

    page.set_viewport_size({'width': 390, 'height': 844})
    page.goto(base + '/index', wait_until='networkidle')
    page.wait_for_selector('#survey-cards .survey-card')
    wait_stats_ready(page, 'status-card-lift-demo')
    assert_home_chrome(page)
    page.wait_for_timeout(200)
    capture(page, out / 'home-cards.png')
    page.set_viewport_size({'width': DESKTOP_WIDTH, 'height': 900})

    page.goto(base + '/index', wait_until='networkidle')
    wait_stats_ready(page)
    assert_home_chrome(page)
    page.wait_for_selector('#compare-filtered')
    page.wait_for_timeout(200)
    capture(page, out / 'home-compare.png', full_page=False)
    page.wait_for_selector('#actions-lift-demo')
    page.click('#actions-lift-demo')
    page.wait_for_selector('#actions-lift-demo + .dropdown-menu.show, .dropdown-menu.show')
    page.wait_for_timeout(200)
    capture(page, out / 'home-actions-menu.png', full_page=False)

    page.goto(base + '/index', wait_until='networkidle')
    wait_stats_ready(page)
    assert_home_chrome(page)
    page.wait_for_selector('#mainTable a.js-preview-open')
    page.locator('#mainTable a.js-preview-open').first.click()
    page.wait_for_selector('#previewModal.show')
    page.wait_for_function(
        """() => {
          const iframe = document.getElementById('previewModalFrame');
          try {
            const doc = iframe && iframe.contentDocument;
            return !!(doc && doc.querySelector('#master_container'));
          } catch (err) {
            return false;
          }
        }""")
    page.wait_for_timeout(400)
    capture(page, out / 'home-preview-modal.png', full_page=False)
    page.locator('#previewModal [data-bs-dismiss="modal"]').click()
    page.wait_for_timeout(200)

    page.set_viewport_size({'width': DESKTOP_WIDTH, 'height': 2100})
    page.goto(base + '/survey/edit?survey_id=lift-demo', wait_until='networkidle')
    page.wait_for_selector('iframe.preview-frame')
    page.wait_for_timeout(800)
    capture(page, out / 'editor.png', full_page=False)
    cells = page.locator('#cells-editor')
    cells.scroll_into_view_if_needed()
    page.wait_for_timeout(200)
    box = cells.bounding_box()
    if not box:
      raise RuntimeError('Cells editor not visible')
    capture(
        page, out / 'editor-cells.png', full_page=False, clip=box,
        max_width=UI_MAX_WIDTH)
    page.set_viewport_size({'width': DESKTOP_WIDTH, 'height': 900})

    badge = page.locator('#disclosure-badge')
    badge.scroll_into_view_if_needed()
    page.locator('label.badge-icon-choice', has=page.locator('#badge_icon-Name')).click()
    page.wait_for_timeout(400)
    box = badge.bounding_box()
    if not box:
      raise RuntimeError('Disclosure badge card not visible')
    capture(
        page, out / 'editor-badge.png', full_page=False, clip=box,
        max_width=UI_MAX_WIDTH)
    page.locator('label.badge-icon-choice', has=page.locator('#badge_icon-B')).click()
    page.wait_for_timeout(200)

    qa = page.locator('#html5-spec-qa')
    qa.scroll_into_view_if_needed()
    receiver_help = page.locator(
        '#html5-spec-qa [data-qa-code="receiver"] button.help-meaning-toggle')
    if receiver_help.count():
      receiver_help.first.click()
      page.wait_for_selector(
          '#html5-spec-qa [data-qa-code="receiver"] .help-meaning-body.show')
    page.wait_for_timeout(200)
    box = qa.bounding_box()
    if not box:
      raise RuntimeError('HTML5 spec QA card not visible')
    capture(
        page, out / 'editor-html5-qa.png', full_page=False, clip=box,
        max_width=UI_MAX_WIDTH)

    page.set_viewport_size({'width': 900, 'height': 720})
    page.goto(
        base + '/survey/preview/lift-demo?size=300x250', wait_until='networkidle')
    page.wait_for_selector('#preview-test-frame')
    page.wait_for_timeout(400)
    capture(page, out / 'preview-300x250.png', full_page=False)
    page.set_viewport_size({'width': 1280, 'height': 900})

    creatives = (
        ('lift-demo', '300x250', 'creative-300x250-classic.png'),
        ('tall-eight', '160x600', 'creative-160x600-hazard.png'),
        ('halfpage-dark', '300x600', 'creative-300x600-dark.png'),
        ('mrec-pink', '336x280', 'creative-336x280-hotpink.png'),
        ('track-two', '300x250', 'creative-300x250-two-answers.png'),
        ('tall-eight', '160x600', 'creative-160x600-eight-answers.png'),
    )
    seen = set()
    for survey_id, size, filename in creatives:
      if filename in seen:
        continue
      seen.add(filename)
      w, h = (int(part) for part in size.split('x'))
      page.set_viewport_size({'width': max(w + 48, 400), 'height': h + 80})
      page.goto(
          '%s/survey/preview/%s?embed=1&size=%s' % (base, survey_id, size),
          wait_until='networkidle')
      page.wait_for_selector('#master_container')
      page.wait_for_timeout(300)
      box = page.locator('#master_container').bounding_box()
      if not box:
        raise RuntimeError('No master_container for %s' % filename)
      capture(
          page, out / filename, full_page=False, clip=box, max_width=None)

    page.set_viewport_size({'width': DESKTOP_WIDTH, 'height': 1600})
    page.goto(
        base + '/reports/compare?ids=lift-demo,lift-coffee',
        wait_until='networkidle')
    page.wait_for_selector('#compare-table')
    page.wait_for_timeout(800)
    capture(page, out / 'compare-studies.png', full_page=False)
    page.goto(base + '/survey/reporting/lift-demo', wait_until='networkidle')
    page.wait_for_selector('#dailyChart')
    page.wait_for_selector('table')
    page.wait_for_timeout(800)
    capture(page, out / 'report-lift.png', full_page=False)
    page.set_viewport_size({'width': DESKTOP_WIDTH, 'height': 900})
    seq = page.locator('#sequential-status')
    if seq.count():
      seq.scroll_into_view_if_needed()
      toggle = page.locator('#sequential-status button.help-meaning-toggle')
      if toggle.count():
        toggle.first.click()
        page.wait_for_selector('#sequential-status .help-meaning-body.show')
      page.wait_for_timeout(200)
      box = seq.bounding_box()
      if box:
        capture(
            page, out / 'report-sequential.png', full_page=False, clip=box,
            max_width=UI_MAX_WIDTH)

    page.set_viewport_size({'width': DESKTOP_WIDTH, 'height': 1100})
    page.goto(base + '/survey/sample-size', wait_until='networkidle')
    page.wait_for_selector('#sample-size-page')
    page.locator('#planner-form button.help-meaning-toggle').first.click()
    page.wait_for_selector('#planner-form .help-meaning-body.show')
    page.wait_for_timeout(200)
    capture(page, out / 'sample-size-planner.png', full_page=False)
    page.set_viewport_size({'width': DESKTOP_WIDTH, 'height': 900})

    page.goto(base + '/survey/reporting/lift-small', wait_until='networkidle')
    page.wait_for_selector('#min-n-warning')
    page.locator('#min-n-warning button.help-meaning-toggle').click()
    page.wait_for_selector('#min-n-warning .help-meaning-body.show')
    page.wait_for_timeout(200)
    box = page.locator('#min-n-warning').bounding_box()
    if not box:
      raise RuntimeError('min-n warning not visible')
    capture(
        page, out / 'report-min-n-help.png', full_page=False, clip=box,
        max_width=UI_MAX_WIDTH)

    page.goto(base + '/admin', wait_until='networkidle')
    page.wait_for_selector('table')
    page.wait_for_timeout(300)
    capture(page, out / 'admin.png')

    page.set_viewport_size({'width': DESKTOP_WIDTH, 'height': 900})
    page.goto(base + '/index', wait_until='networkidle')
    wait_stats_ready(page)
    assert_home_chrome(page)
    page.wait_for_timeout(200)
    page.click('#userMenu')
    page.wait_for_selector('.dropdown-menu.show')
    page.wait_for_timeout(200)
    capture(page, out / 'avatar-dropdown.png', full_page=False)

    app.config['AUTH_BYPASS'] = False
    login_context = browser.new_context(
        viewport={'width': DESKTOP_WIDTH, 'height': 900})
    login_page = login_context.new_page()
    login_page.goto(base + '/login', wait_until='networkidle')
    login_page.wait_for_selector('a.btn-primary')
    capture(login_page, out / 'login.png', full_page=False)
    login_context.close()

    viewer_context = browser.new_context(
        viewport={'width': DESKTOP_WIDTH, 'height': 900})
    viewer_context.add_cookies([viewer_cookie])
    viewer_page = viewer_context.new_page()
    viewer_page.goto(base + '/admin', wait_until='networkidle')
    viewer_page.wait_for_selector('h1')
    capture(viewer_page, out / 'forbidden-viewer.png', full_page=False)
    viewer_context.close()

    app.config['AUTH_BYPASS'] = True
    browser.close()


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--out-dir', default=str(DEFAULT_OUT))
  parser.add_argument('--port', type=int, default=DEFAULT_PORT)
  parser.add_argument(
      '--only', nargs='+', default=None,
      help='Basenames to write (e.g. editor.png editor-badge.png). Default: all.')
  args = parser.parse_args(argv)
  global PORT, ONLY_NAMES
  PORT = args.port
  ONLY_NAMES = {Path(name).name for name in args.only} if args.only else None
  _prepare_env()
  fs = install_firestore()
  import main as flask_main
  flask_main.app.config['AUTH_BYPASS'] = True
  flask_main.app.config['WTF_CSRF_ENABLED'] = True
  seed(fs)
  patch_bigquery()
  server = start_app(flask_main.app)
  try:
    run_browser(flask_main.app, Path(args.out_dir))
  finally:
    server.shutdown()
  return 0


if __name__ == '__main__':
  sys.exit(main())
