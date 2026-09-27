"""
Regenerate the OCR test samples (synthetic, no real plant data).

    ../env/bin/python make_samples.py

Creates:
  scanned_inspection_report.pdf   2-page image-only PDF (no text layer)
  inspection_page1.png / inspection_page2.jpg
  degraded/*                      rotated, skewed, low-resolution, noisy and JPEG-artifact scans
  layout/table_report.png         a readings table
  layout/two_column.png           two-column page
  handwriting_proxy.png           cursive *font* (a proxy - NOT real handwriting)
  kannada_notice.png              Kannada-script notice (OCR language test)
"""

import io
import os
import random

import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
CURSIVE = "/usr/share/fonts/opentype/urw-base35/Z003-MediumItalic.otf"
KANNADA = "/usr/share/fonts/truetype/noto/NotoSansKannada-Regular.ttf"

PAGE_1 = """MANGALORE REFINERY - FIELD INSPECTION REPORT
Report No: INS-2026-0417
Inspection Date: 14 September 2026
Inspector: R. Shetty (Mechanical Integrity)
Unit: Crude Distillation Unit (CDU-2)

Equipment: Heat Exchanger E-2104 (Shell & Tube)
Tag: E-2104A   Service: Crude Preheat

Finding 1: External corrosion observed on shell near
the south saddle support, approx. 150 mm x 80 mm.
Measured wall thickness: 7.2 mm (nominal 10.0 mm).

Finding 2: Minor weep at channel head gasket (bolt 7).
No active leak at time of inspection.

Observation: Insulation damaged over 1.5 m section on
inlet nozzle N1; moisture ingress likely."""

PAGE_2 = """Page 2 - Continued: INS-2026-0417

Equipment: Centrifugal Pump P-2210B
Finding 3: Vibration 7.8 mm/s at drive-end bearing
(alarm limit 7.1 mm/s). Bearing temperature 82 C.

Recommendation 1: Carry out UT thickness mapping of
E-2104A shell within 30 days; evaluate fitness for
service per API 579 if thickness is below 6.5 mm.

Recommendation 2: Replace channel head gasket during
next planned shutdown; re-torque bolts meanwhile.

Recommendation 3: Repair insulation on nozzle N1 and
inspect for corrosion under insulation (CUI).

Recommendation 4: Schedule P-2210B bearing replacement
and laser alignment check within 7 days.

Overall Risk Rating: MEDIUM
Next Inspection Due: March 2027"""


def page(text, font=MONO, size=26, width=1240, height=1754, margin=100, spacing=12):
    """A 150-dpi A4 'scan' (1240x1754) with the given text."""
    img = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(img)
    f = ImageFont.truetype(font, size)
    draw.multiline_text((margin, margin), text, fill=0, font=f, spacing=spacing)
    return img


def save(img, name, **kw):
    path = os.path.join(HERE, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, **kw)
    return path


def main():
    random.seed(7)
    np.random.seed(7)
    p1, p2 = page(PAGE_1), page(PAGE_2)
    save(p1, "inspection_page1.png")
    save(p2.convert("RGB"), "inspection_page2.jpg", quality=85)

    # Image-only PDF (JPEG pages keep it small)
    pdf = pymupdf.open()
    for img in (p1, p2):
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=80)
        pg = pdf.new_page(width=595, height=842)
        pg.insert_image(pg.rect, stream=buf.getvalue())
    pdf.save(os.path.join(HERE, "scanned_inspection_report.pdf"), deflate=True)

    # Degraded scans of page 1
    save(p1.rotate(90, expand=True, fillcolor=255), "degraded/rotated_90.png")
    save(p1.rotate(180, expand=True, fillcolor=255), "degraded/rotated_180.png")
    save(p1.rotate(5, expand=True, fillcolor=255, resample=Image.BICUBIC), "degraded/skew_5deg.png")
    save(p1.resize((p1.width * 2 // 3, p1.height * 2 // 3), Image.LANCZOS), "degraded/lowres_100dpi.png")
    save(p1.resize((p1.width // 2, p1.height // 2), Image.LANCZOS), "degraded/lowres_75dpi.png")
    arr = np.asarray(p1).astype(np.int16)
    noise = np.random.normal(0, 40, arr.shape)
    speckle = np.random.random(arr.shape) < 0.02
    noisy = np.clip(arr + noise, 0, 255)
    noisy[speckle] = 0
    save(Image.fromarray(noisy.astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8)), "degraded/noisy.png")
    save(p1.convert("RGB"), "degraded/jpeg_q15.jpg", quality=15)

    # Table
    img = Image.new("L", (1240, 900), 255)
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(SANS, 24)
    d.text((80, 60), "Table 1 - UT thickness readings, E-2104A shell", fill=0, font=f)
    cols = [80, 330, 600, 870, 1160]
    heads = ["Location", "Nominal (mm)", "Measured (mm)", "Status"]
    rows = [["North head", "10.0", "9.6", "OK"], ["South saddle", "10.0", "7.2", "Monitor"],
            ["Inlet nozzle N1", "12.0", "11.1", "OK"], ["Outlet nozzle N2", "12.0", "10.9", "OK"],
            ["Shell mid-span", "10.0", "8.4", "Monitor"]]
    y0, rh = 130, 70
    for r in range(len(rows) + 2):
        d.line([(cols[0], y0 + r * rh), (cols[-1], y0 + r * rh)], fill=0, width=2)
    for c in cols:
        d.line([(c, y0), (c, y0 + (len(rows) + 1) * rh)], fill=0, width=2)
    for r, row in enumerate([heads] + rows):
        for c, cell in enumerate(row):
            d.text((cols[c] + 14, y0 + r * rh + 20), cell, fill=0, font=f)
    save(img, "layout/table_report.png")

    # Two columns
    left = ("LEFT COLUMN\nThe crude preheat train\nconsists of six shell and\ntube exchangers in series.\n"
            "Fouling is monitored\nweekly by duty trend.")
    right = ("RIGHT COLUMN\nPump P-2210B shows rising\nvibration at the drive-end\nbearing. Alignment is\n"
             "scheduled within seven\ndays of this report.")
    img = Image.new("L", (1240, 700), 255)
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(SANS, 26)
    d.multiline_text((80, 80), left, fill=0, font=f, spacing=14)
    d.multiline_text((680, 80), right, fill=0, font=f, spacing=14)
    save(img, "layout/two_column.png")

    # Handwriting proxy (cursive font - not real handwriting)
    save(page("Pump P-2210B vibration high.\nReplace bearing within 7 days.\nChecked by R. Shetty",
              font=CURSIVE, size=48, height=600, spacing=24), "handwriting_proxy.png")

    # Kannada notice
    img = Image.new("L", (1240, 420), 255)
    d = ImageDraw.Draw(img)
    d.multiline_text((80, 80), "ಸುರಕ್ಷತಾ ಸೂಚನೆ\nಪಂಪ್ ಪರಿಶೀಲನೆ ಏಳು ದಿನಗಳಲ್ಲಿ ಮಾಡಬೇಕು",
                     fill=0, font=ImageFont.truetype(KANNADA, 48), spacing=30)
    save(img, "kannada_notice.png")
    print("samples written to", HERE)


if __name__ == "__main__":
    main()
