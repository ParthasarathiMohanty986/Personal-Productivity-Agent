# Daylight — AI Personal Productivity Agent

A locally running, single-user Django application with task/goal management, a deterministic planner, an approval inbox, a Gemini-powered LangGraph agent, and analytics from SQLite records. The UI uses Django templates, CSS, and vanilla JavaScript. No deployment, separate frontend server, or paid API is needed for the core features.

## Windows PowerShell setup

Use Python **3.12** (the verified runtime). From this project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env as described below.
python manage.py migrate
python manage.py check
python manage.py test
python manage.py runserver 127.0.0.1:8000
```

Open **http://127.0.0.1:8000/**. Keep the terminal running. Stop with Ctrl+C. Do not bind this single-user application to `0.0.0.0` or expose it publicly.

If PowerShell blocks activation, activation is optional:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py test
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

An admin account is optional, not required for the dashboard:

```powershell
python manage.py createsuperuser
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py test
python manage.py runserver 127.0.0.1:8000
```

## Gemini configuration and offline mode

Edit `.env`:

```dotenv
GEMINI_API_KEY=your-own-key
GEMINI_MODEL=gemini-2.5-flash
DJANGO_SECRET_KEY=your-own-random-local-secret
DJANGO_DEBUG=False
TIME_ZONE=Asia/Kolkata
```

Obtain a key through [Google AI Studio](https://aistudio.google.com/apikey). Choose a Gemini model available to your account that supports tool calling and structured output. The model is configurable because availability and quotas can change. Availability, pricing, and any free-tier limits depend on Google's current terms; this application does not promise free API use.

Integration uses `langchain_google_genai.ChatGoogleGenerativeAI`, `with_structured_output(PydanticSchema)`, and `bind_tools`. See [LangChain's integration reference](https://reference.langchain.com/python/langchain-google-genai/chat_models/ChatGoogleGenerativeAI). Dependency versions in `requirements.txt` are the exact installed, jointly resolved set. Run `python -m pip check` to verify your environment.

Restart Django after editing environment variables. A blank key enables **no-key mode**: tasks, goals, planning, approvals, analytics, and reports all work. Chat/extraction returns a helpful HTTP 503. No real Gemini request is needed by tests. A configured key indicator means only that a key exists, not that connectivity or quota has been verified.

Conversation content and the bounded task/goal snapshot needed for your question are sent to Gemini when you use AI. There are no external database or calendar integrations. Conversation history stays in local SQLite; only the latest ten messages per session are supplied to the model. The browser keeps the session ID in session storage.

## Using the application

1. Add tasks with estimates, explicit deadlines, priorities, optional goals, and dependency IDs. Leave unknown values blank. Past deadlines are allowed so overdue work can be tracked; malformed dates are rejected. Completed/cancelled tasks can be reopened explicitly.
2. Open **Planner**, enter dates, available clock hours, and daily focus capacity. Empty task IDs means all active tasks. Busy periods are optional JSON using ISO timestamps with timezone offsets.
3. Generate a draft. Review scheduled work and every unscheduled reason. **Nothing is scheduled until approval**.
4. Approve or reject. Approval revalidates against current task data and commitments in one database transaction. Retrying the same approval is idempotent.
5. **Edit proposal** offers a JSON editor for task fields and schedule blocks. Saving creates a new draft requiring approval. **Recalculate** reruns deterministic planning. Approved schedules remain active until their replacement is approved. Already-applied task creation proposals cannot be reapproved through revision; edit the resulting tasks instead.
6. Use the assistant for extraction, goal decomposition, priorities, overdue work, feasibility, or summaries. Critical missing details result in clarification questions. Write tools always create approval drafts. A chat message cannot approve a draft.
7. Inspect **Insights** and **Activity**. Insights show computed facts; AI recommendations are requested separately. Dashboard cards are based on actual saved data, with no demo metrics.

Goal decomposition uses goal references and dependency references in structured output. Recurring requirements are extracted explicitly. Ask for a **finite date range** to create dated occurrences; this application does not run an infinite recurrence generator or background scheduler. Availability extracted from prose is shown for review; confirm structured availability in Planner before scheduling.

## Project structure

```text
config/       Django settings, root routing, CSRF authentication, ASGI/WSGI
tasks/        Task/Goal/ActivityLog models, migrations, serializers, CRUD services/APIs
planner/      Plan/ScheduleBlock models, schemas, deterministic scheduler, approval/revision
agent/        Gemini provider, Pydantic schemas, prompts, tools, LangGraph, conversations
analytics/    Computed metrics, endpoints, report management command
frontend/     Django template and vanilla CSS/JavaScript
tests/        Repeatable Django/API/agent integration tests with mocked model responses
manage.py
requirements.txt
.env.example
```

SQLite is stored in ignored `db.sqlite3`. All schema changes use checked-in Django migrations. `tasks.services` owns task/goal writes and audit attribution. `planner.services` owns schedule calculation and transactional approval. Views handle HTTP validation and serialization. No model receives arbitrary Python, SQL, or shell tools.

## Agent architecture

`agent/workflow.py` constructs a real LangGraph `StateGraph`:

```text
START → classify
           ├─ extract → validate structured extraction → persist draft / clarify → END
           └─ inspect tasks + goals → model reasoning
                                      ├─ selected validated tools → observations → reasoning
                                      ├─ tool limit → explanatory stop → END
                                      └─ final answer → END
```

At most four tool rounds / twelve selected tool calls, with a graph recursion limit of twenty. Each provider request has a 30-second timeout and at most one retry. A whole multi-step request can take longer than a single provider call. Provider failures and malformed output return sanitized errors. Tool errors are returned as observations, never as successful actions. Only actual completed tool calls appear in the UI; while waiting it displays a processing state.

Tools: `list_tasks`, `get_task_details`, `create_task`, `update_task`, `complete_task`, `get_overdue_tasks`, `list_goals`, `get_available_time`, `calculate_priority`, `generate_plan`, `get_productivity_summary`.

The graph produces persistent **Plan drafts**, and explicit approval resumes the business process through the approval API/service. This is a persisted human-review boundary, not an in-memory graph interrupt. Approval is not an LLM tool. All task mutation tools propose operations. Approval applies the operations through the same validated application services used by CRUD. The approving action is attributed to user/API; AI-proposed task operations are attributed to agent.

## Planner rules

- Local dates/hours use `TIME_ZONE`; storage uses timezone-aware Django timestamps.
- Importance points: low 10, medium 25, high 40, urgent 60.
- Overdue tasks receive 60 urgency points. Otherwise urgency is `max(0, 48 - hours_to_deadline)` plus up to 20 effort-pressure points, `min(20, estimated_minutes / max(hours_to_deadline*60,1)*20)`.
- Higher scores are considered first; task ID breaks ties. Dependencies must finish first regardless of score.
- Each task occupies one contiguous block of its estimated duration. The planner searches the earliest permitted slot before its explicit deadline, avoiding busy intervals and approved commitments. Existing approved durations count against daily focus capacity.
- Missing durations, blocked dependencies, insufficient capacity, and impossible deadlines are reported as unscheduled. Completed/cancelled tasks are excluded. Already committed tasks are identified and preserved.
- This is a greedy, conservative scheduler, **not an optimal solver or a guarantee**. It does not split long tasks across days. A different order may fit more work. Date ranges are capped at 31 days and task selections at 500 IDs.
- Approval verifies current duration, task status, deadlines, dependencies, future timestamps, permitted hours, daily capacity, and overlaps again. Changes since draft creation can require revision.

## REST API

All bodies are JSON. List endpoints are paginated (`count`, `next`, `previous`, `results`), 50 per page. Frontend follows pagination. Validation errors return 400, missing records 404, missing/failed AI 503, and CSRF failures 403. Create returns 201; delete 204.

| Endpoint | Methods / purpose |
|---|---|
| `/api/tasks/` | GET, POST; filters `search`, `status`, `priority`, `goal` |
| `/api/tasks/<id>/` | GET, PATCH, DELETE |
| `/api/tasks/<id>/complete/` | POST, optional `actual_minutes` |
| `/api/goals/` | GET, POST |
| `/api/goals/<id>/` | GET, PATCH, DELETE |
| `/api/agent/chat/` | POST `{message, session_id?}` |
| `/api/agent/parse-tasks/` | POST `{message, session_id?}`; structured extraction and draft |
| `/api/agent/plans/` | GET, POST with explicit planning constraints |
| `/api/agent/plans/<id>/` | GET |
| `/api/agent/plans/<id>/approve/` | POST `{}` |
| `/api/agent/plans/<id>/reject/` | POST `{}` |
| `/api/agent/plans/<id>/revise/` | POST constraint overrides, or `{proposal: {...}}` |
| `/api/analytics/summary/` | GET computed summary |
| `/api/analytics/trends/` | GET daily/weekly series |
| `/api/analytics/report/` | POST `{}` computed report, also used by UI download |
| `/api/activity/` | GET paginated history |

Example task body:

```json
{"title":"Finish DRF lesson","priority":"high","estimated_minutes":60,"deadline":"2026-10-15T20:00:00+05:30","dependencies":[]}
```

Example plan body (use actual future dates):

```json
{"title":"Evening focus","plan_type":"weekly","start_date":"2026-10-12","end_date":"2026-10-18","day_start":"19:00","day_end":"22:00","daily_minutes":120,"weekdays":[0,1,2,3,4],"busy":[],"task_ids":null}
```

**CSRF is enforced for anonymous writes too.** For scripts, first GET `/` to receive the `csrftoken` cookie, preserve that cookie, and send it as `X-CSRFToken` on mutations. The frontend does this automatically. `X-Productivity-UI: 1` attributes UI actions to `user`; other HTTP clients are labelled `api`. This is audit context in a local single-user app, not proof of identity.

## Analytics pipeline

```powershell
python manage.py generate_productivity_report
python manage.py generate_productivity_report --output reports/productivity.json
```

Runs read current ORM records, compute a fresh JSON report, and optionally overwrite the chosen file. Repeated runs create no duplicate summary records. Metrics include current task states, completion rate excluding cancelled tasks, overdue active tasks, priority distribution, daily/weekly completions, and matched estimated/actual duration samples. Missing actual durations produce `null`, not zero time spent. Postponed-task counts use recorded deadline extensions only. Deleted tasks are excluded from task metrics; activity records are retained. Reopening clears the current completion timestamp, so trends describe current completion records rather than immutable historical completion events.

## Reliability, security, and limits

- Intended for one person on loopback only; dashboard authentication and multi-user isolation are deliberately omitted. Django admin has its standard authentication.
- CSRF, host validation, template escaping, and Django's security middleware remain enabled. UI renders model/task content as text, not executable HTML. Secrets and local data are ignored by Git.
- `DEBUG=False` by default avoids tracebacks in responses. Local-only static serving is explicitly enabled so the dashboard works without deployment tooling.
- All approvals use database transactions and a conditional status update. SQLite serializes writes; this is not designed for high-concurrency use.
- No automatic calendar synchronization, reminders, or background jobs. Schedule revisions and report generation are manual.
- Editing task details after scheduling can invalidate a commitment; Insights reports changed durations, missed deadlines, overlaps, and incomplete work whose scheduled time has passed. Recalculate/revise the plan to reconcile it. Approval validates newly proposed blocks, not future changes to unrelated records.
- The proposal editor is a developer-oriented JSON editor, not drag-and-drop. Review edits before approval.
- Optional web fonts fall back to system fonts without connectivity.
- No live Gemini request was used for automated verification. Configure your own key to verify provider access. Model answers can still be imperfect; scheduling arithmetic and applied data are validated deterministically.

## Troubleshooting

- `No module named ...`: use the project virtual environment, then install requirements.
- `no such table`: run `python manage.py migrate` from this directory.
- Port busy: use `python manage.py runserver 127.0.0.1:8001`.
- CSRF 403: open/refresh the dashboard, use the same hostname consistently, and ensure cookies are enabled. Scripts need the cookie and header.
- AI unavailable: check `.env`, restart, confirm the configured model supports your account, and check quota/network access. Provider errors deliberately omit raw upstream details to avoid leaking credentials.
- Draft cannot be approved: inspect changed estimates/status/deadlines, busy times, and existing commitments; revise it.
- Nothing scheduled: provide task durations and actual available capacity; inspect the explicit unscheduled reasons.

## Verification commands

```powershell
python -m pip check
python manage.py makemigrations --check --dry-run
python manage.py migrate
python manage.py check
python manage.py test --verbosity 2
python manage.py generate_productivity_report
```

Tests use Django's isolated test database and mocked model outputs. They cover CRUD, validation, goal links, audit sources, CSRF, priority, scheduling, dependencies, busy periods/capacity, approval/rejection/revision/idempotency, stale task data, structured output, narrow tools, bounded graph execution, provider errors, known analytics fixtures, report repeatability, and frontend/static/API responses.

Verified during implementation: 34 tests passed; migrations applied to local SQLite; Django system checks passed; no pending model migrations; `pip check` reported no broken requirements; `node --check frontend/static/frontend/app.js` passed; the report command returned valid JSON; the local development server started and returned HTTP 200. Browser automation was blocked by the available browser tool's URL policy, so visual/click-through browser QA was not completed. Gemini calls were mocked; live provider access remains unverified without your API key.
