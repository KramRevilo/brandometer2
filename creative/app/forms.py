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
"""Description of QuestionForm: Generates a survey name field input and 5 questions and answers for customers to fill out.

It would capture the input of the customers and create a survey based on user
input.
"""
import re
from flask_wtf import FlaskForm
from wtforms import RadioField
from wtforms import SelectField
from wtforms import SelectMultipleField
from wtforms import StringField
from wtforms import SubmitField
from wtforms import TextAreaField
from wtforms.validators import DataRequired
from wtforms.validators import ValidationError
from wtforms.validators import Length
import brand
import creative_size

BRAND_TRACK = 'brand_track'
BRAND_LIFT = 'brand_lift'
ANSWERS_ORDERED = 'ORDERED'
ANSWERS_SHUFFLED = 'SHUFFLED'
RESPONSES_AT_END = "Submit Responses at End of Survey"
RESPONSES_IMMEDIATELY = "Submit Responses after each Question"
ANSWER_LETTERS = ('a', 'b', 'c', 'd', 'e', 'f', 'g', 'h')
MIN_ANSWERS = 2
MAX_ANSWERS = 8
NEXT_END = 'end'
_NEXT_FIELD_NAME = re.compile(r'^answer([1-5])([a-h])next$')

# this is the default stylesheet for the custom creative
DEFAULT_CSS = """
body {
    margin: 0;
    display: block;
}
/* The .invisible class is used for hiding the 'Thank You' message that
   is not shown until the end of the survey questions.
   It is probably best not to change this class.
*/
.invisible {
    display: none;
}

.master_container {
    border: 1px solid red;
}

/* The #master_container is the box containing all survey elements as a DIV.  
   It contains the survey_container, the thankyou_container, and the bottom
   container - all divs.
*/
#master_container {
    background-color:#008000;
    width: 300px;
    height: 250px;
    border: solid black 1px;
}

/* The #survey_container is the box (div) containing the question
   container and all option_container_[0-4] divs.
*/
#survey_container {
    padding: 7px;
    padding-bottom: 3px;
}

/* .Qbox is the CSS class for controlling the look of the question
   container, including the text of the question itself.
*/
.Qbox {
    font-family: 'Open Sans', sans-serif;
    font-size: 13px;
    padding: 2px 5px;
    height: 45px;
    width: 274px;
    border: 1px solid rgba(255, 255, 255, 0.290196);
    border-radius: 5px;
    color: white;
    text-shadow: rgba(0, 0, 0, 0.8) 1px 1px 1px;
    background-color: rgba(255, 255, 255, 0.14902);
    box-shadow: rgba(0, 0, 0, 0.8) 0px 0px 3px 0px;
    display: table;
    user-select: none;
    -webkit-user-select: none;
}

.Qbox span {
    display: table-cell;
    vertical-align: middle;
}

/* .Abox is the CSS class for controlling the look of the option
   containers (the answers) but does NOT including the formatting
   of the answer/option text: that is in .AText
*/
.Abox {
    border: 1px solid rgba(255, 255, 255, 0.290196);
    border-radius: 5px;
    text-shadow: rgba(0, 0, 0, 0.8) 1px 1px 1px;
    background-color: rgba(255, 255, 255, 0.14902);
    box-shadow: rgba(0, 0, 0, 0.8) 0px 0px 3px 0px;
    position: relative;
    margin: 4px 0;
    width: 100%;
    box-sizing: border-box;
    cursor: pointer;
    user-select: none;
    -webkit-user-select: none;
    -webkit-tap-highlight-color: transparent;
}

/* The .Abox[selected="true"] class allows for the formmating of
   the answer/option box if the user is using keyboard controls 
   to manually select the answer.
*/
.Abox[selected="true"] {
    background-color: rgba(255, 127, 0, 0.7);
}

/* The .Abox:hover class allows for the formmating of
   the answer/option box when the user hovers their mouse over
   it.
*/
.Abox:hover {
    cursor: pointer;
    background-color: rgba(255, 127, 0, 0.4);
}

/* .AText is used to select the formatting of the answer/option
   text.
*/
.AText {
    font-family: 'Open Sans', sans-serif;
    font-size: 12px;
    color: white;
    text-shadow: rgba(0, 0, 0, 0.8) 1px 1px 1px;
    padding: 4px 6px 4px 5px;
    min-height: 27px;
    height: auto;
    line-height: 1.25;
    overflow-wrap: anywhere;
    word-break: break-word;
    white-space: normal;
    cursor: pointer;
    user-select: none;
    -webkit-user-select: none;
}

/* The #bottom_container class is used to format the blank space
   shown at the bottom of the survey creative.
*/
#bottom_container {
    position: relative;
}

/* The #next_button class is used to format the button that is
   shown at the bottom of a survey question page when that question
   is multiple option as it allows the user to advancce to the next
   question after all their selections are made.
*/
#next_button {
    font-family: 'Open Sans', sans-serif;
    font-size: 13px;
    position: absolute;
    right: 8px;
    top: 0px;
    color: beige;
    padding: 3px 15px;
    text-shadow: rgba(0, 0, 0, 1) 1px 1px 1px;
    background-color: rgba(255, 200, 0, 0.6);
    cursor: pointer;
    user-select: none;
    -webkit-user-select: none;
    -webkit-tap-highlight-color: transparent;
}

/* The #next_button:hover class is used to format the 'next' button
   when the user hovers over it with their mouse.
*/
#next_button:hover {
    background-color: rgba(255, 127, 80, 0.8);
    color: white;
}

/* Unused */
#question_comment {
    color: #e8e7e7;
    margin: 0 -2px 0 7px;
    font-size: 13px;
}

/* The .thankyoucontainer class allows for formatting of the div
   and its text that is shown at the end of the survey.
*/
.thankyoucontainer {
    height: 100px;
    width: 300px;
    position: absolute;
    top: 100px;
    left: 0px;
    text-align: center;
    font-family: 'Open Sans', sans-serif;
    font-size: 26px;
    color: beige;
    text-shadow: rgba(0, 0, 0, 0.8) 2px 2px 2px
}

body {
    margin:0 auto;
    display:block;
}

/*
add display:none; to make it invisible

If less than 5 answers, it is better to use position: relative; 
With 5 answers position: relative; will push Next button out of the box. 
Use position: absolute; with 5 answers that has multiple options
*/
#ad_background {
    display:none;
    position: absolute;
    background-color: rgba(0, 118, 0, 0.5);
    width: 299px;
}
#ad_text {
    text-align: center;
    color: rgba(0, 98, 0, 0.5);
    font-size: 5px;
    cursor: pointer;
    user-select: none;
    -webkit-user-select: none;
}
"""

class CreativeSizeField(SelectMultipleField):
  """Accept a legacy string, a list, or checkbox form data."""

  def process_data(self, value):
    self.data = creative_size.selected_keys(value)

  def process_formdata(self, valuelist):
    self.data = creative_size.selected_keys(valuelist or [])


# LANGUAGE_CHOICES = "'en', 'ms', 'zh', 'ja', 'ko'"

def question_text_filled(form, question_number):
  field_name = 'question' + str(question_number)
  value = ''
  if hasattr(form, 'data') and form.data is not None:
    value = form.data.get(field_name) or ''
  return bool(str(value).strip())


def next_choices(form, from_question, current_value=None):
  """Dropdown values: End survey, then later questions that have text.

  Invalid stored values are appended so the editor can show them as invalid.
  """
  choices = [(NEXT_END, 'End survey')]
  for later in range(int(from_question) + 1, 6):
    if question_text_filled(form, later):
      choices.append((str(later), 'Question %s' % later))
  current = NEXT_END if current_value in (None, '') else str(current_value).strip()
  valid = {item[0] for item in choices}
  if current not in valid:
    choices.append((current, 'Invalid (%s)' % current))
  return choices


def next_target_error(form, from_question, value):
  """Return an error message if value is not 'end' or a later filled question."""
  if value is None or str(value).strip() == '':
    return 'Choose End survey or a later question.'
  text = str(value).strip()
  if text.lower() == NEXT_END and text != NEXT_END:
    return "Syntax for end of survey is 'end' in lowercase, please fix."
  if text == NEXT_END:
    return None
  if not re.fullmatch(r'[1-5]', text):
    return 'Next question must be End survey or a later question that has text.'
  target = int(text)
  if target <= int(from_question):
    return 'Next question must be a later question (or End survey).'
  if not question_text_filled(form, target):
    return 'Next question must be a later question that has text.'
  return None


def validate_next_target(form, field):
  """Reject next values that are earlier, the same question, empty, or non-end junk."""
  match = _NEXT_FIELD_NAME.match(field.name)
  if not match:
    return
  from_question = int(match.group(1))
  letter = match.group(2)
  answer_text = ''
  if hasattr(form, 'data') and form.data is not None:
    answer_text = form.data.get('answer' + str(from_question) + letter) or ''
  if not str(answer_text).strip():
    return
  message = next_target_error(form, from_question, field.data)
  if message:
    raise ValidationError(message)


def question_section_is_empty(form, questionNumber):
  """Check if any field of the question input including answer is empty."""
  questionField = 'question' + questionNumber
  answerAField = 'answer' + questionNumber + 'a'
  answerBField = 'answer' + questionNumber + 'b'
  return not (form.data[questionField] and form.data[answerAField] and
              form.data[answerBField] and form.data[answerAField + 'next'] and
              form.data[answerBField + 'next'])


def validate_next_question(form, field):
  """Validate if the question is linked by any other question's answer."""
  questionNumberMatch = re.search(r'\d', field.name)
  questionNumber = questionNumberMatch.group()
  for questionIndex in range(1, 6):
    for answerChoice in ANSWER_LETTERS:
      answerFieldName = 'answer' + str(questionIndex) + answerChoice + 'next'
      answerLinkData = form.data[answerFieldName]
      if answerLinkData == questionNumber and question_section_is_empty(
          form, questionNumber):
        raise ValidationError(
            'Answer ' + answerChoice.upper() + ' from question ' +
            str(questionIndex) +
            ' linked to this question, please fill in this section')

      # Require the literal lowercase token 'end' (the creative lowercases at runtime).
      if answerLinkData and answerLinkData.lower() == 'end' and answerLinkData != 'end':
        raise ValidationError("Syntax for end of survey is 'end' in lowercase, please fix.")


class QuestionForm(FlaskForm):
  """QuestionForm that takes in the survey creation parameters."""

  question1type = SelectField(
      'question1Type', choices=('SINGLE_OPTION', 'MULTIPLE_OPTION'))
  question2type = SelectField(
      'question2Type', choices=('SINGLE_OPTION', 'MULTIPLE_OPTION'))
  question3type = SelectField(
      'question3Type', choices=('SINGLE_OPTION', 'MULTIPLE_OPTION'))
  question4type = SelectField(
      'question4Type', choices=('SINGLE_OPTION', 'MULTIPLE_OPTION'))
  question5type = SelectField(
      'question5Type', choices=('SINGLE_OPTION', 'MULTIPLE_OPTION'))

  # default is 'shuffled'
  question_order_choices = [(ANSWERS_SHUFFLED, 'Shuffled'),
          (ANSWERS_ORDERED, 'Ordered')]

  question1order = SelectField('question1Order', choices=question_order_choices)
  question2order = SelectField('question2Order', choices=question_order_choices)
  question3order = SelectField('question3Order', choices=question_order_choices)
  question4order = SelectField('question4Order', choices=question_order_choices)
  question5order = SelectField('question5Order', choices=question_order_choices)

  # Codes with translations in survey_service, plus English fallback.
  language = SelectField('language', choices=(
      'en', 'ar', 'bn', 'cs', 'da', 'de', 'el', 'es', 'fa', 'fi', 'fr', 'gu',
      'he', 'hi', 'hu', 'id', 'it', 'ja', 'kn', 'ko', 'ml', 'mr', 'ms', 'nl',
      'no', 'pl', 'pt', 'ru', 'sv', 'ta', 'te', 'th', 'tl', 'tr', 'uk', 'ur',
      'vi', 'zh'))

  # make BRAND_TRACK to be the default
  surveytype = SelectField('surveyType', choices=[(
    BRAND_TRACK, 'Brand Track'), (BRAND_LIFT, 'Brand Lift'), ])
    
  surveyname = StringField('surveyName', validators=[DataRequired()])
  displayname = StringField('displayName')
  client = StringField('client')
  agency = StringField('agency')
  campaign_id = StringField('campaignId')
  placement_id = StringField('placementId')
  ad_server = SelectField(
      'adServer',
      choices=[
          ('cm360', 'Campaign Manager 360'),
          ('dv360', 'Display & Video 360'),
          ('gam', 'Google Ad Manager'),
          ('generic', 'Generic / none'),
      ],
      default='cm360')

  # adding responseType as a property of the survey
  responsetype = SelectField('responseType', choices=[
    (RESPONSES_AT_END, 'Submit Responses at End of Survey'),
    (RESPONSES_IMMEDIATELY, 'Submit Responses after each Question')])

  # adding portion of form to customize creative
  custom_css = TextAreaField('custom_css', default=DEFAULT_CSS)

  creativesize = CreativeSizeField(
      'creativeSize',
      choices=creative_size.SIZE_CHOICES,
      default=[creative_size.DEFAULT_SIZE])

  badge_icon = RadioField(
      'badgeIcon',
      choices=brand.badge_icon_choices(),
      default=brand.DEFAULT_BADGE_ICON)
  badge_name = StringField(
      'badgeName',
      validators=[Length(max=brand.BADGE_NAME_MAX)])
  badge_text = StringField(
      'badgeText',
      validators=[Length(max=brand.BADGE_TEXT_MAX)])

  question1 = StringField('question1', validators=[DataRequired()])
  answer1a = StringField('answer1a', validators=[DataRequired()])
  answer1b = StringField('answer1b', validators=[DataRequired()])
  answer1c = StringField('answer1c')
  answer1d = StringField('answer1d')
  answer1e = StringField('answer1e')
  answer1f = StringField('answer1f')
  answer1g = StringField('answer1g')
  answer1h = StringField('answer1h')
  answer1anext = StringField(
      'answer1aNext', default=NEXT_END,
      validators=[DataRequired(), validate_next_target])
  answer1bnext = StringField(
      'answer1bNext', default=NEXT_END,
      validators=[DataRequired(), validate_next_target])
  answer1cnext = StringField(
      'answer1cNext', default=NEXT_END, validators=[validate_next_target])
  answer1dnext = StringField(
      'answer1dNext', default=NEXT_END, validators=[validate_next_target])
  answer1enext = StringField(
      'answer1eNext', default=NEXT_END, validators=[validate_next_target])
  answer1fnext = StringField(
      'answer1fNext', default=NEXT_END, validators=[validate_next_target])
  answer1gnext = StringField(
      'answer1gNext', default=NEXT_END, validators=[validate_next_target])
  answer1hnext = StringField(
      'answer1hNext', default=NEXT_END, validators=[validate_next_target])
  answer2anext = StringField(
      'answer2aNext', default=NEXT_END, validators=[validate_next_target])
  answer2bnext = StringField(
      'answer2bNext', default=NEXT_END, validators=[validate_next_target])
  answer2cnext = StringField(
      'answer2cNext', default=NEXT_END, validators=[validate_next_target])
  answer2dnext = StringField(
      'answer2dNext', default=NEXT_END, validators=[validate_next_target])
  answer2enext = StringField(
      'answer2eNext', default=NEXT_END, validators=[validate_next_target])
  answer2fnext = StringField(
      'answer2fNext', default=NEXT_END, validators=[validate_next_target])
  answer2gnext = StringField(
      'answer2gNext', default=NEXT_END, validators=[validate_next_target])
  answer2hnext = StringField(
      'answer2hNext', default=NEXT_END, validators=[validate_next_target])
  answer3anext = StringField(
      'answer3aNext', default=NEXT_END, validators=[validate_next_target])
  answer3bnext = StringField(
      'answer3bNext', default=NEXT_END, validators=[validate_next_target])
  answer3cnext = StringField(
      'answer3cNext', default=NEXT_END, validators=[validate_next_target])
  answer3dnext = StringField(
      'answer3dNext', default=NEXT_END, validators=[validate_next_target])
  answer3enext = StringField(
      'answer3eNext', default=NEXT_END, validators=[validate_next_target])
  answer3fnext = StringField(
      'answer3fNext', default=NEXT_END, validators=[validate_next_target])
  answer3gnext = StringField(
      'answer3gNext', default=NEXT_END, validators=[validate_next_target])
  answer3hnext = StringField(
      'answer3hNext', default=NEXT_END, validators=[validate_next_target])
  answer4anext = StringField(
      'answer4aNext', default=NEXT_END, validators=[validate_next_target])
  answer4bnext = StringField(
      'answer4bNext', default=NEXT_END, validators=[validate_next_target])
  answer4cnext = StringField(
      'answer4cNext', default=NEXT_END, validators=[validate_next_target])
  answer4dnext = StringField(
      'answer4dNext', default=NEXT_END, validators=[validate_next_target])
  answer4enext = StringField(
      'answer4eNext', default=NEXT_END, validators=[validate_next_target])
  answer4fnext = StringField(
      'answer4fNext', default=NEXT_END, validators=[validate_next_target])
  answer4gnext = StringField(
      'answer4gNext', default=NEXT_END, validators=[validate_next_target])
  answer4hnext = StringField(
      'answer4hNext', default=NEXT_END, validators=[validate_next_target])
  answer5anext = StringField(
      'answer5aNext', default=NEXT_END, validators=[validate_next_target])
  answer5bnext = StringField(
      'answer5bNext', default=NEXT_END, validators=[validate_next_target])
  answer5cnext = StringField(
      'answer5cNext', default=NEXT_END, validators=[validate_next_target])
  answer5dnext = StringField(
      'answer5dNext', default=NEXT_END, validators=[validate_next_target])
  answer5enext = StringField(
      'answer5eNext', default=NEXT_END, validators=[validate_next_target])
  answer5fnext = StringField(
      'answer5fNext', default=NEXT_END, validators=[validate_next_target])
  answer5gnext = StringField(
      'answer5gNext', default=NEXT_END, validators=[validate_next_target])
  answer5hnext = StringField(
      'answer5hNext', default=NEXT_END, validators=[validate_next_target])
  question2 = StringField('question2')
  answer2a = StringField('answer2a')
  answer2b = StringField('answer2b')
  answer2c = StringField('answer2c')
  answer2d = StringField('answer2d')
  answer2e = StringField('answer2e')
  answer2f = StringField('answer2f')
  answer2g = StringField('answer2g')
  answer2h = StringField('answer2h')
  question3 = StringField('question3')
  answer3a = StringField('answer3a')
  answer3b = StringField('answer3b')
  answer3c = StringField('answer3c')
  answer3d = StringField('answer3d')
  answer3e = StringField('answer3e')
  answer3f = StringField('answer3f')
  answer3g = StringField('answer3g')
  answer3h = StringField('answer3h')
  question4 = StringField('question4')
  answer4a = StringField('answer4a')
  answer4b = StringField('answer4b')
  answer4c = StringField('answer4c')
  answer4d = StringField('answer4d')
  answer4e = StringField('answer4e')
  answer4f = StringField('answer4f')
  answer4g = StringField('answer4g')
  answer4h = StringField('answer4h')
  question5 = StringField('question5')
  answer5a = StringField('answer5a')
  answer5b = StringField('answer5b')
  answer5c = StringField('answer5c')
  answer5d = StringField('answer5d')
  answer5e = StringField('answer5e')
  answer5f = StringField('answer5f')
  answer5g = StringField('answer5g')
  answer5h = StringField('answer5h')
  submit = SubmitField('Submit')

  def validate_creativesize(form, field):
    keys = creative_size.selected_keys(field.data)
    if not keys:
      raise ValidationError('Choose at least one creative size.')
    field.data = keys
    limit = creative_size.max_answers(keys)
    extra = []
    for question_index in range(1, 6):
      for letter in ANSWER_LETTERS[limit:]:
        text = form.data.get('answer' + str(question_index) + letter) or ''
        if str(text).strip():
          extra.append('Q%s %s' % (question_index, letter.upper()))
    if extra:
      raise ValidationError(
          'Answers F–H are only allowed when every selected size is 160×600 or '
          '300×600. Remove extra answers or deselect the smaller sizes.')

  def validate_question1(form, field):
    validate_next_question(form, field)

  def validate_question2(form, field):
    validate_next_question(form, field)

  def validate_question3(form, field):
    validate_next_question(form, field)

  def validate_question4(form, field):
    validate_next_question(form, field)

  def validate_question5(form, field):
    validate_next_question(form, field)
