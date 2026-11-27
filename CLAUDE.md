# Bifrost – working notes for Claude

Bifrost is a local Home Assistant app (stdlib-only Python, served via Ingress) that answers "is the house empty?" and, once proven, signals "house empty confirmed" to an alarm system. It **never disarms** anything.

## Working rules (from the maintainer)
- Answer in **German**. Changelog and release notes in English; README and app docs (bifrost/DOCS.md) in English **and** German.
- Ideas go to `NEXT.md` first; write code only after the maintainer says "mach es". Every new version is first written up in `NEXT.md` as its own section (scope, entities/UI, limits, open questions, tests) and discussed before any programming.
- Every update: security check (input validation, permissions, no secrets, bandit), tests for new logic, all tests green, then show a checklist (Security, Tests, Privacy, Best practices, Docs).
- **Privacy:** this repo is public. Never put real names, family data, addresses, area names of the maintainer's house or screenshots of real data into code, tests, docs or commits – use example data. Private context belongs in `CLAUDE.local.md` (git-ignored).
- Ask before every push or release. Bump `bifrost/config.yaml` and `bifrost_app/__init__.py`, add a `CHANGELOG.md` entry and copy it to `bifrost/CHANGELOG.md` (a test checks this).
- UI: Home Assistant look, light and dark, German or English (never mixed; every text via `t()` or the `i18n.py` table), states capitalised. Check every UI change in a browser: light, dark, 390 px phone width; no text overflow; every button works.
- Mockups and design proposals are delivered as HTML files.

## Commands
```bash
pytest -q                      # tests (demo household in tests/demo.py)
ruff check . && ruff format --check .
bandit -q -r bifrost/app -c pyproject.toml
PYTHONPATH=bifrost/app python3 tools/demo_server.py 8765   # demo UI with example data
python3 tools/gui_check.py http://127.0.0.1:8765/ /tmp/gui # overflow, buttons, JS errors, English left in German UI (BIFROST_CHROME=… for another browser)
python3 tools/backtest.py /path/to/bifrost.db              # hindsight vs past decisions on a local copy of real data
```

## Architecture (bifrost/app/bifrost_app)
- `service.py` – scan (registries incl. areas/floors), evaluate loop, live WebSocket stream, published entities, API views.
- `engine.py` – rule decision with reasons; `guard.py` – fixed safety rules (Heimdall); `brain.py` – pattern recognition (Muninn) + inbox.
- `hindsight.py` – labels the past (certainly empty / home / unclear); all learning uses it, never the live decision. `evidence.py` – learned weight per signal, probabilities, calibration. `baseline.py` – rarity per hour of week, path matrix. `house.py` – room grid per floor, avatars, incidents, pattern entities. `value.py` – verdict per signal (valuable / little / nothing / slow).
- `preprocess.py` (edges), `live.py` (origin person/app/automation/timer, numeric events, live board), `blocks.py` (neighbours, inside/outside, entrances, door roles, sensor doctor), `routines.py`, `calwords.py`, `timing.py`, `floorplan.py`, `balance.py` (release gate), `people.py` (people, visibility from source_type, access system, shared codes), `questions.py`, `optimize.py` (Setup suggestions), `i18n.py`.
- `web.py` – HTTP API; POSTs need header `X-Bifrost-Request: 1`, bodies are size-limited and validated.
- `static/index.html` – the whole UI (one file); tabs Status · People · House · Patterns · Incidents · Balance · Setup.
