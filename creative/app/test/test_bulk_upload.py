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

import bulk_upload
import main
import survey_service


class BulkUploadFilesTest(unittest.TestCase):

  def test_lift_survey_has_one_row_per_inner_zip(self):
    survey = {
        'surveyname': 'cola-lift',
        'surveytype': 'brand_lift',
        'creativesizes': ['300x250', '160x600'],
        'campaign_id': 'camp-1',
        'ad_server': 'cm360',
        'exit_url': 'https://example.com/land',
    }
    files = dict(bulk_upload.sidecar_files(
        'sid', survey, when=datetime.datetime(2026, 11, 20),
        creative_version=4))
    self.assertIn(bulk_upload.README_NAME, files)
    readme = files[bulk_upload.README_NAME].decode('utf-8')
    self.assertIn('does not call', readme)
    self.assertIn('OAuth', readme)
    self.assertNotIn('client_secret', readme.lower())

    cm = files[bulk_upload.CM360_CSV_NAME].decode('utf-8-sig')
    self.assertIn('Display HTML5', cm)
    self.assertIn('camp-1', cm)
    self.assertIn('300,250', cm)
    self.assertIn('160,600', cm)
    self.assertIn('https://example.com/land', cm)
    self.assertIn('default_control', cm)
    self.assertIn('default_expose', cm)
    self.assertEqual(cm.count('\n'), 5)  # header + 4 rows
    first_data = cm.splitlines()[1]
    # Advertiser ID is the first column and must stay blank.
    self.assertTrue(first_data.startswith(','))

    dv = files[bulk_upload.DV360_CSV_NAME].decode('utf-8-sig')
    self.assertIn('HTML5', dv)
    self.assertIn('cola-lift_300x250_default_control', dv)
    self.assertIn('ver=', readme)

  def test_download_zip_contains_only_sidecars(self):
    name, payload = bulk_upload.download_zip('sid', {
        'surveyname': 'track',
        'surveytype': 'brand_track',
        'creativesizes': ['300x250'],
    }, when=datetime.datetime(2026, 11, 20))
    self.assertEqual(name, 'track_bulk_upload.zip')
    with zipfile.ZipFile(BytesIO(payload)) as zf:
      names = set(zf.namelist())
    self.assertEqual(names, {
        bulk_upload.README_NAME,
        bulk_upload.CM360_CSV_NAME,
        bulk_upload.DV360_CSV_NAME,
    })

  @mock.patch.object(survey_service.survey_collection, 'add_version')
  @mock.patch.object(survey_service, 'get_html_template', return_value='<html></html>')
  def test_outer_zip_embeds_bulk_files(self, _html, version_mock):
    version_mock.return_value = {'version': 2}
    _filename, data = survey_service.zip_file('sid', {
        'surveyname': 'pack',
        'surveytype': 'brand_lift',
        'creativesize': '300x250',
    })
    names = zipfile.ZipFile(data).namelist()
    self.assertIn(bulk_upload.CM360_CSV_NAME, names)
    self.assertIn(bulk_upload.DV360_CSV_NAME, names)
    self.assertIn(bulk_upload.README_NAME, names)
    self.assertIn('html5_qa.txt', names)
    zips = [n for n in names if n.endswith('.zip')]
    self.assertEqual(len(zips), 2)


class BulkUploadRouteTest(unittest.TestCase):

  def setUp(self):
    self.client = main.app.test_client()
    main.app.config['TESTING'] = True
    main.app.config['AUTH_BYPASS'] = True

  def test_download_bulk_upload_zip(self):
    doc = mock.Mock()
    doc.exists = True
    doc.to_dict.return_value = {
        'surveyname': 'cola',
        'surveytype': 'brand_track',
        'creativesizes': ['300x250'],
        'ad_server': 'dv360',
    }
    with mock.patch.object(survey_service, 'get_doc_by_id', return_value=doc):
      response = self.client.get('/survey/download_bulk_upload/sid-1')
    self.assertEqual(response.status_code, 200)
    self.assertIn('zip', response.content_type)
    with zipfile.ZipFile(BytesIO(response.data)) as zf:
      names = zf.namelist()
    self.assertIn(bulk_upload.CM360_CSV_NAME, names)
    body = zipfile.ZipFile(BytesIO(response.data)).read(
        bulk_upload.CM360_CSV_NAME).decode('utf-8-sig')
    self.assertIn('Display HTML5', body)
    self.assertTrue(body.splitlines()[1].startswith(','))
