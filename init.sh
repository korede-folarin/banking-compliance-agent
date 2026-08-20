#!/bin/bash
# init.sh — sets up the environment. Read this at the start of every
# Claude Code session before doing anything else.

set -e

echo "Setting up Banking Compliance Agent environment..."

# Create venv if it doesn't exist
if [ ! -d ".venv" ]; then
  if command -v py >/dev/null 2>&1; then
    py -3.11 -m venv .venv
  else
    python3 -m venv .venv
  fi
fi

# venv layout differs: POSIX uses bin/, Windows uses Scripts/
if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
else
  source .venv/Scripts/activate
fi

# Install dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Copy env template if .env doesn't exist yet
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "Created .env from .env.example — add your ANTHROPIC_API_KEY before running."
fi

echo "Setup complete. Run 'streamlit run src/app.py' to start the app."
echo "Run 'python -m pytest tests/' to run tests."
