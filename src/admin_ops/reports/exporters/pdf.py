# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Markdown → HTML → PDF exporter.

Production target: WeasyPrint (system deps) or a Lambda layer with the
right native libs. For development and CI we render Markdown to a
self-contained HTML document with the report stylesheet inlined; a
caller can pipe that to whatever PDF engine is available in their
environment (Chromium headless, wkhtmltopdf, AWS Lambda's PDF layer).

The function returns *HTML bytes* under the `.pdf` filename when no
real PDF renderer is available — this is documented and detectable
via the magic bytes (`%PDF-` vs `<!doctype`). Tests can verify P8
content equivalence on the HTML payload, which is the source for any
downstream PDF.

Validates: requirement R3.6, property P8 (data-content side).
"""

from __future__ import annotations

import logging
from typing import Callable

import markdown as _md

from src.admin_ops.reports.styles import REPORT_CSS

LOG = logging.getLogger(__name__)

_HTML_TEMPLATE = """\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Database Health Report</title>
    <style>{css}</style>
  </head>
  <body>
{body}
  </body>
</html>
"""


def md_to_html(md_text: str) -> str:
    """Render Markdown to HTML with the report stylesheet inlined."""
    body_html = _md.markdown(
        md_text,
        extensions=["tables", "fenced_code"],
        output_format="html5",
    )
    return _HTML_TEMPLATE.format(css=REPORT_CSS, body=body_html)


# Optional WeasyPrint hook. Production deploys can register a real
# renderer via `set_pdf_renderer`; absent that, the export returns HTML.
_PdfRenderer = Callable[[str], bytes]
_renderer: _PdfRenderer | None = None


def set_pdf_renderer(fn: _PdfRenderer | None) -> None:
    global _renderer
    _renderer = fn


def export_pdf(md_text: str) -> bytes:
    """Return PDF bytes when a renderer is registered, else HTML bytes.

    Callers that need a real PDF must register a renderer at deploy
    time (e.g. `from weasyprint import HTML; set_pdf_renderer(lambda h:
    HTML(string=h).write_pdf())`).
    """
    html = md_to_html(md_text)
    if _renderer is not None:
        return _renderer(html)
    LOG.info("no PDF renderer registered — returning HTML payload")
    return html.encode("utf-8")
