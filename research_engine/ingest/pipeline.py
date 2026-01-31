"""Ingest pipeline: OA acquisition + text extraction + optional B2 upload.

Processes one reference at a time to keep disk usage minimal:
  check Unpaywall → download PDF → extract text → upload B2 → delete local.
"""

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional


def _load_bibliography(data_dir: Path) -> list:
    """Load references from bibliography.json."""
    bib_path = data_dir / "bibliography.json"
    if not bib_path.exists():
        raise FileNotFoundError(f"No bibliography.json found at {bib_path}")
    with open(bib_path) as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("references", [])
    return data


def _filter_by_paper(refs: list, paper_filter: str) -> list:
    """Filter references to those from a specific paper folder."""
    filtered = []
    for r in refs:
        sources = r.get("source_files", [])
        if not sources:
            sf = r.get("source_file", "")
            if sf:
                sources = [sf]
        for sf in sources:
            if paper_filter in sf:
                filtered.append(r)
                break
    return filtered


def _paper_folder(ref: dict) -> str:
    """Extract paper folder from a reference's source file path."""
    sources = ref.get("source_files", [])
    if not sources:
        sf = ref.get("source_file", "")
        if sf:
            sources = [sf]
    for sf in sources:
        parts = sf.split("/")
        for i, p in enumerate(parts):
            if p == "highdimensional" and i + 2 < len(parts):
                return parts[i + 1] + "/" + parts[i + 2]
    return "unknown"


def _process_one_ref(
    ref: dict,
    pdf_dir: Path,
    text_dir: Path,
    manifest_path: Path,
    manifest: dict,
    session,
    b2_bucket,
) -> dict:
    """Process a single reference: check OA → download → extract → upload → delete.

    Returns a stats dict with keys: checked, oa_found, downloaded, extracted, uploaded, failed.
    """
    from .open_access import check_unpaywall, RATE_LIMIT_DELAY

    stats = {
        "checked": 1, "oa_found": 0, "downloaded": 0,
        "extracted": 0, "uploaded": 0, "failed": 0, "skipped_done": 0,
    }

    cite_key = ref["cite_key"]
    doi = ref["doi"]
    text_path = text_dir / f"{cite_key}.txt"

    # Already have text — skip entirely
    if text_path.exists():
        stats["skipped_done"] = 1
        return stats

    time.sleep(RATE_LIMIT_DELAY)

    # Step 1: Check Unpaywall for OA PDF URL
    pdf_url = check_unpaywall(doi, session=session)
    if not pdf_url:
        return stats

    stats["oa_found"] = 1
    pdf_path = pdf_dir / f"{cite_key}.pdf"

    # Step 2: Download PDF
    try:
        import requests
        resp = session.get(pdf_url, timeout=60, stream=True, allow_redirects=True)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        is_pdf = (
            "pdf" in content_type.lower()
            or pdf_url.endswith(".pdf")
            or "/pdf/" in pdf_url
            or resp.url.endswith(".pdf")
        )
        if not is_pdf:
            return stats

        with open(pdf_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        # Verify magic bytes
        with open(pdf_path, "rb") as f:
            header = f.read(5)
        if header != b"%PDF-":
            pdf_path.unlink()
            return stats

        stats["downloaded"] = 1
    except Exception:
        if pdf_path.exists():
            pdf_path.unlink()
        return stats

    # Step 3: Extract text
    try:
        from .extract_text import extract_text
        extract_text(pdf_path, text_path)
        stats["extracted"] = 1
    except Exception as e:
        stats["failed"] = 1
        # Clean up PDF even if text extraction fails
        if pdf_path.exists():
            pdf_path.unlink()
        return stats

    # Step 4: Upload to B2 (if configured)
    if b2_bucket and cite_key not in manifest.get("pdfs", {}):
        try:
            from .cloud_store import upload_pdf, update_manifest
            file_id = upload_pdf(pdf_path, cite_key, bucket=b2_bucket)
            update_manifest(manifest_path, cite_key, file_id, doi=doi)
            stats["uploaded"] = 1
        except Exception as e:
            # Text is saved — PDF stays local as fallback
            pass

    # Step 5: Delete local PDF (text is saved, PDF is in B2 or not needed locally)
    if pdf_path.exists():
        pdf_path.unlink()

    return stats


def ingest_main(
    data_dir: Path,
    limit: int = 0,
    paper_filter: Optional[str] = None,
    skip_download: bool = False,
    upload_b2: bool = False,
) -> int:
    """Run the ingest pipeline: per-ref OA acquisition + text extraction + B2.

    Processes one reference at a time to keep disk usage minimal.
    For each DOI: check Unpaywall → download PDF → extract text → upload B2 → delete local.

    Args:
        data_dir: Path to literature-data directory
        limit: Max references to process (0 = all)
        paper_filter: Only process refs from this paper folder
        skip_download: Skip OA download, only extract text from existing PDFs
        upload_b2: Upload acquired PDFs to B2 after download (and delete local)
    """
    import requests

    refs = _load_bibliography(data_dir)
    total = len(refs)

    # Filter by paper if requested
    if paper_filter:
        refs = _filter_by_paper(refs, paper_filter)
        print(f"Filtered to {len(refs)} refs from '{paper_filter}' (of {total} total)")
    else:
        print(f"Processing all {total} references")

    # Filter to refs with DOIs
    with_doi = [r for r in refs if r.get("doi")]
    print(f"  With DOIs: {len(with_doi)}")

    if limit > 0:
        with_doi = with_doi[:limit]
        print(f"  Limited to: {limit}")

    pdf_dir = data_dir / "pdfs"
    text_dir = data_dir / "text"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)

    # Load manifest
    manifest_path = data_dir / "pdf_manifest.json"
    manifest = {"pdfs": {}}
    if manifest_path.exists():
        with open(manifest_path) as f:
            manifest = json.load(f)

    # Set up B2 if requested
    b2_bucket = None
    if upload_b2:
        try:
            from .cloud_store import get_b2_bucket
            b2_bucket = get_b2_bucket()
            print(f"  B2 bucket connected: md3-storage")
        except Exception as e:
            print(f"  B2 setup failed: {e}")
            print("  Continuing without B2. PDFs will stay on disk.")
            b2_bucket = None

    # Handle skip_download: just extract text from existing PDFs
    if skip_download:
        existing_pdfs = list(pdf_dir.glob("*.pdf"))
        print(f"\nSkipping download. Processing {len(existing_pdfs)} existing PDFs.")
        extracted = 0
        for pdf_path in sorted(existing_pdfs):
            cite_key = pdf_path.stem
            text_path = text_dir / f"{cite_key}.txt"
            if not text_path.exists():
                try:
                    from .extract_text import extract_text
                    extract_text(pdf_path, text_path)
                    extracted += 1
                except Exception as e:
                    print(f"  Failed: {pdf_path.name}: {e}")
            if b2_bucket:
                if cite_key not in manifest.get("pdfs", {}):
                    try:
                        from .cloud_store import upload_pdf, update_manifest
                        file_id = upload_pdf(pdf_path, cite_key, bucket=b2_bucket)
                        ref = next((r for r in refs if r.get("cite_key") == cite_key), {})
                        update_manifest(manifest_path, cite_key, file_id, doi=ref.get("doi", ""))
                        with open(manifest_path) as f:
                            manifest = json.load(f)
                    except Exception:
                        pass
                pdf_path.unlink()
        print(f"  Extracted: {extracted}")
        return 0

    # Main per-reference loop
    session = requests.Session()
    session.headers["User-Agent"] = "research-engine/0.1.0 (mailto:itod2305@uni.sydney.edu.au)"

    print(f"\n{'='*60}")
    print("Per-PDF Ingest: Unpaywall → Download → Extract → B2 → Delete")
    print(f"{'='*60}")

    totals = {
        "checked": 0, "oa_found": 0, "downloaded": 0,
        "extracted": 0, "uploaded": 0, "failed": 0, "skipped_done": 0,
    }

    for i, ref in enumerate(with_doi):
        result = _process_one_ref(
            ref, pdf_dir, text_dir, manifest_path, manifest, session, b2_bucket,
        )

        for k in totals:
            totals[k] += result.get(k, 0)

        # Reload manifest periodically (after uploads)
        if result.get("uploaded") and manifest_path.exists():
            with open(manifest_path) as f:
                manifest = json.load(f)

        # Progress every 50 refs
        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(with_doi)}] "
                  f"OA: {totals['oa_found']}, "
                  f"text: {totals['extracted']}, "
                  f"B2: {totals['uploaded']}, "
                  f"skip: {totals['skipped_done']}")

    # Summary
    total_pdfs_b2 = len(manifest.get("pdfs", {}))
    total_text = len(list(text_dir.glob("*.txt")))
    print(f"\n{'='*60}")
    print("Ingest Summary")
    print(f"{'='*60}")
    print(f"  Checked:              {totals['checked']}")
    print(f"  Already had text:     {totals['skipped_done']}")
    print(f"  OA found:             {totals['oa_found']}")
    print(f"  Downloaded:           {totals['downloaded']}")
    print(f"  Text extracted:       {totals['extracted']}")
    if totals['failed']:
        print(f"  Failed:               {totals['failed']}")
    print(f"  Uploaded to B2:       {totals['uploaded']}")
    print(f"  Total text files:     {total_text}")
    print(f"  Total PDFs in B2:     {total_pdfs_b2}")
    print(f"{'='*60}")

    return 0


def status_main(data_dir: Path, by_paper: bool = False) -> int:
    """Show pipeline status."""
    refs = _load_bibliography(data_dir)

    depth1 = [r for r in refs if r.get("depth", 1) == 1]
    depth2 = [r for r in refs if r.get("depth") == 2]

    with_doi = [r for r in refs if r.get("doi")]
    d1_doi = [r for r in depth1 if r.get("doi")]
    d2_doi = [r for r in depth2 if r.get("doi")]

    pdf_dir = data_dir / "pdfs"
    text_dir = data_dir / "text"
    readings_dir = data_dir / "readings"
    embed_dir = data_dir / "embeddings"

    total_pdfs = len(list(pdf_dir.glob("*.pdf"))) if pdf_dir.exists() else 0
    total_text = len(list(text_dir.glob("*.txt"))) if text_dir.exists() else 0
    total_readings = len(list(readings_dir.glob("*.json"))) if readings_dir.exists() else 0

    has_embeddings = (embed_dir / "claims.npy").exists() if embed_dir.exists() else False

    print(f"\n{'='*60}")
    print("Research Engine — Pipeline Status")
    print(f"{'='*60}")

    print(f"\n  Depth-1 references:   {len(depth1)}")
    print(f"    With DOIs:          {len(d1_doi)} ({100*len(d1_doi)//max(len(depth1),1)}%)")
    if depth2:
        print(f"  Depth-2 references:   {len(depth2)}")
        print(f"    With DOIs:          {len(d2_doi)} ({100*len(d2_doi)//max(len(depth2),1)}%)")
    print(f"  Total references:     {len(refs)}")
    print(f"  Total with DOIs:      {len(with_doi)}")
    print()
    print(f"  PDFs acquired:        {total_pdfs}")
    print(f"  Text extracted:       {total_text}")
    print(f"  Readings generated:   {total_readings}")
    print(f"  Embeddings:           {'yes' if has_embeddings else 'no'}")

    # Coverage percentages
    if len(with_doi) > 0:
        print(f"\n  PDF coverage:         {total_pdfs}/{len(with_doi)} DOI refs ({100*total_pdfs//len(with_doi)}%)")
    if total_pdfs > 0:
        print(f"  Text coverage:        {total_text}/{total_pdfs} PDFs ({100*total_text//max(total_pdfs,1)}%)")

    if by_paper:
        print(f"\n{'='*60}")
        print("Breakdown by Paper (depth-1 only)")
        print(f"{'='*60}")

        paper_stats = defaultdict(lambda: {"total": 0, "doi": 0, "pdf": 0, "text": 0})

        pdf_keys = set()
        if pdf_dir.exists():
            pdf_keys = {p.stem for p in pdf_dir.glob("*.pdf")}
        text_keys = set()
        if text_dir.exists():
            text_keys = {p.stem for p in text_dir.glob("*.txt")}

        for r in depth1:
            folder = _paper_folder(r)
            paper_stats[folder]["total"] += 1
            if r.get("doi"):
                paper_stats[folder]["doi"] += 1
            if r["cite_key"] in pdf_keys:
                paper_stats[folder]["pdf"] += 1
            if r["cite_key"] in text_keys:
                paper_stats[folder]["text"] += 1

        # Filter out _archive papers and sort by total refs descending
        active_papers = {k: v for k, v in paper_stats.items() if not k.startswith("_archive")}

        print(f"\n  {'Paper':<45} {'Refs':>5} {'DOI':>5} {'PDF':>5} {'Text':>5}")
        print(f"  {'-'*45} {'-'*5} {'-'*5} {'-'*5} {'-'*5}")
        for folder in sorted(active_papers, key=lambda k: active_papers[k]["total"], reverse=True):
            s = active_papers[folder]
            print(f"  {folder:<45} {s['total']:>5} {s['doi']:>5} {s['pdf']:>5} {s['text']:>5}")

        if paper_stats.keys() - active_papers.keys():
            archive_total = sum(v["total"] for k, v in paper_stats.items() if k.startswith("_archive"))
            print(f"\n  (+ {archive_total} refs from archived papers)")

    print()
    return 0
