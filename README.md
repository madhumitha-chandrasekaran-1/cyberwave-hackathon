# PhysioBot - AI Physiotherapy Robot Assistant

An AI-powered physiotherapy coaching system that uses a SO101 robot arm to demonstrate exercises, captures patient movements via camera, evaluates form using a Vision Language Model, and provides spoken feedback — all in a seamless rehabilitation loop.

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
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │ /api/session │  │  /api/voice  │  │       /health            │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────────────────────┘  │
│         │                 │                                         │
│  ┌──────▼───────────────────────────────────────────────────────┐  │
│  │                    App Modules                                │  │
│  │                                                              │  │
│  │  cyberwave.py   camera.py    vlm.py    voice.py   session.py │  │
│  └──────┬──────────────────────────────────────────────────────┘  │
└─────────┼───────────────────────────────────────────────────────────┘
          │
          ├──► Cyberwave API  ──► SO101 Robot Arm (demonstrates exercise)
          │
          ├──► OpenCV          ──► Webcam on rover (captures patient)
          │
          ├──► OpenAI GPT-4o  ──► VLM evaluation (scores movement)
          │
          └──► Smallest.ai    ──► STT (voice commands) + TTS (feedback)
```

---

## Demo Flow

```
Patient: "Start shoulder rehab"
    │
    ▼ STT (smallest.ai)
    │
    ▼ FastAPI parses command → creates RehabSession
    │
    ▼ Cyberwave API → triggers shoulder_rotation workflow
    │
    ▼ SO101 arm demonstrates shoulder rotation
    │
    ▼ Patient mirrors the exercise
    │
    ▼ Camera (OpenCV) records 10 seconds of footage
    │
    ▼ Frames sent to GPT-4o vision with evaluation criteria
    │
    ▼ VLM returns: { score: 8, corrections: ["Raise arm higher"] }
    │
    ▼ Reasoning maps corrections → spoken feedback
    │
    ▼ TTS (smallest.ai) speaks: "Good effort! Try raising your arm higher."
    │
    ▼ Session logged, patient can repeat or move to next exercise
```

---

## Prerequisites

- Python 3.11+
- A webcam (or USB camera on the rover)
- API keys for:
  - [Cyberwave](https://cyberwave.com) — robot arm control
  - [Smallest.ai](https://smallest.ai) — speech-to-text and text-to-speech
  - [OpenAI](https://platform.openai.com) — GPT-4o vision evaluation

---

## Installation

### 1. Clone / navigate to project

```bash
cd /Users/lawrancechen/Documents/cyberwave-hackathon
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
| `OPENAI_API_KEY` | OpenAI API key for GPT-4o vision |
| `CAMERA_INDEX` | OpenCV camera index (0 = default webcam) |

---

## Running the App

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Then open your browser at: **http://localhost:8000**

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
│   ├── config.py            # Pydantic settings
│   ├── cyberwave.py         # Robot arm client
│   ├── camera.py            # OpenCV frame capture
│   ├── vlm.py               # GPT-4o vision evaluation
│   ├── voice.py             # Smallest.ai STT + TTS
│   ├── session.py           # Session state management
│   └── routers/
│       ├── __init__.py
│       ├── session.py       # /api/session/* endpoints
│       └── voice.py         # /api/voice/* endpoints
└── static/
    ├── index.html           # Frontend UI
    └── app.js               # Frontend JS logic
```

---

## API Reference

### Session Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/session/start` | Start session, trigger arm demo |
| `POST` | `/api/session/{id}/record` | Record 10s of patient movement |
| `POST` | `/api/session/{id}/evaluate` | VLM evaluation of captured frames |
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
