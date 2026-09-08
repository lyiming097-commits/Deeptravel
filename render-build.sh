#!/usr/bin/env bash

set -Eeuo pipefail

python -m pip install --upgrade pip
python -m pip install -e './backend' 'mcp-server-12306==0.5.0.post20260822'

