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
import unittest
import zipfile
from io import BytesIO
from unittest import mock

import ad_macros
import main
import survey_service


class AdMacroPresetTest(unittest.TestCase):

  def test_default_is_cm360(self):
    spec = ad_macros.preset({})
    self.assertEqual(spec['id'], 'cm360')
    self.assertEqual(spec['click_tag'], '%c')
    self.assertEqual(spec['placement'], '%epid!')
    self.assertFalse(spec['overwrite_click_tag'])

  def test_dv360_and_gam_presets(self):
    self.assertEqual(ad_macros.preset({'ad_server': 'dv360'})['click_tag'],
                     '${CLICK_URL}')
    self.assertEqual(ad_macros.preset({'ad_server': 'gam'})['cachebuster'],
                     '%%CACHEBUSTER%%')
    self.assertTrue(ad_macros.preset({'ad_server': 'generic'})['overwrite_click_tag'])

  def test_unknown_ad_server_falls_back_to_cm360(self):
    self.assertEqual(ad_macros.normalize_ad_server('nope'), 'cm360')

  def test_render_vars_include_survey_fallback_ids(self):
    vars_ = ad_macros.render_vars({
        'ad_server': 'cm360',
        'campaign_id': 'camp-1',
        'placement_id': 'plc-9',
    })
    self.assertEqual(vars_['click_tag'], '%c')
    self.assertEqual(vars_['survey_campaign_id'], 'camp-1')
    self.assertEqual(vars_['survey_placement_id'], 'plc-9')
    self.assertIn('%u', vars_['ad_user_id_candidates'])


class TagSheetTest(unittest.TestCase):

  def test_lift_survey_has_control_and_expose_rows(self):
    when = datetime.datetime(2026, 11, 20)
    rows = ad_macros.tag_sheet_rows('sid', {
        'surveyname': 'cola-lift',
        'surveytype': 'brand_lift',
        'creativesizes': ['300x250', '160x600'],
        'campaign_id': 'camp-1',
        'placement_id': 'plc-9',
        'ad_server': 'cm360',
    }, when=when)
    self.assertEqual(len(rows), 4)
    segs = sorted(set(row['segment'] for row in rows))
    self.assertEqual(segs, ['default_control', 'default_expose'])
    self.assertTrue(all(row['inner_zip'].endswith('.zip') for row in rows))
    self.assertTrue(all(row['campaign_id'] == 'camp-1' for row in rows))
    self.assertIn('%c', rows[0]['click_tag'])

  def test_csv_and_xlsx_round_trip(self):
    headers, rows = ad_macros.tag_sheet_matrix('sid', {
        'surveyname': 'track',
        'surveytype': 'brand_track',
        'creativesizes': ['300x250'],
    }, when=datetime.datetime(2026, 11, 20))
    csv_data = ad_macros.csv_bytes(headers, rows).decode('utf-8-sig')
    self.assertIn('inner_zip', csv_data)
    self.assertIn('300x250', csv_data)
    xlsx = ad_macros.xlsx_bytes(headers, rows)
    with zipfile.ZipFile(BytesIO(xlsx)) as zf:
      self.assertIn('xl/worksheets/sheet1.xml', zf.namelist())
      sheet = zf.read('xl/worksheets/sheet1.xml').decode('utf-8')
      self.assertIn('300x250', sheet)
      self.assertIn('trafficking_notes', sheet)


class TagSheetRouteTest(unittest.TestCase):

  def setUp(self):
    self.client = main.app.test_client()
    main.app.config['TESTING'] = True
    main.app.config['AUTH_BYPASS'] = True

  def test_download_tags_csv(self):
    doc = mock.Mock()
    doc.exists = True
    doc.to_dict.return_value = {
        'surveyname': 'cola',
        'surveytype': 'brand_track',
        'creativesizes': ['300x250'],
        'ad_server': 'cm360',
    }
    with mock.patch.object(survey_service, 'get_doc_by_id', return_value=doc):
      response = self.client.get('/survey/download_tags/sid-1')
    self.assertEqual(response.status_code, 200)
    self.assertIn('text/csv', response.content_type)
    self.assertIn(b'inner_zip', response.data)
    self.assertIn(b'cm360', response.data)

  def test_download_tags_xlsx(self):
    doc = mock.Mock()
    doc.exists = True
    doc.to_dict.return_value = {
        'surveyname': 'cola',
        'surveytype': 'brand_lift',
        'creativesizes': ['300x250'],
    }
    with mock.patch.object(survey_service, 'get_doc_by_id', return_value=doc):
      response = self.client.get('/survey/download_tags/sid-1?format=xlsx')
    self.assertEqual(response.status_code, 200)
    self.assertIn(
        'spreadsheetml', response.content_type)
    self.assertTrue(response.data.startswith(b'PK'))
