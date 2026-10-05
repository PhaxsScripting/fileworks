"""CSV operations with no network access or implicit value conversions."""

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile

MAX_BYTES = 20 * 1024 * 1024
SAMPLE_LIMIT = 20
MAX_RECORDS = 100_001  # Includes the header.
MAX_CELLS = 1_000_000
DELIMITERS = {"comma": ",", "semicolon": ";", "tab": "\t", "pipe": "|"}


class FileworksError(ValueError):
    """A rejected input or output operation."""


def formula_like(value):
    """Conservative heuristic; this deliberately also flags negative numbers."""
    return value.lstrip().startswith(("=", "+", "-", "@"))


def read_csv(path, delimiter=None):
    path = Path(path)
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise FileworksError("Input exceeds the 20 MiB limit.")
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FileworksError("Input must be UTF-8 or UTF-8 with a BOM.") from exc
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(content[:65536], delimiters=",;\t|").delimiter
        except csv.Error as exc:
            raise FileworksError("Cannot reliably detect the delimiter; use --delimiter.") from exc
    if delimiter not in DELIMITERS.values():
        raise FileworksError("Delimiter must be comma, semicolon, tab, or pipe.")
    # The byte limit is also a safe upper bound for any individual CSV field.
    previous_limit = csv.field_size_limit()
    try:
        csv.field_size_limit(MAX_BYTES)
        rows = []
        cells = 0
        for row in csv.reader(io.StringIO(content, newline=""), delimiter=delimiter, strict=True):
            rows.append(row)
            cells += len(row)
            if len(rows) > MAX_RECORDS or cells > MAX_CELLS:
                raise FileworksError("Input exceeds the 100,000 data-record or 1,000,000 cell limit.")
    except csv.Error as exc:
        raise FileworksError(f"Invalid CSV syntax: {exc}") from exc
    finally:
        csv.field_size_limit(previous_limit)
    if not rows or not rows[0]:
        raise FileworksError("CSV must start with a nonempty header record.")
    return {
        "rows": rows,
        "delimiter": delimiter,
        "encoding": "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8",
        "input_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def audit_document(document):
    rows = document["rows"]
    header = rows[0]
    width = len(header)
    normalized_header = [value.strip() for value in header]
    seen_headers = set()
    duplicate_headers = []
    for column, value in enumerate(normalized_header, 1):
        if value and value in seen_headers:
            duplicate_headers.append(column)
        seen_headers.add(value)
    counts = {"data_records": len(rows) - 1, "columns": width,
              "empty_headers": sum(not value for value in normalized_header),
              "duplicate_headers": len(duplicate_headers), "width_mismatches": 0,
              "fully_blank_records": 0, "duplicate_records": 0,
              "blank_data_cells": 0, "formula_like_cells": 0}
    examples = {"width_mismatches": [], "duplicate_records": [], "formula_like_cells": []}
    seen_rows = set()
    for record, row in enumerate(rows, 1):
        for column, value in enumerate(row, 1):
            if formula_like(value):
                counts["formula_like_cells"] += 1
                if len(examples["formula_like_cells"]) < SAMPLE_LIMIT:
                    examples["formula_like_cells"].append({"record": record, "column": column})
        if record == 1:
            continue
        # Empty physical lines are [] in csv.reader and counted separately.
        if row and len(row) != width:
            counts["width_mismatches"] += 1
            if len(examples["width_mismatches"]) < SAMPLE_LIMIT:
                examples["width_mismatches"].append({"record": record, "actual_columns": len(row)})
        if not any(value.strip() for value in row):
            counts["fully_blank_records"] += 1
        counts["blank_data_cells"] += sum(not value.strip() for value in row)
        key = tuple(row)
        if key in seen_rows:
            counts["duplicate_records"] += 1
            if len(examples["duplicate_records"]) < SAMPLE_LIMIT:
                examples["duplicate_records"].append(record)
        seen_rows.add(key)
    return {"schema_version": 1, "input_bytes": document["input_bytes"],
            "input_sha256": document["sha256"], "encoding": document["encoding"],
            "delimiter": next(name for name, value in DELIMITERS.items() if value == document["delimiter"]),
            "counts": counts, "empty_header_columns": [i for i, value in enumerate(normalized_header, 1) if not value],
            "duplicate_header_columns": duplicate_headers, "examples": examples,
            "example_limit": SAMPLE_LIMIT}


def audit_file(path, delimiter=None):
    return audit_document(read_csv(path, delimiter))


def atomic_new_file(path, write):
    """Publish a completed private file atomically, failing if any output exists."""
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise FileworksError("Output already exists; choose a new path.")
    fd, temporary = tempfile.mkstemp(prefix=".fileworks-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            write(stream)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise FileworksError("Output already exists; choose a new path.") from exc
    finally:
        os.unlink(temporary)


def clean_file(input_path, output_path, delimiter=None, *, trim=False,
               remove_blank_rows=False, remove_duplicates=False, escape_formulas=False):
    if Path(input_path).resolve() == Path(output_path).resolve():
        raise FileworksError("Input and output must be different paths.")
    document = read_csv(input_path, delimiter)
    before = audit_document(document)
    if before["counts"]["width_mismatches"]:
        raise FileworksError("Malformed record widths; cleanup refused. Audit the input first.")
    if any(not row for row in document["rows"][1:]) and not remove_blank_rows:
        raise FileworksError("Empty physical lines require --remove-blank-rows.")
    changes = {"trimmed_cells": 0, "blank_records_removed": 0,
               "duplicate_records_removed": 0, "formula_cells_escaped": 0}
    result = []
    seen = set()
    for index, original in enumerate(document["rows"]):
        if index and remove_blank_rows and not any(value.strip() for value in original):
            changes["blank_records_removed"] += 1
            continue
        # Exact duplicates refer to the original data, before whitespace trimming.
        key = tuple(original)
        if index and remove_duplicates and key in seen:
            changes["duplicate_records_removed"] += 1
            continue
        if index:
            seen.add(key)
        row = []
        for value in original:
            if trim:
                stripped = value.strip()
                changes["trimmed_cells"] += stripped != value
                value = stripped
            if escape_formulas and formula_like(value):
                value = "'" + value
                changes["formula_cells_escaped"] += 1
            row.append(value)
        result.append(row)
    text = io.StringIO(newline="")
    csv.writer(text, delimiter=document["delimiter"], lineterminator="\n").writerows(result)
    raw = text.getvalue().encode(document["encoding"])
    atomic_new_file(output_path, lambda stream: stream.write(raw))
    return {"schema_version": 1, "before": before, "changes": changes,
            "output_data_records": len(result) - 1, "output_bytes": len(raw),
            "output_sha256": hashlib.sha256(raw).hexdigest()}


def report_text(report, format="json"):
    if format == "json":
        return json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    lines = ["# CSV audit", "", f"Input SHA-256: `{report['input_sha256']}`", "",
             f"Encoding: {report['encoding']}; delimiter: {report['delimiter']}", "",
             "| Check | Count |", "| --- | ---: |"]
    lines.extend(f"| {key.replace('_', ' ')} | {value} |" for key, value in report["counts"].items())
    lines.extend(["", "Record numbers are CSV records (header is 1), not physical line numbers.",
                  "Header checks trim whitespace and compare case-sensitively. Values are omitted.",
                  "Formula-like means the first non-whitespace character is =, +, -, or @.", "",
                  "## Issue coordinates (first 20 per check)", "",
                  "```json", json.dumps({key: report[key] for key in
                                         ("empty_header_columns", "duplicate_header_columns", "examples")}, indent=2),
                  "```", ""])
    return "\n".join(lines)
