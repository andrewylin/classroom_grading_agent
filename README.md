# Classroom Essay Grading Agent

Watches Google Classroom for turned-in essays, grades them against a
Classroom-native rubric using a locally-run model, posts a draft grade +
feedback comment on the student's Doc, and (optionally) returns the grade
automatically.

## How it works

1. Polls Classroom every `POLL_INTERVAL_SECONDS` for `TURNED_IN` submissions
   on the courses you list, but **only for assignments that have a rubric
   attached in Classroom** (Classwork → assignment → Rubric).
2. Exports the student's Google Doc as plain text via Drive.
3. Sends the rubric + essay to your local model (via Ollama) and gets back a
   structured score-per-criterion + written feedback.
4. Sets `draftGrade` in Classroom and posts the feedback as a Drive comment
   on the Doc.
5. If `AUTO_RETURN=true`, also sets `assignedGrade` and returns the
   submission immediately. If `false` (default), it stops at the draft —
   you skim and click "Return" yourself in Classroom.
6. Tracks graded submissions in a local SQLite file so it won't re-grade a
   Doc unless the student has edited it since (detected via Drive's
   `headRevisionId`).

## 1. Set up the local model

```bash
# Install Ollama: https://ollama.com/download
ollama pull qwen3:8b
ollama serve   # usually starts automatically after install
```

If 8B is too slow on your machine, swap to `ollama pull qwen3:4b` and set
`MODEL_NAME=qwen3:4b` in `.env` — no other code changes needed.

## 2. Set up Google API access

1. In [Google Cloud Console](https://console.cloud.google.com/), create a
   project (or use an existing one) and enable the **Google Classroom API**
   and **Google Drive API**.
2. Configure the OAuth consent screen (External is fine for personal use;
   add yourself as a test user).
3. Create an **OAuth client ID** of type **Desktop app**. Download the JSON
   and save it as `client_secret.json` in this folder.
4. Find the Classroom course IDs you want to watch — open the course in
   Classroom, the ID is the number in the URL
   (`classroom.google.com/c/COURSE_ID`).

## 3. Install and configure

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: COURSE_IDS, MODEL_NAME, AUTO_RETURN, etc.
```

## 4. First run (interactive, for OAuth consent)

```bash
python pipeline.py
```

This opens a browser window for the one-time Google consent screen, then
caches the token to `token.json` (path set by `GOOGLE_TOKEN_PATH`) and
starts polling. Leave it running, or Ctrl+C once you've confirmed it grades
a test submission correctly, then move to always-on deployment below.

## 5. Deploy as an always-on service (Linux/systemd)

```bash
# Edit grading-agent.service: replace YOUR_USERNAME and the paths.
mkdir -p ~/.config/systemd/user
cp grading-agent.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now grading-agent
systemctl --user status grading-agent   # check it's running
journalctl --user -u grading-agent -f   # tail logs
```

On macOS, use a `launchd` plist instead (same idea: run
`.venv/bin/python pipeline.py` with `KeepAlive=true`); happy to write that
version if that's your platform.

## Before you trust it with real grades

- Test on a handful of already-graded essays first and compare the AI's
  scores to your own, per rubric criterion, not just the total — that's
  where you'll catch a criterion the model is misreading.
- Start with `AUTO_RETURN=false`. Once you've watched it grade a full class
  set with no meaningful misses, decide if you want to flip it on.
- Only assignments with a Classroom rubric get auto-graded — anything
  without one is silently skipped, so you always know what the pipeline
  will and won't touch.
