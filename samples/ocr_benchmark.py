"""
OCR test plan / benchmark (L15, L18-L23). Runs PaddleOCR locally on the samples.

    cd backend && ../env/bin/python ../samples/ocr_benchmark.py [config ...]

Configs: server, mobile, textline, docori, unwarp, all_pre (default: server)
Accuracy = character similarity to the known text (difflib ratio, whitespace-normalised);
it is a measured score for these synthetic samples, unlike PaddleOCR's own
"recognition confidence".
"""

import difflib
import os
import re
import resource
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django  # noqa: E402

django.setup()
import psutil  # noqa: E402
from django.conf import settings  # noqa: E402

from documents import ocr  # noqa: E402

sys.path.insert(0, os.path.dirname(__file__))
from make_samples import PAGE_1, PAGE_2  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TRUTH = {
    "inspection_page1.png": PAGE_1, "inspection_page2.jpg": PAGE_2,
    "degraded/rotated_90.png": PAGE_1, "degraded/rotated_180.png": PAGE_1,
    "degraded/skew_5deg.png": PAGE_1, "degraded/lowres_100dpi.png": PAGE_1,
    "degraded/lowres_75dpi.png": PAGE_1, "degraded/noisy.png": PAGE_1,
    "degraded/jpeg_q15.jpg": PAGE_1,
    "handwriting_proxy.png": "Pump P-2210B vibration high.\nReplace bearing within 7 days.\nChecked by R. Shetty",
    "layout/table_report.png": None, "layout/two_column.png": None,
}
CONFIGS = {
    "server": {},
    "mobile": {"OCR_MODEL_PROFILE": "mobile"},
    "textline": {"OCR_USE_TEXTLINE_ORIENTATION": True},
    "docori": {"OCR_USE_DOC_ORIENTATION": True},
    "unwarp": {"OCR_USE_UNWARPING": True},
    "all_pre": {"OCR_USE_DOC_ORIENTATION": True, "OCR_USE_TEXTLINE_ORIENTATION": True},
}


def norm(t):
    return re.sub(r"\s+", " ", t).strip().lower()


def rss_mb():
    return psutil.Process().memory_info().rss / 2**20


def run(config_name):
    defaults = {"OCR_MODEL_PROFILE": "server", "OCR_USE_DOC_ORIENTATION": False,
                "OCR_USE_TEXTLINE_ORIENTATION": False, "OCR_USE_UNWARPING": False}
    for k, v in {**defaults, **CONFIGS[config_name]}.items():
        setattr(settings, k, v)
    before = rss_mb()
    t = time.monotonic()
    ocr._get_engine("en")
    load_s = time.monotonic() - t
    after = rss_mb()
    print(f"\n### config={config_name}  engine load {load_s:.1f}s  RSS {before:.0f} -> {after:.0f} MB")
    print(f"{'sample':30} {'time':>6} {'accuracy':>9} {'conf':>6} {'layout':>7}")
    for name, truth in TRUTH.items():
        data = open(os.path.join(HERE, name), "rb").read()
        t = time.monotonic()
        r = ocr.ocr_image(data, "en")
        dt = time.monotonic() - t
        acc = f"{difflib.SequenceMatcher(None, norm(truth), norm(r['text'])).ratio():.3f}" if truth else "  n/a"
        print(f"{name:30} {dt:5.1f}s {acc:>9} {r['confidence']:6.3f} {str(r['complex_layout']):>7}")
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"RSS now {rss_mb():.0f} MB, peak {peak:.0f} MB")


if __name__ == "__main__":
    for name in sys.argv[1:] or ["server"]:
        run(name)
