# Classroom Essay Grading Agent

Watches Google Classroom for turned-in essays and grades them against a
Classroom-native rubric using a locally-run model.

**Read-only.** It never writes a grade or comment back to Classroom or
Drive, and never touches student files. It only reads coursework, rubrics,
submissions, and student names, then appends each recommendation (grade +
rubric breakdown + feedback) to a local CSV file for you to review and
enter yourself. The only Google scopes requested are:
`classroom.courses.readonly`, `classroom.coursework.students.readonly`,
`classroom.rosters.readonly`, `drive.readonly`.

**Calibratable.** Before grading a given assignment for real, you can hand-
grade a few submissions yourself through an interactive script. Those
become few-shot examples that steer the model toward your actual grading
standards for that specific assignment, rather than some generic notion of
"good writing."

## How it works

1. Polls Classroom every `POLL_INTERVAL_SECONDS` for `TURNED_IN`
   submissions on the courses you list, but **only for assignments that
   have a rubric attached in Classroom** (Classwork → assignment →
   Rubric) — anything without one is silently skipped.
2. Exports each student's Google Doc as plain text via Drive (read-only).
3. Sends the rubric + essay + any calibration examples you've saved for
   that assignment to your local model (via Ollama) and gets back a
   structured score-per-criterion + written feedback.
4. Appends one row per submission to `OUTPUT_PATH` (default
   `grading_recommendations.csv`): student name, recommended grade, a
   breakdown per rubric criterion, and the written feedback summary.
5. Tracks processed submissions in a local SQLite file so it won't
   re-grade a Doc unless the student has edited it since (detected via
   Drive's `headRevisionId`) — if they have, a fresh row is added on the
   next pass. Submissions you've used as calibration examples are skipped
   entirely, since you already graded those yourself.

## 1. Set up the local model

\`\`\`bash
# Install Ollama: https://ollama.com/download
ollama pull qwen3:8b
ollama serve   # usually starts automatically after install
\`\`\`

Realistic expectations on CPU-only hardware: an 8B model with
`MODEL_THINKING=true` can take 10+ minutes per essay. Defaults here are
tuned for CPU: `MODEL_THINKING=false` and `MODEL_TIMEOUT_SECONDS=1800`.
With thinking off, expect roughly a minute or so per essay depending on
your machine — still worth timing on your own hardware before you queue
up a full class set. If it's still too slow, `ollama pull qwen3:4b` and
set `MODEL_NAME=qwen3:4b` in `.env` — no code changes needed either way.

## 2. Set up Google API access

1. In [Google Cloud Console](https://console.cloud.google.com/), create a
   project (or use an existing one) and **enable both** the **Google
   Classroom API** and **Google Drive API** — each is a separate toggle,
   and a 403 `SERVICE_DISABLED` error means one of them got missed. Give
   it a minute or two to propagate after enabling.
2. Configure the OAuth consent screen (External is fine for personal use;
   add yourself as a test user).
3. Create an **OAuth client ID** of type **Desktop app**. Download the
   JSON and save it as `client_secret.json` in this folder.
4. Find the Classroom course IDs you want to watch. **Don't copy the
   number straight out of the browser URL** — Classroom's web UI uses a
   base64-encoded slug there (`classroom.google.com/c/<encoded-slug>`),
   not the raw numeric ID the API expects. Decode it first:
   \`\`\`bash
   echo "<encoded-slug-from-the-url>" | base64 -d
   \`\`\`
   That decoded number is what goes in `COURSE_IDS`.

## 3. Install and configure

\`\`\`bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: COURSE_IDS (decoded, see above), MODEL_NAME, OUTPUT_PATH, etc.
\`\`\`

## 4. Calibrate an assignment (optional but recommended)

Before letting the pipeline grade a given assignment for real, hand-grade
a few of its submissions so the model has real examples of your standards
to match:

\`\`\`bash
python calibrate.py
\`\`\`

This asks for a course ID and lists its assignments; pick one with a
rubric attached. It then walks through turned-in submissions one at a
time — for each one you choose to use, you enter your own per-criterion
scores and an overall feedback summary. 2–4 examples per assignment is
usually enough. These are saved to `calibration/<coursework_id>.json` and
automatically picked up by `pipeline.py` the next time it grades that
assignment — and those specific submissions are skipped by the main
pipeline, since you've already graded them yourself.

## 5. First run (interactive, for OAuth consent)

\`\`\`bash
python pipeline.py
\`\`\`

This opens a browser window for the one-time Google consent screen, then
caches the token to `token.json` (path set by `GOOGLE_TOKEN_PATH`) and
starts polling. Leave it running, or Ctrl+C once you've confirmed it
grades a test submission correctly, then move to always-on deployment
below. Ctrl+C is always safe — nothing is marked as processed until a
grading call actually succeeds, so an interrupted essay just gets
retried on the next run rather than lost or duplicated.

If you ever change `COURSE_IDS` or otherwise need Google to re-issue
tokens under different scopes, delete `token.json` first so it re-runs
the consent flow instead of reusing a stale grant.

## 6. Deploy as an always-on service (Linux/systemd)

\`\`\`bash
# Edit grading-agent.service: replace YOUR_USERNAME and the paths.
mkdir -p ~/.config/systemd/user
cp grading-agent.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now grading-agent
systemctl --user status grading-agent   # check it's running
journalctl --user -u grading-agent -f   # tail logs
\`\`\`

On macOS, use a `launchd` plist instead (same idea: run
`.venv/bin/python pipeline.py` with `KeepAlive=true`); happy to write that
version if that's your platform.

## Before you trust the recommendations

- Calibrate each assignment (step 4) before trusting its recommendations —
  an uncalibrated model is grading against a generic notion of "good
  writing," not your rubric's actual standards.
- Even after calibrating, spot-check a handful of recommendations against
  your own judgment, per rubric criterion rather than just the total —
  that's where you'll catch a criterion the model is still misreading.
- Every row in the report is a recommendation, not a posted grade —
  nothing reaches Classroom or the student until you enter it yourself.
