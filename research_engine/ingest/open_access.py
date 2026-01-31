"""Open access PDF acquisition via multiple sources.

Strategy order (per DOI):
  1. Publisher-specific direct PDF URL patterns (no Cloudflare)
  2. PMC (via NCBI ID converter → PMC PDF)
  3. Unpaywall best PDF URL
  4. If all fail → queued for browser automation

Publisher-specific patterns work because many OA publishers have predictable
PDF URLs that bypass Cloudflare/bot detection when accessed directly.
"""

import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import requests
except ImportError:
    raise ImportError("'requests' package required. Install with: pip install requests")

UNPAYWALL_API = "https://api.unpaywall.org/v2"
NCBI_ID_CONVERTER = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
MAILTO = "itod2305@uni.sydney.edu.au"
RATE_LIMIT_DELAY = 0.2  # 5 req/sec for Unpaywall


# --- Publisher-specific direct PDF URL builders ---
# These return a direct PDF URL from a DOI, bypassing publisher landing pages.

def _plos_pdf(doi: str) -> Optional[str]:
    """PLOS journals: fully OA, direct PDF via API."""
    if doi.startswith("10.1371/"):
        return f"https://journals.plos.org/plosone/article/file?id={doi}&type=printable"
    return None


def _pmc_pdf(doi: str, session: requests.Session) -> Optional[str]:
    """Check NCBI for PMC version and return PMC PDF URL."""
    try:
        resp = session.get(
            NCBI_ID_CONVERTER,
            params={"ids": doi, "format": "json", "tool": "research-engine", "email": MAILTO},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        records = data.get("records", [])
        if records and records[0].get("pmcid"):
            pmcid = records[0]["pmcid"]
            return f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"
    except (requests.RequestException, json.JSONDecodeError, KeyError):
        pass
    return None


def _arxiv_pdf(doi: str) -> Optional[str]:
    """arXiv papers: direct PDF."""
    if "arxiv" in doi.lower():
        # DOI format: 10.48550/arXiv.XXXX.XXXXX
        m = re.search(r"arXiv\.(\d+\.\d+)", doi, re.IGNORECASE)
        if m:
            return f"https://arxiv.org/pdf/{m.group(1)}"
    return None


def _biorxiv_pdf(doi: str) -> Optional[str]:
    """bioRxiv/medRxiv: direct PDF via content server."""
    if doi.startswith("10.1101/"):
        # Try bioRxiv first, then medRxiv
        return f"https://www.biorxiv.org/content/{doi}v1.full.pdf"
    return None


def _elife_pdf(doi: str) -> Optional[str]:
    """eLife: fully OA, direct PDF."""
    if doi.startswith("10.7554/eLife."):
        article_id = doi.replace("10.7554/eLife.", "")
        return f"https://elifesciences.org/articles/{article_id}.pdf"
    return None


def _mdpi_pdf(doi: str) -> Optional[str]:
    """MDPI: fully OA, direct PDF."""
    if doi.startswith("10.3390/"):
        return f"https://www.mdpi.com/{doi.replace('10.3390/', '')}/pdf"
    return None


def _frontiers_pdf(doi: str) -> Optional[str]:
    """Frontiers: fully OA, but needs DOI resolution for the path."""
    # Frontiers PDFs are at predictable paths but need the article path
    # which isn't derivable from DOI alone. Skip — Unpaywall handles these.
    return None


def _peerj_pdf(doi: str) -> Optional[str]:
    """PeerJ: fully OA."""
    if doi.startswith("10.7717/peerj."):
        article_id = doi.replace("10.7717/peerj.", "")
        return f"https://peerj.com/articles/{article_id}.pdf"
    return None


def _royal_society_pdf(doi: str) -> Optional[str]:
    """Royal Society Open Science: OA papers have predictable PDF URLs."""
    if doi.startswith("10.1098/rsos."):
        return None  # Blocked by Cloudflare
    return None


# Ordered list of publisher-specific strategies
# Only includes publishers confirmed to serve PDFs without Cloudflare gates.
# bioRxiv, eLife, MDPI, PeerJ, PMC all return 403 from requests.
PUBLISHER_STRATEGIES = [
    _arxiv_pdf,
    _plos_pdf,
]


def find_pdf_url(
    doi: str,
    session: requests.Session,
    try_unpaywall: bool = False,
    try_pmc: bool = False,
) -> Tuple[Optional[str], str]:
    """Find a downloadable PDF URL for a DOI.

    Tries publisher-specific patterns first, then optionally PMC/Unpaywall.
    PMC and Unpaywall are disabled by default because most URLs they return
    are blocked by Cloudflare when accessed via requests.

    Returns:
        (url, source) where source is one of: 'publisher', 'pmc', 'unpaywall', or None if not found.
    """
    # 1. Publisher-specific direct URL (PLOS, arXiv — confirmed working)
    for strategy in PUBLISHER_STRATEGIES:
        url = strategy(doi)
        if url:
            return url, "publisher"

    # 2. PMC (usually blocked by Cloudflare, disabled by default)
    if try_pmc:
        url = _pmc_pdf(doi, session)
        if url:
            return url, "pmc"

    # 3. Unpaywall (URLs usually blocked by Cloudflare, disabled by default)
    if try_unpaywall:
        time.sleep(RATE_LIMIT_DELAY)
        url = check_unpaywall(doi, session)
        if url:
            return url, "unpaywall"

    return None, ""


def check_unpaywall(doi: str, session: Optional[requests.Session] = None) -> Optional[str]:
    """Check Unpaywall for an open access PDF URL.

    Returns the best OA direct PDF URL, or None.
    Only returns url_for_pdf (not landing pages, which can't be downloaded).
    """
    s = session or requests.Session()

    try:
        resp = s.get(
            f"{UNPAYWALL_API}/{doi}",
            params={"email": MAILTO},
            timeout=15,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, json.JSONDecodeError):
        return None

    # Collect all PDF URLs from all OA locations
    pdf_urls = []

    best = data.get("best_oa_location") or {}
    if best.get("url_for_pdf"):
        pdf_urls.append(best["url_for_pdf"])

    for loc in data.get("oa_locations", []):
        url = loc.get("url_for_pdf")
        if url and url not in pdf_urls:
            pdf_urls.append(url)

    # Prefer URLs that look like direct PDF links
    for url in pdf_urls:
        if url.endswith(".pdf") or "/pdf/" in url:
            return url

    # Fall back to any PDF URL
    return pdf_urls[0] if pdf_urls else None


def download_pdf(
    url: str,
    output_path: Path,
    session: requests.Session,
) -> bool:
    """Download a PDF from a URL and verify it's a real PDF.

    Returns True if successful, False otherwise. Cleans up on failure.
    """
    try:
        resp = session.get(url, timeout=60, stream=True, allow_redirects=True)
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        is_pdf = (
            "pdf" in content_type.lower()
            or url.endswith(".pdf")
            or "/pdf/" in url
            or resp.url.endswith(".pdf")
        )
        if not is_pdf:
            return False

        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        # Verify magic bytes
        with open(output_path, "rb") as f:
            header = f.read(5)
        if header != b"%PDF-":
            output_path.unlink()
            return False

        return True

    except requests.RequestException:
        if output_path.exists():
            output_path.unlink()
        return False


def acquire_oa_pdfs(
    refs: List[Dict],
    output_dir: Path,
    session: Optional[requests.Session] = None,
    limit: int = 0,
    verbose: bool = True,
) -> Dict[str, str]:
    """Acquire open access PDFs for references with DOIs.

    Args:
        refs: List of reference dicts with 'doi' and 'cite_key' fields
        output_dir: Directory to save PDFs
        session: requests Session
        limit: Max to process (0 = all)
        verbose: Print progress

    Returns:
        Dict mapping cite_key -> local PDF path
    """
    s = session or requests.Session()
    s.headers.setdefault("User-Agent", f"research-engine/0.1.0 (mailto:{MAILTO})")

    output_dir.mkdir(parents=True, exist_ok=True)

    with_doi = [r for r in refs if r.get("doi")]
    if limit > 0:
        with_doi = with_doi[:limit]

    if verbose:
        print(f"Checking Unpaywall for {len(with_doi)} references...")

    acquired = {}
    checked = 0
    found = 0

    for ref in with_doi:
        checked += 1
        if verbose and checked % 25 == 0:
            print(f"  [{checked}/{len(with_doi)}] found: {found}")

        time.sleep(RATE_LIMIT_DELAY)

        pdf_url = check_unpaywall(ref["doi"], session=s)
        if not pdf_url:
            continue

        found += 1
        cite_key = ref["cite_key"]

        # Download the PDF
        pdf_path = output_dir / f"{cite_key}.pdf"
        if pdf_path.exists():
            acquired[cite_key] = str(pdf_path)
            continue

        if download_pdf(pdf_url, pdf_path, s):
            acquired[cite_key] = str(pdf_path)

    if verbose:
        print(f"\n  Checked: {checked}")
        print(f"  OA found: {found}")
        print(f"  Downloaded: {len(acquired)}")

    return acquired
