# Cybercrime Triage — Frontend

A React (Vite + Tailwind CSS) console for the Cybercrime Triage AI backend. Log in,
submit a complaint narrative and/or an evidence screenshot, and view the structured
AI triage report.

## Prerequisites

- Node.js 18+ (tested on 22)
- The FastAPI backend running (see the project root `README`):
  ```bash
  uv run uvicorn app.main:app --reload   # http://localhost:8000
  ```
  Ollama must be running with `llama3.2` and `nomic-embed-text` pulled.

## Run

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

Log in with **any** username and password (demo mode — no real auth).

## Configuration

The backend URL defaults to `http://localhost:8000`. To change it, create a `.env`
file (see `.env.example`):

```
VITE_API_URL=http://localhost:8000
```

## How it connects

`src/api/client.js` posts a multipart form (`query` + `file`) to
`POST /api/v1/analyze` and renders the returned
`{ query, analysis, retrieved_context_count }`.
CORS for `http://localhost:5173` is enabled in `app/main.py`.
