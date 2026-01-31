"""Open access PDF acquisition via Unpaywall and arXiv."""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

try:
    import requests
except ImportError:
    raise ImportError("'requests' package required. Install with: pip install requests")

UNPAYWALL_API = "https://api.unpaywall.org/v2"
MAILTO = "itod2305@uni.sydney.edu.au"
RATE_LIMIT_DELAY = 0.2  # 5 req/sec


def check_unpaywall(doi: str, session: Optional[requests.Session] = None) -> Optional[str]:
    """Check Unpaywall for an open access PDF URL.

    Returns the best OA PDF URL, or None.
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

    # Check best OA location
    best = data.get("best_oa_location", {})
    if best:
        pdf_url = best.get("url_for_pdf")
        if pdf_url:
            return pdf_url
        landing = best.get("url_for_landing_page")
        if landing:
            return landing

    # Check all OA locations
    for loc in data.get("oa_locations", []):
        pdf_url = loc.get("url_for_pdf")
        if pdf_url:
            return pdf_url

    return None


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

        try:
            resp = s.get(pdf_url, timeout=60, stream=True)
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")
            if "pdf" not in content_type.lower() and not pdf_url.endswith(".pdf"):
                continue

            with open(pdf_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

            acquired[cite_key] = str(pdf_path)

        except requests.RequestException:
            continue

    if verbose:
        print(f"\n  Checked: {checked}")
        print(f"  OA found: {found}")
        print(f"  Downloaded: {len(acquired)}")

    return acquired
