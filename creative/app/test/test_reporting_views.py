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
import sys
import unittest
from urllib.parse import unquote_plus

import reporting_views
import respondent


class ReportingViewsTest(unittest.TestCase):

  def test_deduped_sql_uses_source_table_and_session_key(self):
    sql = reporting_views.deduped_view_sql('proj-1')
    self.assertIn('CREATE OR REPLACE VIEW `proj-1.brandometer_reporting.deduped_responses`', sql)
    self.assertIn('FROM `proj-1.responses.responses`', sql)
    self.assertIn(respondent.SESSION_KEY_SQL, sql)
    self.assertIn('PARTITION BY survey_id, respondent_key', sql)
    self.assertIn('ORDER BY n_answers DESC, CreatedAt DESC', sql)
    self.assertIn('RespondentID', sql)
    self.assertIn('PlacementID', sql)
    self.assertIn('CreativeSize', sql)
    self.assertIn('CreativeVersion', sql)
    self.assertIn('Type', sql)
    self.assertIn("IFNULL(Type, 'survey') != 'test'", sql)
    self.assertNotIn('RandomTimeStamp', sql)
    self.assertNotIn('HashedIP', sql)

  def test_summary_sql_groups_deduped_view(self):
    sql = reporting_views.summary_view_sql('proj-1')
    self.assertIn(
        'CREATE OR REPLACE VIEW `proj-1.brandometer_reporting.survey_summaries`',
        sql)
    self.assertIn('FROM `proj-1.brandometer_reporting.deduped_responses`', sql)
    self.assertIn('GROUP BY survey_id, Type, Segmentation', sql)
    self.assertIn('Type', sql)
    self.assertIn('COUNT(*) AS respondents', sql)
    self.assertIn('last_creative_version', sql)

  def test_data_studio_url(self):
    self.assertEqual(reporting_views.data_studio_url(''), '')
    url = reporting_views.data_studio_url('proj-1', environ={})
    self.assertTrue(url.startswith('https://datastudio.google.com/reporting/create?'))
    self.assertIn('ds.connector=bigQuery', url)
    self.assertIn('ds.projectId=proj-1', url)
    self.assertIn('ds.datasetId=brandometer_reporting', url)
    self.assertIn('ds.tableId=deduped_responses', url)
    self.assertIn('ds.type=TABLE', url)
    self.assertNotIn('ds.ds0.', url)
    self.assertNotIn('c.reportId=', url)

  def test_data_studio_url_filters_survey_with_custom_query(self):
    url = reporting_views.data_studio_url(
        'brandometer2', survey_id='demo_1_0003', environ={})
    self.assertIn('ds.type=CUSTOM_QUERY', url)
    self.assertIn('survey_id', url)
    self.assertIn('demo_1_0003', url)
    self.assertIn('deduped_responses', url)
    self.assertIn('ds.billingProjectId=brandometer2', url)
    self.assertNotIn('ds.ds0.', url)
    self.assertNotIn('ds.tableId=', url)
    bad = reporting_views.data_studio_url(
        'brandometer2', survey_id="abc'; DROP TABLE x", environ={})
    self.assertIn('ds.type=TABLE', bad)
    self.assertNotIn('DROP TABLE', bad)

  def test_data_studio_url_in_clause_capped(self):
    ids = ['s%s' % i for i in range(35)]
    url = reporting_views.data_studio_url(
        'proj-1', survey_ids=ids, environ={})
    decoded = unquote_plus(url)
    self.assertIn('survey_id IN (', decoded)
    self.assertIn("'s0'", decoded)
    self.assertIn("'s29'", decoded)
    self.assertNotIn("'s30'", decoded)
    self.assertNotIn("'s34'", decoded)

  def test_data_studio_url_uses_template_alias_when_configured(self):
    url = reporting_views.data_studio_url(
        'proj-1',
        survey_id='s1',
        environ={
            'DATA_STUDIO_TEMPLATE_REPORT_ID': 'tmpl-abc',
            'DATA_STUDIO_TEMPLATE_DS_ALIAS': 'ds0',
        })
    self.assertIn('c.reportId=tmpl-abc', url)
    self.assertIn('ds.ds0.connector=bigQuery', url)
    self.assertIn('ds.ds0.type=CUSTOM_QUERY', url)
    self.assertIn('ds.ds0.sql=', url)
    unnamed = reporting_views.data_studio_url(
        'proj-1',
        environ={'DATA_STUDIO_TEMPLATE_REPORT_ID': 'tmpl-abc'})
    self.assertIn('c.reportId=tmpl-abc', unnamed)
    self.assertIn('ds.connector=bigQuery', unnamed)
    self.assertNotIn('ds.ds0.', unnamed)

  def test_cli_sql_and_datastudio(self):
    helper = os.path.join(os.path.dirname(__file__), '..', 'reporting_views.py')
    sql = subprocess.check_output(
        [sys.executable, helper, 'deduped', 'p'], text=True)
    self.assertIn('CREATE OR REPLACE VIEW `p.brandometer_reporting.deduped_responses`', sql)
    self.assertTrue(sql.strip().endswith(';'))
    studio = subprocess.check_output(
        [sys.executable, helper, 'datastudio', 'p'], text=True).strip()
    self.assertIn('datastudio.google.com', studio)
    self.assertIn('ds.connector=bigQuery', studio)
    self.assertNotIn('ds.ds0.', studio)
    filtered = subprocess.check_output(
        [sys.executable, helper, 'datastudio', 'p', 'demo_1_0003'], text=True).strip()
    self.assertIn('CUSTOM_QUERY', filtered)
    self.assertIn('demo_1_0003', filtered)
    multi = subprocess.check_output(
        [sys.executable, helper, 'datastudio', 'p', 'a', 'b'], text=True).strip()
    self.assertIn('IN', multi)
    self.assertEqual(subprocess.call(
        [sys.executable, helper, 'nope', 'p'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL), 2)
