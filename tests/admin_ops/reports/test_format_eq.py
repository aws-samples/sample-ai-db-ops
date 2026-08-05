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

"""Property P8 — Markdown → CSV (and HTML/PDF surrogate) preserves report data.

For every Health_Report, the set of `(query_id, mean_time_sec)` tuples
extracted from the Top Slow Queries section is identical across the
Markdown source, the CSV export, and the HTML payload (which is the
source for any downstream PDF renderer registered via
`exporters.pdf.set_pdf_renderer`).
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from html.parser import HTMLParser

from hypothesis import given, settings, strategies as st

from src.admin_ops.reports.exporters.csv import export_csvs
from src.admin_ops.reports.exporters.pdf import md_to_html
from src.admin_ops.reports.generator import render_report

_QUERY_ID = st.text(
    alphabet="0123456789abcdef",
    min_size=4,
    max_size=12,
)
_PREVIEW = st.text(
    alphabet="abcdefghij _,.",
    min_size=0,
    max_size=80,
)


def _slow_query_rows():
    return st.lists(
        st.fixed_dictionaries(
            {
                "query_id": _QUERY_ID,
                "preview": _PREVIEW,
                "calls": st.integers(min_value=0, max_value=10**6),
                "mean_time_sec": st.floats(min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
                "total_time_sec": st.floats(min_value=0.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
            }
        ),
        min_size=0,
        max_size=10,
        unique_by=lambda r: r["query_id"],
    )


@settings(deadline=None, max_examples=80)
@given(rows=_slow_query_rows())
def test_p8_md_csv_equivalence(rows):
    md, _ = render_report(
        bundle={"top_slow_queries": rows},
        db_identifier="db",
        engine="postgresql",
        cadence="manual",
        run_id="run-1",
        generated_at=datetime(2026, 5, 22, tzinfo=timezone.utc),
    )
    csvs = export_csvs(md)
    if not rows:
        # Empty-table case: section emits a placeholder, no CSV written.
        assert "top_slow_queries.csv" not in csvs
        return

    csv_content = csvs.get("top_slow_queries.csv", "")
    assert csv_content, "expected top_slow_queries.csv when rows are present"

    reader = csv.DictReader(io.StringIO(csv_content))
    csv_pairs = {(row["query_id"], row["mean_time_sec"]) for row in reader}

    # Extract the same pairs from the Markdown table.
    md_table = _extract_md_table_section(md, "Top Slow Queries")
    md_pairs = set()
    for row in md_table:
        md_pairs.add((row[0], row[3]))  # columns are query_id, preview, calls, mean_time_sec, total_time_sec

    assert csv_pairs == md_pairs

    # And the HTML payload (PDF surrogate) yields the same set.
    html = md_to_html(md)
    html_pairs = _extract_html_table_pairs(html, "Top Slow Queries")
    assert csv_pairs == html_pairs


class _SectionTableExtractor(HTMLParser):
    """Find the H2-anchored "Top Slow Queries" table and emit its data rows."""

    def __init__(self, target_heading: str) -> None:
        super().__init__()
        self.target_heading = target_heading
        self._capture_heading = False
        self._heading_text = ""
        self._in_target_section = False
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._cell_text: list[str] = []
        self._row_cells: list[str] = []
        self._all_rows: list[list[str]] = []

    def handle_starttag(self, tag, attrs):  # noqa: ARG002
        if tag == "h2":
            self._capture_heading = True
            self._heading_text = ""
            return
        if self._in_target_section and tag == "table":
            self._in_table = True
        elif self._in_table and tag == "tr":
            self._in_row = True
            self._row_cells = []
        elif self._in_row and tag in ("td", "th"):
            self._in_cell = True
            self._cell_text = []

    def handle_endtag(self, tag):
        if tag == "h2":
            self._capture_heading = False
            if self._heading_text.strip() == self.target_heading:
                self._in_target_section = True
            else:
                self._in_target_section = False
            return
        if tag == "td" or tag == "th":
            if self._in_cell:
                self._row_cells.append("".join(self._cell_text).strip())
                self._in_cell = False
        elif tag == "tr":
            if self._row_cells:
                self._all_rows.append(self._row_cells)
            self._in_row = False
        elif tag == "table":
            self._in_table = False

    def handle_data(self, data):
        if self._capture_heading:
            self._heading_text += data
        elif self._in_cell:
            self._cell_text.append(data)


def _extract_html_table_pairs(html: str, heading: str) -> set[tuple[str, str]]:
    p = _SectionTableExtractor(heading)
    p.feed(html)
    pairs: set[tuple[str, str]] = set()
    # Drop the header row.
    for row in p._all_rows[1:]:
        if len(row) >= 4:
            pairs.add((row[0], row[3]))
    return pairs


def _extract_md_table_section(md: str, heading: str) -> list[list[str]]:
    """Return the data rows of the table under `## heading`."""
    lines = md.splitlines()
    in_section = False
    rows: list[list[str]] = []
    for line in lines:
        if line.strip() == f"## {heading}":
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section and line.startswith("|"):
            inner = line.strip().strip("|")
            cells = [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", inner)]
            rows.append(cells)
    if rows and re.match(r"^[\-:|]+$", "".join(rows[1])):
        # rows[0] is headers, rows[1] is separator, rows[2:] is data
        return rows[2:]
    return rows
