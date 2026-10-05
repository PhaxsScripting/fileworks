# Fileworks local CSV utility

An original Python utility for a small, reviewable CSV cleanup workflow. It audits
local files and applies only the requested value and record changes. It uses the
Python standard library, performs no uploads or network requests, and runs no
external programs. This repository includes synthetic demonstration data; it
contains no customer results or revenue claims.

Python 3.10 or newer is required. From this folder, run without installing:

```bash
python3 -m fileworks audit examples/before.csv
python3 -m fileworks audit examples/before.csv --format markdown
python3 -m fileworks clean examples/before.csv /tmp/fileworks-cleaned.csv \
  --trim --remove-blank-rows --remove-duplicates --escape-formulas
```

Choose a fresh output path for each run. The included `examples/after.csv` already
exists and cannot be overwritten. `--output new-report.json` saves an audit;
without it, the audit goes to stdout. An optional `pip install --no-deps .`
installs the `fileworks` command, but running as a module needs no installation.
The build uses setuptools; it is not a runtime dependency.

## What it checks

- Delimiter detection for comma, semicolon, tab, and pipe. Use
  `--delimiter comma|semicolon|tab|pipe` if detection is uncertain or fails.
- UTF-8 input, with or without a byte order mark (BOM).
- Empty and duplicate headers, malformed record widths, blank cells, fully blank
  records, exact duplicate data records, and formula-like cells.
- JSON and Markdown audit reports with counts and issue coordinates. Cell values
  and header names are omitted. Each issue-coordinate sample is capped at 20;
  the total counts cover the entire accepted input. Reports include a source hash
  and file size, so treat them as metadata rather than anonymized data.

Records refer to parsed CSV records: a quoted multiline field belongs to one
record. The header is record 1. Header checks trim surrounding whitespace and
compare case-sensitively; duplicate-header coordinates identify subsequent
occurrences. Empty headers are counted separately. Blank means empty or entirely
whitespace. Exact duplicate checks compare original data fields and exclude the
header.

Auto-detection is a heuristic based on the first 64 KiB. Headerless files, alternate
encodings, schema/type validation, field-specific business rules, and spreadsheet
workbook formats are outside this utility's scope. The first record is always
treated as the header. Input limits are 20 MiB, 100,000 data records, and 1,000,000
total cells. Files are parsed in memory; this is a bounded small-file utility.
NUL bytes are rejected as a binary-input indicator.

## Explicit cleanup behavior

| Flag | Change |
| --- | --- |
| `--trim` | Trim surrounding whitespace in all cells, including headers. |
| `--remove-blank-rows` | Remove fully blank data records and empty physical lines. |
| `--remove-duplicates` | Keep the first exact original data record; remove later matches. |
| `--escape-formulas` | Prefix formula-like cells, including headers, with an apostrophe. |

Duplicate removal compares original records **before trimming**. Two originally
different records that become equal after trimming both survive. No type coercion
occurs: `0001` remains the string `0001`. Quoting and line endings are normalized
by the CSV writer, with LF record separators and the original delimiter. A UTF-8
BOM is preserved when present. Embedded newlines within quoted fields are retained.
With no cleanup flags, output is a serialized copy with the same cell values.

Nonempty parsed records with a different number of fields than the header cause
cleanup to fail before creating output, even if blank-row removal is requested.
Empty physical lines parse as zero-field records; audit counts them as fully blank
records, and cleanup accepts them only with `--remove-blank-rows`. Headers are
never silently renamed or invented. Audit reports malformed widths without fixing
them, and a successful audit can still contain issues.

The formula heuristic flags cells whose first non-whitespace character is `=`,
`+`, `-`, or `@`. This deliberately includes legitimate negative numbers. Escaping
is opt-in because it changes the cell value. Spreadsheet behavior varies: an
apostrophe prefix is a practical mitigation, not a guarantee for every importer
or later transformation. CSV quoting alone does not disable formulas. Review the
result in the intended spreadsheet application before delivering it for that use.

## File handling

Input and output must be separate. Existing files, symbolic links, and competing
writers cannot be overwritten. The tool writes a private temporary file in the
destination directory, flushes it, then publishes it with an exclusive hard link.
A failure before publication leaves no partial output. The destination directory
must exist and support hard links; unsupported filesystems fail instead of falling
back to an unsafe overwrite. New files use owner-only permissions. This protects
the destination's atomic visibility; it does not promise recovery from a storage
device failure. The input is never written.

CLI exit code 0 means the command completed; code 2 means invalid input or a file
operation failed. Audit issue counts are review findings, not an automatic failure
exit code. Cleanup prints a JSON change summary and source audit to stdout; redirect
that summary into a new review file if desired.

## Synthetic example and verification

`examples/before.csv` is invented data using reserved `example.com` addresses.
Its generated result and reports are committed beside it:

- `after.csv`: output of all four cleanup flags.
- `before-audit.json` and `before-audit.md`: original audit.
- `after-audit.json`: output audit.
- `cleanup-summary.json`: measured changes and input/output hashes.

The sample contains 8 data records, 1 exact duplicate, 1 fully blank record,
5 blank data cells, and 2 formula-like cells. All four flags produce 6 data
records, remove the duplicate and blank record, trim 8 cells, and prefix 2 cells.
The missing email remains blank; no value is invented. Customer IDs retain
their leading zeroes. See `examples/EXAMPLE.md` for the measured before/after table.

Run the focused tests:

```bash
python3 -m unittest discover -s tests -v
```

The tests exercise quoted multiline fields, semicolon detection, BOM preservation,
malformed CSV/UTF-8/width rejection, exact duplicate semantics, original
preservation, leading zeroes, formula detection and opt-in escaping, bounded
reports and input limits, no-clobber races, and partial-write cleanup. Spreadsheet
application acceptance and customer-file validation have not been performed.

MIT licensed; see `LICENSE`.
