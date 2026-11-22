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
"""Reject App Engine flexible-only keys before `gcloud app deploy`."""
import sys

# AppInfoExternal (standard python312). secret_environment_variables is not valid.
ALLOWED_TOP_LEVEL = frozenset({
    'runtime',
    'instance_class',
    'env_variables',
    'handlers',
    'service',
    'automatic_scaling',
    'basic_scaling',
    'manual_scaling',
    'inbound_services',
    'vpc_access_connector',
    'entrypoint',
    'app_engine_apis',
    'build_env_variables',
    'includes',
    'error_handlers',
    'default_expiration',
    'service_account',
})

FORBIDDEN_TOP_LEVEL = frozenset({
    'secret_environment_variables',
    'resources',
    'liveness_check',
    'readiness_check',
    'beta_settings',
    'network',
    'vpc_egress',
    'runtime_config',
})

ALLOWED_ENV = frozenset({
    'RECEIVER_URL',
    'PROJECT_ID',
    'TABLE_ID',
    'GTAG_ID',
    'BOOTSTRAP_ADMIN_EMAIL',
    'LOOKER_TEMPLATE_REPORT_ID',
    'LOOKER_TEMPLATE_DS_ALIAS',
})

FORBIDDEN_ENV = frozenset({
    'GOOGLE_OAUTH_CLIENT_ID',
    'GOOGLE_OAUTH_CLIENT_SECRET',
    'SECRET_KEY',
    'RECEIVER_HMAC_SECRET',
    'IP_HMAC_SECRET',
    'AUTH_PASSWORD',
    'AUTH_USERNAME',
    'DISABLE_BASIC_AUTH',
})


def top_level_keys(text):
  keys = []
  for raw in text.splitlines():
    line = raw.rstrip()
    if not line.strip() or line.lstrip().startswith('#'):
      continue
    if line[:1] in (' ', '\t', '-'):
      continue
    if ':' not in line:
      continue
    keys.append(line.split(':', 1)[0].strip())
  return keys


def env_var_keys(text):
  keys = []
  in_env = False
  for raw in text.splitlines():
    line = raw.rstrip()
    stripped = line.strip()
    if not stripped or stripped.startswith('#'):
      continue
    if line[:1] not in (' ', '\t') and not line.startswith('-'):
      in_env = stripped.startswith('env_variables:')
      continue
    if not in_env or ':' not in stripped:
      continue
    keys.append(stripped.split(':', 1)[0].strip())
  return keys


def validate_app_yaml(text):
  errors = []
  for key in top_level_keys(text):
    if key in FORBIDDEN_TOP_LEVEL or key not in ALLOWED_TOP_LEVEL:
      errors.append('Unsupported app.yaml key for App Engine standard: %s' % key)
  for key in env_var_keys(text):
    if key in FORBIDDEN_ENV:
      errors.append('Secret or forbidden env_variables entry: %s' % key)
    elif key not in ALLOWED_ENV:
      errors.append('Unexpected env_variables entry: %s' % key)
  if 'runtime: python312' not in text:
    errors.append('runtime must be python312')
  return errors


def main(argv):
  if len(argv) < 2:
    sys.stderr.write('Usage: app_yaml_check.py path/to/app.yaml\n')
    return 2
  path = argv[1]
  text = open(path, encoding='utf-8').read()
  errors = validate_app_yaml(text)
  if errors:
    sys.stderr.write('Invalid App Engine yaml %s:\n' % path)
    for item in errors:
      sys.stderr.write('  %s\n' % item)
    return 1
  return 0


if __name__ == '__main__':
  sys.exit(main(sys.argv))
