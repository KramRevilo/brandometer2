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

import datetime
import json
import os
import unittest

import pandas
import reporting
import respondent


_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))


class SessionKeyTest(unittest.TestCase):

  def test_prefers_respondent_id_over_bomid(self):
    df = pandas.DataFrame({
        'RespondentID': ['r1', 'r1', ''],
        'BomID': ['b1', 'b2', 'b3'],
    })
    keys = list(respondent.session_keys(df))
    self.assertEqual(keys, ['r1', 'r1', 'b3'])

  def test_blank_ids_become_row_index(self):
    df = pandas.DataFrame({
        'BomID': ['', None],
    })
    keys = list(respondent.session_keys(df))
    self.assertEqual(keys[0][:4], 'row:')
    self.assertEqual(keys[1][:4], 'row:')
    self.assertNotEqual(keys[0], keys[1])

  def test_sql_fragment_uses_coalesce_order(self):
    sql = respondent.SESSION_KEY_SQL
    self.assertIn('RespondentID', sql)
    self.assertIn('BomID', sql)
    self.assertLess(sql.find('RespondentID'), sql.find('BomID'))


class ConsolidateRespondentTest(unittest.TestCase):

  def test_same_respondent_id_collapses_across_bomids(self):
    t1 = datetime.datetime(2026, 11, 1, 10, 0, 0)
    t2 = datetime.datetime(2026, 11, 1, 11, 0, 0)
    df = pandas.DataFrame({
        'CreatedAt': [t1, t2],
        'Segmentation': ['default_expose', 'default_expose'],
        'Response': ['1:A', '1:A|2:B'],
        'BomID': ['imp-1', 'imp-2'],
        'RespondentID': ['person-a', 'person-a'],
    })
    out = reporting.consolidate_frame(df)
    self.assertEqual(len(out), 1)
    self.assertEqual(out.iloc[0]['Response'], '1:A|2:B')
    self.assertEqual(out.iloc[0]['RespondentID'], 'person-a')

  def test_legacy_bomid_only_rows_still_dedupe(self):
    t1 = datetime.datetime(2026, 11, 1, 10, 0, 0)
    t2 = datetime.datetime(2026, 11, 1, 11, 0, 0)
    df = pandas.DataFrame({
        'CreatedAt': [t1, t2],
        'Segmentation': ['seg', 'seg'],
        'Response': ['1:A', '1:A|2:B'],
        'BomID': ['legacy', 'legacy'],
    })
    out = reporting.consolidate_frame(df)
    self.assertEqual(len(out), 1)
    self.assertEqual(out.iloc[0]['Response'], '1:A|2:B')


class SchemaRespondentColumnsTest(unittest.TestCase):

  def test_schema_adds_nullable_respondent_columns(self):
    path = os.path.join(_REPO_ROOT, 'receiver', 'responses.schema.json')
    schema = json.loads(open(path, encoding='utf-8').read())
    by_name = {col['name']: col for col in schema}
    self.assertEqual(by_name['BomID']['mode'], 'REQUIRED')
    self.assertEqual(by_name['RespondentID']['mode'], 'NULLABLE')
    self.assertEqual(by_name['RespondentIDSource']['mode'], 'NULLABLE')
    required = [col['name'] for col in schema if col['mode'] == 'REQUIRED']
    self.assertEqual(required, [
        'CreatedAt', 'Type', 'ID', 'Segmentation', 'Response', 'Visual',
        'CreativeSize', 'RandomTimeStamp', 'BomID',
    ])
