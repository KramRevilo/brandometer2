#!/usr/bin/env python3
"""Load fictional agency-world demo surveys into Firestore + BigQuery.

Dry-run by default. Writes only with --apply. --purge is batch-scoped unless
you pass --all. Mark runs this in Cloud Shell against project brandometer2.

  # Homepage batch (220 surveys, demo_batch=demo-1)
  python3 tools/seed_demo_data.py --project brandometer2 --scenario homepage
  python3 tools/seed_demo_data.py --project brandometer2 --scenario homepage --apply

  # i18n batch (en/ja/zh/ar/he/de, demo_batch=i18n) — coexists with homepage
  python3 tools/seed_demo_data.py --project brandometer2 --scenario i18n
  python3 tools/seed_demo_data.py --project brandometer2 --scenario i18n --apply

  # Purge one batch, or every demo batch
  python3 tools/seed_demo_data.py --project brandometer2 --purge --batch demo-1
  python3 tools/seed_demo_data.py --project brandometer2 --purge --batch i18n --apply
  python3 tools/seed_demo_data.py --project brandometer2 --purge --all
  python3 tools/seed_demo_data.py --project brandometer2 --purge --all --apply

Every Firestore survey has demo_seed=true and a deterministic id (homepage:
demo_<seed>_<n>; i18n: demo_i18n_<lang>). Every BigQuery row has ID starting
with demo_ and RandomTimeStamp demo_seed:<batch>. Each fictional client has a
brand palette (BV2_THEME --bv2-* block: background, text, buttons, accent,
font, optional pattern) with campaign variation; every combo meets WCAG AA.
Re-running --apply for a scenario overwrites that batch only (themes included)
and replaces that batch's BQ rows (load job, not streaming insert, so purge
DELETE is not blocked by the streaming buffer).
"""
from __future__ import annotations

import argparse
import datetime
import io
import json
import os
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / 'creative' / 'app'
_APP_DIR = str(APP_DIR)
if _APP_DIR not in sys.path:
  sys.path.insert(0, _APP_DIR)
import css_theme  # noqa: E402

DEFAULT_PROJECT = 'brandometer2'
DEFAULT_COUNT = 220
MIN_COUNT = 200
DEFAULT_SEED = 1
ID_PREFIX = 'demo_'
STAMP_PREFIX = 'demo_seed:'
I18N_BATCH = 'i18n'
STATUS_ACTIVE_DAYS = 3
STATUS_STALE_DAYS = 7
BATCH_WRITES = 400
WCAG_AA_CONTRAST = 4.5
BATCH_NAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,62}$')

# Layout leftover kept beside the generated BV2_THEME block (no hardcoded green).
# Answer chrome (borders/gaps) also lives in the theme block and layout_fix overlay.
_LAYOUT_CSS = """body { margin: 0; display: block; }
.invisible { display: none; }
.Qbox {
    user-select: none;
    -webkit-user-select: none;
}
.Abox {
    border: 1px solid rgba(0, 0, 0, 0.35);
    border-radius: 5px;
    margin: 0;
    cursor: pointer;
    user-select: none;
    -webkit-user-select: none;
    -webkit-tap-highlight-color: transparent;
}
#next_button {
    padding: 3px 15px;
    border-radius: 4px;
    display: inline-block;
    cursor: pointer;
    user-select: none;
    -webkit-user-select: none;
    -webkit-tap-highlight-color: transparent;
}
#ad_text {
    font-family: Arial, Helvetica, sans-serif;
    cursor: pointer;
    user-select: none;
    -webkit-user-select: none;
}
"""

_RGBA_RE = re.compile(
    r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([0-9.]+))?\s*\)',
    re.I)

# Fictional shops only — no real holding companies or consumer brands.
AGENCIES = (
    {
        'name': 'Northline Media',
        'domain': 'northline.example',
        'people': ('jess.harper', 'marco.vell', 'priya.sundaram'),
        'clients': (
            ('Harbor Grocer', 'groceries', 'Harbor Grocer',
             ('River Market', 'Oak Barrel Foods', 'Not sure')),
            ('Peak Motor Co', 'cars', 'Peak Motor Co',
             ('Summit Auto', 'Cedar Wheels', 'Not sure')),
            ('Arcade Forge', 'games', 'Arcade Forge',
             ('Pixel Harbor', 'Quest Lantern', 'Not sure')),
        ),
    },
    {
        'name': 'Cedar & Pine Collective',
        'domain': 'cedarpine.example',
        'people': ('nina.brook', 'owen.lattimer', 'samira.cho'),
        'clients': (
            ('Brightbyte Computers', 'computers', 'Brightbyte',
             ('Northpeak PCs', 'Lumen Boards', 'Not sure')),
            ('Ember Kitchen', 'restaurants', 'Ember Kitchen',
             ('Copper Spoon', 'Field Table', 'Not sure')),
            ('Loom & Lattice', 'clothes', 'Loom & Lattice',
             ('Threadwell', 'Harbor Cloth', 'Not sure')),
        ),
    },
    {
        'name': 'Riverbend Insights',
        'domain': 'riverbend.example',
        'people': ('theo.marsden', 'aisha.quen', 'lucas.fern'),
        'clients': (
            ('Maple Pantry', 'groceries', 'Maple Pantry',
             ('Harbor Grocer', 'Cinder Mill', 'Not sure')),
            ('Voltway Motors', 'cars', 'Voltway',
             ('Peak Motor Co', 'Driftline Autos', 'Not sure')),
            ('Neon Circuit Games', 'games', 'Neon Circuit',
             ('Arcade Forge', 'Quiet Pixel', 'Not sure')),
        ),
    },
    {
        'name': 'Halcyon Street',
        'domain': 'halcyon.example',
        'people': ('mira.dalton', 'ben.okada', 'cleo.nunez'),
        'clients': (
            ('Nimbus Workstations', 'computers', 'Nimbus',
             ('Brightbyte', 'Aero Desk', 'Not sure')),
            ('Copper Spoon', 'restaurants', 'Copper Spoon',
             ('Ember Kitchen', 'Nightbird Diner', 'Not sure')),
            ('Threadwell Apparel', 'clothes', 'Threadwell',
             ('Loom & Lattice', 'Pine & Wool', 'Not sure')),
        ),
    },
    {
        'name': 'Oak & Anchor',
        'domain': 'oakanchor.example',
        'people': ('ravi.holm', 'elena.pruitt'),
        'clients': (
            ('Field & Basket', 'groceries', 'Field & Basket',
             ('Maple Pantry', 'Harbor Grocer', 'Not sure')),
            ('Driftline Autos', 'cars', 'Driftline',
             ('Voltway', 'Peak Motor Co', 'Not sure')),
        ),
    },
)

# Per-client brand palettes. Campaigns share a family; index picks a variant.
# Keys must match AGENCIES client names. Values are css_theme picker fields
# (or {'preset': STYLE_PRESETS id} plus optional overrides).
CLIENT_BRANDS = {
    'Harbor Grocer': {
        'fonts': ('Georgia, serif', "'Open Sans', sans-serif"),
        'patterns': ('none',),
        'campaigns': (
            {'bg': '#14532D', 'question_color': '#ECFCCB',
             'answer_bg': '#F4C430', 'answer_color': '#1A1400',
             'accent': '#F4C430', 'panel': 'rgba(0, 0, 0, 0.42)'},
            {'bg': '#1B5E20', 'question_color': '#E8F5E9',
             'answer_bg': '#C5E1A5', 'answer_color': '#1B3A1A',
             'accent': '#C5E1A5', 'panel': 'rgba(0, 0, 0, 0.42)'},
            {'preset': 'classic'},
            {'bg': '#052E16', 'question_color': '#ECFCCB',
             'answer_bg': '#86EFAC', 'answer_color': '#052E16',
             'accent': '#86EFAC', 'panel': 'rgba(0, 0, 0, 0.45)'},
        ),
    },
    'Peak Motor Co': {
        'fonts': ('Helvetica, Arial, sans-serif', 'Arial, Helvetica, sans-serif'),
        'patterns': ('none',),
        'campaigns': (
            {'bg': '#1C1917', 'question_color': '#F5F5F4',
             'answer_bg': '#F59E0B', 'answer_color': '#1C1917',
             'accent': '#F59E0B', 'panel': 'rgba(0, 0, 0, 0.42)'},
            {'bg': '#292524', 'question_color': '#FAFAF9',
             'answer_bg': '#E7E5E4', 'answer_color': '#1C1917',
             'accent': '#E7E5E4', 'panel': 'rgba(0, 0, 0, 0.40)'},
            {'bg': '#44403C', 'question_color': '#FAFAF9',
             'answer_bg': '#FBBF24', 'answer_color': '#1C1917',
             'accent': '#FBBF24', 'panel': 'rgba(0, 0, 0, 0.38)'},
        ),
    },
    'Arcade Forge': {
        'fonts': ("'Courier New', Courier, monospace",
                  'Trebuchet MS, Helvetica, sans-serif'),
        'patterns': ('none', css_theme._STRIPES_HAZARD),
        'campaigns': (
            {'preset': 'safety-orange'},
            {'bg': '#2B1408', 'question_color': '#FFEDD5',
             'answer_bg': '#FBBF24', 'answer_color': '#1A0A00',
             'accent': '#FBBF24', 'panel': 'rgba(0, 0, 0, 0.42)'},
            {'bg': '#1A0A00', 'question_color': '#FFD6A5',
             'answer_bg': '#FF7A18', 'answer_color': '#1A0A00',
             'accent': '#FF7A18', 'panel': 'rgba(0, 0, 0, 0.45)'},
        ),
    },
    'Brightbyte Computers': {
        'fonts': ('system-ui, sans-serif', 'Arial, Helvetica, sans-serif'),
        'patterns': ('none',),
        'campaigns': (
            {'bg': '#0F172A', 'question_color': '#E0F2FE',
             'answer_bg': '#38BDF8', 'answer_color': '#0F172A',
             'accent': '#38BDF8', 'panel': 'rgba(0, 0, 0, 0.42)'},
            {'bg': '#1E293B', 'question_color': '#F8FAFC',
             'answer_bg': '#F8FAFC', 'answer_color': '#0F172A',
             'accent': '#F8FAFC', 'panel': 'rgba(0, 0, 0, 0.40)'},
            {'preset': 'royal-blue'},
        ),
    },
    'Ember Kitchen': {
        'fonts': ('Georgia, serif', "'Times New Roman', Times, serif"),
        'patterns': ('none',),
        'campaigns': (
            {'bg': '#7C2D12', 'question_color': '#FFEDD5',
             'answer_bg': '#FED7AA', 'answer_color': '#7C2D12',
             'accent': '#FED7AA', 'panel': 'rgba(0, 0, 0, 0.38)'},
            {'bg': '#431407', 'question_color': '#FFF7ED',
             'answer_bg': '#FDBA74', 'answer_color': '#431407',
             'accent': '#FDBA74', 'panel': 'rgba(0, 0, 0, 0.42)'},
            {'bg': '#7F1D1D', 'question_color': '#FEE2E2',
             'answer_bg': '#FCA5A5', 'answer_color': '#7F1D1D',
             'accent': '#FCA5A5', 'panel': 'rgba(0, 0, 0, 0.40)'},
        ),
    },
    'Loom & Lattice': {
        'fonts': ('Trebuchet MS, Helvetica, sans-serif', 'Georgia, serif'),
        'patterns': ('none',),
        'campaigns': (
            {'bg': '#4C1D3D', 'question_color': '#FCE7F3',
             'answer_bg': '#F9A8D4', 'answer_color': '#4C1D3D',
             'accent': '#F9A8D4', 'panel': 'rgba(0, 0, 0, 0.40)'},
            {'bg': '#831843', 'question_color': '#FDF2F8',
             'answer_bg': '#FBCFE8', 'answer_color': '#831843',
             'accent': '#FBCFE8', 'panel': 'rgba(0, 0, 0, 0.38)'},
            {'bg': '#FDF2F8', 'question_color': '#831843',
             'answer_bg': '#9D174D', 'answer_color': '#FDF2F8',
             'accent': '#9D174D', 'panel': 'rgba(255, 255, 255, 0.72)',
             'font_family': 'Georgia, serif'},
        ),
    },
    'Maple Pantry': {
        'fonts': ('Georgia, serif', "'Open Sans', sans-serif"),
        'patterns': ('none',),
        'campaigns': (
            {'bg': '#78350F', 'question_color': '#FFFBEB',
             'answer_bg': '#FBBF24', 'answer_color': '#78350F',
             'accent': '#FBBF24', 'panel': 'rgba(0, 0, 0, 0.40)'},
            {'bg': '#451A03', 'question_color': '#FEF3C7',
             'answer_bg': '#FDE68A', 'answer_color': '#451A03',
             'accent': '#FDE68A', 'panel': 'rgba(0, 0, 0, 0.42)'},
            {'bg': '#9A3412', 'question_color': '#FFF7ED',
             'answer_bg': '#FED7AA', 'answer_color': '#7C2D12',
             'accent': '#FED7AA', 'panel': 'rgba(0, 0, 0, 0.38)'},
        ),
    },
    'Voltway Motors': {
        'fonts': ('Helvetica, Arial, sans-serif', 'system-ui, sans-serif'),
        'patterns': ('none', css_theme._DOTS_WHITE),
        'campaigns': (
            {'preset': 'electric-cyan'},
            {'preset': 'ocean'},
            {'preset': 'navy-orange'},
            {'bg': '#012A4A', 'question_color': '#E0F2FE',
             'answer_bg': '#00B4D8', 'answer_color': '#012A4A',
             'accent': '#00B4D8', 'panel': 'rgba(0, 0, 0, 0.42)'},
        ),
    },
    'Neon Circuit Games': {
        'fonts': ("'Courier New', Courier, monospace",
                  'Trebuchet MS, Helvetica, sans-serif'),
        'patterns': (
            'none', css_theme._STRIPES_NEON, css_theme._CHECK_LIME,
            css_theme._CHECK_MAGENTA,
        ),
        'campaigns': (
            {'preset': 'electric-lime'},
            {'preset': 'neon-magenta'},
            {'preset': 'neon-stripes'},
            {'preset': 'magenta-checkers'},
        ),
    },
    'Nimbus Workstations': {
        'fonts': ('system-ui, sans-serif', 'Verdana, Geneva, sans-serif'),
        'patterns': ('none',),
        'campaigns': (
            {'bg': '#111827', 'question_color': '#F9FAFB',
             'answer_bg': '#E5E7EB', 'answer_color': '#111827',
             'accent': '#E5E7EB', 'panel': 'rgba(0, 0, 0, 0.42)'},
            {'bg': '#F3F4F6', 'question_color': '#111827',
             'answer_bg': '#111827', 'answer_color': '#F9FAFB',
             'accent': '#1D4ED8', 'panel': 'rgba(255, 255, 255, 0.72)'},
            {'bg': '#1F2937', 'question_color': '#F3F4F6',
             'answer_bg': '#93C5FD', 'answer_color': '#1F2937',
             'accent': '#93C5FD', 'panel': 'rgba(0, 0, 0, 0.40)'},
        ),
    },
    'Copper Spoon': {
        'fonts': ('Georgia, serif', "'Times New Roman', Times, serif"),
        'patterns': ('none',),
        'campaigns': (
            {'bg': '#3B1F0B', 'question_color': '#FFEDD5',
             'answer_bg': '#D97706', 'answer_color': '#1A0A00',
             'accent': '#D97706', 'panel': 'rgba(0, 0, 0, 0.40)'},
            {'bg': '#1A0A00', 'question_color': '#FDE68A',
             'answer_bg': '#F59E0B', 'answer_color': '#1A0A00',
             'accent': '#F59E0B', 'panel': 'rgba(0, 0, 0, 0.45)'},
            {'bg': '#78350F', 'question_color': '#FFFBEB',
             'answer_bg': '#FBBF24', 'answer_color': '#1C1917',
             'accent': '#FBBF24', 'panel': 'rgba(0, 0, 0, 0.38)'},
        ),
    },
    'Threadwell Apparel': {
        'fonts': ('Georgia, serif', 'Trebuchet MS, Helvetica, sans-serif'),
        'patterns': ('none',),
        'campaigns': (
            {'bg': '#1E293B', 'question_color': '#F8FAFC',
             'answer_bg': '#D4AF37', 'answer_color': '#1E293B',
             'accent': '#D4AF37', 'panel': 'rgba(0, 0, 0, 0.40)'},
            {'bg': '#0F172A', 'question_color': '#E2E8F0',
             'answer_bg': '#F8FAFC', 'answer_color': '#0F172A',
             'accent': '#F8FAFC', 'panel': 'rgba(0, 0, 0, 0.42)'},
            {'bg': '#312E81', 'question_color': '#EEF2FF',
             'answer_bg': '#C7D2FE', 'answer_color': '#312E81',
             'accent': '#C7D2FE', 'panel': 'rgba(0, 0, 0, 0.38)'},
        ),
    },
    'Field & Basket': {
        'fonts': ('Georgia, serif', "'Open Sans', sans-serif"),
        'patterns': ('none',),
        'campaigns': (
            {'bg': '#365314', 'question_color': '#ECFCCB',
             'answer_bg': '#FACC15', 'answer_color': '#365314',
             'accent': '#FACC15', 'panel': 'rgba(0, 0, 0, 0.40)'},
            {'bg': '#1A2E05', 'question_color': '#F7FEE7',
             'answer_bg': '#84CC16', 'answer_color': '#1A2E05',
             'accent': '#84CC16', 'panel': 'rgba(0, 0, 0, 0.42)'},
            {'bg': '#3F6212', 'question_color': '#FEFCE8',
             'answer_bg': '#FDE047', 'answer_color': '#3F6212',
             'accent': '#FDE047', 'panel': 'rgba(0, 0, 0, 0.38)'},
        ),
    },
    'Driftline Autos': {
        'fonts': ('Helvetica, Arial, sans-serif', 'Verdana, Geneva, sans-serif'),
        'patterns': ('none',),
        'campaigns': (
            {'bg': '#134E4A', 'question_color': '#CCFBF1',
             'answer_bg': '#2DD4BF', 'answer_color': '#134E4A',
             'accent': '#2DD4BF', 'panel': 'rgba(0, 0, 0, 0.40)'},
            {'bg': '#042F2E', 'question_color': '#F0FDFA',
             'answer_bg': '#5EEAD4', 'answer_color': '#042F2E',
             'accent': '#5EEAD4', 'panel': 'rgba(0, 0, 0, 0.42)'},
            {'bg': '#164E63', 'question_color': '#CFFAFE',
             'answer_bg': '#22D3EE', 'answer_color': '#164E63',
             'accent': '#22D3EE', 'panel': 'rgba(0, 0, 0, 0.40)'},
        ),
    },
}


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
  raw = css_theme.normalize_color(value) or value
  if not raw.startswith('#'):
    raise ValueError('not a hex color: %s' % value)
  digits = raw[1:]
  if len(digits) == 3:
    digits = ''.join(ch * 2 for ch in digits)
  return tuple(int(digits[i:i + 2], 16) for i in (0, 2, 4))


def _srgb_channel_to_lin(channel: float) -> float:
  s = channel / 255.0
  return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str) -> float:
  red, green, blue = _hex_to_rgb(color)
  return (
      0.2126 * _srgb_channel_to_lin(red)
      + 0.7152 * _srgb_channel_to_lin(green)
      + 0.0722 * _srgb_channel_to_lin(blue))


def contrast_ratio(foreground: str, background: str) -> float:
  lighter = max(relative_luminance(foreground), relative_luminance(background))
  darker = min(relative_luminance(foreground), relative_luminance(background))
  return (lighter + 0.05) / (darker + 0.05)


def parse_color_rgba(value: str) -> tuple[int, int, int, float]:
  raw = (value or '').strip()
  match = _RGBA_RE.fullmatch(raw)
  if match:
    alpha = float(match.group(4)) if match.group(4) is not None else 1.0
    return int(match.group(1)), int(match.group(2)), int(match.group(3)), alpha
  red, green, blue = _hex_to_rgb(raw)
  return red, green, blue, 1.0


def composite_hex(overlay: str, background: str) -> str:
  """Blend overlay (hex or rgba) over a solid background; return #rrggbb."""
  fr, fg, fb, alpha = parse_color_rgba(overlay)
  br, bg, bb = _hex_to_rgb(background)
  red = int(round(alpha * fr + (1.0 - alpha) * br))
  green = int(round(alpha * fg + (1.0 - alpha) * bg))
  blue = int(round(alpha * fb + (1.0 - alpha) * bb))
  return '#%02x%02x%02x' % (red, green, blue)


def hex_hue(color: str) -> float | None:
  red, green, blue = [channel / 255.0 for channel in _hex_to_rgb(color)]
  mx, mn = max(red, green, blue), min(red, green, blue)
  delta = mx - mn
  if delta < 1e-6:
    return None
  if mx == red:
    hue = ((green - blue) / delta) % 6
  elif mx == green:
    hue = (blue - red) / delta + 2
  else:
    hue = (red - green) / delta + 4
  return (hue * 60.0) % 360.0


def _with_px(size) -> str:
  text = str(size or '13px').strip()
  if text.endswith('px'):
    return text
  return text + 'px'


def _preset_theme(preset_id: str) -> dict:
  preset = next(item for item in css_theme.STYLE_PRESETS if item['id'] == preset_id)
  return {
      'bg': preset['bg'],
      'question_color': preset['question_color'],
      'answer_bg': preset['answer_bg'],
      'answer_color': preset['answer_color'],
      'accent': preset['accent'],
      'panel': preset['panel'],
      'bg_pattern': preset.get('bg_pattern') or 'none',
      'font_family': preset.get('font_family') or css_theme.DEFAULT_THEME['font_family'],
      'font_size': _with_px(preset.get('font_size') or '13'),
      'bg_image': '',
  }


def resolve_campaign(entry: dict) -> dict:
  theme = dict(entry)
  preset_id = theme.pop('preset', None)
  resolved = _preset_theme(preset_id) if preset_id else {}
  resolved.update(theme)
  resolved.setdefault('accent', resolved.get('answer_bg') or css_theme.DEFAULT_THEME['accent'])
  resolved.setdefault('panel', css_theme.DEFAULT_THEME['panel'])
  resolved.setdefault('bg_pattern', 'none')
  resolved.setdefault('bg_image', '')
  resolved.setdefault(
      'font_family', css_theme.DEFAULT_THEME['font_family'])
  resolved['font_size'] = _with_px(resolved.get('font_size') or '13px')
  return resolved


def theme_contrast_pairs(theme: dict) -> list[tuple[str, str, str]]:
  """Named (label, foreground, background) pairs that must meet WCAG AA."""
  panel_bg = composite_hex(theme['panel'], theme['bg'])
  return [
      ('question_on_panel', theme['question_color'], panel_bg),
      ('answer_on_button', theme['answer_color'], theme['answer_bg']),
      ('answer_on_accent', theme['answer_color'], theme['accent']),
  ]


def theme_meets_aa(theme: dict) -> bool:
  return all(
      contrast_ratio(fg, bg) >= WCAG_AA_CONTRAST
      for _, fg, bg in theme_contrast_pairs(theme))


def require_theme_aa(theme: dict) -> None:
  failures = []
  for label, fg, bg in theme_contrast_pairs(theme):
    ratio = contrast_ratio(fg, bg)
    if ratio < WCAG_AA_CONTRAST:
      failures.append('%s %s on %s ratio=%.2f' % (label, fg, bg, ratio))
  if failures:
    raise ValueError('theme fails WCAG AA: ' + '; '.join(failures))


def brand_backgrounds(client_name: str) -> set[str]:
  brand = CLIENT_BRANDS[client_name]
  return {resolve_campaign(entry)['bg'].lower() for entry in brand['campaigns']}


def theme_for_client(client_name: str, index: int, seed: int,
                     n_clients: int | None = None) -> dict:
  """Deterministic BV2 picker theme: client family + campaign variation."""
  brand = CLIENT_BRANDS[client_name]
  campaigns = brand['campaigns']
  stride = n_clients if n_clients else len(_flat_clients())
  campaign_i = (index // stride) % len(campaigns)
  theme = resolve_campaign(campaigns[campaign_i])
  rng = random.Random(seed * 91711 + index * 13 + 7)
  fonts = brand.get('fonts') or (css_theme.DEFAULT_THEME['font_family'],)
  if rng.random() < 0.45:
    theme['font_family'] = fonts[rng.randrange(len(fonts))]
  theme['font_size'] = ('12px', '13px', '13px', '14px')[rng.randrange(4)]
  extra_patterns = [p for p in brand.get('patterns') or ('none',) if p != 'none']
  if theme.get('bg_pattern') in (None, 'none') and extra_patterns and rng.random() < 0.22:
    theme['bg_pattern'] = extra_patterns[rng.randrange(len(extra_patterns))]
  theme.setdefault('bg_pattern', 'none')
  theme.setdefault('bg_image', '')
  require_theme_aa(theme)
  return theme


def survey_custom_css(theme: dict) -> str:
  return css_theme.combine_css(theme, _LAYOUT_CSS)


_NAME_TEMPLATES = {
    'groceries': (
        'Q3 Summer BBQ Sauce Awareness – {region}',
        '{brand} Pasta Sauce Consideration Wave {wave}',
        'Holiday Baking Mix Recall – {region}',
        '{brand} Organic Produce Lift Wave {wave}',
    ),
    'cars': (
        'EV Crossover Launch Consideration Wave {wave}',
        '{brand} Hybrid Hatchback Recall – {region}',
        'Q1 Truck Bed Accessory Awareness',
        '{brand} Crossover Brand Lift – {region}',
    ),
    'games': (
        'Autumn RPG Launch Awareness – {region}',
        '{brand} Console Bundle Consideration Wave {wave}',
        'Season Pass Brand Recall – {region}',
        '{brand} Co-op Title Lift Wave {wave}',
    ),
    'computers': (
        'Ultrabook Refresh Awareness Wave {wave}',
        '{brand} Workstation Brand Lift – Enterprise',
        'Back-to-Campus Laptop Consideration – {region}',
        '{brand} Monitor Launch Recall Wave {wave}',
    ),
    'restaurants': (
        'Late-Night Drive-Thru Awareness – {region}',
        '{brand} Bowl Menu Consideration Wave {wave}',
        'Breakfast Sandwich Recall – {region}',
        '{brand} Loyalty App Lift Wave {wave}',
    ),
    'clothes': (
        'Fall Denim Drop Awareness – {region}',
        '{brand} Athleisure Launch Consideration Wave {wave}',
        'Holiday Outerwear Recall – {region}',
        '{brand} Knitwear Brand Lift Wave {wave}',
    ),
}

_REGIONS = ('CA', 'TX', 'FL', 'NY', 'IL', 'WA', 'NA')
_WAVES = ('1', '2', '3', '4')
_SIZES_SINGLE = (
    ('300x250',),
    ('300x250',),
    ('160x600',),
    ('300x600',),
    ('336x280',),
    ('970x250',),
)
_SIZES_MULTI = (
    ('300x250', '336x280'),
    ('300x250', '970x250'),
    ('160x600', '300x600'),
)


def classify_status(days):
  if days is None:
    return 'No data'
  if days <= STATUS_ACTIVE_DAYS:
    return 'Active'
  if days <= STATUS_STALE_DAYS:
    return 'Stale'
  return 'Timed out'


def survey_id(seed: int, index: int) -> str:
  return '%s%s_%04d' % (ID_PREFIX, seed, index)


def batch_id(seed: int) -> str:
  return 'demo-%s' % seed


def validate_batch(name: str) -> str:
  text = str(name or '').strip()
  if not BATCH_NAME_RE.match(text):
    raise ValueError('invalid demo batch %r' % name)
  return text


def is_demo_survey_id(sid: str) -> bool:
  return bool(sid) and str(sid).startswith(ID_PREFIX)


def is_demo_bq_row(row: dict) -> bool:
  sid = str(row.get('ID') or '')
  stamp = str(row.get('RandomTimeStamp') or '')
  rid = str(row.get('RespondentID') or '')
  return (
      sid.startswith(ID_PREFIX)
      and stamp.startswith(STAMP_PREFIX)
      and (not rid or rid.startswith(ID_PREFIX)))


def bq_purge_sql(table_id: str, batch: str | None = None) -> str:
  """DELETE tagged demo rows. CreatedAt filter satisfies partition tables.

  batch=None deletes every demo_seed: stamp. A batch value (already
  validate_batch'd) limits RandomTimeStamp to demo_seed:<batch>.
  """
  sql = (
      'DELETE FROM `%s`\n'
      'WHERE CreatedAt >= DATETIME_SUB(CURRENT_DATETIME(), INTERVAL 800 DAY)\n'
      '  AND STARTS_WITH(ID, "%s")\n'
      '  AND STARTS_WITH(RandomTimeStamp, "%s")'
      % (table_id, ID_PREFIX, STAMP_PREFIX)
  )
  if batch:
    sql += '\n  AND RandomTimeStamp = "%s%s"' % (STAMP_PREFIX, validate_batch(batch))
  return sql


@dataclass
class SurveySpec:
  id: str
  index: int
  doc: dict
  audit: dict
  last_days: int | None
  last_at: datetime.datetime | None
  counts: dict
  n_rows: int
  extra_incomplete: bool
  omit_rid: bool
  p_control: float
  p_expose: float
  n_questions: int
  theme: dict
  expected_status: str = field(init=False)

  def __post_init__(self):
    self.expected_status = classify_status(self.last_days)


@dataclass
class World:
  seed: int
  count: int
  now: datetime.datetime
  batch: str
  surveys: list
  n_rows: int
  n_archived: int
  n_lift: int


def _email(local: str, domain: str) -> str:
  return '%s@%s' % (local, domain)


def _flat_clients():
  out = []
  for agency in AGENCIES:
    people = [_email(p, agency['domain']) for p in agency['people']]
    for i, client in enumerate(agency['clients']):
      out.append({
          'agency': agency['name'],
          'domain': agency['domain'],
          'client': client[0],
          'category': client[1],
          'brand': client[2],
          'rivals': client[3],
          'creators': people,
          'creator': people[i % len(people)],
      })
  return out


def _pick_datetime(rng: random.Random, now: datetime.datetime, lo: int, hi: int):
  """Weekday-weighted, business-hours, with campaign-season bursts."""
  burst_months = {1, 2, 6, 7, 8, 11}
  picked = None
  for _ in range(60):
    days = rng.randint(lo, hi)
    hour = rng.choice([8, 9, 10, 11, 13, 14, 15, 16, 17] + [12, 18] * 1)
    minute = rng.randint(0, 59)
    second = rng.randint(0, 59)
    base = now - datetime.timedelta(days=days)
    candidate = base.replace(hour=hour, minute=minute, second=second, microsecond=0)
    if candidate > now:
      continue
    weekday = candidate.weekday()
    if weekday >= 5 and rng.random() > 0.22:
      continue
    if candidate.month in burst_months or rng.random() < 0.55:
      return candidate
    picked = candidate
  return picked or now - datetime.timedelta(days=lo, hours=3)


def _lifecycle(index: int) -> str:
  return (
      'none', 'tiny', 'tiny', 'small', 'small',
      'small', 'medium', 'medium', 'large', 'xl',
      'active', 'active', 'stale', 'timed', 'negative',
      'flat', 'positive', 'new', 'archived', 'medium',
  )[index % 20]


def _band_n(rng: random.Random, band: str, lift: bool) -> tuple[int, int, int | None]:
  """Return (n_control_or_track, n_expose, last_days). last_days None = no rows."""
  if band in ('none', 'new') and rng.random() < 0.55:
    return 0, 0, None
  if band == 'none':
    return 0, 0, None
  if band in ('tiny', 'new'):
    n = rng.randint(6, 24)
    last = rng.randint(0, 2)
  elif band == 'small':
    n = rng.randint(40, 90)
    last = rng.choice([0, 1, 2, 5, 9, 20])
  elif band == 'stale':
    n = rng.randint(80, 220)
    last = rng.randint(4, 7)
  elif band == 'timed':
    n = rng.randint(120, 400)
    last = rng.randint(14, 180)
  elif band == 'archived':
    n = rng.randint(60, 300)
    last = rng.randint(40, 200)
  elif band == 'large':
    n = rng.randint(600, 1200)
    last = rng.randint(0, 3)
  elif band == 'xl':
    n = rng.randint(1800, 3200)
    last = rng.randint(0, 2)
  elif band == 'active':
    n = rng.randint(150, 500)
    last = rng.randint(0, 3)
  else:
    n = rng.randint(120, 420)
    last = rng.randint(0, 10)
  if not lift:
    return n, 0, last
  n_c = int(round(n * rng.uniform(0.47, 0.53)))
  n_e = max(0, n - n_c)
  return n_c, n_e, last


def _lift_rates(band: str, rng: random.Random) -> tuple[float, float]:
  p_c = rng.uniform(0.18, 0.24)
  if band == 'negative':
    return p_c, max(0.08, p_c - rng.uniform(0.06, 0.10))
  if band == 'flat':
    return p_c, p_c + rng.uniform(-0.01, 0.01)
  if band in ('positive', 'xl', 'large', 'active'):
    return p_c, min(0.45, p_c + rng.uniform(0.07, 0.14))
  return p_c, min(0.40, p_c + rng.uniform(0.02, 0.08))


def _sizes(rng: random.Random, n_answers: int) -> list[str]:
  if n_answers > 5:
    return list(rng.choice((('160x600',), ('300x600',), ('160x600', '300x600'))))
  if rng.random() < 0.28:
    return list(rng.choice(_SIZES_MULTI))
  return list(rng.choice(_SIZES_SINGLE))


def _questions(client: dict, n_answers: int, n_questions: int, lift: bool):
  brand = client['brand']
  options = [brand] + list(client['rivals'])
  while len(options) < n_answers:
    options.append('None of these')
  options = options[:n_answers]
  if lift:
    q1 = 'Which of these brands did you notice recently?'
  else:
    q1 = 'Which would you consider next time you shop?'
  questions = [{'text': q1, 'answers': options}]
  if n_questions >= 2:
    questions.append({
        'text': 'Did you see an ad for %s in the last week?' % brand,
        'answers': ['Yes', 'No', 'Not sure', 'Prefer not to say'][:max(2, min(4, n_answers))],
    })
  if n_questions >= 3:
    questions.append({
        'text': 'How likely are you to choose %s?' % brand,
        'answers': ['Very likely', 'Somewhat likely', 'Not likely', 'Not sure'][:max(2, min(4, n_answers))],
    })
  return questions


def _fill_question_fields(doc: dict, questions: list) -> None:
  letters = 'abcdefgh'
  for i, q in enumerate(questions, start=1):
    doc['question%s' % i] = q['text']
    doc['question%stype' % i] = 'radio'
    doc['question%sorder' % i] = 'SHUFFLED'
    for j, ans in enumerate(q['answers']):
      letter = letters[j]
      doc['answer%s%s' % (i, letter)] = ans
      doc['answer%s%snext' % (i, letter)] = 'end'


def generate_world(count: int, seed: int, now: datetime.datetime | None = None) -> World:
  if now is None:
    now = datetime.datetime.now(datetime.timezone.utc)
  if now.tzinfo is None:
    now = now.replace(tzinfo=datetime.timezone.utc)
  rng = random.Random(seed)
  clients = _flat_clients()
  batch = batch_id(seed)
  surveys = []
  n_rows = 0
  n_archived = 0
  n_lift = 0
  for index in range(count):
    client = clients[index % len(clients)]
    creator = client['creator']
    band = _lifecycle(index)
    lift = client['category'] in ('groceries', 'cars', 'computers') and (index % 5 != 1)
    if client['category'] in ('games', 'restaurants', 'clothes'):
      lift = index % 3 == 0
    n_answers = 8 if (lift is False and index % 17 == 0) else rng.choice((3, 4, 4, 5))
    n_questions = 1 if lift else rng.choice((1, 1, 2, 3))
    sizes = _sizes(rng, n_answers)
    n_c, n_e, last_days = _band_n(rng, band, lift)
    archived = band == 'archived' or (
        last_days is not None and last_days > 90 and rng.random() < 0.35)
    if archived:
      n_archived += 1
    created_hi = 520 if archived or band in ('timed',) else 280
    created_lo = (last_days or 0) + 5
    if created_lo >= created_hi:
      created_hi = created_lo + 20
    created = _pick_datetime(rng, now, created_lo, created_hi)
    last_at = None
    if last_days is not None and (n_c + n_e) > 0:
      last_at = now - datetime.timedelta(
          days=last_days, hours=rng.randint(0, 8), minutes=rng.randint(0, 59))
      if last_at < created:
        last_at = created + datetime.timedelta(hours=6)
        last_days = max(0, (now - last_at).days)
    p_c, p_e = _lift_rates(band, rng)
    sid = survey_id(seed, index)
    region = _REGIONS[index % len(_REGIONS)]
    wave = _WAVES[index % len(_WAVES)]
    template = _NAME_TEMPLATES[client['category']][index % 4]
    display = template.format(brand=client['brand'], region=region, wave=wave)
    name = '%s-%s-%04d' % (
        client['client'].lower().replace(' ', '-').replace('&', 'and'),
        'lift' if lift else 'track', index)
    extra_incomplete = (not lift) and n_questions > 1 and (n_c + n_e) >= 20 and index % 11 == 0
    omit_rid = index % 23 == 0
    theme = theme_for_client(client['client'], index, seed, n_clients=len(clients))
    counts = {}
    rows = 0
    if lift:
      if n_c:
        counts['default_control'] = n_c
      if n_e:
        counts['default_expose'] = n_e
      rows = n_c + n_e
      n_lift += 1
    else:
      if n_c:
        counts['survey'] = n_c
      rows = n_c
    if extra_incomplete:
      rows += max(1, int(0.12 * (n_c + n_e)))
    n_rows += rows
    questions = _questions(client, n_answers, n_questions, lift)
    doc = {
        'surveyname': name[:80],
        'displayname': display,
        'surveytype': 'brand_lift' if lift else 'brand_track',
        'archived': archived,
        'client': client['client'],
        'agency': client['agency'],
        'created_at': created.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'created_by': creator,
        'updated_at': (last_at or created).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'updated_by': creator,
        'creativesizes': sizes,
        'creativesize': sizes[0] if len(sizes) == 1 else sizes,
        'language': 'en',
        'responsetype': (
            'Submit Responses after each Question' if extra_incomplete
            else 'Submit Responses at End of Survey'),
        'custom_css': survey_custom_css(theme),
        'badge_icon': (
            'Name' if index % 3 == 0 else ('B2' if index % 4 == 0 else 'B')),
        'badge_name': client['agency'],
        'badge_text': '',
        'demo_seed': True,
        'demo_batch': batch,
        'campaign_id': 'cmp-%s' % sid if index % 6 == 0 else '',
        'placement_id': 'plc-%s' % sid if index % 6 == 0 else '',
        'adserver': 'cm360',
    }
    _fill_question_fields(doc, questions)
    if lift and index % 9 == 0 and (n_c + n_e) >= 80:
      doc['sample_plan'] = {
          'baseline': 0.2,
          'mde_mode': 'relative',
          'mde_relative': 0.1,
          'mde_absolute': 0.05,
          'confidence': 0.95,
          'power': 0.8,
          'comparisons': 1,
          'response_rate': 0.01,
          'control_share': 0.5,
          'n_control': max(30, n_c or 200),
          'n_expose': max(30, n_e or 200),
          'n_total': max(60, (n_c or 200) + (n_e or 200)),
      }
    audit = {
        'action': 'create',
        'actor': creator,
        'survey_id': sid,
        'detail': name[:80],
        'created_at': doc['created_at'],
        'demo_seed': True,
        'demo_batch': batch,
    }
    spec = SurveySpec(
        id=sid,
        index=index,
        doc=doc,
        audit=audit,
        last_days=last_days,
        last_at=last_at,
        counts=counts,
        n_rows=rows,
        extra_incomplete=extra_incomplete,
        omit_rid=omit_rid,
        p_control=p_c,
        p_expose=p_e,
        n_questions=n_questions,
        theme=theme,
    )
    surveys.append(spec)
  return World(
      seed=seed, count=count, now=now, batch=batch, surveys=surveys,
      n_rows=n_rows, n_archived=n_archived, n_lift=n_lift)


# Small translated set (RTL + LTR, long thank-you, both common sizes).
I18N_SURVEYS = (
    {
        'code': 'en',
        'question': 'Which grocery brand did you notice?',
        'answers': ('Harbor Grocer', 'River Market', 'Not sure'),
        'thankyou': (
            'Thank you so much for taking this survey. We really appreciate '
            'your time and feedback today.'),
        'display': 'Harbor Grocer (English)',
    },
    {
        'code': 'ja',
        'question': '最近どの食料品ブランドに気づきましたか？',
        'answers': ('ハーバーグロッサー', 'リバーマーケット', 'わからない'),
        'thankyou': 'このアンケートにご協力いただき、誠にありがとうございました。',
        'display': 'Harbor Grocer (日本語)',
    },
    {
        'code': 'zh',
        'question': '您最近注意到哪个杂货品牌？',
        'answers': ('海港杂货', '河市', '不确定'),
        'thankyou': '谢谢您抽出时间完成这份问卷，我们非常感谢您的反馈。',
        'display': 'Harbor Grocer (中文)',
    },
    {
        'code': 'ar',
        'question': 'أي علامة تجارية للبقالة لاحظتها مؤخراً؟',
        'answers': ('هاربر للبقالة', 'سوق النهر', 'غير متأكد'),
        'thankyou': (
            'شكراً جزيلاً على الوقت الذي أمضيته في هذا الاستطلاع. '
            'نقدر ملاحظاتك كثيراً.'),
        'display': 'Harbor Grocer (العربية)',
    },
    {
        'code': 'he',
        'question': 'באיזה מותג מכולת שמתם לב לאחרונה?',
        'answers': ('הארבור גרוסר', 'שוק הנהר', 'לא בטוח'),
        'thankyou': (
            'תודה רבה על שהקדשתם זמן לסקר הזה. '
            'אנחנו מעריכים את המשוב שלכם.'),
        'display': 'Harbor Grocer (עברית)',
    },
    {
        'code': 'de',
        'question': 'Welche Lebensmittelmarke ist Ihnen kürzlich aufgefallen?',
        'answers': ('Harbor Grocer', 'River Market', 'Nicht sicher'),
        'thankyou': (
            'Vielen Dank, dass Sie sich die Zeit für diese Umfrage genommen '
            'haben. Ihr Feedback ist uns wichtig.'),
        'display': 'Harbor Grocer (Deutsch)',
    },
)


def i18n_survey_id(code: str) -> str:
  return '%si18n_%s' % (ID_PREFIX, code)


def generate_i18n_world(now: datetime.datetime | None = None,
                        seed: int = DEFAULT_SEED) -> World:
  """Six translated Brand Track surveys tagged demo_batch=i18n."""
  if now is None:
    now = datetime.datetime.now(datetime.timezone.utc)
  if now.tzinfo is None:
    now = now.replace(tzinfo=datetime.timezone.utc)
  rng = random.Random(seed * 17 + 9)
  client = next(c for c in _flat_clients() if c['client'] == 'Harbor Grocer')
  created = now - datetime.timedelta(days=12, hours=3)
  last_at = now - datetime.timedelta(hours=rng.randint(2, 10))
  last_days = 0
  n_each = 48
  surveys = []
  for index, item in enumerate(I18N_SURVEYS):
    sid = i18n_survey_id(item['code'])
    theme = theme_for_client(client['client'], index, seed, n_clients=1)
    questions = [{'text': item['question'], 'answers': list(item['answers'])}]
    doc = {
        'surveyname': 'harbor-grocer-i18n-%s' % item['code'],
        'displayname': item['display'],
        'surveytype': 'brand_track',
        'archived': False,
        'client': client['client'],
        'agency': client['agency'],
        'created_at': created.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'created_by': client['creator'],
        'updated_at': last_at.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'updated_by': client['creator'],
        'creativesizes': ['300x250', '160x600'],
        'creativesize': ['300x250', '160x600'],
        'language': item['code'],
        'thankyou_text': item['thankyou'],
        'responsetype': 'Submit Responses at End of Survey',
        'custom_css': survey_custom_css(theme),
        'badge_icon': 'B',
        'badge_name': client['agency'],
        'badge_text': '',
        'demo_seed': True,
        'demo_batch': I18N_BATCH,
        'campaign_id': '',
        'placement_id': '',
        'adserver': 'cm360',
    }
    _fill_question_fields(doc, questions)
    doc['question1order'] = 'ORDERED'
    audit = {
        'action': 'create',
        'actor': client['creator'],
        'survey_id': sid,
        'detail': doc['surveyname'],
        'created_at': doc['created_at'],
        'demo_seed': True,
        'demo_batch': I18N_BATCH,
    }
    spec = SurveySpec(
        id=sid,
        index=index,
        doc=doc,
        audit=audit,
        last_days=last_days,
        last_at=last_at,
        counts={'survey': n_each},
        n_rows=n_each,
        extra_incomplete=False,
        omit_rid=False,
        p_control=0.22,
        p_expose=0.22,
        n_questions=1,
        theme=theme,
    )
    surveys.append(spec)
  return World(
      seed=seed, count=len(surveys), now=now, batch=I18N_BATCH,
      surveys=surveys, n_rows=n_each * len(surveys), n_archived=0, n_lift=0)


def _answer_letter(positive: bool, n_answers: int, rng: random.Random) -> str:
  if positive:
    return 'A'
  choices = [chr(ord('A') + i) for i in range(1, max(2, n_answers))]
  return rng.choice(choices)


def _response_text(spec: SurveySpec, positive: bool, rng: random.Random, complete: bool) -> str:
  n_answers = 4
  letters = []
  limit = spec.n_questions if complete else 1
  for q in range(1, limit + 1):
    letter = _answer_letter(positive if q == 1 else rng.random() < 0.5, n_answers, rng)
    letters.append('%s:%s' % (q, letter))
  return '|'.join(letters)


def _spread_times(created, last_at, n, rng):
  if n <= 0 or last_at is None:
    return []
  start = created
  end = last_at
  if end <= start:
    end = start + datetime.timedelta(hours=2)
  span = (end - start).total_seconds()
  times = []
  for i in range(n):
    frac = (i + 0.5) / n
    jitter = rng.uniform(-0.4, 0.4) / max(n, 1)
    t = start + datetime.timedelta(seconds=max(0, span * (frac + jitter)))
    if t > end:
      t = end - datetime.timedelta(seconds=rng.randint(0, 90))
    if t < start:
      t = start
    times.append(t.replace(microsecond=0))
  times.sort()
  times[-1] = end.replace(microsecond=0)
  return times


def iter_response_rows(world: World, spec: SurveySpec | None = None) -> Iterable[dict]:
  targets = [spec] if spec is not None else world.surveys
  for item in targets:
    rng = random.Random(world.seed * 100003 + item.index)
    created = datetime.datetime.strptime(
        item.doc['created_at'], '%Y-%m-%dT%H:%M:%SZ').replace(
            tzinfo=datetime.timezone.utc)
    last_at = item.last_at or created
    sizes = item.doc.get('creativesizes') or ['300x250']
    size = sizes[0]
    lift = item.doc.get('surveytype') == 'brand_lift'
    segments = []
    if lift:
      segments = (
          [('default_control', item.counts.get('default_control', 0), item.p_control)]
          + [('default_expose', item.counts.get('default_expose', 0), item.p_expose)])
    else:
      segments = [('survey', item.counts.get('survey', 0), item.p_control)]
    seq = 0
    for seg, n, p_pos in segments:
      times = _spread_times(created, last_at, n, rng)
      for i, when in enumerate(times):
        seq += 1
        positive = rng.random() < p_pos
        rid = '%s%s_%06d' % (ID_PREFIX, item.id, seq)
        bom = rid
        row = {
            'CreatedAt': when.strftime('%Y-%m-%dT%H:%M:%S'),
            'Type': 'survey',
            'ID': item.id,
            'Segmentation': seg,
            'Response': _response_text(item, positive, rng, complete=True),
            'Visual': '',
            'CreativeSize': size,
            'RandomTimeStamp': STAMP_PREFIX + world.batch,
            'BomID': bom,
            'RespondentID': '' if item.omit_rid else rid,
            'RespondentIDSource': '' if item.omit_rid else 'bomid',
            'CampaignID': item.doc.get('campaign_id') or '',
            'PlacementID': item.doc.get('placement_id') or '',
            'SiteID': '',
            'AdCreativeID': '',
            'CreativeVersion': 1,
        }
        yield row
        if item.extra_incomplete and i < max(1, int(0.12 * n)):
          earlier = when - datetime.timedelta(minutes=rng.randint(2, 40))
          if earlier < created:
            earlier = created
          incomplete = dict(row)
          incomplete['CreatedAt'] = earlier.strftime('%Y-%m-%dT%H:%M:%S')
          incomplete['Response'] = _response_text(item, positive, rng, complete=False)
          incomplete['BomID'] = bom
          incomplete['RespondentID'] = row['RespondentID']
          yield incomplete


def counts_frame_from_world(world: World, ids=None):
  """Homepage stats-shaped rows from plans (no BQ)."""
  import pandas
  rows = []
  wanted = set(ids) if ids else None
  for spec in world.surveys:
    if wanted is not None and spec.id not in wanted:
      continue
    if not spec.counts:
      continue
    last_date = (
        spec.last_at.date().isoformat() if spec.last_at is not None
        else world.now.date().isoformat())
    for seg, n in spec.counts.items():
      rows.append({
          'ID': spec.id,
          'Segmentation': seg,
          'max_date': last_date,
          'days_since_response': spec.last_days,
          'response_count': n,
      })
  if not rows:
    return pandas.DataFrame(
        columns=['ID', 'Segmentation', 'max_date', 'days_since_response',
                 'response_count'])
  return pandas.DataFrame(rows)


def mock_survey_docs(world: World):
  from unittest import mock
  docs = []
  for spec in world.surveys:
    doc = mock.Mock()
    doc.id = spec.id
    doc.to_dict.return_value = spec.doc
    doc.exists = True
    docs.append(doc)
  return docs


def summary_lines(world: World, sample: int = 8) -> list[str]:
  lines = [
      'Demo batch %s  seed=%s  surveys=%s  lift=%s  archived=%s  bq_rows≈%s'
      % (world.batch, world.seed, world.count, world.n_lift, world.n_archived,
         world.n_rows),
      'Agencies: ' + ', '.join(a['name'] for a in AGENCIES),
      'Tag: Firestore demo_seed=true demo_batch=%s; BQ ID %s* and RandomTimeStamp %s%s'
      % (world.batch, ID_PREFIX, STAMP_PREFIX, world.batch),
      'Themes: %s distinct --bv2-bg values across %s clients (BV2_THEME block; WCAG AA)'
      % (len({s.theme['bg'].lower() for s in world.surveys}),
         len({s.doc['client'] for s in world.surveys})),
      'Sample surveys:',
  ]
  for spec in world.surveys[:sample]:
    lines.append(
        '  %s  %s  %s / %s  %s  last=%s  %s  rows≈%s  counts=%s  bg=%s'
        % (spec.id, spec.doc['displayname'][:48], spec.doc['agency'],
           spec.doc['client'], spec.doc['surveytype'], spec.last_days,
           spec.expected_status, spec.n_rows, spec.counts or '{}',
           spec.theme['bg']))
  return lines


def _fs_client(project: str):
  from google.cloud import firestore
  return firestore.Client(project=project)


def _bq_client(project: str):
  from google.cloud import bigquery
  return bigquery.Client(project=project)


def _new_batch(db):
  maker = getattr(db, 'batch', None)
  if callable(maker):
    try:
      return maker()
    except Exception:
      return None
  return None


def apply_firestore(db, world: World) -> int:
  """Overwrite this world's demo_batch. Other batches and live docs stay."""
  purge_firestore(db, dry_run=False, batch=world.batch)
  col = db.collection('Surveys')
  audit = db.collection('AuditLog')
  batch = _new_batch(db)
  pending = 0
  written = 0

  def flush():
    nonlocal batch, pending
    if batch is not None and pending:
      batch.commit()
      batch = _new_batch(db)
      pending = 0

  for spec in world.surveys:
    survey_ref = col.document(spec.id)
    audit_ref = audit.document('demo_audit_%s' % spec.id)
    if batch is None:
      survey_ref.set(spec.doc)
      audit_ref.set(spec.audit)
    else:
      batch.set(survey_ref, spec.doc)
      pending += 1
      batch.set(audit_ref, spec.audit)
      pending += 1
      if pending >= BATCH_WRITES:
        flush()
    written += 1
  flush()
  bookmark = {
      'demo_seed': True,
      'demo_batch': world.batch,
      'seed': world.seed,
      'count': world.count,
      'n_rows': world.n_rows,
      'applied_at': world.now.strftime('%Y-%m-%dT%H:%M:%SZ'),
  }
  db.collection('DemoSeed').document('current').set(bookmark)
  db.collection('DemoSeed').document(world.batch).set(bookmark)
  return written


def _is_tagged_survey(doc, batch: str | None = None) -> bool:
  data = doc.to_dict() or {}
  if not (data.get('demo_seed') is True and is_demo_survey_id(doc.id)):
    return False
  if batch is not None:
    return data.get('demo_batch') == batch
  return True


def _is_tagged_audit(doc, batch: str | None = None) -> bool:
  data = doc.to_dict() or {}
  sid = data.get('survey_id') or ''
  if not (data.get('demo_seed') is True and (
      is_demo_survey_id(sid) or str(doc.id).startswith('demo_audit_'))):
    return False
  if batch is not None:
    return data.get('demo_batch') == batch
  return True


def _purge_demoseed(db, batch: str | None, deleted: dict) -> None:
  col = db.collection('DemoSeed')
  if batch is None:
    for doc in col.stream():
      doc.reference.delete()
      deleted['demoseed'] += 1
    return
  for name in (batch,):
    ref = col.document(name)
    snap = ref.get()
    if getattr(snap, 'exists', False):
      ref.delete()
      deleted['demoseed'] += 1
  current = col.document('current')
  snap = current.get()
  if getattr(snap, 'exists', False):
    data = snap.to_dict() or {}
    if data.get('demo_batch') == batch:
      current.delete()
      deleted['demoseed'] += 1


def purge_firestore(db, dry_run: bool = True, batch: str | None = None) -> dict:
  if batch is not None:
    batch = validate_batch(batch)
  surveys = [
      doc for doc in db.collection('Surveys').stream()
      if _is_tagged_survey(doc, batch)
  ]
  audits = [
      doc for doc in db.collection('AuditLog').stream()
      if _is_tagged_audit(doc, batch)
  ]
  cache_ids = [doc.id for doc in surveys]
  deleted = {
      'surveys': 0, 'audits': 0, 'stats_cache': 0, 'versions': 0, 'demoseed': 0,
  }
  if dry_run:
    deleted['surveys'] = len(surveys)
    deleted['audits'] = len(audits)
    deleted['stats_cache'] = len(cache_ids)
    return deleted
  for doc in surveys:
    for ver in doc.reference.collection('versions').stream():
      ver.reference.delete()
      deleted['versions'] += 1
    doc.reference.delete()
    deleted['surveys'] += 1
  for doc in audits:
    doc.reference.delete()
    deleted['audits'] += 1
  cache = db.collection('StatsCache')
  for sid in cache_ids:
    ref = cache.document(sid)
    snap = ref.get()
    if getattr(snap, 'exists', False):
      ref.delete()
      deleted['stats_cache'] += 1
  _purge_demoseed(db, batch, deleted)
  return deleted


def apply_bigquery(client, table_id: str, world: World) -> int:
  from google.cloud import bigquery
  job = client.query(bq_purge_sql(table_id, batch=world.batch))
  job.result()
  buf = io.BytesIO()
  n = 0
  for row in iter_response_rows(world):
    buf.write((json.dumps(row) + '\n').encode('utf-8'))
    n += 1
  if n == 0:
    return 0
  buf.seek(0)
  # Load into the existing table. CreatedAt (DATETIME) is the DAY partition
  # field on new deploys; rows still load if the live table is unpartitioned.
  config = bigquery.LoadJobConfig(
      source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
      write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
      ignore_unknown_values=True,
  )
  load = client.load_table_from_file(buf, table_id, job_config=config)
  load.result()
  if load.errors:
    raise RuntimeError('BigQuery load errors: %s' % load.errors)
  return n


def purge_bigquery(client, table_id: str, dry_run: bool = True,
                   batch: str | None = None) -> str:
  sql = bq_purge_sql(table_id, batch=batch)
  if dry_run:
    return sql
  client.query(sql).result()
  return sql


def _prepare_env(project: str) -> None:
  os.environ['GOOGLE_CLOUD_PROJECT'] = project
  os.environ.setdefault('PROJECT_ID', project)
  os.environ.setdefault('TABLE_ID', '%s.responses.responses' % project)
  sys.path.insert(0, str(APP_DIR))


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--project', default=DEFAULT_PROJECT)
  parser.add_argument('--table', default='')
  parser.add_argument('--count', type=int, default=DEFAULT_COUNT)
  parser.add_argument('--seed', type=int, default=DEFAULT_SEED)
  parser.add_argument(
      '--scenario', choices=('homepage', 'i18n'), default='homepage',
      help='homepage: 220-survey agency world (demo-<seed>). '
           'i18n: six translated surveys (batch i18n).')
  parser.add_argument(
      '--batch', default='',
      help='With --purge, delete only this demo_batch (demo-1, i18n, …).')
  parser.add_argument(
      '--all', action='store_true', dest='purge_all',
      help='With --purge, delete every demo batch.')
  parser.add_argument('--apply', action='store_true',
                      help='Write (or, with --purge, actually delete).')
  parser.add_argument('--purge', action='store_true',
                      help='Remove tagged demo data. Requires --batch or --all. '
                           'Dry-run unless --apply.')
  args = parser.parse_args(argv)
  if (not args.purge and args.scenario == 'homepage'
      and args.count < MIN_COUNT):
    print('error: --count must be >= %s (need 4+ homepage pages at 50/page)'
          % MIN_COUNT, file=sys.stderr)
    return 2
  _prepare_env(args.project)
  table_id = args.table or os.environ['TABLE_ID']
  now = datetime.datetime.now(datetime.timezone.utc)

  if args.purge:
    if args.purge_all and args.batch:
      print('error: --purge takes --batch <id> or --all, not both',
            file=sys.stderr)
      return 2
    if not args.purge_all and not args.batch:
      print('error: --purge requires --batch <id> (e.g. demo-1 or i18n) '
            'or --all', file=sys.stderr)
      return 2
    try:
      batch = None if args.purge_all else validate_batch(args.batch)
    except ValueError as exc:
      print('error: %s' % exc, file=sys.stderr)
      return 2
    scope = 'all demo batches' if batch is None else 'batch %s' % batch
    print('PURGE %s from project %s table %s' % (scope, args.project, table_id))
    print('SQL:\n%s' % bq_purge_sql(table_id, batch=batch))
    if not args.apply:
      print('Dry run. Re-run with --purge --apply to delete tagged rows only.')
      db = _fs_client(args.project)
      planned = purge_firestore(db, dry_run=True, batch=batch)
      print('Would delete Firestore: %s' % planned)
      return 0
    db = _fs_client(args.project)
    bq = _bq_client(args.project)
    deleted = purge_firestore(db, dry_run=False, batch=batch)
    sql = purge_bigquery(bq, table_id, dry_run=False, batch=batch)
    print('Deleted Firestore: %s' % deleted)
    print('Ran: %s' % sql)
    print('Load-job rows are immediately deletable. If anything was ever '
          'inserted with insert_rows_json, wait ~90 minutes for the streaming '
          'buffer before DELETE can remove those rows.')
    return 0

  if args.scenario == 'i18n':
    world = generate_i18n_world(now=now, seed=args.seed)
  else:
    world = generate_world(args.count, args.seed, now=now)
  for line in summary_lines(world):
    print(line)
  print('Estimated BigQuery rows: %s (load job, not streaming).' % world.n_rows)
  if world.n_rows > 400000:
    print('error: estimated rows > 400000; lower --count', file=sys.stderr)
    return 2
  if not args.apply:
    print('Dry run. Re-run with --apply to write Firestore + BigQuery.')
    print('WARNING: --apply writes to the live project (%s).' % args.project)
    return 0
  print('APPLY %s batch %s to live project %s'
        % (args.scenario, world.batch, args.project))
  db = _fs_client(args.project)
  bq = _bq_client(args.project)
  n_docs = apply_firestore(db, world)
  print('Wrote %s survey docs (plus audit rows).' % n_docs)
  n_rows = apply_bigquery(bq, table_id, world)
  print('Loaded %s BigQuery rows into %s (after deleting previous %s rows).'
        % (n_rows, table_id, world.batch))
  print('Done. Homepage should paginate; stats fill from /index/stats-partial.')
  return 0


if __name__ == '__main__':
  sys.exit(main())
