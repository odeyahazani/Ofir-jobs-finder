#!/usr/bin/env bash
set -eu
cd /workspace/Ofir-jobs-finder
node -e 'if (Number(process.versions.node.split(".")[0]) < 24) { throw new Error("Node 24+ required"); }'
python -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ required"'
npm ci --cache /workspace/.npm-cache --no-audit --no-fund
python -m collector.cli init
if [ ! -e .env.local ]; then
  printf '%s\n' 'LOCAL_DEV_MODE=1' 'APP_URL=http://127.0.0.1:3000' > .env.local
fi
