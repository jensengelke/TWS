import contextlib
import datetime
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "get-earnings-dates-from-finviz.py"
SPEC = importlib.util.spec_from_file_location("finviz_earnings", SCRIPT)
finviz = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(finviz)


def grid_row(ticker, earnings=None):
    cell = "" if earnings is None else (
        '<div role="gridcell" data-column-id="earningsDate">'
        f'{earnings}</div>'
    )
    return (
        f'<div data-row-key="{ticker}" class="changed-class" role="row">'
        '<div role="presentation"><div data-column-id="ticker">'
        f'<a href="/quote?t={ticker}"><img src="logo.svg"/>'
        f'<span>{ticker}</span></a></div></div>'
        f'<div role="presentation">{cell}</div></div>'
    )


class ParseEarningsTests(unittest.TestCase):
    def test_first_and_last_rows_in_minified_html(self):
        html = (
            '<link href="CEG.svg"><div role="row">Header</div>'
            + grid_row("CEG", "Nov 09/b")
            + grid_row("CBRS", "Nov 12/a")
        )
        self.assertEqual(finviz.parse_earnings(html), [
            {"ticker": "CEG", "scheduled_date": "Nov 09/b"},
            {"ticker": "CBRS", "scheduled_date": "Nov 12/a"},
        ])

    def test_nested_markup_entities_and_multiline_html(self):
        html = grid_row("CEG", '\n<span>Nov&nbsp;09</span><span>/b</span>\n')
        self.assertEqual(finviz.parse_earnings(html)[0]["scheduled_date"], "Nov 09/b")

    def test_missing_earnings_do_not_leak_from_previous_row(self):
        rows = finviz.parse_earnings(
            grid_row("CEG", "Nov 09/b") + grid_row("CBRS") + grid_row("AMAT", "")
        )
        self.assertEqual([row["scheduled_date"] for row in rows],
                         ["Nov 09/b", "N/A", "N/A"])

    def test_no_results(self):
        self.assertEqual(finviz.parse_earnings('<div>No results</div>'), [])

    def test_pagination_offsets(self):
        self.assertEqual([finviz.r_for_iteration(i) for i in (1, 2, 3)],
                         [None, 21, 41])


class MainTests(unittest.TestCase):
    def test_pagination_filter_dates_and_json_in_temporary_directory(self):
        pages = [
            grid_row("CEG", "Nov 09/b")
            + "".join(grid_row(f"SKIP{i}", "Nov 10/a") for i in range(19)),
            grid_row("CBRS", "Nov 12/a"),
        ]

        def fetch(page, base_url):
            Path("finviz.html").write_text(pages[page - 1], encoding="utf-8")

        # Exercise the real output/index writing without touching repository data.
        with tempfile.TemporaryDirectory() as directory:
            original_directory = Path.cwd()
            try:
                os.chdir(directory)
                Path("docs/data").mkdir(parents=True)
                with patch.object(finviz, "read_weekly_options_from_csv",
                                  return_value={"CEG": "", "CBRS": ""}), \
                        patch.object(finviz, "fetch_and_save", side_effect=fetch) as get_page, \
                        patch.object(finviz.time, "sleep"), \
                        contextlib.redirect_stdout(io.StringIO()):
                    finviz.main(20)

                self.assertEqual(get_page.call_count, 2)
                output = json.loads(next(Path("docs/data").glob("earnings-for-*.json"))
                                    .read_text(encoding="utf-8"))
                self.assertEqual([row["ticker"] for row in output["data"]], ["CEG", "CBRS"])
                year = datetime.datetime.now().year
                for row, day in zip(output["data"], (8, 12)):
                    expected = datetime.date(year, 11, day)
                    self.assertEqual(row["open_trade_date"],
                                     f"{expected} ({expected.strftime('%A')})")
                index = json.loads(Path("docs/data/all-earnings-index.json").read_text())
                self.assertEqual(index[0]["date"], output["week_start"])
                self.assertFalse(Path("finviz.html").exists())
            finally:
                os.chdir(original_directory)


if __name__ == "__main__":
    unittest.main()