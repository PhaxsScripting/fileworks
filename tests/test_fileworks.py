import contextlib
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fileworks.__main__ import main
from fileworks.core import FileworksError, MAX_BYTES, atomic_new_file, audit_file, clean_file, report_text


class FileworksTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.source = self.directory / "input.csv"
        self.output = self.directory / "output.csv"

    def source_text(self, text, encoding="utf-8"):
        self.source.write_bytes(text.encode(encoding))

    def output_rows(self, delimiter=","):
        with self.output.open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.reader(stream, delimiter=delimiter))

    def test_multiline_quoted_field_and_embedded_delimiter(self):
        self.source_text('id,note\n001,"a,b\nnext line"\n')
        report = audit_file(self.source)
        self.assertEqual(report["counts"]["data_records"], 1)
        clean_file(self.source, self.output)
        self.assertEqual(self.output_rows(), [["id", "note"], ["001", "a,b\nnext line"]])

    def test_auto_semicolon_and_bom_preserved(self):
        self.source_text('id;note\n007;"x;y"\n008;ok\n', "utf-8-sig")
        report = audit_file(self.source)
        self.assertEqual(report["delimiter"], "semicolon")
        self.assertEqual(report["encoding"], "utf-8-sig")
        clean_file(self.source, self.output)
        self.assertTrue(self.output.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertEqual(self.output_rows(";")[1], ["007", "x;y"])

    def test_audit_counts_and_no_sensitive_values_in_reports(self):
        self.source_text('name, name , \nTOP_SECRET,ok,\nTOP_SECRET,ok,\n,,\n"  =PRIVATE",x,y\n')
        report = audit_file(self.source, ",")
        counts = report["counts"]
        self.assertEqual(counts["empty_headers"], 1)
        self.assertEqual(counts["duplicate_headers"], 1)
        self.assertEqual(counts["duplicate_records"], 1)
        self.assertEqual(counts["fully_blank_records"], 1)
        self.assertEqual(counts["blank_data_cells"], 5)
        self.assertEqual(counts["formula_like_cells"], 1)
        self.assertEqual(report["examples"]["formula_like_cells"], [{"record": 5, "column": 1}])
        for format in ("json", "markdown"):
            rendered = report_text(report, format)
            self.assertNotIn("TOP_SECRET", rendered)
            self.assertNotIn("PRIVATE", rendered)
            self.assertNotIn("name", rendered)

    def test_cleanup_is_explicit_preserves_original_and_leading_zeroes(self):
        self.source_text(' id , note \n 001 , hello \n 001 , hello \n,\n')
        original = self.source.read_bytes()
        clean_file(self.source, self.output, ",")
        self.assertEqual(self.output_rows()[1], [" 001 ", " hello "])
        self.assertEqual(len(self.output_rows()), 4)
        cleaned = self.directory / "cleaned.csv"
        report = clean_file(self.source, cleaned, ",", trim=True, remove_blank_rows=True, remove_duplicates=True)
        self.assertEqual(cleaned.read_text(), "id,note\n001,hello\n")
        self.assertEqual(report["changes"], {"trimmed_cells": 4, "blank_records_removed": 1,
                                             "duplicate_records_removed": 1, "formula_cells_escaped": 0})
        self.assertEqual(self.source.read_bytes(), original)

    def test_deduplicate_compares_original_rows_before_trim(self):
        self.source_text('id\n001\n 001 \n001\n')
        clean_file(self.source, self.output, ",", trim=True, remove_duplicates=True)
        self.assertEqual(self.output_rows(), [["id"], ["001"], ["001"]])

    def test_malformed_widths_refused_even_if_blank_or_duplicate_removal_requested(self):
        for text in ('a,b\n1,2,3\n', 'a,b\n\"\"\n'):
            with self.subTest(text=text):
                self.source_text(text)
                self.assertEqual(audit_file(self.source, ",")["counts"]["width_mismatches"], 1)
                with self.assertRaisesRegex(FileworksError, "Malformed"):
                    clean_file(self.source, self.output, ",", remove_blank_rows=True, remove_duplicates=True)
                self.assertFalse(self.output.exists())

    def test_empty_physical_lines_are_removed_only_when_requested(self):
        self.source_text('a,b\n\n1,2\n')
        self.assertEqual(audit_file(self.source, ",")["counts"]["fully_blank_records"], 1)
        with self.assertRaisesRegex(FileworksError, "Empty physical lines"):
            clean_file(self.source, self.output, ",")
        clean_file(self.source, self.output, ",", remove_blank_rows=True)
        self.assertEqual(self.output_rows(), [["a", "b"], ["1", "2"]])

    def test_malformed_quoting_encoding_and_empty_header_rejected(self):
        for raw in (b'a,b\n"unterminated,2\n', b'a,b\n\xff,2\n', b'\na,b\n'):
            with self.subTest(raw=raw):
                self.source.write_bytes(raw)
                with self.assertRaises(FileworksError):
                    clean_file(self.source, self.output, ",")
                self.assertFalse(self.output.exists())

    def test_no_clobber_same_path_existing_and_symlink(self):
        self.source_text("id\n001\n")
        original = self.source.read_bytes()
        with self.assertRaisesRegex(FileworksError, "different paths"):
            clean_file(self.source, self.source, ",")
        self.output.write_bytes(b"existing")
        with self.assertRaisesRegex(FileworksError, "already exists"):
            clean_file(self.source, self.output, ",")
        self.assertEqual(self.output.read_bytes(), b"existing")
        link = self.directory / "link.csv"
        link.symlink_to(self.directory / "missing.csv")
        with self.assertRaisesRegex(FileworksError, "already exists"):
            clean_file(self.source, link, ",")
        self.assertTrue(link.is_symlink())
        self.assertEqual(self.source.read_bytes(), original)

    def test_no_clobber_race_and_temporary_cleanup_on_failure(self):
        def competing_writer(temporary, destination):
            Path(destination).write_bytes(b"competitor")
            raise FileExistsError()
        with patch("fileworks.core.os.link", side_effect=competing_writer):
            with self.assertRaisesRegex(FileworksError, "already exists"):
                atomic_new_file(self.output, lambda stream: stream.write(b"ours"))
        self.assertEqual(self.output.read_bytes(), b"competitor")
        self.assertEqual(list(self.directory.glob(".fileworks-*")), [])
        other = self.directory / "other.csv"
        def failed_writer(stream):
            stream.write(b"partial")
            raise OSError("simulated failure")
        with self.assertRaises(OSError):
            atomic_new_file(other, failed_writer)
        self.assertFalse(other.exists())
        self.assertEqual(list(self.directory.glob(".fileworks-*")), [])

    def test_formula_risk_including_headers_and_negative_numbers_is_opt_in(self):
        self.source_text('=HEADER,value\n  =1+1,001\n+SUM(A1),002\n-12,003\n@X,004\nordinary,005\n')
        report = audit_file(self.source, ",")
        self.assertEqual(report["counts"]["formula_like_cells"], 5)
        clean_file(self.source, self.output, ",")
        self.assertEqual(self.output_rows()[1][0], "  =1+1")
        safe = self.directory / "escaped.csv"
        result = clean_file(self.source, safe, ",", escape_formulas=True)
        self.assertEqual(result["changes"]["formula_cells_escaped"], 5)
        self.assertEqual(audit_file(safe, ",")["counts"]["formula_like_cells"], 0)
        self.assertIn("'  =1+1,001", safe.read_text())

    def test_input_byte_record_and_cell_limits(self):
        with self.source.open("wb") as stream:
            stream.truncate(MAX_BYTES + 1)
        with self.assertRaisesRegex(FileworksError, "20 MiB"):
            audit_file(self.source, ",")
        self.source_text('a,b\n1,2\n3,4\n')
        with patch("fileworks.core.MAX_RECORDS", 2):
            with self.assertRaisesRegex(FileworksError, "data-record"):
                audit_file(self.source, ",")
        with patch("fileworks.core.MAX_CELLS", 5):
            with self.assertRaisesRegex(FileworksError, "cell limit"):
                audit_file(self.source, ",")

    def test_issue_examples_are_bounded_while_counts_are_complete(self):
        self.source_text('a,b\n' + '=X,value\n' * 25)
        report = audit_file(self.source, ",")
        self.assertEqual(report["counts"]["formula_like_cells"], 25)
        self.assertEqual(len(report["examples"]["formula_like_cells"]), 20)
        self.assertEqual(report["counts"]["duplicate_records"], 24)
        self.assertEqual(len(report["examples"]["duplicate_records"]), 20)

    def test_cli_audit_and_clean_error(self):
        self.source_text('id,note\n001,hello\n')
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main(["audit", str(self.source)]), 0)
        self.assertEqual(json.loads(stdout.getvalue())["counts"]["data_records"], 1)
        report = self.directory / "audit.md"
        self.assertEqual(main(["audit", str(self.source), "--format", "markdown", "--output", str(report)]), 0)
        self.assertTrue(report.read_text().startswith("# CSV audit"))
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(main(["clean", str(self.source), str(self.source)]), 2)
        self.assertIn("different paths", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
