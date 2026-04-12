# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Parakeet Podcast Processor (P3) is a CLI tool that processes podcasts into structured summaries and blog posts. It runs a pipeline: RSS fetch -> ffmpeg audio normalization -> transcription (Parakeet MLX or Whisper) -> LLM analysis (Ollama/OpenAI) -> export (Markdown/JSON). Designed for 100% local processing on Apple Silicon Macs.

## Build & Development Commands

```bash
# Setup
python3 -m venv venv && source venv/bin/activate
pip install -e .            # Install with all dependencies
pip install -e ".[dev]"     # Install with dev dependencies (pytest, black, isort, mypy)

# CLI entry point (supports -v for verbose, -q for quiet)
p3 --help                   # All commands
p3 init                     # Initialize dirs, check prereqs, create DuckDB database
p3 fetch                    # Download episodes from RSS feeds
p3 fetch --dry-run          # Preview what would be downloaded
p3 transcribe               # Transcribe audio (Parakeet MLX preferred, Whisper fallback)
p3 digest                   # Generate structured summaries via LLM
p3 export                   # Export markdown/JSON digests to exports/
p3 write --topic "Topic"    # Generate blog post with AP English grading loop
p3 write --topic "T" --dry-run  # Preview available summaries without generating

# Tests
PYTHONPATH=. pytest tests/ -v           # Run all tests
PYTHONPATH=. pytest tests/test_database.py  # Run a single test file
PYTHONPATH=. pytest tests/ -k "test_name"   # Run a specific test by name

# Formatting
black .
isort .

# Type checking
mypy p3/
```

## Architecture

The CLI (`p3/cli.py`) is a Click group command. Each subcommand instantiates the relevant processing class and passes the shared `P3Database` instance via Click context. Logging is configured globally via `RichHandler` in the CLI, controlled by `-v`/`-q` flags.

**Pipeline flow through modules:**

1. **`downloader.py`** - `PodcastDownloader`: Parses RSS via `feedparser`, downloads audio via `requests` with retry+backoff, normalizes with `ffmpeg` subprocess (16kHz mono WAV). Temp files are cleaned up in `finally` blocks. Falls back to raw ffmpeg if primary normalization fails.

2. **`transcriber.py`** - `AudioTranscriber`: Lazy-loads models. Tries Parakeet MLX first (`parakeet_mlx.from_pretrained`), falls back to OpenAI Whisper. Both produce a common segment format `{start, end, text, speaker, confidence}`. Call `unload_models()` to free memory.

3. **`cleaner.py`** - `TranscriptCleaner`: Cleans transcripts (regex filler removal + LLM polish), then extracts structured JSON (topics, themes, quotes, companies, summary). Supports OpenAI (httpx) and Ollama (ollama SDK) backends; Anthropic raises `NotImplementedError`. Long transcripts are truncated to fit LLM context windows. Has `_basic_extraction` fallback using word frequency when no LLM is available. LLM calls are routed through a shared `_chat()` method.

4. **`exporter.py`** - `DigestExporter`: Pure formatting. Generates Markdown, JSON, and HTML email from summary dicts. Groups episodes by podcast. HTML output is escaped via `html.escape()`. Exports default to `exports/` directory.

5. **`writer.py`** - `BlogWriter`: Accepts multiple summaries to build combined context. Iterative grading loop (up to 3 iterations targeting 91/100 score) uses a distinct strict-evaluator persona to reduce self-grading bias. Also generates Twitter/LinkedIn social posts. Saves blog posts as Markdown with YAML frontmatter to `blog_posts/`.

6. **`database.py`** - `P3Database`: DuckDB storage layer with context manager support. Schema: `podcasts` -> `episodes` -> `transcripts` + `summaries`. Uses sequences for auto-increment IDs. Episode status tracks pipeline progress: `downloaded` -> `transcribed` -> `processed`. Query results are mapped to dicts via cursor column names. Indexes on `episodes(status, url)`, `transcripts(episode_id)`, `summaries(digest_date, episode_id)`.

## Configuration

`config/feeds.yaml` controls feeds and all settings. Key settings:
- `parakeet_enabled`: toggles Parakeet vs Whisper
- `llm_provider`: `ollama` or `openai` (default: `ollama`)
- `llm_model`: model name for the chosen provider
- `max_episodes_per_feed`: limits downloads per feed

## Key Design Decisions

- Database results are mapped to dicts using `cursor.description` column names — no hardcoded column positions.
- LLM JSON extraction uses balanced-brace matching with code fence stripping (see `_extract_json` in `cleaner.py`).
- Parakeet MLX and Ollama imports are guarded with try/except at module level (`PARAKEET_AVAILABLE` / `OLLAMA_AVAILABLE` flags).
- All modules use Python `logging` (configured by the CLI via `RichHandler`), not `print()`.
- Audio files are stored in `data/audio/`; database in `data/p3.duckdb`. Both directories are gitignored.
