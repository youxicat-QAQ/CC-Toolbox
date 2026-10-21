# Contributing to CC-Toolbox

Thanks for your interest in contributing! 🧰

This project is a local dashboard for managing Claude Code tooling (Skills / MCP / CLI / Hooks / Plugins / Commands). Issues and PRs in both **English and Chinese** are welcome.

## Getting started

```bash
git clone https://github.com/youxicat-QAQ/CC-Toolbox.git
cd CC-Toolbox
python -m venv venv
# Windows: venv\Scripts\activate   macOS/Linux: source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python app.py
```

The panel auto-detects a free port (starting at 8765) and prints the actual URL to `server_addr.txt`.

## Before you submit a PR

1. **Run the test suite** — all tests must pass:

   ```bash
   python -m pytest tests/ -q
   ```

2. **Add tests for new behavior.** Tests must pass on a clean machine *without* a real `~/.claude/` directory — the suite is intentionally isolated (see `tests/conftest.py`). Follow the existing patterns for temp-dir fixtures.

3. **Keep the project portable.** No hardcoded machine-specific paths or fixed ports; scan paths belong in `config/paths_config.json`, port config in `CC_TOOLBOX_HOST` / `CC_TOOLBOX_PORT`.

## Code conventions

- Python 3.9+, standard library + Flask only (no new runtime dependencies without discussion)
- Comments and UI text are in **Simpified Chinese**; code identifiers stay in English
- Scanner modules follow the same pattern: `scan_all()` for real scanning, `get_*(force_refresh=False)` as the cached entry point (120s TTL)
- Route order matters in `app.py`: specific routes (e.g. `/api/mcp/<name>/test`) must come before the generic `/api/<tool_type>/<path:name>` — see the comments there

## Reporting bugs

Open an issue with:

- OS and Python version
- What you expected vs. what happened
- Relevant log output (`server.log` / terminal / `server_addr.txt`)

## Feature ideas

Check the [Roadmap](README.en.md#-roadmap) in the README first. If your idea isn't listed, open an issue to discuss it before investing in a large PR.
