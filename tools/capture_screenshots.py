#!/usr/bin/env python3
"""Seed a local Flask app with sample data and capture README screenshots.

Uses MockFirestore (no GCP, no real client data) and patches BigQuery reads
with synthetic Brand Lift rows so the report page has CIs and a chart.

  pip install -r creative/app/requirements.txt -r tools/requirements-screenshots.txt
  python3 -m playwright install chromium
  python3 tools/capture_screenshots.py

Images land in docs/images/ as optimised PNG (UI capped at 1200px wide;
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
UI_MAX_WIDTH = 1200


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
      'agency': fields.pop('agency', 'Example Media'),
      'language': 'en',
      'responsetype': 'Submit Responses at End of Survey',
      'question1': fields.pop('question1', 'Which brand did you see?'),
      'question1type': 'SINGLE_OPTION',
      'question1order': 'ORDERED',
      'badge_icon': fields.pop('badge_icon', 'B'),
      'badge_text': '',
      'custom_css': _theme_css(preset),
      'creativesizes': sizes,
      'creativesize': sizes[0] if len(sizes) == 1 else sizes,
  }
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
      },
      {
          'ID': 'lift-demo', 'Segmentation': 'default_expose',
          'max_date': now, 'days_since_response': 1, 'response_count': 42,
      },
      {
          'ID': 'track-two', 'Segmentation': 'survey',
          'max_date': now, 'days_since_response': 2, 'response_count': 24,
      },
      {
          'ID': 'tall-eight', 'Segmentation': 'survey',
          'max_date': now, 'days_since_response': 4, 'response_count': 18,
      },
      {
          'ID': 'halfpage-dark', 'Segmentation': 'survey',
          'max_date': now, 'days_since_response': 8, 'response_count': 11,
      },
      {
          'ID': 'mrec-pink', 'Segmentation': 'survey',
          'max_date': now, 'days_since_response': 1, 'response_count': 30,
      },
  ]
  counts = pandas.DataFrame(counts_rows)

  def fake_counts(survey_ids=None):
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

  def fake_rows(surveyid, client=None):
    if surveyid == 'lift-demo':
      return lift_df.copy()
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

  survey_service.get_response_counts = fake_counts
  survey_service.fetch_survey_response_rows = fake_rows
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
  path.parent.mkdir(parents=True, exist_ok=True)
  page.screenshot(path=str(path), full_page=full_page, clip=clip)
  _optimize_png(path, None if clip else max_width)
  print('Wrote', path)


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
        viewport={'width': 1280, 'height': 900},
        device_scale_factor=1)
    context.add_cookies([admin_cookie])
    page = context.new_page()

    page.goto(base + '/index', wait_until='networkidle')
    page.wait_for_selector('#status-lift-demo')
    page.wait_for_timeout(400)
    capture(page, out / 'home.png')

    page.goto(base + '/index?client=Acme&size=300x250', wait_until='networkidle')
    page.wait_for_timeout(400)
    capture(page, out / 'home-filters.png')

    page.goto(base + '/survey/edit?survey_id=lift-demo', wait_until='networkidle')
    page.wait_for_selector('iframe')
    page.wait_for_timeout(800)
    capture(page, out / 'editor.png', full_page=False)

    page.set_viewport_size({'width': 720, 'height': 420})
    page.goto(
        base + '/survey/preview/lift-demo?size=300x250', wait_until='networkidle')
    page.wait_for_selector('#master_container')
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
          '%s/survey/preview/%s?size=%s' % (base, survey_id, size),
          wait_until='networkidle')
      page.wait_for_selector('#master_container')
      page.wait_for_timeout(300)
      box = page.locator('#master_container').bounding_box()
      if not box:
        raise RuntimeError('No master_container for %s' % filename)
      capture(
          page, out / filename, full_page=False, clip=box, max_width=None)

    page.set_viewport_size({'width': 1280, 'height': 900})
    page.goto(base + '/survey/reporting/lift-demo', wait_until='networkidle')
    page.wait_for_selector('#dailyChart')
    page.wait_for_timeout(800)
    capture(page, out / 'report-lift.png', full_page=False)

    page.goto(base + '/admin', wait_until='networkidle')
    page.wait_for_selector('table')
    page.wait_for_timeout(300)
    capture(page, out / 'admin.png')

    page.goto(base + '/index', wait_until='networkidle')
    page.wait_for_timeout(300)
    page.click('#userMenu')
    page.wait_for_selector('.dropdown-menu.show')
    page.wait_for_timeout(200)
    capture(page, out / 'avatar-dropdown.png', full_page=False)

    app.config['AUTH_BYPASS'] = False
    login_context = browser.new_context(
        viewport={'width': 1280, 'height': 900})
    login_page = login_context.new_page()
    login_page.goto(base + '/login', wait_until='networkidle')
    login_page.wait_for_selector('a.btn-primary')
    capture(login_page, out / 'login.png', full_page=False)
    login_context.close()

    viewer_context = browser.new_context(
        viewport={'width': 1280, 'height': 900})
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
  args = parser.parse_args(argv)
  global PORT
  PORT = args.port
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
