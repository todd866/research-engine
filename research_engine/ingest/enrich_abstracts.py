"""Enrich bibliography with abstracts from OpenAlex.

OpenAlex provides abstracts as inverted indexes (word -> [positions]).
We reconstruct them and store in bibliography.json and the SQLite DB.

Rate limits: 10 req/sec with polite pool (mailto in User-Agent).
Batch: up to 50 DOIs per request via pipe-delimited filter.
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

try:
    import requests
except ImportError:
    raise ImportError("'requests' package required.")

OPENALEX_API = "https://api.openalex.org/works"
MAILTO = "itod2305@uni.sydney.edu.au"
BATCH_SIZE = 50  # Max DOIs per OpenAlex request
RATE_LIMIT_DELAY = 0.12  # ~8 req/sec, stay in polite pool


def _reconstruct_abstract(inverted_index: dict) -> str:
    """Reconstruct abstract text from OpenAlex inverted index."""
    if not inverted_index:
        return ""
    words = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            words[pos] = word
    return " ".join(words[i] for i in sorted(words.keys()))


def fetch_abstracts_batch(
    dois: List[str],
    session: requests.Session,
) -> Dict[str, str]:
    """Fetch abstracts for a batch of DOIs from OpenAlex.

    Args:
        dois: List of DOIs (max 50)
        session: requests Session

    Returns:
        Dict mapping DOI (lowercase) -> abstract text
    """
    if not dois:
        return {}

    # OpenAlex filter uses pipe-delimited DOIs
    doi_filter = "|".join(dois[:BATCH_SIZE])

    try:
        resp = session.get(
            OPENALEX_API,
            params={
                "filter": f"doi:{doi_filter}",
                "select": "doi,abstract_inverted_index",
                "per_page": BATCH_SIZE,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            return {}
        data = resp.json()
    except (requests.RequestException, json.JSONDecodeError):
        return {}

    results = {}
    for work in data.get("results", []):
        doi = work.get("doi", "")
        if doi:
            # OpenAlex returns full URL: https://doi.org/10.xxx
            doi_clean = doi.replace("https://doi.org/", "").lower()
            abstract = _reconstruct_abstract(work.get("abstract_inverted_index"))
            if abstract:
                results[doi_clean] = abstract

    return results


def enrich_bibliography(
    data_dir: Path,
    limit: int = 0,
    verbose: bool = True,
) -> int:
    """Enrich bibliography.json with abstracts from OpenAlex.

    Only processes refs that have DOIs and don't already have abstracts.

    Args:
        data_dir: Path to literature-data directory
        limit: Max refs to process (0 = all)
        verbose: Print progress
    """
    bib_path = data_dir / "bibliography.json"
    with open(bib_path) as f:
        data = json.load(f)

    refs = data["references"]

    # Filter to refs needing abstracts
    need_abstract = [r for r in refs if r.get("doi") and not r.get("abstract")]

    if limit > 0:
        need_abstract = need_abstract[:limit]

    if verbose:
        print(f"\n{'='*60}")
        print("Abstract Enrichment via OpenAlex")
        print(f"{'='*60}")
        print(f"  Total references:          {len(refs)}")
        print(f"  Already have abstracts:    {sum(1 for r in refs if r.get('abstract'))}")
        print(f"  Need abstracts (with DOI): {len(need_abstract)}")

    session = requests.Session()
    session.headers["User-Agent"] = f"research-engine/0.1.0 (mailto:{MAILTO})"

    # Build DOI -> ref index for fast lookup
    doi_to_refs = {}
    for r in need_abstract:
        doi_lower = r["doi"].lower()
        if doi_lower not in doi_to_refs:
            doi_to_refs[doi_lower] = []
        doi_to_refs[doi_lower].append(r)

    # Process in batches
    all_dois = list(doi_to_refs.keys())
    total_found = 0
    total_checked = 0

    for i in range(0, len(all_dois), BATCH_SIZE):
        batch = all_dois[i:i + BATCH_SIZE]
        total_checked += len(batch)

        time.sleep(RATE_LIMIT_DELAY)
        abstracts = fetch_abstracts_batch(batch, session)
        total_found += len(abstracts)

        # Apply abstracts to refs
        for doi_lower, abstract in abstracts.items():
            for ref in doi_to_refs.get(doi_lower, []):
                ref["abstract"] = abstract

        if verbose and (i // BATCH_SIZE + 1) % 20 == 0:
            print(f"  [{total_checked}/{len(all_dois)}] found: {total_found}")

    # Save
    data["references"] = refs
    data["metadata"]["refs_with_abstracts"] = sum(1 for r in refs if r.get("abstract"))

    with open(bib_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    if verbose:
        print(f"\n  Checked:    {total_checked}")
        print(f"  Found:      {total_found}")
        print(f"  Hit rate:   {100 * total_found // max(total_checked, 1)}%")
        print(f"  Total with abstracts now: {data['metadata']['refs_with_abstracts']}")
        print(f"  Saved to {bib_path}")

    # Also update SQLite if it exists
    db_path = data_dir / "literature.db"
    if db_path.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            updated = 0
            for r in refs:
                if r.get("abstract"):
                    cursor.execute(
                        "UPDATE refs SET abstract = ?, has_abstract = 1 WHERE cite_key = ?",
                        (r["abstract"], r["cite_key"]),
                    )
                    updated += 1
            conn.commit()
            conn.close()
            if verbose:
                print(f"  Updated {updated} rows in SQLite")
        except Exception as e:
            if verbose:
                print(f"  SQLite update failed: {e}")

    return total_found
