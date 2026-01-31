"""Generate a browser download queue for papers that can't be fetched via API.

Most publisher CDNs (Elsevier, Springer, Nature, Wiley, etc.) block
automated requests with Cloudflare. These papers need browser automation
to download, either via:
  1. Direct publisher access (for OA papers)
  2. EZProxy (for paywalled papers with institutional access)

This module generates a prioritized queue of DOIs to download via browser,
and provides utilities for processing the downloaded PDFs.
"""

import json
import os
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

# USyd EZProxy prefix
EZPROXY_PREFIX = "https://ezproxy.library.sydney.edu.au/login?url="

# DOI prefixes that are directly downloadable (no browser needed)
DIRECT_DOWNLOAD_PREFIXES = {"10.1371", "10.48550"}  # PLOS, arXiv


def _needs_browser(doi: str) -> bool:
    """Check if a DOI requires browser automation to download."""
    prefix = doi.split("/")[0] if "/" in doi else ""
    if prefix in DIRECT_DOWNLOAD_PREFIXES:
        return False
    if "arxiv" in doi.lower():
        return False
    return True


def generate_queue(
    data_dir: Path,
    output_path: Optional[Path] = None,
    limit: int = 0,
    prioritize_depth1: bool = True,
) -> Dict:
    """Generate a browser download queue from the bibliography.

    Filters to refs that:
      - Have DOIs
      - Don't already have text files
      - Can't be downloaded via API (need browser)

    Args:
        data_dir: Path to literature-data directory
        output_path: Where to save the queue JSON (default: data_dir/browser_queue.json)
        limit: Max entries (0 = all)
        prioritize_depth1: Put depth-1 refs first

    Returns:
        The queue dict
    """
    bib_path = data_dir / "bibliography.json"
    with open(bib_path) as f:
        data = json.load(f)
    refs = data["references"]

    text_dir = data_dir / "text"

    # Filter to refs needing browser download
    queue_refs = []
    for r in refs:
        doi = r.get("doi", "")
        if not doi:
            continue
        cite_key = r.get("cite_key", "")
        if (text_dir / f"{cite_key}.txt").exists():
            continue
        if not _needs_browser(doi):
            continue
        queue_refs.append(r)

    # Sort: depth 1 first, then by DOI prefix (batch by publisher)
    if prioritize_depth1:
        queue_refs.sort(key=lambda r: (r.get("depth", 1), r.get("doi", "")))

    if limit > 0:
        queue_refs = queue_refs[:limit]

    # Build queue entries with EZProxy URLs
    entries = []
    for r in queue_refs:
        doi = r["doi"]
        doi_url = f"https://doi.org/{doi}"
        entries.append({
            "cite_key": r["cite_key"],
            "doi": doi,
            "doi_url": doi_url,
            "ezproxy_url": f"{EZPROXY_PREFIX}{doi_url}",
            "title": r.get("title", "")[:100],
            "depth": r.get("depth", 1),
        })

    # Stats by publisher prefix
    prefix_counts = Counter()
    for e in entries:
        prefix = e["doi"].split("/")[0]
        prefix_counts[prefix] += 1

    queue = {
        "total": len(entries),
        "depth1": sum(1 for e in entries if e["depth"] == 1),
        "depth2": sum(1 for e in entries if e["depth"] == 2),
        "by_publisher": dict(prefix_counts.most_common(20)),
        "entries": entries,
    }

    if output_path is None:
        output_path = data_dir / "browser_queue.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)

    return queue


# Legacy API compatibility
def generate_ezproxy_urls(
    refs: List[Dict],
    ezproxy_host: str = "ezproxy.library.sydney.edu.au",
) -> List[Dict]:
    """Generate EZProxy URLs for paywalled papers with DOIs."""
    queue = []
    for ref in refs:
        doi = ref.get("doi", "")
        if not doi:
            continue
        url = f"https://doi-org.{ezproxy_host}/{doi}"
        queue.append({
            "cite_key": ref["cite_key"],
            "doi": doi,
            "title": ref.get("title", ""),
            "ezproxy_url": url,
        })
    return queue


def write_queue(
    refs: List[Dict],
    output_path: Path,
    ezproxy_host: str = "ezproxy.library.sydney.edu.au",
) -> int:
    """Write a download queue file for browser-automated acquisition."""
    queue = generate_ezproxy_urls(refs, ezproxy_host)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(queue, f, indent=2)
    return len(queue)


def process_downloaded_pdfs(
    data_dir: Path,
    download_dir: Path,
    upload_b2: bool = False,
    verbose: bool = True,
) -> int:
    """Process PDFs that were downloaded via browser automation.

    Scans download_dir for PDFs, extracts text, optionally uploads to B2,
    then deletes the local PDF.

    PDF filenames should be {cite_key}.pdf.

    Args:
        data_dir: Path to literature-data directory
        download_dir: Directory containing downloaded PDFs
        upload_b2: Upload to B2 after text extraction
        verbose: Print progress
    """
    from .extract_text import extract_text

    text_dir = data_dir / "text"
    text_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = data_dir / "pdf_manifest.json"
    manifest = {"pdfs": {}}
    if manifest_path.exists():
        with open(manifest_path) as f:
            manifest = json.load(f)

    b2_bucket = None
    if upload_b2:
        try:
            from .cloud_store import get_b2_bucket
            b2_bucket = get_b2_bucket()
        except Exception as e:
            if verbose:
                print(f"B2 setup failed: {e}")

    extracted = 0
    uploaded = 0
    failed = 0

    for pdf_path in sorted(download_dir.glob("*.pdf")):
        cite_key = pdf_path.stem
        text_path = text_dir / f"{cite_key}.txt"

        if text_path.exists():
            continue

        try:
            extract_text(pdf_path, text_path)
            extracted += 1
            if verbose and extracted % 10 == 0:
                print(f"  Extracted: {extracted}")
        except Exception as e:
            failed += 1
            if verbose:
                print(f"  Failed: {pdf_path.name}: {e}")
            continue

        if b2_bucket and cite_key not in manifest.get("pdfs", {}):
            try:
                from .cloud_store import upload_pdf, update_manifest
                file_id = upload_pdf(pdf_path, cite_key, bucket=b2_bucket)
                update_manifest(manifest_path, cite_key, file_id, doi="")
                with open(manifest_path) as f:
                    manifest = json.load(f)
                uploaded += 1
            except Exception:
                pass

        # Delete local PDF after processing
        pdf_path.unlink()

    if verbose:
        print(f"\n  Extracted: {extracted}")
        if failed:
            print(f"  Failed: {failed}")
        if uploaded:
            print(f"  Uploaded to B2: {uploaded}")

    return extracted
