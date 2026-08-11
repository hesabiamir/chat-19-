from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import main


def validate(name: str, html: str) -> int:
    scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", html, flags=re.I | re.S)
    if not scripts:
        raise SystemExit(f"{name}: no inline JavaScript found")
    checked = 0
    for index, script in enumerate(scripts, 1):
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
            handle.write(script)
            path = Path(handle.name)
        try:
            subprocess.run(["node", "--check", str(path)], check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise SystemExit("Node.js is required for frontend validation") from exc
        except subprocess.CalledProcessError as exc:
            raise SystemExit(f"{name} script {index} failed JavaScript syntax validation:\n{exc.stderr}") from exc
        finally:
            path.unlink(missing_ok=True)
        checked += 1
    return checked


def validate_contracts() -> None:
    main_html=main.MAIN_HTML
    widget_html=main.WIDGET_HTML
    for name,html in (("MAIN_HTML",main_html),("WIDGET_HTML",widget_html)):
        if html.count('BARSAN R35.2 canonical thinking loader') != 1:
            raise SystemExit(f"{name}: thinking loader CSS must be defined exactly once")
        required=(
            'margin:8px 0 10px auto!important',
            'width:196px!important',
            'width:164px!important',
            '/thinking-loader.mp4?v=R35_2',
        )
        for token in required:
            if token not in html:
                raise SystemExit(f"{name}: missing thinking invariant: {token}")
    for label in ('گفت گو','بررسی بار','مسیر یابی','محاسبات'):
        if label not in main_html:
            raise SystemExit(f"MAIN_HTML: missing primary section label: {label}")
    for label in ('بررسی ابعاد بار','بررسی عکس بار','محاسبه کنسلی','محاسبه توقف','محاسبه انحراف مسیر'):
        if label not in main_html:
            raise SystemExit(f"MAIN_HTML: missing required subsection label: {label}")
    # Chat feedback must stay limited to the three requested quality ratings.
    feedback_match = re.search(r"function appendFeedbackButtons\(.*?\nfunction ", main_html, flags=re.S)
    if not feedback_match:
        raise SystemExit('MAIN_HTML: appendFeedbackButtons contract not found')
    feedback_js = feedback_match.group(0)
    for label in ('درست بود','غلط بود','ناقص بود'):
        if label not in feedback_js:
            raise SystemExit(f'MAIN_HTML: feedback option missing: {label}')
    for forbidden in ('توکن','مدل','API','بدون توکن','منبع پاسخ'):
        if forbidden in feedback_js:
            raise SystemExit(f'MAIN_HTML: chat feedback leaked debug/provider metadata: {forbidden}')


if __name__ == "__main__":
    total = validate("MAIN_HTML", main.MAIN_HTML) + validate("WIDGET_HTML", main.WIDGET_HTML)
    validate_contracts()
    print(f"BARSAN_FRONTEND_VALIDATION_OK scripts={total} contracts=ok")
