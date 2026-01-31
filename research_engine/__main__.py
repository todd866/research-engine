"""Allow running as python -m research_engine."""

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Research Engine — AI-assisted research infrastructure",
        prog="research_engine",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # extract command
    extract_parser = subparsers.add_parser(
        "extract", help="Extract citations from a LaTeX project"
    )
    extract_parser.add_argument(
        "project_root",
        type=Path,
        help="Root directory of the LaTeX project",
    )
    extract_parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Output path for bibliography.json (default: <project_root>/literature/bibliography.json)",
    )
    extract_parser.add_argument(
        "--stats-only",
        action="store_true",
        help="Only print stats, don't write output",
    )

    # resolve command
    resolve_parser = subparsers.add_parser(
        "resolve", help="Resolve missing DOIs via CrossRef"
    )
    resolve_parser.add_argument(
        "bibliography",
        type=Path,
        help="Path to bibliography.json",
    )
    resolve_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without saving changes",
    )
    resolve_parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max references to resolve (0 = all)",
    )
    resolve_parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress output",
    )

    # verify command
    verify_parser = subparsers.add_parser(
        "verify", help="Verify DOIs against CrossRef metadata"
    )
    verify_parser.add_argument(
        "bibliography",
        type=Path,
        help="Path to bibliography.json",
    )
    verify_parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max references to verify (0 = all)",
    )

    # harvest command
    harvest_parser = subparsers.add_parser(
        "harvest", help="Discover new papers"
    )
    harvest_parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config.yaml",
    )

    # pre-submit command
    presubmit_parser = subparsers.add_parser(
        "pre-submit", help="Pre-submission citation check"
    )
    presubmit_parser.add_argument(
        "tex_file",
        type=Path,
        help="Path to main .tex file",
    )
    presubmit_parser.add_argument(
        "--bib",
        type=Path,
        default=None,
        help="Path to bibliography.json",
    )

    # ingest command
    ingest_parser = subparsers.add_parser(
        "ingest", help="Acquire OA PDFs and extract text"
    )
    ingest_parser.add_argument(
        "data_dir",
        type=Path,
        help="Path to literature-data directory (contains bibliography.json)",
    )
    ingest_parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max references to process (0 = all)",
    )
    ingest_parser.add_argument(
        "--paper",
        type=str,
        default=None,
        help="Filter to refs from a specific paper folder (e.g. 'biosystems/40_simulated_geometry')",
    )
    ingest_parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip OA download, only extract text from existing PDFs",
    )
    ingest_parser.add_argument(
        "--upload-b2",
        action="store_true",
        help="Upload acquired PDFs to Backblaze B2",
    )

    # depth2 command
    depth2_parser = subparsers.add_parser(
        "depth2", help="Harvest depth-2 references from CrossRef"
    )
    depth2_parser.add_argument(
        "data_dir",
        type=Path,
        help="Path to literature-data directory (contains bibliography.json)",
    )
    depth2_parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max depth-1 refs to harvest from (0 = all)",
    )

    # status command
    status_parser = subparsers.add_parser(
        "status", help="Show pipeline status"
    )
    status_parser.add_argument(
        "data_dir",
        type=Path,
        help="Path to literature-data directory",
    )
    status_parser.add_argument(
        "--by-paper",
        action="store_true",
        help="Show breakdown by paper",
    )

    args = parser.parse_args()

    if args.command == "extract":
        from .bib.extract import extract_all, write_output
        refs, stats = extract_all(args.project_root.resolve())
        _print_extraction_stats(stats)
        if not args.stats_only:
            output_path = args.output or (args.project_root.resolve() / "literature" / "bibliography.json")
            write_output(refs, stats, output_path)
        return 0

    elif args.command == "resolve":
        from .bib.resolve import resolve_main
        return resolve_main(
            args.bibliography.resolve(),
            dry_run=args.dry_run,
            limit=args.limit,
            verbose=not args.quiet,
        )

    elif args.command == "verify":
        from .bib.verify import verify_main
        return verify_main(args.bibliography.resolve(), limit=args.limit)

    elif args.command == "harvest":
        from .harvest.cli import discover
        return discover(config_path=args.config)

    elif args.command == "pre-submit":
        from .bib.pre_submit import pre_submit_main
        return pre_submit_main(args.tex_file.resolve(), bib_path=args.bib)

    elif args.command == "ingest":
        from .ingest.pipeline import ingest_main
        return ingest_main(
            data_dir=args.data_dir.resolve(),
            limit=args.limit,
            paper_filter=args.paper,
            skip_download=args.skip_download,
            upload_b2=args.upload_b2,
        )

    elif args.command == "depth2":
        from .bib.depth2 import harvest_depth2
        return harvest_depth2(
            data_dir=args.data_dir.resolve(),
            limit=args.limit,
            verbose=True,
        )

    elif args.command == "status":
        from .ingest.pipeline import status_main
        return status_main(
            data_dir=args.data_dir.resolve(),
            by_paper=args.by_paper,
        )

    else:
        parser.print_help()
        return 1


def _print_extraction_stats(stats: dict) -> None:
    print(f"\n{'='*60}")
    print("Citation Extraction Report")
    print(f"{'='*60}")
    print(f"  .tex files scanned:     {stats['tex_files_scanned']}")
    print(f"  .bib files scanned:     {stats['bib_files_scanned']}")
    print(f"  bibitem refs found:     {stats['bibitem_refs_found']}")
    print(f"  bibtex refs found:      {stats['bibtex_refs_found']}")
    print(f"  total before dedup:     {stats['total_before_dedup']}")
    print(f"  total after dedup:      {stats['total_after_dedup']}")
    total = max(stats['total_after_dedup'], 1)
    print(f"  with DOI:               {stats['with_doi']} ({100*stats['with_doi']//total}%)")
    print(f"  with arXiv ID:          {stats['with_arxiv']}")
    print(f"  with title extracted:   {stats['with_title']} ({100*stats['with_title']//total}%)")
    print(f"{'='*60}")


if __name__ == "__main__":
    raise SystemExit(main())
