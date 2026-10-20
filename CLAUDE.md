# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Flask web app for a research study on how feedback affects creativity. Participants do 10 timed tasks of 5 minutes each (5 verbal Alternative Uses items + 5 figural drawing tasks, at least 3 answers or drawings per task) between a pre-survey and post-survey hosted on Qualtrics (external; links in `templates/landing.html` and `templates/task.html`, keep them in sync). The first letter of the participant ID sets the group:

| ID | Group (CSV name) | Feedback shown |
|---|---|---|
| A | control | none |
| B | evaluative | originality score: OpenScoring API for text (`/score`), local OCSAI-D model in `ocsai-d-large/` for drawings (`/score-drawing`) |
| C / D / E | informative / positive / negative | LLM feedback via `/feedback`, prompt from `prompts/<name>.txt` |

This group mapping is repeated in `creativity/config.py` (`TABLE_MAP`, `PROMPT_MAP`), `templates/task.html` and `templates/dashboard.html` (`GROUP_LABEL`). Change all of them together.

## Commands

```bash
.venv/bin/python -m pytest tests -q                 # offline tests (temp data folder, no network)
.venv/bin/python -m pytest tests -q -k delete       # run one test by name
PORT=5556 .venv/bin/python app.py                   # local dev server; FLASK_DEBUG=1 enables debug mode
sudo systemctl restart creativity-feedback          # the live site: restart after changing code, templates or .env
sudo journalctl -u creativity-feedback -f           # live logs
.venv/bin/python scripts/run_ocsai.py --image Figural/f1.png   # score one image with the local OCSAI-D model
```

The live site is the systemd service `creativity-feedback` (gunicorn `wsgi:app` on port 5555, one worker with threads), with a watchdog timer that restarts it if `/healthz` stops answering. Unit files and notes are in `deploy/`. It holds port 5555, so use another `PORT` for a dev server.

Config comes from `.env` (see `.env.example`): `OPENAI_API_KEY`, `DASHBOARD_USERNAME` (default `admin`), `DASHBOARD_PASSWORD`, `DASHBOARD_USERS` (extra researcher logins, `name:password` comma separated), and optionally `OPENAI_MODEL`, `OPENAI_REASONING_EFFORT`, `OPENSCORING_API_KEY`, `DATA_DIR`.

**The running service writes to `data/`, which holds real study data.** For experiments, set the `DATA_DIR` environment variable, or patch `creativity.config.DATA_DIR` (it is read at call time; the tests do this).

## Architecture

**Backend (`creativity/` package).** `create_app()` in `__init__.py` registers two blueprints. `wsgi.py` is the production entry point and `app.py` the dev one.
- `config.py`: env settings and constants (groups, CSV columns, word lists).
- `storage.py`: everything under `DATA_DIR` (CSV rows, drawings, issued IDs, delete safeguards).
- `llm.py`: OpenAI calls, the nonsense check and the violence filter.
- `scoring.py`: OpenScoring and the local OCSAI-D model.
- `auth.py`: `researcher_only`. `dashboard.py`: `build_participant`.
- `routes/participant.py`: public pages and endpoints. `routes/researcher.py`: dashboard, exports, admin.

It calls OpenAI Chat Completions with raw `requests` (not an SDK). For drawings, the same group prompt gets a figural-task note and the drawing image. Group C also gets the blank figure (`SEND_FIGURE_PREFIXES`). OpenScoring must receive form-encoded data (`data=`); query params return 400.

**Answer and feedback checks.** `/score` runs `is_meaningful_answer` and the OpenScoring call in parallel; `/feedback` runs the check first (quick gibberish rules, then a model check; it fails open). A nonsense answer gets `{nonsense, message, flag}` instead of a score or feedback, does not count toward the minimum, and is logged with `NONSENSE_FLAG` in the feedback column. Group A gets no feedback, so it only has the quick rules, mirrored in `looksLikeGibberish` in `task.html`; keep the two in sync. LLM feedback passes through `feedback_is_safe` (word list plus OpenAI moderation); unsafe output is regenerated once, then replaced by `SAFE_FALLBACK_FEEDBACK`.

**Storage.** `/store` validates each row (ID format, `ROW_TYPES`, mood values 1–5) and appends it to two files under `CSV_LOCK`:
- `data/<group>.csv`
- `data/participants/<ID>/responses.csv`

Drawing rows carry a PNG. It is saved to `data/participants/<ID>/drawings/`, and the `answer` column holds its path relative to `data/`. Other things to know:
- Every row is an event (answer, drawing, `drawing_unsubmitted`, `mood_pleasant`/`mood_alert`), not one row per participant.
- If a CSV's header differs from `CSV_HEADERS`, `_migrate_legacy_csv` renames the file to `.bak`. Changing the columns moves existing data aside.
- `_ensure_participant_files` fills in `participants/` from the group CSVs once, the first time anything is saved.
- `CSV_LOCK` is a thread lock, so it only protects a single process.

**Researcher pages.** These pages sit behind `researcher_only` (HTTP Basic auth against any login in `RESEARCHER_LOGINS`; locked if no password is set): `/admin`, `/api/admin/*`, `/dashboard`, `/api/dashboard-data`, `/export/<group>.csv`, `/export/participant/<ID>.zip`, `/export/all.zip`, `/participants/<path>`, `/db-test`.

**Logins and data deletion (`/admin`).** Researchers issue participant IDs like `C007`, each with a 6-character password, into `data/participant_ids.csv` (stored as a hash; shown once, resettable). Once any ID has been issued, only issued IDs can log in (`POST /api/login`, which returns an HMAC token the page sends with every `/store` row; the key comes from `SECRET_KEY` or `data/.secret_key`). IDs issued before passwords existed have an empty hash and need no password or token. Researcher logins come from `.env` and from accounts added on `/admin` (`data/researchers.json`, hashed). `/api/admin/delete-data` removes all responses but keeps the ID list. It is only allowed within 30 minutes of an `/export/all.zip` download that is newer than every saved file.

`build_participant` groups rows into blocks: a `task` block per question and a `checkin` block per pair of mood ratings. Check-ins happen before the first task, after the first half and after all tasks; their question is `"Baseline (before starting)"` or `"Check-in after verbal/figural tasks"`. Older data had a rating after every task, logged under that task's question.

**Participant page (`templates/task.html`).** A vanilla-JS single page. Key pieces:
- **Screens:** `showScreen()` switches instructions → task → mood check-in → done, updates the progress bar and focuses the new screen's heading.
- **Resume state:** kept in `localStorage` (`aut_exp_state_v2_api`), keyed to the participant ID. A finished participant logging in again goes straight to the done screen.
- **Task order:** an even ID number means figural tasks come first; odd means verbal first.
- **Timer:** `TASK_SECONDS` (5 minutes) per task. It only counts down on the task screen. When time runs out, the page moves on exactly as "Next Task" does, even with fewer than `MIN_ANSWERS`.
- **Minimum answers:** "Next Task" unlocks at `MIN_ANSWERS` (3) counted answers, or 3 submitted drawings. A submitted drawing is locked; "New Drawing" starts another on the same figure.
- **Question text:** each question has `instruction` (display text) and `text` (stored in the CSV and sent to the LLM). Keep `text` unchanged so the data stays consistent.
- **Failures:** failed scoring or feedback never blocks progress. `[error: feedback unavailable]` goes into the feedback column. `sendEntry` retries failed saves.
- **Accessibility:** icons are decorative (`aria-hidden`), dynamic messages go through `announce()` (a live region), and the check-in scales are native radio groups. The drawing tasks are accepted as not accessible to blind participants.
- **State styling:** feedback boxes use the classes `is-muted` and `is-error`, never inline colors, so dark mode keeps working.

**Look and feel (`static/`).** The participant pages share `static/css/site.css`. Colors are CSS custom properties, with dark mode via `prefers-color-scheme`. The accent is UNT green (darkened slightly for contrast). Buttons are `.btn` / `.btn-primary`, inputs are `.field`, containers are `.panel`.
- **Fonts:** Atkinson Hyperlegible Next, self-hosted in `static/fonts/` (OFL).
- **Icons:** `static/icons.svg` is a sprite built from `@phosphor-icons/core` (regular weight). Use it as `<svg class="icon" aria-hidden="true"><use href="/static/icons.svg#name"/></svg>`. Add icons by extracting them from that package, not by drawing paths.
- **Drawing canvas:** stays white in both themes.
- **Dashboard:** `templates/dashboard.html` has its own separate styles.

## Other files

- `README.md` is in Chinese and documents the data layout, dashboard and admin page.
- `scripts/`: standalone helpers (OCSAI scoring, an OpenScoring example, a simulation plot). Not used by the app.
- `legacy/`: the old unused `main.html` page and plot.
- `docs/data_collection_sample.xlsx`: column guide and sample rows for the research team. Group B sees scores as "Originality: x.x out of 5" (drawing scores, 0-1, are mapped to 1-5 for display only; the CSV keeps raw scores).
