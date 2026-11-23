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

import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import textwrap
import unittest

import app_yaml_check
import bq_dataset_iam


_APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_REPO_ROOT = os.path.abspath(os.path.join(_APP_DIR, '..', '..'))
_VENDOR = os.path.join(_APP_DIR, 'static', 'vendor')


class VendorPinTest(unittest.TestCase):

  def test_pinned_vendor_files_exist(self):
    versions = open(os.path.join(_VENDOR, 'VERSIONS'), encoding='utf-8').read()
    self.assertIn('bootstrap 5.3.3', versions)
    self.assertIn('bootstrap-icons 1.11.3', versions)
    self.assertIn('htmx 1.9.12', versions)
    self.assertIn('alpinejs 3.14.3', versions)
    self.assertIn('chart.js 4.4.6', versions)
    for name in (
        'bootstrap.min.css',
        'bootstrap.bundle.min.js',
        'bootstrap-icons.min.css',
        'htmx.min.js',
        'alpine.min.js',
        'chart.umd.min.js',
        os.path.join('fonts', 'bootstrap-icons.woff2'),
        os.path.join('fonts', 'bootstrap-icons.woff'),
    ):
      path = os.path.join(_VENDOR, name)
      self.assertTrue(os.path.isfile(path), path)
      self.assertGreater(os.path.getsize(path), 100)

  def test_templates_do_not_load_cdns(self):
    needles = (
        'cdn.jsdelivr.net',
        'unpkg.com',
        'cdnjs.cloudflare.com',
        'code.jquery.com',
        'htmx.org',
        'cdn.jsdelivr',
    )
    templates = os.path.join(_APP_DIR, 'templates')
    for filename in os.listdir(templates):
      if not filename.endswith('.html'):
        continue
      text = open(os.path.join(templates, filename), encoding='utf-8').read()
      for needle in needles:
        self.assertNotIn(needle, text, filename)


class DeployIamTest(unittest.TestCase):

  def test_deploy_uses_least_privilege_and_secret_manager(self):
    script = open(os.path.join(_REPO_ROOT, 'deploy'), encoding='utf-8').read()
    self.assertIn('secretmanager.googleapis.com', script)
    self.assertIn('roles/datastore.user', script)
    self.assertIn('roles/bigquery.jobUser', script)
    self.assertIn('roles/logging.logWriter', script)
    self.assertIn('roles/secretmanager.secretAccessor', script)
    self.assertIn('roles/bigquery.dataEditor', script)
    self.assertIn('roles/datastore.viewer', script)
    self.assertIn('roles/cloudbuild.builds.builder', script)
    self.assertIn('roles/artifactregistry.createOnPushWriter', script)
    self.assertIn('roles/storage.objectAdmin', script)
    self.assertIn('brandometer-receiver', script)
    self.assertIn('--max-instances=20', script)
    self.assertIn('--timeout=60s', script)
    self.assertIn('--memory=256MB', script)
    self.assertIn('upsert_secret', script)
    self.assertIn('ensure_generated_secret', script)
    self.assertIn('--app-only', script)
    self.assertIn('--skip-oauth-prompts', script)
    self.assertIn('OAUTH_CLIENT_ID', script)
    self.assertIn('OAUTH_CLIENT_SECRET', script)
    self.assertIn('[press Enter to keep existing]', script)
    self.assertIn('stored ${#value} chars', script)
    self.assertIn('brandometer-oauth-client-id', script)
    self.assertIn('brandometer-receiver-hmac', script)
    self.assertIn('brandometer-ip-hmac', script)
    self.assertIn('RECEIVER_HMAC_SECRET=brandometer-receiver-hmac:latest', script)
    self.assertIn('IP_HMAC_SECRET=brandometer-ip-hmac:latest', script)
    self.assertIn('/auth/callback', script)
    self.assertNotIn("read -sp 'Password: '", script)
    self.assertNotIn('echo $AUTH_PASSWORD', script)
    self.assertNotIn('echo $GOOGLE_OAUTH_CLIENT_SECRET', script)
    self.assertNotIn('--role="roles/editor"', script.split('remove-iam-policy-binding')[0])
    yaml_path = os.path.join(_APP_DIR, 'app.yaml.template')
    yaml_text = open(yaml_path, encoding='utf-8').read()
    self.assertNotIn('secret_environment_variables', yaml_text)
    self.assertIn('secure: always', yaml_text)
    self.assertIn('BOOTSTRAP_ADMIN_EMAIL', yaml_text)
    self.assertIn('DATA_STUDIO_TEMPLATE_REPORT_ID', yaml_text)
    self.assertIn('DATA_STUDIO_TEMPLATE_DS_ALIAS', yaml_text)
    self.assertIn('PROJECT_ID', yaml_text)
    self.assertIn('RECEIVER_URL', yaml_text)
    self.assertIn('RECEIVER_URL must be https://', script)
    self.assertNotIn('GOOGLE_OAUTH_CLIENT_SECRET', yaml_text)
    self.assertNotIn('SECRET_KEY', yaml_text)
    self.assertNotIn('RECEIVER_HMAC_SECRET', yaml_text)
    self.assertNotIn('AUTH_USERNAME', yaml_text)
    self.assertNotIn('AUTH_PASSWORD', yaml_text)
    self.assertIn('automatic_scaling:', yaml_text)
    self.assertIn('max_instances: {{MAX_INSTANCES}}', yaml_text)

  def test_deploy_is_valid_posix_shell(self):
    script = os.path.join(_REPO_ROOT, 'deploy')
    subprocess.check_call(['sh', '-n', script])
    try:
      result = subprocess.run(
          ['shellcheck', '-e', 'SC2086,SC2166,SC2181,SC2129', script],
          capture_output=True, text=True)
    except FileNotFoundError:
      return
    if result.returncode == 127:
      return
    self.assertEqual(
        result.returncode, 0, result.stdout + result.stderr)

  def test_deploy_skips_existing_dataset_and_retries_iam(self):
    script = open(os.path.join(_REPO_ROOT, 'deploy'), encoding='utf-8').read()
    self.assertIn('retry_gcloud()', script)
    self.assertIn('wait_for_service_account()', script)
    self.assertIn('ensure_receiver_sa()', script)
    self.assertIn('already exists (not modified)', script)
    self.assertIn('service-accounts describe', script)
    self.assertIn('--condition=None', script)
    self.assertGreaterEqual(script.count('--condition=None'), 4)
    self.assertIn('Keeping existing secret', script)
    self.assertIn('DEPLOY_RETRY_MAX_SECONDS', script)
    self.assertNotIn('mk --force', script)
    self.assertNotRegex(script, r'bq --location=\$LOCATION mk\s+\\\s+--force')
    self.assertIn(
        'bq show --format=none "$PROJECT_ID:responses"', script)
    self.assertIn(
        'bq show --format=none "$PROJECT_ID:responses.responses"', script)
    self.assertNotIn('bq add-iam-policy-binding', script)
    self.assertIn('bq update --source', script)
    self.assertIn('Dataset IAM confirmed:', script)
    self.assertNotIn('gcloud bigquery', script)
    self.assertIn('PYTHONWARNINGS=ignore', script)
    self.assertIn('bq --format=prettyjson --quiet show --dataset', script)
    self.assertIn('bq --quiet update --source', script)
    self.assertIn('bq_dataset_iam.py', script)
    self.assertIn('Brandometer2 needs Firestore Native', script)
    self.assertIn('ensure_respondent_columns()', script)
    self.assertIn('ensure_reporting_dataset()', script)
    self.assertIn('authorize_reporting_views()', script)
    self.assertIn('brandometer_reporting', script)
    self.assertIn('reporting_views.py', script)
    self.assertIn('authorize-dataset', script)
    self.assertIn('ADD COLUMN IF NOT EXISTS RespondentID STRING', script)
    self.assertIn('ADD COLUMN IF NOT EXISTS RespondentIDSource STRING', script)
    self.assertIn('ADD COLUMN IF NOT EXISTS PlacementID STRING', script)
    self.assertIn('ADD COLUMN IF NOT EXISTS AdCreativeID STRING', script)
    self.assertIn('ADD COLUMN IF NOT EXISTS CreativeVersion INT64', script)
    self.assertIn(
        'Removing project roles/bigquery.dataEditor from $member', script)
    self.assertIn('MAX_INSTANCES', script)
    self.assertIn('ensure_dataset_descriptions()', script)
    self.assertIn('warn_if_unpartitioned()', script)
    self.assertIn('migrate_responses_partition.py', script)
    self.assertIn('bq update --description', script)
    self.assertIn('Main response dataset for Brandometer2', script)
    self.assertIn(
        'Authorized Brandometer2 reporting views for Data Studio', script)
    self.assertIn('Survey response rows for Brandometer2', script)
    self.assertNotIn('Main response data set for Brandometer"', script)
    self.assertNotIn('Survey response rows for Brandometer"', script)

  def test_deploy_rejects_known_invalid_command_forms(self):
    script = open(os.path.join(_REPO_ROOT, 'deploy'), encoding='utf-8').read()
    invalid = (
        'gcloud bigquery',
        'gcloud alpha bigquery',
        'gcloud beta bigquery',
        'gcloud datasets',
        'gcloud functions deploy --v2',
        'gcloud secrets get-iam-policy-binding',
        'gcloud iam add-iam-policy-binding',
        'bq mk --force',
        'secret_environment_variables',
        'bq add-iam-policy-binding',
    )
    for form in invalid:
      self.assertNotIn(form, script, form)
    self.assertNotRegex(script, r'(^|[^_])gcloud bq\b')
    self.assertNotIn('bq add-iam-policy-binding', script)
    self.assertIn('bq update --source', script)
    self.assertIn('gcloud secrets add-iam-policy-binding', script)
    self.assertIn('gcloud functions deploy', script)
    self.assertIn('--gen2', script)
    self.assertIn('gcloud app deploy', script)
    self.assertIn('gcloud iam service-accounts create', script)
    self.assertIn('gcloud iam service-accounts describe', script)
    self.assertIn('gcloud secrets create', script)
    self.assertIn('gcloud secrets versions add', script)
    self.assertIn('gcloud storage buckets add-iam-policy-binding', script)

  def test_deploy_grants_gae_cloud_build_roles_on_app_only(self):
    script = open(os.path.join(_REPO_ROOT, 'deploy'), encoding='utf-8').read()
    self.assertIn('grant_gae_build_roles()', script)
    self.assertIn('grant_bucket_object_admin()', script)
    self.assertIn('roles/cloudbuild.builds.builder', script)
    self.assertIn('roles/artifactregistry.createOnPushWriter', script)
    self.assertIn('roles/storage.objectAdmin', script)
    self.assertIn('gcloud storage buckets describe', script)
    self.assertIn('gcloud storage buckets add-iam-policy-binding', script)
    self.assertIn('gs://staging.${PROJECT_ID}.appspot.com', script)
    self.assertIn('gs://${PROJECT_ID}.appspot.com', script)
    self.assertIn('does not exist (skipping IAM)', script)
    self.assertIn('retry_gcloud gcloud storage buckets add-iam-policy-binding', script)
    call_at = script.rindex('\ngrant_gae_build_roles\n')
    self.assertGreater(call_at, script.index('Set up App Engine'))
    self.assertGreater(
        script.index('Set up App Engine'),
        script.index('-- Deploy Cloud Function'))
    receiver_dataset = script.rindex(
        'grant_dataset_editor "serviceAccount:$RECEIVER_SA"')
    self.assertGreater(receiver_dataset, script.index('Set up App Engine'))

  def test_retry_gcloud_succeeds_after_failures_and_times_out(self):
    script = open(os.path.join(_REPO_ROOT, 'deploy'), encoding='utf-8').read()
    start = script.index('retry_is_transient() {')
    end = script.index('\nwait_for_service_account()')
    retry_fn = script[start:end]
    with tempfile.TemporaryDirectory() as tmp:
      helper = os.path.join(tmp, 'retry.sh')
      open(helper, 'w', encoding='utf-8').write(textwrap.dedent('''\
          #!/bin/sh
          set -e
          RETRY_MAX_SECONDS=3
          RETRY_START_SECONDS=1
          RETRY_MAX_DELAY_SECONDS=1
          sleep() { :; }
      ''') + retry_fn + textwrap.dedent('''\
          n=0
          flaky() {
            n=$((n+1))
            echo "INVALID_ARGUMENT: Service account x does not exist" >&2
            [ "$n" -ge 3 ]
          }
          retry_gcloud flaky
          invalid() {
            echo "ERROR: (gcloud) Invalid choice: 'bigquery'" >&2
            return 1
          }
          if retry_gcloud invalid; then
            echo unexpectedly_ok
            exit 1
          fi
          always_fail() { echo "NOT_FOUND" >&2; return 1; }
          if retry_gcloud always_fail; then
            echo unexpectedly_ok
            exit 1
          fi
          echo ok
      '''))
      out = subprocess.check_output(['sh', helper], stderr=subprocess.STDOUT, text=True)
    self.assertIn('ok', out.splitlines()[-1])
    self.assertIn('Retrying in', out)
    self.assertIn('not retrying (non-transient)', out)
    self.assertGreaterEqual(out.count('Invalid choice'), 1)
    between_invalid_and_notfound = out.split(
        "Invalid choice: 'bigquery'", 1)[1].split('NOT_FOUND', 1)[0]
    self.assertNotIn('Retrying in', between_invalid_and_notfound)

  def test_rendered_app_yaml_only_allows_standard_keys(self):
    template = open(
        os.path.join(_APP_DIR, 'app.yaml.template'), encoding='utf-8').read()
    rendered = (
        template
        .replace('{{RECEIVER_URL}}', 'https://receiver.example/run')
        .replace('{{PROJECT_ID}}', 'brandometer2')
        .replace('{{GTAG_ID}}', '')
        .replace('{{BOOTSTRAP_ADMIN_EMAIL}}', 'mark@google.com')
        .replace('{{MAX_INSTANCES}}', '5')
        .replace('{{DATA_STUDIO_TEMPLATE_REPORT_ID}}', '')
        .replace('{{DATA_STUDIO_TEMPLATE_DS_ALIAS}}', ''))
    self.assertEqual(app_yaml_check.validate_app_yaml(rendered), [])
    self.assertIn('automatic_scaling:', rendered)
    self.assertIn('max_instances: 5', rendered)
    keys = set(app_yaml_check.top_level_keys(rendered))
    self.assertTrue(keys <= app_yaml_check.ALLOWED_TOP_LEVEL, keys)
    self.assertEqual(
        set(app_yaml_check.env_var_keys(rendered)),
        app_yaml_check.ALLOWED_ENV)
    self.assertNotIn('secret_environment_variables', rendered)
    bad = rendered + '\nsecret_environment_variables:\n- name: SECRET_KEY\n'
    errors = app_yaml_check.validate_app_yaml(bad)
    self.assertTrue(any('secret_environment_variables' in item for item in errors))
    checker = os.path.join(_APP_DIR, 'app_yaml_check.py')
    with tempfile.TemporaryDirectory() as tmp:
      path = os.path.join(tmp, 'app.yaml')
      open(path, 'w', encoding='utf-8').write(rendered)
      subprocess.check_call([sys.executable, checker, path])
      open(path, 'w', encoding='utf-8').write(bad)
      result = subprocess.run(
          [sys.executable, checker, path], capture_output=True, text=True)
      self.assertNotEqual(result.returncode, 0)

  def test_dataset_iam_merge_adds_writer_once(self):
    email = 'sa@project.iam.gserviceaccount.com'
    warning = (
        '/usr/lib/python3/dist-packages/requests/__init__.py:87: '
        "RequestsDependencyWarning: urllib3 (1.26.5) or chardet (4.0.0) "
        "doesn't match a supported version!\n"
        '  warnings.warn(\n')
    payload = json.dumps({
        'access': [
            {'role': 'OWNER', 'specialGroup': 'projectOwners'},
        ],
    })
    with tempfile.TemporaryDirectory() as tmp:
      path = os.path.join(tmp, 'ds.json')
      open(path, 'w', encoding='utf-8').write(warning + payload + '\ntrailing\n')
      helper = os.path.join(_APP_DIR, 'bq_dataset_iam.py')
      first = subprocess.run(
          [sys.executable, helper, 'merge', path, email],
          capture_output=True, text=True)
      self.assertEqual(first.returncode, 2, first.stderr)
      data = json.loads(open(path, encoding='utf-8').read())
      emails = [row.get('userByEmail') for row in data['access']]
      self.assertIn(email, emails)
      writers = [
          row for row in data['access']
          if row.get('userByEmail') == email]
      self.assertEqual(writers[0]['role'], 'WRITER')
      second = subprocess.run(
          [sys.executable, helper, 'merge', path, email],
          capture_output=True, text=True)
      self.assertEqual(second.returncode, 0, second.stderr)
      verified = subprocess.check_output(
          [sys.executable, helper, 'verify', path, email], text=True)
      self.assertEqual(verified.strip(), 'WRITER')

  def test_dataset_iam_authorize_reporting_dataset_once(self):
    payload = json.dumps({
        'access': [
            {'role': 'OWNER', 'specialGroup': 'projectOwners'},
        ],
    })
    with tempfile.TemporaryDirectory() as tmp:
      path = os.path.join(tmp, 'ds.json')
      open(path, 'w', encoding='utf-8').write(payload)
      helper = os.path.join(_APP_DIR, 'bq_dataset_iam.py')
      first = subprocess.run(
          [sys.executable, helper, 'authorize-dataset', path, 'proj',
           'brandometer_reporting'],
          capture_output=True, text=True)
      self.assertEqual(first.returncode, 2, first.stderr)
      data = json.loads(open(path, encoding='utf-8').read())
      self.assertTrue(
          bq_dataset_iam.authorized_dataset_present(
              data, 'proj', 'brandometer_reporting'))
      types = data['access'][1]['dataset']['targetTypes']
      self.assertEqual(types, ['VIEWS'])
      second = subprocess.run(
          [sys.executable, helper, 'authorize-dataset', path, 'proj',
           'brandometer_reporting'],
          capture_output=True, text=True)
      self.assertEqual(second.returncode, 0, second.stderr)

  def test_dataset_iam_merge_reader_user_and_group(self):
    payload = json.dumps({'access': []})
    with tempfile.TemporaryDirectory() as tmp:
      path = os.path.join(tmp, 'ds.json')
      open(path, 'w', encoding='utf-8').write(payload)
      helper = os.path.join(_APP_DIR, 'bq_dataset_iam.py')
      first = subprocess.run(
          [sys.executable, helper, 'merge-reader', path, 'ana@example.com'],
          capture_output=True, text=True)
      self.assertEqual(first.returncode, 2, first.stderr)
      data = json.loads(open(path, encoding='utf-8').read())
      self.assertEqual(data['access'][0]['role'], 'READER')
      self.assertEqual(data['access'][0]['userByEmail'], 'ana@example.com')
      group = subprocess.run(
          [sys.executable, helper, 'merge-reader', path,
           'group:analysts@example.com'],
          capture_output=True, text=True)
      self.assertEqual(group.returncode, 2, group.stderr)
      data = json.loads(open(path, encoding='utf-8').read())
      self.assertEqual(data['access'][1]['groupByEmail'], 'analysts@example.com')
      verified = subprocess.check_output(
          [sys.executable, helper, 'verify-reader', path, 'ana@example.com'],
          text=True)
      self.assertEqual(verified.strip(), 'READER')
      again = subprocess.run(
          [sys.executable, helper, 'merge-reader', path, 'ana@example.com'],
          capture_output=True, text=True)
      self.assertEqual(again.returncode, 0, again.stderr)

  def test_dataset_iam_strips_stdout_noise_before_json(self):
    noisy = (
        'RequestsDependencyWarning: urllib3 (1.26.5) or chardet (4.0.0) '
        "doesn't match a supported version!\n"
        '{"access": [{"role": "WRITER", '
        '"userByEmail": "recv@p.iam.gserviceaccount.com"}]}\n')
    data = bq_dataset_iam.extract_json_object(noisy)
    self.assertEqual(
        bq_dataset_iam.writer_role(data, 'recv@p.iam.gserviceaccount.com'),
        'WRITER')
    with self.assertRaises(ValueError):
      bq_dataset_iam.extract_json_object('not json at all')

  def test_dev_requirements_include_pip_audit(self):
    text = open(
        os.path.join(_REPO_ROOT, 'requirements-dev.txt'), encoding='utf-8').read()
    self.assertIn('pip-audit==', text)
    self.assertIn('pytest==9.0.3', text)
    reqs = open(
        os.path.join(_APP_DIR, 'requirements.txt'), encoding='utf-8').read()
    self.assertNotIn('Flask-BasicAuth', reqs)
    self.assertIn('google-cloud-secret-manager', reqs)
    self.assertIn('Authlib==1.9.9', reqs)
    self.assertIn('protobuf==5.29.6', reqs)
    receiver_reqs = open(
        os.path.join(_REPO_ROOT, 'receiver', 'requirements.txt'),
        encoding='utf-8').read()
    self.assertIn('setuptools>=70,<81', receiver_reqs)
    self.assertIn('pytest==9.0.3', reqs)
    self.assertIn('pyarrow==', reqs)


def _png_size(path):
  data = open(path, 'rb').read(24)
  if data[:8] != b'\x89PNG\r\n\x1a\n':
    raise AssertionError('%s is not a PNG' % path)
  width, height = struct.unpack('>II', data[16:24])
  return width, height


def _ico_sizes(path):
  data = open(path, 'rb').read()
  _reserved, itype, count = struct.unpack_from('<HHH', data)
  if itype != 1 or count < 1:
    raise AssertionError('%s is not a multi-image ICO' % path)
  sizes = []
  for index in range(count):
    width = data[6 + index * 16]
    height = data[7 + index * 16]
    sizes.append((width or 256, height or 256))
  return sizes


class FaviconAssetsTest(unittest.TestCase):

  def test_svg_mark_and_brand_blue(self):
    svg = open(
        os.path.join(_APP_DIR, 'static', 'favicon.svg'), encoding='utf-8').read()
    self.assertIn('Bv2', svg)
    self.assertIn('#0d6efd', svg)
    self.assertIn('Brandometer2', svg)

  def test_committed_raster_sizes(self):
    apple = os.path.join(_APP_DIR, 'static', 'apple-touch-icon.png')
    self.assertEqual(_png_size(apple), (180, 180))
    ico_static = os.path.join(_APP_DIR, 'static', 'favicon.ico')
    ico_root = os.path.join(_APP_DIR, 'favicon.ico')
    self.assertEqual(sorted(_ico_sizes(ico_static)), [(16, 16), (32, 32), (48, 48)])
    self.assertEqual(
        open(ico_static, 'rb').read(), open(ico_root, 'rb').read())

  def test_templates_and_yaml_link_icons(self):
    for name in ('base.html', 'login.html'):
      html = open(
          os.path.join(_APP_DIR, 'templates', name), encoding='utf-8').read()
      self.assertIn("filename='favicon.svg'", html)
      self.assertIn("filename='favicon.ico'", html)
      self.assertIn("filename='apple-touch-icon.png'", html)
      self.assertIn('rel="icon"', html)
      self.assertIn('rel="apple-touch-icon"', html)
    yaml_text = open(
        os.path.join(_APP_DIR, 'app.yaml.template'), encoding='utf-8').read()
    self.assertIn('/favicon\\.ico', yaml_text)
    self.assertIn('static_files: favicon.ico', yaml_text)
    generator = open(
        os.path.join(_REPO_ROOT, 'tools', 'generate_favicons.py'),
        encoding='utf-8').read()
    self.assertIn('write_ico', generator)
    self.assertIn('rsvg-convert', generator)


class ReadmeImagesTest(unittest.TestCase):

  _REQUIRED = (
      'docs/images/home.png',
      'docs/images/home-filters.png',
      'docs/images/home-progress.png',
      'docs/images/home-narrow.png',
      'docs/images/home-1024.png',
      'docs/images/home-cards.png',
      'docs/images/home-actions-menu.png',
      'docs/images/home-preview-modal.png',
      'docs/images/editor.png',
      'docs/images/editor-badge.png',
      'docs/images/preview-300x250.png',
      'docs/images/creative-300x250-classic.png',
      'docs/images/creative-300x250-two-answers.png',
      'docs/images/creative-160x600-hazard.png',
      'docs/images/creative-160x600-eight-answers.png',
      'docs/images/creative-300x600-dark.png',
      'docs/images/creative-336x280-hotpink.png',
      'docs/images/report-lift.png',
      'docs/images/editor-html5-qa.png',
      'docs/images/report-min-n-help.png',
      'docs/images/sample-size-planner.png',
      'docs/images/report-sequential.png',
      'docs/images/admin.png',
      'docs/images/avatar-dropdown.png',
      'docs/images/login.png',
      'docs/images/forbidden-viewer.png',
  )

  def _docs_image_refs(self):
    refs = []
    for name in ('README.md', 'DEVELOPERS.md', 'AGENTS.md'):
      path = os.path.join(_REPO_ROOT, name)
      if not os.path.isfile(path):
        continue
      text = open(path, encoding='utf-8').read()
      refs += re.findall(r'\((docs/images/[^)\s]+)\)', text)
      refs += re.findall(r'src="(docs/images/[^"]+)"', text)
      refs += re.findall(r'`(docs/images/[^`]+)`', text)
    docs_dir = os.path.join(_REPO_ROOT, 'docs')
    if os.path.isdir(docs_dir):
      for root, _dirs, files in os.walk(docs_dir):
        for filename in files:
          if not filename.endswith('.md'):
            continue
          text = open(os.path.join(root, filename), encoding='utf-8').read()
          refs += re.findall(r'\((docs/images/[^)\s]+)\)', text)
          refs += re.findall(r'src="(docs/images/[^"]+)"', text)
    return refs

  def test_readme_embeds_existing_docs_images(self):
    readme_path = os.path.join(_REPO_ROOT, 'README.md')
    readme = open(readme_path, encoding='utf-8').read()
    paths = self._docs_image_refs()
    embedded = set(
        re.findall(r'\((docs/images/[^)\s]+)\)', readme)
        + re.findall(r'src="(docs/images/[^"]+)"', readme))
    self.assertTrue(embedded, 'README.md should embed docs/images/*')
    for rel in sorted(set(paths) | embedded):
      full = os.path.join(_REPO_ROOT, rel)
      self.assertTrue(os.path.isfile(full), full)
      self.assertGreater(os.path.getsize(full), 100, rel)
    for required in self._REQUIRED:
      self.assertIn(required, readme, required)
    images_dir = os.path.join(_REPO_ROOT, 'docs', 'images')
    on_disk = set()
    if os.path.isdir(images_dir):
      for filename in os.listdir(images_dir):
        if filename.endswith('.png'):
          on_disk.add('docs/images/' + filename)
    self.assertEqual(
        on_disk, embedded,
        'docs/images PNG files must match README embeds (orphans or missing)')
    self.assertIn('PYSEC-2026-113', readme)
    self.assertIn('RespondentID', readme)
    self.assertIn('Known limitations', readme)
    self.assertIn('DISABLE_BASIC_AUTH', readme)
    capture = os.path.join(_REPO_ROOT, 'tools', 'capture_screenshots.py')
    self.assertTrue(os.path.isfile(capture), capture)
    capture_src = open(capture, encoding='utf-8').read()
    self.assertIn('def assert_home_chrome', capture_src)
    self.assertIn('assert_home_chrome(page)', capture_src)
    self.assertIn('select#filter-status', capture_src)
    self.assertIn('select#filter-result', capture_src)
    self.assertIn('#filter-include-test', capture_src)
    self.assertIn('.container-fluid', capture_src)
    self.assertIn('th.cell-result', capture_src)
    self.assertIn('th.cell-progress', capture_src)
    self.assertIn('home.png', capture_src)
    self.assertIn('home-filters.png', capture_src)
    agents = open(
        os.path.join(_REPO_ROOT, 'AGENTS.md'), encoding='utf-8').read()
    self.assertIn('README.md', agents)
    self.assertIn('same commit', agents)
