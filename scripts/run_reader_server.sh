#!/usr/bin/env bash
set -euo pipefail
cd /home/orange/paper-search-reader-site
exec python3 -m paper_search.reader_server \
  --site-dir private-reader-site \
  --profile private \
  --site-title 'Sidney Deep Paper Reader' \
  --host 127.0.0.1 \
  --port 8765
