/* Keep the generated theme block in sync with css_theme.py. */
(function (window) {
  'use strict';

  var THEME_START = '/* BV2_THEME_START */';
  var THEME_END = '/* BV2_THEME_END */';

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function sanitizeUrl(url) {
    if (!url) return '';
    var cleaned = String(url).trim().replace(/[\\()'"]/g, '');
    if (/^(https?:)?\/\//i.test(cleaned)) return cleaned;
    return '';
  }

  function parseRgba(value) {
    var match = String(value || '').trim().match(
      /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([0-9.]+))?\s*\)$/i
    );
    if (!match) return null;
    return {
      hex: '#' + [match[1], match[2], match[3]].map(function (part) {
        return ('0' + Number(part).toString(16)).slice(-2);
      }).join(''),
      opacity: match[4] == null ? 1 : Number(match[4])
    };
  }

  function namedOrHex(value) {
    var named = {
      white: '#ffffff',
      black: '#000000',
      beige: '#f5f5dc',
      red: '#ff0000',
      green: '#008000'
    };
    var raw = String(value || '').trim();
    if (named[raw.toLowerCase()]) return { hex: named[raw.toLowerCase()], opacity: 1 };
    var hex = raw.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
    if (hex) {
      var digits = hex[1];
      if (digits.length === 3) {
        digits = digits.split('').map(function (ch) { return ch + ch; }).join('');
      }
      return { hex: '#' + digits.toLowerCase(), opacity: 1 };
    }
    return parseRgba(raw);
  }

  function formatCssColor(hex, opacity) {
    var parsed = namedOrHex(hex) || { hex: '#008000', opacity: 1 };
    var op = opacity == null ? 1 : Number(opacity);
    if (op >= 0.999) return parsed.hex;
    var n = parsed.hex.replace('#', '');
    var r = parseInt(n.slice(0, 2), 16);
    var g = parseInt(n.slice(2, 4), 16);
    var b = parseInt(n.slice(4, 6), 16);
    return 'rgba(' + r + ', ' + g + ', ' + b + ', ' + op + ')';
  }

  function generateThemeBlock(theme) {
    var image = sanitizeUrl(theme.bgImage);
    var imageValue = image ? 'url("' + image.replace(/"/g, '') + '")' : 'none';
    var pattern = theme.bgPattern && theme.bgPattern !== 'none' ? theme.bgPattern : 'none';
    var patternSize = 'auto';
    if (pattern.indexOf('conic-gradient') !== -1) patternSize = '16px 16px';
    else if (pattern.indexOf('radial-gradient') !== -1) patternSize = '10px 10px';
    var panel = theme.panel || 'rgba(0, 0, 0, 0.35)';
    var accent = theme.accent || theme.answerBg || '#ffc800';
    return [
      THEME_START,
      ':root {',
      '  --bv2-bg: ' + theme.bg + ';',
      '  --bv2-question-color: ' + theme.questionColor + ';',
      '  --bv2-answer-bg: ' + theme.answerBg + ';',
      '  --bv2-answer-color: ' + theme.answerColor + ';',
      '  --bv2-font-family: ' + theme.fontFamily + ';',
      '  --bv2-font-size: ' + theme.fontSize + ';',
      '  --bv2-bg-image: ' + imageValue + ';',
      '  --bv2-bg-pattern: ' + pattern + ';',
      '  --bv2-bg-pattern-size: ' + patternSize + ';',
      '  --bv2-panel: ' + panel + ';',
      '  --bv2-accent: ' + accent + ';',
      '}',
      '#master_container {',
      '  background-color: var(--bv2-bg);',
      '  background-image: var(--bv2-bg-image), var(--bv2-bg-pattern);',
      '  background-size: cover, var(--bv2-bg-pattern-size);',
      '  background-position: center, 0 0;',
      '}',
      '.Qbox {',
      '  color: var(--bv2-question-color);',
      '  font-family: var(--bv2-font-family);',
      '  font-size: var(--bv2-font-size);',
      '  background-color: var(--bv2-panel);',
      '  user-select: none;',
      '  -webkit-user-select: none;',
      '}',
      '#thankyou_text, .thankyoucontainer {',
      '  color: var(--bv2-question-color);',
      '  font-family: var(--bv2-font-family);',
      '}',
      '.Abox {',
      '  background-color: var(--bv2-answer-bg);',
      '  border: 1px solid rgba(0, 0, 0, 0.35);',
      '  border-radius: 5px;',
      '  margin: 0;',
      '  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.18);',
      '  cursor: pointer;',
      '  user-select: none;',
      '  -webkit-user-select: none;',
      '  -webkit-tap-highlight-color: transparent;',
      '}',
      '.AText, #next_button {',
      '  color: var(--bv2-answer-color);',
      '  font-family: var(--bv2-font-family);',
      '}',
      '.AText {',
      '  font-size: var(--bv2-font-size);',
      '  cursor: pointer;',
      '  user-select: none;',
      '  -webkit-user-select: none;',
      '}',
      '#next_button {',
      '  background-color: var(--bv2-accent);',
      '  padding: 3px 15px;',
      '  border: 1px solid rgba(0, 0, 0, 0.28);',
      '  border-radius: 4px;',
      '  display: inline-block;',
      '  cursor: pointer;',
      '  user-select: none;',
      '  -webkit-user-select: none;',
      '  -webkit-tap-highlight-color: transparent;',
      '}',
      '#ad_text {',
      '  font-family: Arial, Helvetica, sans-serif;',
      '  cursor: pointer;',
      '  user-select: none;',
      '  -webkit-user-select: none;',
      '}',
      THEME_END
    ].join('\n');
  }

  function fieldValue(name) {
    var el = document.querySelector('[name="' + name + '"]');
    return el ? el.value : '';
  }

  window.surveyEditor = function surveyEditor() {
    var boot = window.BV2_EDITOR || { theme: {}, extra: '' };
    var theme = boot.theme || {};
    var bgParsed = namedOrHex(theme.bg) || { hex: '#008000', opacity: 1 };
    var answerParsed = namedOrHex(theme.answer_bg) || { hex: '#ffffff', opacity: 0.149 };
    var qParsed = namedOrHex(theme.question_color) || { hex: '#ffffff', opacity: 1 };
    var aParsed = namedOrHex(theme.answer_color) || { hex: '#ffffff', opacity: 1 };
    var fontSize = String(theme.font_size || '13px').replace(/px$/i, '');
    var letters = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'];
    var tallKeys = { '160x600': true, '300x600': true };

    function filledAnswerCount(q, maxN) {
      var count = 2;
      var cap = maxN || 8;
      for (var i = 0; i < letters.length; i++) {
        if (fieldValue('answer' + q + letters[i])) count = i + 1;
      }
      return Math.max(2, Math.min(cap, count));
    }

    return {
      bg: bgParsed.hex,
      questionColor: qParsed.hex,
      answerBg: answerParsed.hex,
      answerBgOpacity: Math.round((answerParsed.opacity == null ? 1 : answerParsed.opacity) * 100),
      answerColor: aParsed.hex,
      fontFamily: theme.font_family || "'Open Sans', sans-serif",
      fontSize: fontSize || '13',
      bgImage: theme.bg_image || '',
      extraCss: boot.extra || '',
      previewSrcdoc: '',
      previewSize: '',
      bgPattern: theme.bg_pattern || 'none',
      panel: theme.panel || 'rgba(0, 0, 0, 0.35)',
      accent: theme.accent || '#ffc800',
      formEpoch: 0,
      editorReady: false,
      prevFilled: {},
      nextWarnings: {},
      answerCounts: {
        1: filledAnswerCount(1),
        2: filledAnswerCount(2),
        3: filledAnswerCount(3),
        4: filledAnswerCount(4),
        5: filledAnswerCount(5)
      },

      init: function () {
        this.prevFilled = this.filledQuestionMap();
        var keys = this.selectedSizeKeys();
        this.previewSize = keys[0] || '300x250';
        this.trimAnswersToMax();
        this.syncCss();
        this.editorReady = true;
      },

      selectedSizeKeys: function () {
        void this.formEpoch;
        var boxes = document.querySelectorAll('input[name="creativesize"]:checked');
        var keys = [];
        for (var i = 0; i < boxes.length; i++) {
          if (boxes[i].value && keys.indexOf(boxes[i].value) === -1) keys.push(boxes[i].value);
        }
        return keys.length ? keys : ['300x250'];
      },

      maxAnswers: function () {
        var keys = this.selectedSizeKeys();
        for (var i = 0; i < keys.length; i++) {
          if (!tallKeys[keys[i]]) return 5;
        }
        return 8;
      },

      onSizesChange: function () {
        var keys = this.selectedSizeKeys();
        if (keys.indexOf(this.previewSize) === -1) this.previewSize = keys[0];
        this.trimAnswersToMax();
        this.syncCss();
      },

      trimAnswersToMax: function () {
        var maxN = this.maxAnswers();
        for (var q = 1; q <= 5; q++) {
          while ((this.answerCounts[q] || 2) > maxN) this.removeAnswer(q);
        }
      },

      resetBadgeText: function () {
        var el = document.getElementById('badge_text');
        if (el) el.value = '';
        this.syncCss();
      },

      selectedBadgeIcon: function () {
        void this.formEpoch;
        var checked = document.querySelector('input[name="badge_icon"]:checked');
        return (checked && checked.value) || 'B';
      },

      selectedBadgeSpec: function () {
        var id = this.selectedBadgeIcon();
        var icons = boot.badgeIcons || [];
        for (var i = 0; i < icons.length; i++) {
          if (icons[i].id === id) return icons[i];
        }
        return { id: 'B', kind: 'letter', mark: null };
      },

      badgeNameText: function () {
        void this.formEpoch;
        var typed = String(fieldValue('badge_name') || '').trim();
        var agency = String(fieldValue('agency') || '').trim();
        var raw = (typed || agency).replace(/<[^>]*>/g, '').replace(/[<>]/g, '');
        return raw.replace(/\s+/g, ' ').trim().slice(0, 40);
      },

      badgeTooltipText: function () {
        void this.formEpoch;
        var typed = String(fieldValue('badge_text') || '').trim();
        if (typed) return typed.slice(0, 120);
        return (boot.badgeTextDefault || (boot.brand && boot.brand.tooltip) ||
          'Survey Type Brandometer2 Ad - powered by Google');
      },

      badgeMarkup: function () {
        var spec = this.selectedBadgeSpec();
        var tip = this.badgeTooltipText();
        var kind = spec.kind || 'letter';
        var mark = spec.mark || (boot.brand && boot.brand.letter) || 'B';
        if (kind === 'wordmark') {
          mark = this.badgeNameText() || 'Ad';
        }
        var face;
        if (spec.svg) {
          face = spec.svg;
        } else if (kind === 'letter') {
          face = '<svg viewBox="0 0 20 20" width="20" height="20" aria-hidden="true">' +
            '<rect x="1" y="1" width="18" height="18" rx="3.5" fill="#ddd" stroke="#111" stroke-width="1.2"/>' +
            '<text x="10" y="14.5" text-anchor="middle" font-size="12" font-family="Georgia,serif" font-weight="700" fill="#111">' +
            escapeHtml(mark) + '</text></svg>';
        } else {
          face = '<span class="brand-badge-face">' + escapeHtml(mark) + '</span>';
        }
        return '<button type="button" class="brand-badge badge-kind-' + escapeHtml(kind) +
          ' badge-icon-' + escapeHtml(spec.id || 'B') + '" title="' + escapeHtml(tip) + '">' +
          face + '<span class="brand-badge-tip">' + escapeHtml(tip) + '</span></button>';
      },

      currentSize: function () {
        var keys = this.selectedSizeKeys();
        var key = this.previewSize && keys.indexOf(this.previewSize) !== -1
          ? this.previewSize : (keys[0] || '300x250');
        var parts = String(key).toLowerCase().split('x');
        var width = parseInt(parts[0], 10) || 300;
        var height = parseInt(parts[1], 10) || 250;
        var layout = (key === '970x250') ? 'wide' : ((key === '160x600' || key === '300x600') ? 'tall' : 'stack');
        return { width: width, height: height, key: key, layout: layout };
      },

      sizeLabel: function () {
        return this.currentSize().key.replace('x', '×');
      },

      previewFrameStyle: function () {
        var size = this.currentSize();
        return 'width:' + (size.width + 2) + 'px;height:' + (size.height + 2) + 'px';
      },

      answerVisible: function (question, letter) {
        var idx = letters.indexOf(letter);
        return idx > -1 && idx < (this.answerCounts[question] || 2);
      },

      questionFilled: function (n) {
        void this.formEpoch;
        return Boolean(String(fieldValue('question' + n) || '').trim());
      },

      answerHasText: function (question, letter) {
        void this.formEpoch;
        return Boolean(String(fieldValue('answer' + question + letter) || '').trim());
      },

      filledQuestionMap: function () {
        var filled = {};
        for (var n = 1; n <= 5; n++) {
          filled[n] = this.questionFilled(n);
        }
        return filled;
      },

      nextValue: function (question, letter) {
        void this.formEpoch;
        var el = document.querySelector('[name="answer' + question + letter + 'next"]');
        return el ? String(el.value || 'end') : 'end';
      },

      nextIsInvalid: function (question, letter) {
        void this.formEpoch;
        if (!this.answerHasText(question, letter)) return false;
        var val = this.nextValue(question, letter);
        if (!val || val === 'end') return false;
        var target = parseInt(val, 10);
        if (!target || target <= question || target > 5) return true;
        return !this.questionFilled(target);
      },

      nextWarning: function (question, letter) {
        return this.nextWarnings[question + letter] || '';
      },

      clearNextWarning: function (question, letter) {
        var key = question + letter;
        if (this.nextWarnings[key]) {
          var copy = Object.assign({}, this.nextWarnings);
          delete copy[key];
          this.nextWarnings = copy;
        }
      },

      nextOptions: function (question, letter) {
        var opts = [{ value: 'end', label: 'End survey' }];
        for (var later = question + 1; later <= 5; later++) {
          if (this.questionFilled(later)) {
            opts.push({ value: String(later), label: 'Question ' + later });
          }
        }
        var current = this.nextValue(question, letter);
        var valid = false;
        for (var i = 0; i < opts.length; i++) {
          if (opts[i].value === current) valid = true;
        }
        if (current && !valid) {
          opts.push({ value: current, label: 'Invalid (' + current + ')' });
        }
        return opts;
      },

      rebuildNextSelect: function (question, letter) {
        var el = document.querySelector('[name="answer' + question + letter + 'next"]');
        if (!el || el.tagName !== 'SELECT') return;
        var current = this.nextValue(question, letter);
        var opts = this.nextOptions(question, letter);
        var html = '';
        for (var i = 0; i < opts.length; i++) {
          html += '<option value="' + escapeHtml(opts[i].value) + '"' +
            (opts[i].value === current ? ' selected' : '') + '>' +
            escapeHtml(opts[i].label) + '</option>';
        }
        el.innerHTML = html;
        el.value = current;
      },

      syncNextTargets: function (repairCleared) {
        var nowFilled = this.filledQuestionMap();
        for (var q = 1; q <= 5; q++) {
          for (var li = 0; li < letters.length; li++) {
            var letter = letters[li];
            var el = document.querySelector('[name="answer' + q + letter + 'next"]');
            if (!el) continue;
            var val = String(el.value || 'end');
            var target = parseInt(val, 10);
            if (repairCleared && val !== 'end' && target && this.prevFilled[target] && !nowFilled[target] && target > q) {
              el.value = 'end';
              var warnings = Object.assign({}, this.nextWarnings);
              warnings[q + letter] = 'Question ' + target + ' is empty. Next was reset to End survey.';
              this.nextWarnings = warnings;
            }
            this.rebuildNextSelect(q, letter);
          }
        }
        this.prevFilled = nowFilled;
      },

      addAnswer: function (question) {
        var current = this.answerCounts[question] || 2;
        if (current >= this.maxAnswers()) return;
        this.answerCounts[question] = current + 1;
        this.syncCss();
      },

      removeAnswer: function (question) {
        var current = this.answerCounts[question] || 2;
        if (current <= 2) return;
        var letter = letters[current - 1];
        var text = document.querySelector('[name="answer' + question + letter + '"]');
        var next = document.querySelector('[name="answer' + question + letter + 'next"]');
        if (text) text.value = '';
        if (next) next.value = 'end';
        this.answerCounts[question] = current - 1;
        this.syncCss();
      },

      applyPreset: function (id) {
        if (!id) return;
        var presets = boot.presets || [];
        var preset = null;
        for (var i = 0; i < presets.length; i++) {
          if (presets[i].id === id) {
            preset = presets[i];
            break;
          }
        }
        if (!preset) return;
        this.bg = preset.bg;
        this.questionColor = preset.question_color;
        this.answerBg = preset.answer_bg;
        this.answerBgOpacity = preset.answer_bg_opacity == null ? 100 : preset.answer_bg_opacity;
        this.answerColor = preset.answer_color;
        this.fontFamily = preset.font_family;
        this.fontSize = preset.font_size;
        this.bgImage = preset.bg_image || '';
        this.bgPattern = preset.bg_pattern || 'none';
        this.panel = preset.panel || 'rgba(0, 0, 0, 0.42)';
        this.accent = preset.accent || preset.answer_bg;
        this.syncCss();
      },

      presetSwatchStyle: function () {
        return 'background: linear-gradient(135deg, ' + this.bg + ' 50%, ' +
          (this.accent || this.answerBg) + ' 50%);';
      },

      composedTheme: function () {
        return {
          bg: this.bg,
          questionColor: this.questionColor,
          answerBg: formatCssColor(this.answerBg, this.answerBgOpacity / 100),
          answerColor: this.answerColor,
          fontFamily: this.fontFamily,
          fontSize: String(this.fontSize || '13') + 'px',
          bgImage: this.bgImage,
          bgPattern: this.bgPattern || 'none',
          panel: this.panel || 'rgba(0, 0, 0, 0.35)',
          accent: this.accent || this.answerBg
        };
      },

      combinedCss: function () {
        var extra = this.extraCss || '';
        var start = extra.indexOf(THEME_START);
        var end = extra.indexOf(THEME_END);
        if (start !== -1 && end !== -1 && end >= start) {
          extra = (extra.slice(0, start) + extra.slice(end + THEME_END.length)).trim();
        }
        var block = generateThemeBlock(this.composedTheme());
        return extra ? extra + '\n\n' + block + '\n' : block + '\n';
      },

      syncCss: function () {
        this.formEpoch += 1;
        var combined = this.combinedCss();
        var hidden = document.getElementById('custom_css');
        if (hidden) hidden.value = combined;
        this.previewSrcdoc = this.buildPreview(combined);
        this.syncNextTargets(this.editorReady);
      },

      buildPreview: function (css) {
        var q = fieldValue('question1') || 'Sample question';
        var visible = this.answerCounts[1] || 2;
        var answers = letters.slice(0, visible).map(function (letter) {
          return fieldValue('answer1' + letter);
        }).filter(Boolean);
        if (!answers.length) answers = ['Option A', 'Option B'];
        var safeCss = String(css || '').replace(/<\/style/gi, '<\\/style');
        var options = answers.map(function (text, index) {
          return '<div id="option_container_' + index + '" class="Abox">' +
            '<div id="option_text_' + index + '" class="AText">' + escapeHtml(text) + '</div></div>';
        }).join('');
        var size = this.currentSize();
        var w = size.width;
        var h = size.height;
        var overlay = (boot.sizeOverlayCss && boot.sizeOverlayCss[size.key]) || '';
        var layoutFix = boot.layoutFixCss || '';
        var chromeCss = 'html,body{margin:0!important;padding:0!important;overflow:hidden!important;' +
          'width:' + w + 'px;height:' + h + 'px;box-sizing:border-box;}' +
          '*,*::before,*::after{box-sizing:border-box;}' +
          '#master_container{box-sizing:border-box;width:' + w + 'px!important;height:' + h + 'px!important;' +
          'overflow:hidden;margin:0;max-width:' + w + 'px;max-height:' + h + 'px;}';
        var badge = this.badgeMarkup();
        var lang = (fieldValue('language') || 'en').trim().toLowerCase() || 'en';
        var dir = ({ ar: 1, he: 1, fa: 1, ur: 1 }[lang.split('-')[0]]) ? 'rtl' : 'ltr';
        return '<!DOCTYPE html><html lang="' + escapeHtml(lang) + '" dir="' + dir + '"><head><meta charset="utf-8">' +
          '<style>' + safeCss + '</style>' +
          '<style>' + overlay + '</style>' +
          '<style>' + layoutFix + '</style>' +
          '<style>' + chromeCss + '</style></head><body>' +
          '<div id="master_container" class="size-' + size.key + ' layout-' + size.layout + '">' +
          '<div id="ad_background"><div id="ad_text">Advertisement</div></div>' +
          '<div id="survey_container"><div id="question_container" class="Qbox">' +
          '<span id="question_text">' + escapeHtml(q) + '</span></div>' +
          '<div class="answers-grid">' + options + '</div></div>' +
          '<div id="thankyou_container" class="invisible"><div id="thankyou_text"></div></div>' +
          '<div id="bottom_container"><span id="question_comment"></span>' +
          '<span id="next_button">Next</span></div>' + badge + '</div></body></html>';
      }
    };
  };
})(window);
