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

      init: function () {
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
        var combined = this.combinedCss();
        var hidden = document.getElementById('custom_css');
        if (hidden) hidden.value = combined;
        this.previewSrcdoc = this.buildPreview(combined);
      },

      buildPreview: function (css) {
        var q = fieldValue('question1') || 'Sample question';
        var answers = ['a', 'b', 'c', 'd'].map(function (letter) {
          return fieldValue('answer1' + letter);
        }).filter(Boolean);
        if (!answers.length) answers = ['Option A', 'Option B'];
        var safeCss = String(css || '').replace(/<\/style/gi, '<\\/style');
        var options = answers.map(function (text, index) {
          return '<div id="option_container_' + index + '" class="Abox">' +
            '<div id="option_text_' + index + '" class="AText">' + escapeHtml(text) + '</div></div>';
        }).join('');
        return '<!DOCTYPE html><html><head><meta charset="utf-8">' +
          '<style>' + safeCss + '</style></head><body>' +
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
