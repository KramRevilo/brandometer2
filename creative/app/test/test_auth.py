# Copyright 2023 Google LLC
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

import unittest

import main


class AuthAndRedirectTest(unittest.TestCase):

  def tearDown(self):
    main.app.config['BASIC_AUTH_FORCE'] = True

  def test_root_redirect_is_relative_when_auth_disabled(self):
    main.app.config['BASIC_AUTH_FORCE'] = False
    client = main.app.test_client()
    response = client.get('/', follow_redirects=False)
    self.assertEqual(response.status_code, 302)
    self.assertEqual(response.headers['Location'], '/index')
    self.assertNotIn('://', response.headers['Location'])

  def test_root_requires_basic_auth_by_default(self):
    main.app.config['BASIC_AUTH_FORCE'] = True
    client = main.app.test_client()
    response = client.get('/', follow_redirects=False)
    self.assertEqual(response.status_code, 401)
