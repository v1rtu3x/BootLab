#!/usr/bin/env bash
# Regenerate the terminal-style README/WALKTHROUGH animations.
# Requires Python 3.10+ and Pillow. Arguments are forwarded to the renderer.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -n "${BOOTLAB_ANIMATION_PYTHON:-}" ]]; then
    renderer_python="$BOOTLAB_ANIMATION_PYTHON"
elif [[ -x .venv/bin/python ]] && .venv/bin/python -c "import PIL" 2>/dev/null; then
    renderer_python=".venv/bin/python"
else
    renderer_python="python3"
fi

if ! "$renderer_python" -c "import PIL" 2>/dev/null; then
    echo "Pillow is required. Install it in your environment: python -m pip install Pillow" >&2
    exit 1
fi

echo "Generating explanatory animations and still frames..."
"$renderer_python" source/render_bootlab.py "$@"

echo "Done. Assets: assets/animations/; local gallery: preview.html"
