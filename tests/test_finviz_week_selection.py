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


class WeekSelectionTests(unittest.TestCase):
    def test_arguments(self):
        for argv, count, this_week in [
            ([], finviz.DEFAULT_COUNT, False),
            (["--this-week"], finviz.DEFAULT_COUNT, True),
            (["2"], 2, False),
            (["2", "--this-week"], 2, True),
            (["--this-week", "2"], 2, True),
        ]:
            with self.subTest(argv=argv):
                args = finviz.parse_args(argv)
                self.assertEqual((args.count, args.this_week), (count, this_week))

    def test_every_day_of_week(self):
        monday = datetime.date(2026, 11, 2)
        for offset in range(7):
            today = monday + datetime.timedelta(days=offset)
            with self.subTest(today=today):
                self.assertEqual(finviz.week_start_date(today, True), monday)
                self.assertEqual(finviz.week_start_date(today), datetime.date(2026, 11, 9))

    def test_year_boundary(self):
        today = datetime.date(2027, 1, 1)
        self.assertEqual(finviz.week_start_date(today, True), datetime.date(2026, 12, 28))
        self.assertEqual(finviz.week_start_date(today), datetime.date(2027, 1, 4))

    def test_fetch_uses_selected_url_on_all_pages(self):
        for base_url in (finviz.BASE_NEXTWEEK, finviz.BASE_THISWEEK):
            for page, suffix in ((1, ""), (2, "&r=21")):
                with self.subTest(base_url=base_url, page=page), \
                        patch.object(finviz.requests, "get") as get, \
                        patch("builtins.open", unittest.mock.mock_open()), \
                        contextlib.redirect_stdout(io.StringIO()):
                    get.return_value.text = "<html></html>"
                    finviz.fetch_and_save(page, base_url)
                    get.assert_called_once_with(base_url + suffix,
                                                headers=finviz.HEADERS, timeout=15)

    def test_selected_url_filename_payload_and_index(self):
        for this_week in (False, True):
            with self.subTest(this_week=this_week), tempfile.TemporaryDirectory() as directory:
                original_directory = Path.cwd()
                try:
                    os.chdir(directory)
                    Path("docs/data").mkdir(parents=True)

                    def fetch(page, base_url):
                        Path("finviz.html").write_text("<html>No results</html>", encoding="utf-8")

                    with patch.object(finviz, "read_weekly_options_from_csv", return_value={}), \
                            patch.object(finviz, "fetch_and_save", side_effect=fetch) as fetch_mock, \
                            patch.object(finviz.datetime, "datetime", wraps=datetime.datetime) as clock, \
                            contextlib.redirect_stdout(io.StringIO()):
                        clock.now.return_value = datetime.datetime(2026, 11, 3, 12)
                        finviz.main(2, this_week=this_week)

                    expected_url = finviz.BASE_THISWEEK if this_week else finviz.BASE_NEXTWEEK
                    fetch_mock.assert_called_once_with(1, expected_url)
                    date_str = "2026-11-02" if this_week else "2026-11-09"
                    filename = f"earnings-for-week-starting-{date_str}.json"
                    output = json.loads((Path("docs/data") / filename).read_text())
                    self.assertEqual(output["week_start"], date_str)
                    index = json.loads(Path("docs/data/all-earnings-index.json").read_text())
                    self.assertEqual(index, [{"date": date_str, "filename": filename}])
                finally:
                    os.chdir(original_directory)


if __name__ == "__main__":
    unittest.main()