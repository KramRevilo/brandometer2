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
"""Plain-English 'What does this mean?' copy for editor and report warnings.

Keep every help entry here so survey creators see one voice and editors can
change the wording in a single file.
"""

# HTML5 spec QA codes → help id. Unknown codes fall back to qa.other.
QA_CODE_TO_HELP = {
    'iab.initial': 'qa.filesize',
    'iab.polite': 'qa.filesize',
    'cm360.size': 'qa.filesize',
    'iab.files': 'qa.filecount',
    'cm360.files': 'qa.filecount',
    'clickTag': 'qa.clickTag',
    'ad.size': 'qa.adsize',
    'ad.size.mismatch': 'qa.adsize',
    'size.css': 'qa.adsize',
    'nested.zip': 'qa.nested',
    'external': 'qa.external',
    'receiver': 'qa.receiver',
    'xhr': 'qa.xhr',
    'filename': 'qa.filename',
    'index.html': 'qa.index',
}

ENTRIES = {
    'qa.filesize': {
        'title': 'File size',
        'body': (
            'Ad networks cap how heavy an HTML5 banner can be. IAB’s common '
            'display budget is about 200 KB for the first load and 2.2 MB for '
            'the whole polite load; Campaign Manager 360 allows up to 10 MB. '
            'This survey zip is almost only one HTML file, so it is usually '
            'fine. If you see this, strip large images from Advanced CSS or '
            'pick a simpler theme. The download is not blocked.'
        ),
    },
    'qa.filecount': {
        'title': 'File count',
        'body': (
            'Some specs limit how many files sit inside the HTML5 zip (IAB '
            'often mentions about 10 host-initiated files; Campaign Manager '
            '360 allows 100). Each inner zip from this app is supposed to '
            'contain only index.html. Extra files usually mean something was '
            'added by hand. Unzip, remove extras, and re-download from the app.'
        ),
    },
    'qa.clickTag': {
        'title': 'clickTag',
        'body': (
            'clickTag is the click-through URL the ad server fills in when '
            'someone clicks the banner. Campaign Manager and IAB HTML5 expect '
            'a JavaScript variable named clickTag. This app always writes one '
            'for new zips. If it is missing, re-download the zip instead of '
            'editing index.html by hand.'
        ),
    },
    'qa.adsize': {
        'title': 'ad.size vs labelled size',
        'body': (
            'The file name (for example 300x250) must match the ad.size meta '
            'tag and the width/height of the survey box. Trafficking tools '
            'reject a 300×250 placement that contains a 160×600 creative. '
            'Re-download the zip from the size you actually selected. Do not '
            'rename the inner zip to a different size.'
        ),
    },
    'qa.nested': {
        'title': 'Nested zip',
        'body': (
            'Upload each inner zip as the creative — the one that contains '
            'index.html. Do not upload the outer package, and do not put a '
            'zip inside a zip. Nested archives fail HTML5 upload in Campaign '
            'Manager. Unzip the outer file and traffic only the inner zips.'
        ),
    },
    'qa.external': {
        'title': 'External requests',
        'body': (
            'HTML5 banners are meant to be self-contained. A request to an '
            'unexpected website (fonts, extra pixels, live images) can fail '
            'publisher scanners or CM360 backup/preview. Macros the ad server '
            'replaces, Google click-through hosts, and avatar hosts are '
            'ignored. Remove other https:// URLs from Advanced CSS, or keep '
            'assets inside the creative. This does not block the download.'
        ),
    },
    'qa.receiver': {
        'title': 'Survey response call',
        'body': (
            'Every live survey calls this app’s own response address so '
            'answers reach BigQuery. That call is required — without it the '
            'report stays empty. It is not a third-party tracker. Some '
            'publishers still ask you to allowlist the domain. Preview does '
            'not send this call.'
        ),
    },
    'qa.xhr': {
        'title': 'fetch / XHR',
        'body': (
            'Scripts that call fetch, XMLHttpRequest, or sendBeacon can fail '
            'Campaign Manager’s backup image and some publisher previews. '
            'This app’s answer pixel is a simple image request, which is the '
            'usual HTML5 pattern. If you pasted custom JavaScript that talks '
            'to another server, remove it from Advanced CSS / the zip.'
        ),
    },
    'qa.filename': {
        'title': 'Inner zip file name',
        'body': (
            'Campaign Manager limits HTML5 zip file names (this app uses 50 '
            'characters). A very long survey name can overshoot. Shorten the '
            'survey name (the one used in zip files, not the display name) '
            'and download again.'
        ),
    },
    'qa.index': {
        'title': 'index.html',
        'body': (
            'An HTML5 display creative must have an index.html at the top of '
            'the zip. This app always writes that file. If it is missing, the '
            'archive was edited after download — re-download from the app and '
            'do not add or rename files.'
        ),
    },
    'qa.other': {
        'title': 'HTML5 spec check',
        'body': (
            'This is an IAB / Campaign Manager / DV360 HTML5 check. Warnings '
            'never block the download. Read the line above, fix the zip if '
            'you will traffic it, or re-download a fresh copy from the app.'
        ),
    },
    'report.min_n': {
        'title': 'Small sample',
        'body': (
            'Lift is shaky with fewer than 30 people in control or in exposed. '
            'Percentages can jump when one extra person answers. Treat the '
            'numbers as a direction of travel, not a final result, until both '
            'arms reach 30. Breakouts often stay small even when the overall '
            'table is large enough.'
        ),
    },
    'report.holm': {
        'title': 'Holm-adjusted p-value',
        'body': (
            'The report runs many similar tests (every answer, and every '
            'breakout slice). Unadjusted p-values then look “significant” too '
            'often by chance. p-adj (Holm) tightens the bar within this table '
            '(or within one breakout). Use p-adj when you want a cautious '
            'read. Unadjusted breakout p-values are exploratory.'
        ),
    },
    'report.ci': {
        'title': 'Confidence interval',
        'body': (
            'The percentage under each arm is an estimate. The Wilson 95% '
            'interval is a range that usually covers the true percentage if '
            'you repeated the survey. Wide ranges mean the sample is still '
            'thin. Overlapping control and exposed ranges often go with a '
            'non-significant p-value.'
        ),
    },
    'report.pvalue': {
        'title': 'p-value',
        'body': (
            'This is a two-sided test of “are exposed and control different?” '
            'A small p-value (often below 0.05) means the difference is '
            'unlikely if there were no real effect. It is not the size of the '
            'lift. With a small sample, or many breakouts, wait for p-adj and '
            'the small-n warning before acting on it.'
        ),
    },
    'report.no_control': {
        'title': 'No control segment',
        'body': (
            'Brand Lift needs a control group (people who did not see the '
            'campaign) and an exposed group. This app stores that on the row '
            'as seg (default_control vs default_expose). If control is '
            'missing, traffic the control zip or wait for those responses. '
            'Lift is not computed until both sides exist.'
        ),
    },
    'report.no_expose': {
        'title': 'No exposed segment',
        'body': (
            'Brand Lift needs responses from people who saw the campaign '
            '(seg contains “expos”). If that zip was not trafficked, or the '
            'pixel is not firing, only control (or neither) will show. Lift '
            'waits until both arms have data.'
        ),
    },
    'report.no_data': {
        'title': 'No responses yet',
        'body': (
            'Preview in the app does not write to BigQuery. Live zips post to '
            'the receiver after someone answers. Use a trafficked creative or '
            'a curl to the receiver (see DEVELOPERS.md) to populate this page.'
        ),
    },
}


def help_id_for_code(code):
  return QA_CODE_TO_HELP.get(code or '', 'qa.other')


def entry(help_id):
  return ENTRIES.get(help_id)
