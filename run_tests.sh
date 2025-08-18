#!/bin/bash
set -e

if [[ "$1" == "--real" ]]; then
    echo "--- Running real integration tests ---"
    python3 -m pytest -m real
else
    echo "--- Running mocked tests ---"
    # This will run all tests that are NOT marked as 'real'
    python3 -m pytest
fi
