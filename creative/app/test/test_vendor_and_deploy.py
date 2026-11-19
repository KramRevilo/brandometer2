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

import os
import subprocess
import tempfile
import textwrap
import unittest


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
    self.assertIn('brandometer-receiver', script)
    self.assertIn('--max-instances=20', script)
    self.assertIn('--timeout=60s', script)
    self.assertIn('--memory=256MB', script)
    self.assertIn('upsert_secret', script)
    self.assertIn('ensure_generated_secret', script)
    self.assertIn("read -p 'OAuth client ID: '", script)
    self.assertIn("read -sp 'OAuth client secret: '", script)
    self.assertIn("read -p 'Bootstrap admin email: '", script)
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
    self.assertIn('secret_environment_variables', yaml_text)
    self.assertIn('secure: always', yaml_text)
    self.assertIn('brandometer-secret-key', yaml_text)
    self.assertIn('brandometer-oauth-client-id', yaml_text)
    self.assertIn('brandometer-receiver-hmac', yaml_text)
    self.assertIn('BOOTSTRAP_ADMIN_EMAIL', yaml_text)
    self.assertNotIn('AUTH_USERNAME', yaml_text)
    self.assertNotIn('AUTH_PASSWORD', yaml_text)

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
    self.assertGreaterEqual(script.count('--condition=None'), 3)
    self.assertIn('Keeping existing secret', script)
    self.assertIn('DEPLOY_RETRY_MAX_SECONDS', script)
    self.assertNotIn('mk --force', script)
    self.assertNotRegex(script, r'bq --location=\$LOCATION mk\s+\\\s+--force')
    self.assertIn(
        'bq show --format=none "$PROJECT_ID:responses"', script)
    self.assertIn(
        'bq show --format=none "$PROJECT_ID:responses.responses"', script)

  def test_retry_gcloud_succeeds_after_failures_and_times_out(self):
    script = open(os.path.join(_REPO_ROOT, 'deploy'), encoding='utf-8').read()
    start = script.index('retry_gcloud() {')
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
          flaky() { n=$((n+1)); [ "$n" -ge 3 ]; }
          retry_gcloud flaky
          always_fail() { return 1; }
          if retry_gcloud always_fail; then
            echo unexpectedly_ok
            exit 1
          fi
          echo ok
      '''))
      out = subprocess.check_output(['sh', helper], stderr=subprocess.STDOUT, text=True)
    self.assertIn('ok', out.splitlines()[-1])
    self.assertIn('Retrying in', out)

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
    self.assertIn('pytest==9.0.3', reqs)
    self.assertIn('pyarrow==', reqs)
