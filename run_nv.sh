#!/bin/bash

python '/home/misael/Dev/novel-manager/main.py'

# Clean up pycache directories after the app closes
find "$(dirname "$0")/src" -type d -name "__pycache__" -exec rm -rf {} +
