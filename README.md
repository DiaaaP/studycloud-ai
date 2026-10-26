# StudyCloud AI 2.0

StudyCloud is a local-first study assistant. It turns course files into source-backed summaries, flashcards, quizzes, grounded answers, and adaptive review sessions.

Its signature workflow combines **ProofLoop**, **BlindSpot Detector**, and **Feynman Defense**. Every wrong answer becomes a knowledge debt linked to the exact page, slide, paragraph, or section that explains the concept. When a learner is highly confident and still gets it wrong—or confidently omits a key concept while explaining a topic—the debt is promoted to a confidence trap and receives extra review priority.

## Features

- Upload PDF, PPTX, DOCX, TXT, and Markdown files up to 25 MB.
- Extract source locations by page, slide, paragraph, table, or section.
- Generate summaries, five key ideas, flashcards, and 5-7 quiz questions.
- Ask questions against one uploaded source and inspect supporting excerpts.
- Explain a topic in your own words with Feynman Defense and measure concept coverage.
- Optionally dictate an explanation with the browser's speech-recognition support.
- Record confidence for every quiz answer and detect high-confidence mistakes.
- Track quiz results, confidence traps, and knowledge health.
- Repair weak concepts through ProofLoop reviews.
- Search the local lecture library and edit generated summaries/key ideas before studying.
- Export a complete study pack as Markdown.
- Build a browser-local exam roadmap.
- Install the responsive interface as a local-first PWA with an offline app shell.
- Use Gemini when configured or stay offline with the local extractive engine.
- Run locally, in PyCharm, or with Docker.

## Quick start on Windows

Open the `StudyCloudAI` folder as a PyCharm project. In the PyCharm terminal run:

```powershell
.\run.ps1
```

Then open <http://127.0.0.1:8000>. The first run creates `.venv`, installs dependencies, and seeds a Raft demo lecture.

Manual setup:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Gemini setup (optional)

The local engine works without any account or key. For higher-quality generative summaries and answers:

```powershell
Copy-Item .env.example .env
```

Add your key to `.env`:

```text
GEMINI_API_KEY=your-key
GEMINI_MODEL=gemini-2.5-flash
```

`run.ps1` loads `.env` automatically.

## Docker

```powershell
docker compose up --build
```

The `data` directory is mounted into the container, so lectures and progress survive restarts.

## API

- `GET /api/health`
- `GET /api/stats`
- `GET /api/lectures`
- `GET /api/lectures/{id}`
- `POST /api/lectures`
- `PATCH /api/lectures/{id}`
- `POST /api/lectures/{id}/ask`
- `POST /api/lectures/{id}/defend`
- `POST /api/lectures/{id}/quiz`
- `GET /api/lectures/{id}/export`
- `GET /api/lectures/{id}/source`
- `GET /api/radar`
- `POST /api/radar/{gap_id}/review`
- `DELETE /api/lectures/{id}`

Interactive API documentation: <http://127.0.0.1:8000/docs>.

## Tests

```powershell
python -m pip install pytest
python -m pytest -q
```

The 10-test suite covers ingestion, study-pack generation and editing, grounded Q&A, confidence-aware quiz scoring, BlindSpot Detector, Feynman Defense, ProofLoop updates, PWA assets, exports, and invalid files.

## Current limits

- Scanned PDFs still need OCR.
- The app stores data locally and does not yet have user accounts.
- Browser roadmap data uses `localStorage`.
- Speech recognition depends on browser support; typed Feynman explanations always work.
- The offline shell opens without a network, but AI/API operations still require the local FastAPI server.
- “Unique” is a product direction, not a universal market claim. The differentiated workflow combines calibrated confidence, self-explanation, source evidence, and spaced recall in one loop.

See [ROADMAP.md](ROADMAP.md) for the production deployment sequence.
