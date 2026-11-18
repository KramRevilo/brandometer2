/* Keep the generated theme block in sync with css_theme.py. */
(function (window) {
  'use strict';

  var THEME_START = '/* SONAR_THEME_START */';
  var THEME_END = '/* SONAR_THEME_END */';

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
    return [
      THEME_START,
      ':root {',
      '  --sonar-bg: ' + theme.bg + ';',
      '  --sonar-question-color: ' + theme.questionColor + ';',
      '  --sonar-answer-bg: ' + theme.answerBg + ';',
      '  --sonar-answer-color: ' + theme.answerColor + ';',
      '  --sonar-font-family: ' + theme.fontFamily + ';',
      '  --sonar-font-size: ' + theme.fontSize + ';',
      '  --sonar-bg-image: ' + imageValue + ';',
      '}',
      '#master_container {',
      '  background-color: var(--sonar-bg);',
      '  background-image: var(--sonar-bg-image);',
      '  background-size: cover;',
      '  background-position: center;',
      '}',
      '.Qbox {',
      '  color: var(--sonar-question-color);',
      '  font-family: var(--sonar-font-family);',
      '  font-size: var(--sonar-font-size);',
      '}',
      '.Abox {',
      '  background-color: var(--sonar-answer-bg);',
      '}',
      '.AText, #next_button {',
      '  color: var(--sonar-answer-color);',
      '  font-family: var(--sonar-font-family);',
      '}',
      '.AText {',
      '  font-size: var(--sonar-font-size);',
      '}',
      THEME_END
    ].join('\n');
  }

  function fieldValue(name) {
    var el = document.querySelector('[name="' + name + '"]');
    return el ? el.value : '';
  }

  window.surveyEditor = function surveyEditor() {
    var boot = window.SONAR_EDITOR || { theme: {}, extra: '' };
    var theme = boot.theme || {};
    var bgParsed = namedOrHex(theme.bg) || { hex: '#008000', opacity: 1 };
    var answerParsed = namedOrHex(theme.answer_bg) || { hex: '#ffffff', opacity: 0.149 };
    var qParsed = namedOrHex(theme.question_color) || { hex: '#ffffff', opacity: 1 };
    var aParsed = namedOrHex(theme.answer_color) || { hex: '#ffffff', opacity: 1 };
    var fontSize = String(theme.font_size || '13px').replace(/px$/i, '');
    var letters = ['a', 'b', 'c', 'd', 'e'];

    function filledAnswerCount(q) {
      var count = 2;
      for (var i = 0; i < letters.length; i++) {
        if (fieldValue('answer' + q + letters[i])) count = i + 1;
      }
      return Math.max(2, Math.min(5, count));
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
        this.syncCss();
        this.editorReady = true;
      },

      currentSize: function () {
        var raw = fieldValue('creativesize') || '300x250';
        var parts = String(raw).toLowerCase().split('x');
        var width = parseInt(parts[0], 10) || 300;
        var height = parseInt(parts[1], 10) || 250;
        return { width: width, height: height, key: width + 'x' + height };
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
        if (current >= 5) return;
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
        this.answerBgOpacity = preset.answer_bg_opacity;
        this.answerColor = preset.answer_color;
        this.fontFamily = preset.font_family;
        this.fontSize = preset.font_size;
        this.bgImage = preset.bg_image || '';
        this.syncCss();
      },

      composedTheme: function () {
        return {
          bg: this.bg,
          questionColor: this.questionColor,
          answerBg: formatCssColor(this.answerBg, this.answerBgOpacity / 100),
          answerColor: this.answerColor,
          fontFamily: this.fontFamily,
          fontSize: String(this.fontSize || '13') + 'px',
          bgImage: this.bgImage
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
        var chromeCss = 'html,body{margin:0!important;padding:0!important;overflow:hidden!important;' +
          'width:' + w + 'px;height:' + h + 'px;box-sizing:border-box;}' +
          '*,*::before,*::after{box-sizing:border-box;}' +
          '#master_container{box-sizing:border-box;width:' + w + 'px!important;height:' + h + 'px!important;' +
          'overflow:hidden;margin:0;max-width:' + w + 'px;max-height:' + h + 'px;}';
        return '<!DOCTYPE html><html><head><meta charset="utf-8">' +
          '<style>' + safeCss + '</style>' +
          '<style>' + chromeCss + '</style></head><body>' +
          '<div id="master_container"><div id="ad_background"><div id="ad_text">Advertisement</div></div>' +
          '<div id="survey_container"><div id="question_container" class="Qbox">' +
          '<span id="question_text">' + escapeHtml(q) + '</span></div>' +
          options + '</div>' +
          '<div id="thankyou_container" class="invisible"><div id="thankyou_text"></div></div>' +
          '<div id="bottom_container"><span id="question_comment"></span>' +
          '<span id="next_button">Next</span></div></div></body></html>';
      }
    };
  };
})(window);
