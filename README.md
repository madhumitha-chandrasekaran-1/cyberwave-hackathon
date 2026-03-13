# PhysioBot - AI Physiotherapy Robot Assistant

An AI-powered physiotherapy coaching system that uses a SO101 robot arm to demonstrate exercises, captures patient movements via camera, evaluates form using Claude vision, and provides spoken feedback — orchestrated end-to-end by a **Toolhouse agent**.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Patient Interface                            │
│                   Browser (index.html + app.js)                     │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ HTTP / REST
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     FastAPI Backend (main.py)                       │
│                                                                     │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────┐  │
│  │ /api/agent  │  │ /api/session │  │  /api/voice  │  │ /health │  │
│  └──────┬──────┘  └──────┬───────┘  └──────┬───────┘  └─────────┘  │
│         │                │                 │                        │
│  ┌──────▼──────────────────────────────────────────────────────┐   │
│  │              App Modules                                     │   │
│  │  agent.py  cyberwave.py  camera.py  vlm.py  voice.py  ...   │   │
│  └──────┬───────────────────────────────────────────────────────┘   │
└─────────┼───────────────────────────────────────────────────────────┘
          │
          ├──► Toolhouse       ──► Agent orchestration (Claude claude-sonnet-4-6 brain)
          │         │
          │         ├──► demonstrate_exercise  ──► Cyberwave API ──► SO101 arm
          │         ├──► capture_patient_attempt ──► OpenCV ──► rover camera
          │         ├──► evaluate_exercise_form ──► Claude vision (Anthropic)
          │         └──► speak_feedback         ──► Smallest.ai TTS
          │
          └──► Smallest.ai STT ──► voice commands from patient
```

---

## Demo Flow

```
Patient: "Start shoulder rehab"
    │
    ▼ STT (smallest.ai)
    │
    ▼ POST /api/agent/run → creates RehabSession
    │
    ▼ Toolhouse agent (Claude claude-sonnet-4-6) starts agentic loop:
    │
    ▼ [Tool call] demonstrate_exercise("shoulder_rotation")
    │   └──► Cyberwave API → SO101 arm performs the motion
    │
    ▼ [Tool call] capture_patient_attempt(session_id, duration=10)
    │   └──► OpenCV records 10s of patient mirroring the exercise
    │
    ▼ [Tool call] evaluate_exercise_form(session_id, "shoulder_rotation")
    │   └──► Frames → Claude claude-sonnet-4-6 vision → { score: 8, corrections: [...] }
    │
    ▼ [Tool call] speak_feedback("Good effort! Raise your arm 20° higher.")
    │   └──► Smallest.ai TTS → audio played to patient
    │
    ▼ Agent returns final evaluation JSON
    │
    ▼ Poll GET /api/agent/{session_id}/result → { score, feedback, corrections }
```

---

## Prerequisites

- Python 3.11+
- A webcam (or USB camera on the rover)
- API keys for:
  - [Cyberwave](https://cyberwave.com) — robot arm control
  - [Smallest.ai](https://smallest.ai) — speech-to-text and text-to-speech
  - [Anthropic](https://console.anthropic.com) — Claude claude-sonnet-4-6 vision evaluation
  - [Toolhouse](https://app.toolhouse.ai) — agent orchestration and tool execution

---

## Installation

### 1. Navigate to project

```bash
cd cyberwave-hackathon
```

### 2. Create and activate a virtual environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate   # macOS / Linux
# .venv\Scripts\activate    # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Set up environment variables

```bash
cp .env.example .env
# Edit .env and fill in your API keys
```

---

## Environment Variables

| Variable | Description |
|---|---|
| `CYBERWAVE_API_KEY` | Bearer token for Cyberwave robot API |
| `CYBERWAVE_BASE_URL` | Cyberwave API base URL (default provided) |
| `SMALLEST_API_KEY` | API key for smallest.ai STT/TTS |
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude claude-sonnet-4-6 vision |
| `TOOLHOUSE_API_KEY` | Toolhouse API key for agent orchestration |
| `CAMERA_INDEX` | OpenCV camera index (0 = default webcam) |

---

## Running the App

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Then open your browser at: **http://localhost:8000**

The interactive API docs are at: **http://localhost:8000/docs**

---

## Supported Exercises

| Exercise Key | Description |
|---|---|
| `shoulder_rotation` | Full shoulder rotation for rotator cuff rehab |
| `elbow_flex` | Elbow flexion/extension for bicep recovery |
| `wrist_rotation` | Wrist pronation/supination for wrist rehab |

---

## Project Structure

```
cyberwave-hackathon/
├── main.py                  # FastAPI entry point
├── requirements.txt
├── .env.example
├── README.md
├── app/
│   ├── __init__.py
│   ├── config.py            # Pydantic settings (all env vars)
│   ├── agent.py             # Toolhouse agent + local tool registration
│   ├── cyberwave.py         # SO101 robot arm client (Cyberwave API)
│   ├── camera.py            # OpenCV frame capture
│   ├── vlm.py               # Claude claude-sonnet-4-6 vision evaluation (Anthropic)
│   ├── voice.py             # Smallest.ai STT + TTS
│   ├── session.py           # In-memory session state
│   └── routers/
│       ├── __init__.py
│       ├── agent.py         # /api/agent/* — autonomous Toolhouse agent endpoint
│       ├── session.py       # /api/session/* — manual step-by-step endpoints
│       └── voice.py         # /api/voice/* — STT / TTS / command parsing
└── static/
    ├── index.html           # Frontend UI (dark theme)
    └── app.js               # Vanilla JS session flow + mic recording
```

---

## API Reference

### Agent Endpoints (Toolhouse-powered autonomous mode)

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/agent/run` | Start a fully autonomous rehab session |
| `GET` | `/api/agent/{id}/result` | Poll session phase and get evaluation result |

### Session Endpoints (manual step-by-step mode)

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/session/start` | Create session, trigger arm demo |
| `POST` | `/api/session/{id}/record` | Record 10s of patient movement |
| `POST` | `/api/session/{id}/evaluate` | Claude vision evaluation of frames |
| `POST` | `/api/session/{id}/speak` | TTS of evaluation feedback |
| `GET` | `/api/session/{id}/status` | Get current session phase |

### Voice Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/voice/stt` | Upload audio → transcribed text |
| `POST` | `/api/voice/tts` | `{text}` → audio stream |
| `POST` | `/api/voice/command` | Audio → parsed command action |

### Health

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Service health check |

---

## Toolhouse Integration Details

The Toolhouse SDK (`toolhouse` Python package) is used with `Provider.ANTHROPIC` so Claude claude-sonnet-4-6 acts as the reasoning brain. Four local tools are registered:

| Tool | What it does |
|---|---|
| `demonstrate_exercise` | Calls Cyberwave API to move the SO101 arm |
| `capture_patient_attempt` | Runs OpenCV to record the patient |
| `evaluate_exercise_form` | Sends frames to Claude claude-sonnet-4-6 vision, returns scored JSON |
| `speak_feedback` | Calls Smallest.ai TTS and caches audio |

Toolhouse handles the agentic loop: it calls tools, feeds results back to Claude, and repeats until Claude produces a final response with no further tool calls.

---

## Cyberwave Setup

On hack day, update `EXERCISE_WORKFLOWS` in `app/cyberwave.py` with real workflow IDs from your Cyberwave dashboard:

```python
EXERCISE_WORKFLOWS = {
    "shoulder_rotation": "your-real-workflow-id-here",
    "elbow_flex":        "your-real-workflow-id-here",
    "wrist_rotation":    "your-real-workflow-id-here",
}
```
