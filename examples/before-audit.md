# CSV audit

Input SHA-256: `d7eed77111fa59a9e73e78289b99a6b202a913990efd64591ffbae7e7e2ce2e2`

Encoding: utf-8; delimiter: comma

| Check | Count |
| --- | ---: |
| data records | 8 |
| columns | 4 |
| empty headers | 0 |
| duplicate headers | 0 |
| width mismatches | 0 |
| fully blank records | 1 |
| duplicate records | 1 |
| blank data cells | 5 |
| formula like cells | 2 |

Record numbers are CSV records (header is 1), not physical line numbers.
Header checks trim whitespace and compare case-sensitively. Values are omitted.
Formula-like means the first non-whitespace character is =, +, -, or @.

## Issue coordinates (first 20 per check)

```json
{
  "empty_header_columns": [],
  "duplicate_header_columns": [],
  "examples": {
    "width_mismatches": [],
    "duplicate_records": [
      3
    ],
    "formula_like_cells": [
      {
        "record": 7,
        "column": 4
      },
      {
        "record": 9,
        "column": 3
      }
    ]
  }
}
```
