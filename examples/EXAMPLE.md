# Synthetic CSV cleanup example

This is a demonstration using invented records and reserved `example.com`
addresses. It is not a customer case study. Counts below were produced by the
included utility from these checked-in files.

| Measure | Before | After |
| --- | ---: | ---: |
| Data records | 8 | 6 |
| Columns | 4 | 4 |
| Exact duplicate records | 1 | 0 |
| Fully blank records | 1 | 0 |
| Blank data cells | 5 | 1 |
| Formula-like cells | 2 | 0 |
| Malformed record widths | 0 | 0 |

The cleanup trimmed 8 cells, removed 1 duplicate and 1 blank record, and prefixed
2 formula-like cells with an apostrophe. The retained blank email needs human
review; the tool cannot supply missing information. The negative refund amount
was conservatively flagged and escaped along with `=1+1`. Use the formula option
only when that change matches the intended spreadsheet import workflow.

Representative parsed values:

| Field | Before | After |
| --- | --- | --- |
| First customer ID | ` 0001 ` | `0001` |
| First email | ` buyer01@example.com ` | `buyer01@example.com` |
| Formula-like note | `=1+1` | `'=1+1` |
| Refund amount | `-12.00` | `'-12.00` |
| Missing email | empty | empty |
| Quoted delivery note | `delivery, afternoon` | `delivery, afternoon` |

The quoted multiline note is also preserved. Source bytes were checked again
after cleanup and were unchanged. Source SHA-256:

```text
d7eed77111fa59a9e73e78289b99a6b202a913990efd64591ffbae7e7e2ce2e2
```

Reproduce to a fresh output path from the project directory:

```bash
python3 -m fileworks audit examples/before.csv --format markdown
python3 -m fileworks clean examples/before.csv /tmp/fileworks-example-new.csv \
  --trim --remove-blank-rows --remove-duplicates --escape-formulas
python3 -m fileworks audit /tmp/fileworks-example-new.csv --format markdown
```

`cleanup-summary.json` records hashes and exact change counts. Audit reports list
coordinates without cell values. No external spreadsheet application has been
used to validate the result; the verification covers Python CSV parsing and the
documented transformation behavior.
