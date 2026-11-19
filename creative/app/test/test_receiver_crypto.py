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
import hashlib
import unittest

import receiver_crypto


class ReceiverCryptoTest(unittest.TestCase):

  def test_survey_token_is_hex_hmac(self):
    token = receiver_crypto.survey_token('sid-1', 'master')
    self.assertEqual(len(token), 64)
    self.assertTrue(receiver_crypto.token_is_valid('sid-1', token, 'master'))
    self.assertFalse(receiver_crypto.token_is_valid('sid-1', token, 'other'))
    self.assertFalse(receiver_crypto.token_is_valid('sid-2', token, 'master'))
    self.assertFalse(receiver_crypto.token_is_valid('sid-1', '', 'master'))
    self.assertEqual(receiver_crypto.survey_token('', 'master'), '')
    self.assertEqual(receiver_crypto.survey_token('sid-1', ''), '')

  def test_hash_ip_is_stable_same_utc_day_and_rotates(self):
    secret = 'ip-master'
    day1 = datetime.datetime(2026, 11, 19, 1, tzinfo=datetime.timezone.utc)
    day1_later = datetime.datetime(2026, 11, 19, 23, tzinfo=datetime.timezone.utc)
    day2 = datetime.datetime(2026, 11, 20, 1, tzinfo=datetime.timezone.utc)
    first = receiver_crypto.hash_ip('203.0.113.9', secret, when=day1)
    same_day = receiver_crypto.hash_ip('203.0.113.9', secret, when=day1_later)
    next_day = receiver_crypto.hash_ip('203.0.113.9', secret, when=day2)
    other_ip = receiver_crypto.hash_ip('203.0.113.10', secret, when=day1)
    self.assertEqual(first, same_day)
    self.assertNotEqual(first, next_day)
    self.assertNotEqual(first, other_ip)
    self.assertNotEqual(first, hashlib.sha256(b'203.0.113.9').hexdigest())
    self.assertEqual(receiver_crypto.hash_ip('203.0.113.9', ''), '')
    self.assertEqual(len(first), 64)
