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

# CLI entry point
p3 --help                   # All commands
p3 init                     # Initialize dirs and DuckDB database
p3 fetch                    # Download episodes from RSS feeds
p3 transcribe               # Transcribe audio (Parakeet MLX preferred, Whisper fallback)
p3 digest                   # Generate structured summaries via LLM
p3 export                   # Export markdown/JSON digests
p3 write --topic "Topic"    # Generate blog post with AP English grading loop

# Formatting
black .
isort .

# Type checking
mypy p3/
```

No tests exist yet. The `dev` optional dependencies include pytest but no test files have been created.

## Architecture

The CLI (`p3/cli.py`) is a Click group command. Each subcommand instantiates the relevant processing class and passes the shared `P3Database` instance via Click context.

**Pipeline flow through modules:**

1. **`downloader.py`** - `PodcastDownloader`: Parses RSS via `feedparser`, downloads audio via `requests`, normalizes with `ffmpeg` subprocess (16kHz mono WAV). Falls back to raw ffmpeg if primary normalization fails.

2. **`transcriber.py`** - `AudioTranscriber`: Lazy-loads models. Tries Parakeet MLX first (`parakeet_mlx.from_pretrained`), falls back to OpenAI Whisper. Both produce a common segment format `{start, end, text, speaker, confidence}`.

3. **`cleaner.py`** - `TranscriptCleaner`: Cleans transcripts (regex filler removal + LLM polish), then extracts structured JSON (topics, themes, quotes, companies, summary). Supports three LLM backends: OpenAI (httpx), Anthropic (placeholder), Ollama (ollama SDK). Has `_basic_extraction` fallback using word frequency when no LLM is available.

4. **`exporter.py`** - `DigestExporter`: Pure formatting. Generates Markdown, JSON, and HTML email from summary dicts. Groups episodes by podcast.

5. **`writer.py`** - `BlogWriter`: Generates blog posts with an iterative grading loop (up to 3 iterations targeting 91/100 score). Also generates Twitter/LinkedIn social posts. Saves blog posts as Markdown with YAML frontmatter to `blog_posts/`.

6. **`database.py`** - `P3Database`: DuckDB storage layer. Schema: `podcasts` -> `episodes` -> `transcripts` + `summaries`. Uses sequences for auto-increment IDs. Episode status tracks pipeline progress: `downloaded` -> `transcribed` -> `processed`.

## Configuration

`config/feeds.yaml` controls feeds and all settings. Key settings:
- `parakeet_enabled`: toggles Parakeet vs Whisper
- `llm_provider`: `ollama`, `openai`, or `anthropic`
- `llm_model`: model name for the chosen provider
- `max_episodes_per_feed`: limits downloads per feed

## Key Design Decisions

- All database query results are manually mapped to dicts (no ORM). Column positions are hardcoded in result mapping methods.
- LLM responses for structured data are parsed by finding the first `{` and last `}` in the response text.
- Parakeet MLX import is guarded with try/except at module level (`PARAKEET_AVAILABLE` / `OLLAMA_AVAILABLE` flags).
- The Anthropic LLM backend in `cleaner.py` is a placeholder (returns input unchanged or None).
- Audio files are stored in `data/audio/`; database in `data/p3.duckdb`. Both directories are gitignored.
