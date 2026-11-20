#!/usr/bin/env python3
"""Rasterize creative/app/static/favicon.svg into ICO and PNG sizes.

Requires rsvg-convert (librsvg2-bin). Outputs are committed so App Engine
does not need that tool at deploy time.

librsvg does not honour the SVG's 16px media query, so the 16×16 ICO layer
is rendered from TINY_SVG (B2). Browsers that load favicon.svg still switch
via @media (max-width: 20px).

  python3 tools/generate_favicons.py
"""
from __future__ import annotations

import argparse
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / 'creative' / 'app' / 'static' / 'favicon.svg'
STATIC = ROOT / 'creative' / 'app' / 'static'
APP_DIR = ROOT / 'creative' / 'app'
ICO_SIZES = (16, 32, 48)
APPLE_TOUCH = 180

# 16px-legible B2. Same background as favicon.svg; no media query.
TINY_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <defs>
    <linearGradient id="bv2-bg" x1="16" y1="0" x2="16" y2="32" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#3d8bfd"/>
      <stop offset="1" stop-color="#0d6efd"/>
    </linearGradient>
  </defs>
  <rect width="32" height="32" rx="8" fill="url(#bv2-bg)"/>
  <g fill="#fff" font-family="DejaVu Sans, Arial, Helvetica, sans-serif" font-weight="700">
    <text x="4" y="24.5" font-size="20">B</text>
    <text x="20.4" y="14.2" font-size="11">2</text>
  </g>
</svg>
"""


def rsvg_png(svg: Path, dest: Path, size: int) -> None:
  dest.parent.mkdir(parents=True, exist_ok=True)
  subprocess.check_call([
      'rsvg-convert',
      '--width', str(size),
      '--height', str(size),
      str(svg),
      '-o', str(dest),
  ])


def write_ico(png_by_size: dict[int, Path], dest: Path) -> None:
  """Pack SVG-rendered 16/32/48 PNGs into a multi-size ICO (PNG-in-ICO)."""
  blobs = []
  for size in ICO_SIZES:
    data = png_by_size[size].read_bytes()
    blobs.append((size, data))
  header = struct.pack('<HHH', 0, 1, len(blobs))
  offset = 6 + 16 * len(blobs)
  entries = bytearray()
  body = bytearray()
  for size, data in blobs:
    width = 0 if size >= 256 else size
    entries += struct.pack(
        '<BBBBHHII', width, width, 0, 0, 1, 32, len(data), offset)
    body += data
    offset += len(data)
  dest.write_bytes(header + entries + body)


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument(
      '--preview-dir',
      default='',
      help='Also write 32px and 512px PNG previews here',
  )
  args = parser.parse_args(argv)
  if shutil.which('rsvg-convert') is None:
    sys.stderr.write('rsvg-convert is required (apt install librsvg2-bin)\n')
    return 1
  if not SVG.is_file():
    sys.stderr.write('Missing %s\n' % SVG)
    return 1

  with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    tiny = tmp_path / 'favicon-tiny.svg'
    tiny.write_text(TINY_SVG, encoding='utf-8')
    png_by_size = {}
    for size in sorted(set(ICO_SIZES + (APPLE_TOUCH, 32, 512))):
      png = tmp_path / ('favicon-%s.png' % size)
      rsvg_png(tiny if size == 16 else SVG, png, size)
      png_by_size[size] = png

    ico = STATIC / 'favicon.ico'
    write_ico(png_by_size, ico)
    apple = STATIC / 'apple-touch-icon.png'
    shutil.copyfile(png_by_size[APPLE_TOUCH], apple)
    # Default /favicon.ico for App Engine + browsers that ignore <link rel>.
    shutil.copyfile(ico, APP_DIR / 'favicon.ico')

    if args.preview_dir:
      preview = Path(args.preview_dir)
      preview.mkdir(parents=True, exist_ok=True)
      shutil.copyfile(png_by_size[32], preview / 'brandometer2-favicon-32.png')
      shutil.copyfile(png_by_size[512], preview / 'brandometer2-favicon-512.png')

  print('Wrote', ico)
  print('Wrote', apple)
  print('Wrote', APP_DIR / 'favicon.ico')
  return 0


if __name__ == '__main__':
  sys.exit(main())
