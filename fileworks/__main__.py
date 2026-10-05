import argparse
import sys

from .core import DELIMITERS, FileworksError, atomic_new_file, audit_file, clean_file, report_text


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit and explicitly clean local UTF-8 CSV files.")
    commands = parser.add_subparsers(dest="command", required=True)
    audit = commands.add_parser("audit", help="Report structural issues without exposing cell values.")
    clean = commands.add_parser("clean", help="Write a separate new CSV; never overwrite a file.")
    for command in (audit, clean):
        command.add_argument("input", help="CSV with a header record, maximum 20 MiB.")
        command.add_argument("--delimiter", choices=DELIMITERS, help="Explicit delimiter; default is auto-detect.")
    audit.add_argument("--format", choices=("json", "markdown"), default="json")
    audit.add_argument("--output", help="Save report to a new file; default is stdout.")
    clean.add_argument("output", help="New output file; parent directory must already exist.")
    clean.add_argument("--trim", action="store_true", help="Trim surrounding whitespace, including headers.")
    clean.add_argument("--remove-blank-rows", action="store_true")
    clean.add_argument("--remove-duplicates", action="store_true", help="Remove exact original duplicate data records.")
    clean.add_argument("--escape-formulas", action="store_true", help="Prefix formula-like cells with an apostrophe.")
    args = parser.parse_args(argv)
    delimiter = DELIMITERS.get(args.delimiter)
    try:
        if args.command == "audit":
            report = report_text(audit_file(args.input, delimiter), args.format)
            if args.output:
                atomic_new_file(args.output, lambda stream: stream.write(report.encode("utf-8")))
            else:
                sys.stdout.write(report)
        else:
            report = clean_file(args.input, args.output, delimiter, trim=args.trim,
                                remove_blank_rows=args.remove_blank_rows,
                                remove_duplicates=args.remove_duplicates,
                                escape_formulas=args.escape_formulas)
            sys.stdout.write(report_text(report))
    except (FileworksError, OSError) as exc:
        print(f"fileworks: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
