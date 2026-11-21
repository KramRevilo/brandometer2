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

import importlib.util
import os
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))


def _load_backfill():
  path = os.path.join(_ROOT, 'tools', 'backfill_created.py')
  spec = importlib.util.spec_from_file_location('backfill_created', path)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


class BackfillCreatedTest(unittest.TestCase):

  def setUp(self):
    self.mod = _load_backfill()

  def test_fills_only_missing_from_create_and_copy(self):
    surveys = {
        'old': {'surveyname': 'Old'},
        'partial': {'created_at': '2026-01-01T00:00:00Z'},
        'complete': {
            'created_at': '2026-02-01T00:00:00Z',
            'created_by': 'keep@agency.example',
        },
        'copied': {},
    }
    audits = [
        {
            'action': 'create', 'survey_id': 'old',
            'actor': 'mark@agency.example',
            'created_at': '2026-11-19T21:08:19Z',
        },
        {
            'action': 'create', 'survey_id': 'partial',
            'actor': 'sam@agency.example',
            'created_at': '2026-11-20T00:00:00Z',
        },
        {
            'action': 'create', 'survey_id': 'complete',
            'actor': 'other@agency.example',
            'created_at': '2025-01-01T00:00:00Z',
        },
        {
            'action': 'copy', 'survey_id': 'old',
            'detail': 'copied',
            'actor': 'editor@agency.example',
            'created_at': '2026-11-21T12:00:00Z',
        },
        {'action': 'edit', 'survey_id': 'old', 'actor': 'x', 'created_at': 'z'},
    ]
    patches = {item['survey_id']: item['patch']
               for item in self.mod.propose_patches(surveys, audits)}
    self.assertEqual(patches['old']['created_at'], '2026-11-19T21:08:19Z')
    self.assertEqual(patches['old']['created_by'], 'mark@agency.example')
    self.assertEqual(patches['partial'], {'created_by': 'sam@agency.example'})
    self.assertNotIn('complete', patches)
    self.assertEqual(patches['copied']['created_by'], 'editor@agency.example')
    self.assertEqual(patches['copied']['created_at'], '2026-11-21T12:00:00Z')
    self.assertEqual(surveys['complete']['created_by'], 'keep@agency.example')

  def test_skips_audit_for_unknown_survey_id(self):
    patches = self.mod.propose_patches(
        {'s1': {}},
        [{'action': 'create', 'survey_id': 'gone', 'actor': 'a',
          'created_at': '2026-01-01T00:00:00Z'}])
    self.assertEqual(patches, [])
