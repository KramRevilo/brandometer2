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
"""Product brand for the admin UI and the creative disclosure badge."""
import os

DEFAULT_BRAND_NAME = 'Brandometer'


def brand_name():
  value = (os.environ.get('APP_BRAND_NAME') or DEFAULT_BRAND_NAME).strip()
  return value or DEFAULT_BRAND_NAME


def badge_letter():
  override = (os.environ.get('APP_BRAND_BADGE_LETTER') or '').strip()
  if override:
    return override[0].upper()
  name = brand_name()
  return name[0].upper() if name else 'B'


def badge_tooltip():
  override = (os.environ.get('APP_BRAND_BADGE_TOOLTIP') or '').strip()
  if override:
    return override
  return 'Survey Type %s Ad - powered by Google' % brand_name()
