# Research Engine — Claude Code Instructions

## What This Is

Research Engine is the toolchain for AI-assisted academic research. It manages citations, discovers papers, ingests literature, and builds queryable knowledge bases.

## Quick Commands

```bash
# Extract citations from a LaTeX project
python3 -m research_engine extract /path/to/latex/project

# Resolve missing DOIs
python3 -m research_engine resolve /path/to/bibliography.json

# Verify resolved DOIs against CrossRef
python3 -m research_engine verify /path/to/bibliography.json

# Run paper discovery
python3 -m research_engine harvest --config config.yaml

# Pre-submission citation check
python3 -m research_engine pre-submit /path/to/paper.tex --bib /path/to/bibliography.json
```

## Architecture

Three layers — see ARCHITECTURE.md for full detail:

1. **Bibliography** (`research_engine/bib/`): Extract → Resolve → Verify → Pre-submit
2. **Harvest + Ingest** (`research_engine/harvest/`, `research_engine/ingest/`): Discover → Acquire → Extract text → Store
3. **Read + Embed** (`research_engine/read/`, `research_engine/embed/`): Structured reading → Claim vectors → Query

## Key Files

| File | Purpose |
|------|---------|
| `research_engine/bib/extract.py` | Citation extraction from .tex/.bib |
| `research_engine/bib/resolve.py` | DOI resolution via CrossRef |
| `research_engine/harvest/sources/` | Paper discovery (OpenAlex, arXiv, bioRxiv) |
| `research_engine/ingest/open_access.py` | Unpaywall + arXiv PDF download |
| `research_engine/ingest/extract_text.py` | PyMuPDF text extraction |

## Development

```bash
# Install deps
pip install -r requirements.txt

# Run from project root
python3 -m research_engine <command> [args]
```

## Data Storage

- **Text + metadata + embeddings** → git (version controlled)
- **PDFs** → Backblaze B2 (cloud, not in git)
- **bibliography.json** → git (the central database)

## API Keys / Rate Limits

- CrossRef: mailto header for polite pool (no key needed)
- OpenAlex: email param for polite pool (no key needed)
- B2: requires `B2_APPLICATION_KEY_ID` and `B2_APPLICATION_KEY` env vars
- Unpaywall: email param (no key needed)
