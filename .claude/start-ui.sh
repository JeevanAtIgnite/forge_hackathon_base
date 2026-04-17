#!/bin/bash
cd "$(dirname "$0")/../ui"
exec ./node_modules/.bin/vite --port "${PORT:-4731}" --strictPort --host 127.0.0.1
