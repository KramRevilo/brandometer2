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
"""Merge and verify BigQuery dataset access[] from `bq show` JSON.

`bq show --format=prettyjson` can prefix stdout with Python warnings
(RequestsDependencyWarning). Strip everything before the first '{' and
parse with raw_decode so trailing junk is ignored.
"""
import json
import sys


def extract_json_object(text):
  start = text.find('{')
  if start < 0:
    raise ValueError('no JSON object in bq show output')
  data, _end = json.JSONDecoder().raw_decode(text[start:])
  return data


def load_dataset_json(path):
  return extract_json_object(open(path, encoding='utf-8').read())


def _entry_emails(entry, email):
  return (
      entry.get('userByEmail') == email
      or entry.get('iamMember') in (
          'serviceAccount:' + email, 'user:' + email, email)
  )


def _is_writer_role(role):
  role = role or ''
  return (
      'dataEditor' in role
      or 'dataOwner' in role
      or role in ('WRITER', 'OWNER'))


def writer_role(data, email):
  for entry in data.get('access') or []:
    if not _entry_emails(entry, email):
      continue
    role = entry.get('role') or ''
    if _is_writer_role(role):
      return role
  return None


def ensure_writer(data, email):
  access = data.setdefault('access', [])
  existing = writer_role(data, email)
  if existing:
    return data, False
  access.append({'role': 'WRITER', 'userByEmail': email})
  return data, True


def dump_dataset_json(path, data):
  with open(path, 'w', encoding='utf-8') as fh:
    json.dump(data, fh, indent=2)
    fh.write('\n')


def main(argv):
  if len(argv) < 4:
    sys.stderr.write(
        'Usage: bq_dataset_iam.py merge|verify path email\n')
    return 2
  cmd, path, email = argv[1], argv[2], argv[3]
  try:
    data = load_dataset_json(path)
  except (OSError, ValueError, json.JSONDecodeError) as exc:
    sys.stderr.write('Failed to parse bq dataset JSON %s: %s\n' % (path, exc))
    return 1
  if cmd == 'merge':
    data, changed = ensure_writer(data, email)
    dump_dataset_json(path, data)
    return 2 if changed else 0
  if cmd == 'verify':
    role = writer_role(data, email)
    if not role:
      return 1
    sys.stdout.write('%s\n' % role)
    return 0
  sys.stderr.write('Unknown command %s\n' % cmd)
  return 2


if __name__ == '__main__':
  sys.exit(main(sys.argv))
