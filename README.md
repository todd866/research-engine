# Research Engine

**AI-assisted research infrastructure: citation management, literature ingestion, claim verification, and two-system methodology.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

---

## What This Is

Research Engine is the toolchain behind [Coherence Dynamics](https://coherencedynamics.com) — a research program producing 30+ papers across physics, neuroscience, biology, and mathematics. It manages the full lifecycle of AI-assisted academic research:

```
LaTeX projects  ──→  Citation extraction  ──→  DOI resolution  ──→  Bibliography database
                                                                            │
                                                                            ▼
OpenAlex/arXiv  ──→  Paper discovery     ──→  PDF acquisition  ──→  Text extraction
                                                                            │
                                                                            ▼
                                              Structured reading  ──→  Claim embedding
                                                                            │
                                                                            ▼
                                              Conflict detection  ◄──  Queryable index
```

## Quick Start

```bash
# Clone
git clone https://github.com/todd866/research-engine.git
cd research-engine

# Install
pip install -r requirements.txt

# Extract citations from a LaTeX project
python3 -m research_engine extract /path/to/your/latex/project

# Resolve missing DOIs via CrossRef
python3 -m research_engine resolve /path/to/bibliography.json

# Discover new papers matching your research profile
python3 -m research_engine harvest --config config.yaml
```

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system design.

**Three layers:**

| Layer | What it does | Key modules |
|-------|-------------|-------------|
| **Bibliography** | Extract, resolve, verify citations | `bib/extract.py`, `bib/resolve.py`, `bib/verify.py` |
| **Harvest + Ingest** | Discover papers, acquire PDFs, extract text | `harvest/`, `ingest/` |
| **Read + Embed** | Structured summaries, claim vectors, gap detection | `read/`, `embed/` |

**Storage strategy:**
- Text + embeddings + metadata → **git** (small, versionable)
- PDFs → **Backblaze B2** (cheap, durable, not in git)

## Methodology

See [PHILOSOPHY.md](PHILOSOPHY.md) for the two-system methodology.

This toolchain is designed for a specific workflow: using high-dimensional reasoning (Claude Opus) for ideation and framework construction, paired with grounded verification (GPT) for error detection and fact-checking. The tools support both modes — discovery and audit.

## Current Scale

- **1,540** unique references extracted from 175 .tex + 60 .bib files
- **75%** DOI coverage (1,157/1,540 resolved via CrossRef)
- **4** paper discovery sources (OpenAlex, arXiv, bioRxiv, Semantic Scholar)
- **30+** papers in the research program

## Project Structure

```
research_engine/
├── __init__.py
├── __main__.py            # CLI entry point
├── bib/                   # Bibliography management
│   ├── extract.py         # Citation extraction from .tex/.bib
│   ├── resolve.py         # DOI resolution via CrossRef
│   ├── verify.py          # Verification against CrossRef metadata
│   └── pre_submit.py      # Pre-submission checklist
├── harvest/               # Paper discovery
│   ├── sources/           # OpenAlex, arXiv, bioRxiv, Semantic Scholar
│   ├── config.py          # Research profile configuration
│   └── cli.py             # Harvest command
├── ingest/                # PDF acquisition + text extraction
│   ├── open_access.py     # Unpaywall + arXiv download
│   ├── extract_text.py    # PyMuPDF text extraction
│   ├── cloud_store.py     # B2/S3 upload/download
│   └── browser_queue.py   # EZProxy download queue
├── read/                  # Structured reading
│   ├── read_paper.py      # Generate structured summaries
│   └── audit_usage.py     # Compare cited claims vs actual
└── embed/                 # Vector embedding space
    ├── embed_claims.py    # sentence-transformers encoding
    └── query.py           # Nearest neighbors, conflicts, gaps
```

## Workflows

- [Writing a Paper](workflows/writing-a-paper.md)
- [Auditing Citations](workflows/auditing-citations.md)
- [Reading Literature](workflows/reading-literature.md)
- [Two-System Methodology](workflows/two-system-methodology.md)

## Requirements

- Python 3.8+
- `requests` — HTTP client (CrossRef, Unpaywall, paper APIs)
- `PyMuPDF` — PDF text extraction
- `sentence-transformers` — claim embedding (optional, for embed module)
- `pyyaml`, `pydantic` — configuration

## Citation

If you use Research Engine in your work:

```bibtex
@software{todd2025researchengine,
  author = {Todd, Ian},
  title = {Research Engine: AI-Assisted Research Infrastructure},
  year = {2025},
  url = {https://github.com/todd866/research-engine}
}
```

## License

MIT — see [LICENSE](LICENSE).
