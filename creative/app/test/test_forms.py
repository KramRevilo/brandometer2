# Copyright 2019 Google LLC
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
from flask import Flask
import forms

COMPLETE_QUESTION1 = {
    'question1': 'question',
    'answer1a': 'answerA',
    'answer1b': 'answerB',
    'answer1c': 'answerC',
    'answer1d': 'answerD',
    'answer1anext': '2',
    'answer1bnext': '2',
    'answer1cnext': '2',
    'answer1dnext': '2'
}
class QuestionFormTest(unittest.TestCase):
    def create_form(self, data):
        app = Flask(__name__)
        with app.app_context():
            app.config['WTF_CSRF_ENABLED'] = False
            return forms.QuestionForm(data=data)

    def test_question_section_is_empty_when_question_has_2_or_more_answers(self):
        cases = [COMPLETE_QUESTION1,
            dict(COMPLETE_QUESTION1, answer1d=None, answer1dnext=None),
            dict(COMPLETE_QUESTION1, answer1c=None, answer1cnext=None,
                answer1d=None, answer1dnext=None),
        ]
 
        for valid_question in cases:
            valid_form = self.create_form(valid_question)
            test_valid = forms.question_section_is_empty(valid_form, '1')
            self.assertFalse(test_valid)

    def test_question_section_is_empty_when_question_is_invalid(self):
        invalid_question_cases = [dict(COMPLETE_QUESTION1, question1=None),
            dict(COMPLETE_QUESTION1, answer1a=None),
            dict(COMPLETE_QUESTION1, answer1b=None),
            dict(COMPLETE_QUESTION1, answer1anext=None),
            dict(COMPLETE_QUESTION1, answer1bnext=None),
        ]

        for invalid_question in invalid_question_cases:
            invalid_form = self.create_form(invalid_question)
            test_invalid = forms.question_section_is_empty(invalid_form, '1')
            self.assertTrue(test_invalid)

    def test_two_answers_is_enough_and_fifth_is_optional(self):
        two = dict(COMPLETE_QUESTION1, answer1c=None, answer1cnext=None,
                   answer1d=None, answer1dnext=None)
        self.assertFalse(forms.question_section_is_empty(self.create_form(two), '1'))
        with_e = dict(COMPLETE_QUESTION1, answer1e='answerE', answer1enext='end')
        form = self.create_form(with_e)
        self.assertEqual(form.answer1e.data, 'answerE')
        self.assertFalse(forms.question_section_is_empty(form, '1'))

    def test_client_agency_and_ids_are_optional(self):
        form = self.create_form({
            'client': 'Acme',
            'agency': 'OMD',
            'campaign_id': '123',
            'placement_id': '456',
            'ad_server': 'dv360',
        })
        self.assertEqual(form.client.data, 'Acme')
        self.assertEqual(form.agency.data, 'OMD')
        self.assertEqual(form.campaign_id.data, '123')
        self.assertEqual(form.placement_id.data, '456')
        self.assertEqual(form.ad_server.data, 'dv360')
        empty = self.create_form({})
        self.assertFalse(empty.client.data)
        self.assertFalse(empty.agency.data)

    def test_creativesize_defaults_to_300x250(self):
        form = self.create_form({})
        self.assertEqual(form.creativesize.data, ['300x250'])
        values = [
            c[0] if isinstance(c, (list, tuple)) else c
            for c in form.creativesize.choices
        ]
        self.assertEqual(
            values, ['300x250', '160x600', '300x600', '336x280', '970x250'])

    def test_badge_defaults_and_text_length(self):
        form = self.create_form({})
        self.assertEqual(form.badge_icon.data, 'B')
        self.assertFalse(form.badge_text.data)
        ok, valid = self._validate(self._valid_survey(badge_icon='Ad', badge_text='Hi'))
        self.assertTrue(ok, valid.errors)
        too_long = 'x' * 121
        ok, long_form = self._validate(self._valid_survey(badge_text=too_long))
        self.assertFalse(ok)
        self.assertTrue(long_form.badge_text.errors)

    def test_creativesize_coerces_legacy_string(self):
        form = self.create_form({'creativesize': '160x600'})
        self.assertEqual(form.creativesize.data, ['160x600'])

    def test_answers_beyond_e_rejected_on_standard_size(self):
        data = self._valid_survey(answer1f='Too many')
        ok, form = self._validate(data)
        self.assertFalse(ok)
        self.assertTrue(form.creativesize.errors)

    def test_eight_answers_allowed_on_tall_sizes_only(self):
        data = self._valid_survey(
            creativesize=['160x600', '300x600'],
            answer1c='C', answer1d='D', answer1e='E',
            answer1f='F', answer1g='G', answer1h='H',
            answer1cnext='end', answer1dnext='end', answer1enext='end',
            answer1fnext='end', answer1gnext='end', answer1hnext='end')
        ok, form = self._validate(data)
        self.assertTrue(ok, form.errors)

    def _validate(self, data):
        app = Flask(__name__)
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['SECRET_KEY'] = 'test'
        with app.app_context():
            form = forms.QuestionForm(data=data)
            return form.validate(), form

    def _valid_survey(self, **overrides):
        data = {
            'surveyname': 'Survey',
            'surveytype': forms.BRAND_TRACK,
            'responsetype': forms.RESPONSES_AT_END,
            'language': 'en',
            'creativesize': '300x250',
            'question1': 'Question 1',
            'question1type': 'SINGLE_OPTION',
            'question1order': forms.ANSWERS_SHUFFLED,
            'answer1a': 'A',
            'answer1b': 'B',
            'answer1anext': 'end',
            'answer1bnext': 'end',
            'question2': 'Question 2',
            'question2type': 'SINGLE_OPTION',
            'question2order': forms.ANSWERS_SHUFFLED,
            'answer2a': 'A2',
            'answer2b': 'B2',
            'answer2anext': 'end',
            'answer2bnext': 'end',
            'question3type': 'SINGLE_OPTION',
            'question3order': forms.ANSWERS_SHUFFLED,
            'question4type': 'SINGLE_OPTION',
            'question4order': forms.ANSWERS_SHUFFLED,
            'question5type': 'SINGLE_OPTION',
            'question5order': forms.ANSWERS_SHUFFLED,
        }
        data.update(overrides)
        return data

    def test_next_choices_only_later_filled_questions(self):
        form = self.create_form({
            'question1': 'Q1',
            'question3': 'Q3',
            'question4': '',
        })
        values = [item[0] for item in forms.next_choices(form, 1, 'end')]
        self.assertEqual(values, ['end', '3'])
        invalid = forms.next_choices(form, 1, '2')
        self.assertIn(('2', 'Invalid (2)'), invalid)
        from_q3 = [item[0] for item in forms.next_choices(form, 3, 'end')]
        self.assertEqual(from_q3, ['end'])

    def test_next_end_and_later_question_are_valid(self):
        ok, form = self._validate(self._valid_survey())
        self.assertTrue(ok, form.errors)
        ok, form = self._validate(self._valid_survey(answer1anext='2'))
        self.assertTrue(ok, form.errors)

    def test_next_rejects_empty_later_question(self):
        ok, form = self._validate(self._valid_survey(
            question2='', answer2a='', answer2b='', answer1anext='2'))
        self.assertFalse(ok)
        self.assertTrue(form.answer1anext.errors)

    def test_next_rejects_earlier_and_same_question(self):
        ok, form = self._validate(self._valid_survey(answer2anext='1'))
        self.assertFalse(ok)
        self.assertTrue(form.answer2anext.errors)
        ok, form = self._validate(self._valid_survey(answer1anext='1'))
        self.assertFalse(ok)
        self.assertTrue(form.answer1anext.errors)

    def test_next_rejects_uppercase_end_and_junk(self):
        ok, form = self._validate(self._valid_survey(answer1anext='End'))
        self.assertFalse(ok)
        self.assertTrue(form.answer1anext.errors)
        ok, form = self._validate(self._valid_survey(answer1anext='later'))
        self.assertFalse(ok)
        self.assertTrue(form.answer1anext.errors)

    def test_next_skips_empty_answer_rows(self):
        ok, form = self._validate(self._valid_survey(answer1cnext='1'))
        self.assertTrue(ok, form.errors)

    def test_language_dropdown_matches_translation_dicts(self):
        form = self.create_form({})
        choice_values = [
            c[0] if isinstance(c, (list, tuple)) else c
            for c in form.language.choices
        ]
        for code in (
            'en', 'es', 'fr', 'ms', 'zh', 'ja', 'ko', 'de', 'it', 'pt', 'th',
            'ar', 'hi', 'id', 'nl', 'pl', 'ru', 'sv', 'tr', 'vi'):
            self.assertIn(code, choice_values)

