# GoalForge AI

GoalForge AI is an adaptive, multi-agent platform for turning ambitious long-term fitness goals into practical, measurable training progress.

Give GoalForge a goal such as “perform an aerial hoop routine in nine months” or “bench press 300 lb.” It assesses the starting point, maps the competencies required, creates a training plan, tracks goal-specific readiness, and adapts recommendations as progress arrives.

Built for the [AI Tinkerers Global Hackathon: Agents Everywhere — Bots, Channels & More](https://columbus.aitinkerers.org/p/agents-everywhere-bots-channels-more-global-hackathon).

> **Beyond fitness:** Fitness and weight training are the current demonstration domain, not the product boundary. GoalForge’s agent workflow and provider abstraction can be extended to goals of many kinds—learning, creative practice, career development, financial habits, and more—by connecting the relevant application APIs and translating their evidence into goal-specific competencies and milestones.

## Highlights

- Create, save, and switch between multiple active goals.
- Generate a personalized roadmap, milestones, and complete 60-minute workout sessions.
- Track progressive, goal-specific readiness—for example, bench targets for a 300-lb bench goal rather than a generic aerial checklist.
- Complete readiness steps manually, undo the latest step, or allow matched Hevy data to verify them.
- Sync post-goal Hevy workouts, update competency evidence, and export routines back to Hevy.
- Get AI coaching with a progress review, targeted adjustments, next steps, and encouragement.
- Inspect the structured output from each agent in the Agent Activity view.

## Real multi-agent architecture

GoalForge does not imitate agents with one large prompt. Each agent has a dedicated system prompt, callable function, retained state, and Pydantic-validated JSON output. LangGraph passes state between the agent nodes.

### Initial goal workflow

```text
Assessment Agent
  → Skill Mapping Agent
  → Gap Analysis Agent
  → Planning Agent
  → Workout Programming Agent
  → Goal Readiness Agent
  → Achievement Agent
  → Dashboard
```

### Adaptive progress workflow

```text
Hevy sync or readiness update
  → Achievement Agent
  → Coaching Agent
  → Planning Agent
  → Workout Programming Agent
  → Goal Readiness Agent
  → Achievement Agent
  → Dashboard refresh
```

| Agent | Responsibility |
| --- | --- |
| Assessment Agent | Establishes starting level, constraints, time availability, and baseline metrics. |
| Skill Mapping Agent | Maps the outcome to the competencies needed to achieve it. |
| Gap Analysis Agent | Identifies skill gaps, risks, and priorities. |
| Planning Agent | Produces a phased roadmap and milestones. |
| Workout Programming Agent | Produces a structured 1–4 week, 60-minute workout block. |
| Goal Readiness Agent | Creates progressive readiness tracks and unlocks. |
| Achievement Agent | Calculates readiness-driven overall progress and milestones. |
| Coaching Agent | Creates a useful progress review, adjustments, and next steps. |

## Tech stack

- **Frontend:** Next.js 15, React 19, TypeScript, Tailwind CSS
- **Backend:** Python, FastAPI, SQLAlchemy
- **AI:** OpenAI structured outputs with Pydantic schemas
- **Orchestration:** LangGraph
- **Storage:** SQLite by default; ready for PostgreSQL via `DATABASE_URL`
- **Fitness integrations:** provider abstraction with Mock and Hevy implementations

## Run locally

### Prerequisites

- Git
- Python 3.11 or newer
- Node.js 20 or newer and npm

### Clone the project

```bash
git clone https://github.com/vacobb/GoalForge-AI.git
cd GoalForge-AI
```

### Configure the backend

```bash
cp backend/.env.example backend/.env
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

Edit `backend/.env`:

```env
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
HEVY_API_KEY=
HEVY_SYNC_INTERVAL_MINUTES=180
```

`OPENAI_API_KEY` enables model-generated structured outputs. Without it, GoalForge uses deterministic local fallbacks that preserve the same agent boundaries and JSON contracts—useful for development and demos.

`HEVY_API_KEY` is optional. Add a personal Hevy Pro API key only if you want workout syncing and routine export. Never commit `backend/.env` or expose any API key in the frontend.

### Start the API

```bash
cd backend
source ../.venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

The API runs at `http://127.0.0.1:8000`.

### Start the web app

In a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The frontend defaults to `http://localhost:8000`; use `NEXT_PUBLIC_API_URL` to point it elsewhere.

> On Windows, activate the virtual environment with `.venv\Scripts\activate` from the project root before starting the API.

### Fresh-clone behavior

The repository intentionally excludes local SQLite databases, API keys, and Hevy history. A fresh clone starts with an empty dashboard; create a goal in the app to begin. Add your own OpenAI and Hevy credentials only if you want those optional integrations.

## Hevy integration

GoalForge is not tightly coupled to Hevy. Its `FitnessDataProvider` abstraction currently includes `MockFitnessProvider` and `HevyFitnessProvider`, with room for Garmin, Strava, and other sources.

After setting `HEVY_API_KEY` in `backend/.env`, use **Sync Hevy** for an on-demand import. The backend also checks for new activity every 180 minutes by default.

- Only workouts that occurred after a goal was created count toward that goal.
- A per-goal checkpoint avoids duplicate imports.
- Exercise data updates a competency or readiness step only when it directly matches that criterion.
- Workout export is always explicit: **Export plan to Hevy** creates or updates linked Hevy routines. Automatic sync never overwrites routines.

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/goal` | Create a goal. |
| `POST` | `/goal/analyze` | Run the initial LangGraph workflow. |
| `GET` | `/goals` | List saved goals. |
| `GET` | `/goal/{id}` | Retrieve dashboard state. |
| `GET` | `/goal/{id}/roadmap` | Retrieve roadmap and milestones. |
| `POST` | `/goal/{id}/sync/hevy` | Import recent Hevy evidence and adapt the plan. |
| `POST` | `/goal/{id}/readiness/{criterion_id}/manual` | Complete or undo the latest allowed readiness step. |
| `POST` | `/goal/{id}/program/generate` | Generate a fresh workout program. |
| `POST` | `/goal/{id}/program/export/hevy` | Export or update the current program in Hevy. |

## Project layout

```text
backend/
  app/
    agents.py         # Agent prompts, schemas, functions, and LangGraph graphs
    main.py           # FastAPI routes and workflow persistence
    models.py         # SQLAlchemy models
    providers.py      # FitnessDataProvider, Mock, and Hevy adapters
    hevy_sync.py      # Goal-scoped Hevy synchronization
    competencies.py   # Hevy-verifiable competency evidence
frontend/
  app/
    page.tsx          # Dashboard and goal creation UI
    activity/page.tsx # Agent Activity view
    globals.css       # Dashboard styles
```

## Extending GoalForge

- Move from SQLite to PostgreSQL through `DATABASE_URL`.
- Implement Garmin, Strava, manual, or non-fitness application providers through the provider abstraction.
- Add specialist agents and LangGraph nodes without collapsing the existing agent boundaries.
- Add authentication and scope `/goals` queries per authenticated user for production.

## Disclaimer

GoalForge provides general fitness-planning support, not medical advice. Stop activity and seek professional guidance for pain, injury, or medical concerns.

---

## Author

**Vaughn Cobb**

Software Development Student @ CSCC \
AWS Certified Cloud & AI Practitioner \
Aspiring Full-Stack Developer
