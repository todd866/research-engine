#!/bin/bash
set -e

echo "=== Research Engine Setup ==="

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install development tools
pip install pytest black ruff

# Clone literature-data (private repo) if not already present
echo "Setting up literature data..."
LITERATURE_DIR="/workspaces/literature-data"
if [ ! -d "$LITERATURE_DIR" ]; then
    echo "Cloning literature-data..."
    gh repo clone todd866/literature-data "$LITERATURE_DIR" || {
        echo "WARNING: Could not clone literature-data."
        echo "Run: gh auth login && gh repo clone todd866/literature-data $LITERATURE_DIR"
    }
else
    echo "literature-data already present, pulling latest..."
    cd "$LITERATURE_DIR" && git pull && cd -
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Run the pipeline:"
echo "  python3 -m research_engine status \$RESEARCH_DATA"
echo "  bash workflows/run-pipeline.sh status"
echo "  bash workflows/run-pipeline.sh all      # Full pipeline"
echo "  bash workflows/run-pipeline.sh depth2    # Depth-2 only"
echo "  bash workflows/run-pipeline.sh ingest    # OA + text only"
