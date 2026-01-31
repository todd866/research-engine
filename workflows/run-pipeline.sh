#!/bin/bash
# Research Engine — Full Pipeline Runner
# Run this in a GitHub Codespace to process the entire literature database.
#
# Usage:
#   bash workflows/run-pipeline.sh              # Run all stages
#   bash workflows/run-pipeline.sh depth2       # Run only depth-2 harvesting
#   bash workflows/run-pipeline.sh ingest       # Run only OA acquisition + text extraction
#   bash workflows/run-pipeline.sh status       # Show pipeline status
#
# Prerequisites:
#   - RESEARCH_DATA env var pointing to literature-data directory
#     (set automatically by .devcontainer/setup.sh)
#   - pip install -r requirements.txt

set -e

DATA_DIR="${RESEARCH_DATA:-/workspaces/literature-data}"
BATCH_SIZE="${BATCH_SIZE:-200}"  # Papers per depth-2 batch
STAGE="${1:-all}"

if [ ! -f "$DATA_DIR/bibliography.json" ]; then
    echo "Error: bibliography.json not found at $DATA_DIR"
    echo "Set RESEARCH_DATA env var or clone literature-data first."
    exit 1
fi

echo "============================================"
echo "Research Engine Pipeline"
echo "============================================"
echo "Data directory: $DATA_DIR"
echo "Stage: $STAGE"
echo ""

run_status() {
    python3 -m research_engine status "$DATA_DIR" --by-paper
}

run_depth2() {
    echo "--- Depth-2 Reference Harvesting ---"
    echo "Processing in batches of $BATCH_SIZE..."
    echo ""

    # Run in batches until all depth-1 papers are harvested
    while true; do
        python3 -m research_engine depth2 "$DATA_DIR" --limit "$BATCH_SIZE"

        # Check if there are more to harvest
        HARVESTED=$(python3 -c "
import json
with open('$DATA_DIR/depth2_harvest_log.json') as f:
    log = json.load(f)
print(len(log['harvested_dois']))
")
        echo ""
        echo "Papers harvested so far: $HARVESTED"

        # Total depth-1 with DOI
        TOTAL=$(python3 -c "
import json
with open('$DATA_DIR/bibliography.json') as f:
    refs = json.load(f)['references']
print(sum(1 for r in refs if r.get('doi') and r.get('depth', 1) == 1))
")

        if [ "$HARVESTED" -ge "$TOTAL" ]; then
            echo "All depth-1 papers harvested!"
            break
        fi

        echo "Continuing... ($HARVESTED / $TOTAL)"
        echo ""

        # Commit progress after each batch
        cd "$DATA_DIR"
        git add bibliography.json depth2_harvest_log.json
        git commit -m "Depth-2 batch: $HARVESTED/$TOTAL papers harvested" || true
        git push origin main || true
        cd -
    done
}

run_ingest() {
    echo "--- OA Acquisition + Text Extraction ---"
    python3 -m research_engine ingest "$DATA_DIR"

    # Commit results
    cd "$DATA_DIR"
    git add bibliography.json text/ depth2_harvest_log.json
    git commit -m "Ingest: $(ls text/ | wc -l) text files extracted" || true
    git push origin main || true
    cd -
}

case "$STAGE" in
    status)
        run_status
        ;;
    depth2)
        run_depth2
        run_status
        ;;
    ingest)
        run_ingest
        run_status
        ;;
    all)
        run_status
        echo ""
        echo "============================================"
        echo "Stage 1: Depth-2 Harvesting"
        echo "============================================"
        run_depth2
        echo ""
        echo "============================================"
        echo "Stage 2: OA Acquisition + Text Extraction"
        echo "============================================"
        run_ingest
        echo ""
        echo "============================================"
        echo "Final Status"
        echo "============================================"
        run_status
        ;;
    *)
        echo "Unknown stage: $STAGE"
        echo "Usage: $0 [all|depth2|ingest|status]"
        exit 1
        ;;
esac
