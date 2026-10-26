from __future__ import annotations

import io
import json
import os
import re
import sqlite3
import uuid
import zipfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from docx import Document
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pptx import Presentation
from pydantic import BaseModel, Field
from pypdf import PdfReader


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
MAX_FILE_SIZE = 25 * 1024 * 1024
SUPPORTED_EXTENSIONS = {".pdf", ".pptx", ".docx", ".txt", ".md"}


def data_dir() -> Path:
    path = Path(os.getenv("STUDYCLOUD_DATA_DIR", BASE_DIR / "data")).resolve()
    path.mkdir(parents=True, exist_ok=True)
    (path / "uploads").mkdir(parents=True, exist_ok=True)
    return path


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(data_dir() / "studycloud.db")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def ensure_column(db: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
    columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def init_database() -> None:
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS lectures (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                filename TEXT NOT NULL,
                pages INTEGER NOT NULL DEFAULT 0,
                word_count INTEGER NOT NULL DEFAULT 0,
                text_content TEXT NOT NULL,
                summary TEXT NOT NULL,
                key_ideas TEXT NOT NULL,
                quiz TEXT NOT NULL,
                engine TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS quiz_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lecture_id TEXT NOT NULL,
                score INTEGER NOT NULL,
                total INTEGER NOT NULL,
                answers TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (lecture_id) REFERENCES lectures(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS knowledge_gaps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lecture_id TEXT NOT NULL,
                concept TEXT NOT NULL,
                mistakes INTEGER NOT NULL DEFAULT 0,
                successes INTEGER NOT NULL DEFAULT 0,
                evidence TEXT NOT NULL,
                source_ref TEXT NOT NULL,
                next_review TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(lecture_id, concept),
                FOREIGN KEY (lecture_id) REFERENCES lectures(id) ON DELETE CASCADE
            );
            """
        )
        ensure_column(db, "lectures", "file_type", "TEXT NOT NULL DEFAULT 'PDF'")
        ensure_column(db, "lectures", "source_chunks", "TEXT NOT NULL DEFAULT '[]'")
        ensure_column(db, "lectures", "flashcards", "TEXT NOT NULL DEFAULT '[]'")
        ensure_column(db, "quiz_attempts", "confidences", "TEXT NOT NULL DEFAULT '[]'")
        ensure_column(db, "knowledge_gaps", "false_confidence", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(db, "knowledge_gaps", "last_confidence", "INTEGER NOT NULL DEFAULT 0")

        if os.getenv("STUDYCLOUD_SEED_DEMO", "1") != "0":
            count = db.execute("SELECT COUNT(*) FROM lectures").fetchone()[0]
            if count == 0:
                seed_demo(db)
        upgrade_legacy_lectures(db)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-ZА-ЯЁ0-9])", clean_text(text))
    return [part.strip() for part in parts if len(part.split()) >= 5]


STOP_WORDS = {
    "about", "after", "again", "also", "among", "and", "are", "because", "been", "before",
    "being", "between", "both", "but", "can", "could", "does", "each", "from", "have", "into",
    "more", "most", "not", "only", "other", "over", "same", "should", "some", "such", "than",
    "that", "their", "then", "there", "these", "they", "this", "through", "under", "using", "very",
    "was", "were", "when", "where", "which", "while", "will", "with", "would", "your",
    "для", "или", "как", "это", "при", "его", "она", "они", "были", "может", "после", "через",
    "также", "между", "этот", "эти", "когда", "который", "чтобы", "если", "более", "всего",
    "того", "есть", "быть", "такой", "своих", "свой", "один", "одна", "будет", "можно",
}


def keywords(text: str, limit: int = 22) -> list[str]:
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    for token in re.findall(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё-]{3,}", text):
        normalized = token.lower().strip("-")
        if normalized in STOP_WORDS:
            continue
        counts[normalized] = counts.get(normalized, 0) + 1
        display.setdefault(normalized, token.strip("-"))
    ranked = sorted(counts, key=lambda item: (-counts[item], item))
    return [display[item] for item in ranked[:limit]]


def find_source(sentence: str, chunks: list[dict[str, str]]) -> dict[str, str]:
    sentence_words = set(re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", sentence.lower()))
    best = {"ref": "Source", "text": sentence}
    best_score = 0
    for chunk in chunks:
        chunk_words = set(re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", chunk["text"].lower()))
        score = len(sentence_words & chunk_words)
        if score > best_score:
            best = chunk
            best_score = score
    return best


def local_study_material(text: str, chunks: list[dict[str, str]]) -> dict[str, Any]:
    sentences = split_sentences(text)
    if not sentences:
        sentences = [clean_text(text)[:800] or "The document contains no extractable text."]

    terms = keywords(text)
    weights = {term.lower(): len(terms) - index for index, term in enumerate(terms)}

    def sentence_score(sentence: str) -> float:
        words = re.findall(r"[A-Za-zА-Яа-яЁё-]+", sentence.lower())
        return sum(weights.get(word, 0) for word in words) / max(len(words), 1)

    selected = sorted(
        sorted(enumerate(sentences), key=lambda item: sentence_score(item[1]), reverse=True)[:7],
        key=lambda item: item[0],
    )
    summary_sentences = [sentence for _, sentence in selected]
    ideas = summary_sentences[:5]

    quiz: list[dict[str, Any]] = []
    distractors = terms[:]
    for sentence in sentences:
        if len(quiz) >= 7:
            break
        found = next(
            (term for term in terms if re.search(rf"\b{re.escape(term)}\b", sentence, flags=re.IGNORECASE)),
            None,
        )
        if not found or any(item["answer"].lower() == found.lower() for item in quiz):
            continue
        choices = [found]
        for term in distractors:
            if term.lower() != found.lower() and term.lower() not in {choice.lower() for choice in choices}:
                choices.append(term)
            if len(choices) == 4:
                break
        if len(choices) < 4:
            continue
        offset = len(quiz) % 4
        choices = choices[1 : offset + 1] + [found] + choices[offset + 1 :]
        choices = choices[:4]
        source = find_source(sentence, chunks)
        prompt = re.sub(rf"\b{re.escape(found)}\b", "_____", sentence, count=1, flags=re.IGNORECASE)
        quiz.append(
            {
                "question": f"Which term best completes this statement? {prompt}",
                "options": choices,
                "correct_index": choices.index(found),
                "answer": found,
                "concept": found,
                "explanation": sentence,
                "source_ref": source["ref"],
            }
        )

    while len(quiz) < 5:
        index = len(quiz) % len(ideas)
        correct = ideas[index]
        alternatives = [idea for idea in ideas if idea != correct][:3]
        while len(alternatives) < 3:
            alternatives.append("This statement is not supported by the uploaded material.")
        options = [correct, *alternatives]
        shift = len(quiz) % 4
        options = options[shift:] + options[:shift]
        source = find_source(correct, chunks)
        quiz.append(
            {
                "question": "Which statement is supported by the source material?",
                "options": options,
                "correct_index": options.index(correct),
                "answer": correct,
                "concept": terms[index] if terms else f"Key idea {index + 1}",
                "explanation": correct,
                "source_ref": source["ref"],
            }
        )

    flashcards = []
    for index, idea in enumerate(ideas):
        term = terms[index] if index < len(terms) else f"Key idea {index + 1}"
        source = find_source(idea, chunks)
        flashcards.append({"front": term, "back": idea, "source_ref": source["ref"]})

    return {
        "summary": " ".join(summary_sentences),
        "key_ideas": ideas,
        "quiz": quiz[:7],
        "flashcards": flashcards,
        "engine": "Local extractive engine",
    }


def upgrade_legacy_lectures(db: sqlite3.Connection) -> None:
    rows = db.execute(
        "SELECT id, text_content, source_chunks, flashcards, quiz FROM lectures"
    ).fetchall()
    for row in rows:
        try:
            chunks = json.loads(row["source_chunks"] or "[]")
        except json.JSONDecodeError:
            chunks = []
        try:
            flashcards = json.loads(row["flashcards"] or "[]")
        except json.JSONDecodeError:
            flashcards = []
        try:
            quiz = json.loads(row["quiz"] or "[]")
        except json.JSONDecodeError:
            quiz = []
        quiz_needs_upgrade = bool(quiz) and any(
            "concept" not in item or "source_ref" not in item for item in quiz
        )
        demo_needs_sources = row["id"] == "demo-raft" and (
            not chunks or chunks[0].get("ref") == "Imported source"
        )
        if chunks and flashcards and not quiz_needs_upgrade and not demo_needs_sources:
            continue
        if demo_needs_sources:
            sentences = split_sentences(row["text_content"])
            page_refs = ["Page 2", "Page 4", "Page 7", "Page 9", "Page 11"]
            chunks = [
                {"ref": ref, "text": " ".join(sentences[index * 2 : index * 2 + 2])}
                for index, ref in enumerate(page_refs)
                if sentences[index * 2 : index * 2 + 2]
            ]
            quiz_needs_upgrade = True
        else:
            chunks = chunks or [{"ref": "Imported source", "text": clean_text(row["text_content"])}]
        material = local_study_material(row["text_content"], chunks)
        db.execute(
            "UPDATE lectures SET source_chunks=?, flashcards=?, quiz=? WHERE id=?",
            (
                json.dumps(chunks, ensure_ascii=False),
                json.dumps(flashcards or material["flashcards"], ensure_ascii=False),
                json.dumps(material["quiz"] if quiz_needs_upgrade or not quiz else quiz, ensure_ascii=False),
                row["id"],
            ),
        )


def normalize_material(material: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    quiz = material.get("quiz") if isinstance(material.get("quiz"), list) else fallback["quiz"]
    normalized_quiz = []
    for index, item in enumerate(quiz[:7]):
        fallback_item = fallback["quiz"][index % len(fallback["quiz"])]
        options = item.get("options") if isinstance(item.get("options"), list) else fallback_item["options"]
        if len(options) != 4:
            options = fallback_item["options"]
        correct_index = item.get("correct_index", fallback_item["correct_index"])
        if not isinstance(correct_index, int) or correct_index not in range(4):
            correct_index = fallback_item["correct_index"]
        normalized_quiz.append(
            {
                "question": str(item.get("question") or fallback_item["question"]),
                "options": [str(option) for option in options],
                "correct_index": correct_index,
                "answer": str(item.get("answer") or options[correct_index]),
                "concept": str(item.get("concept") or fallback_item["concept"]),
                "explanation": str(item.get("explanation") or fallback_item["explanation"]),
                "source_ref": str(item.get("source_ref") or fallback_item["source_ref"]),
            }
        )
    if len(normalized_quiz) < 5:
        normalized_quiz = fallback["quiz"]

    flashcards = material.get("flashcards")
    if not isinstance(flashcards, list) or len(flashcards) < 3:
        flashcards = fallback["flashcards"]
    return {
        "summary": str(material.get("summary") or fallback["summary"]),
        "key_ideas": material.get("key_ideas") if isinstance(material.get("key_ideas"), list) else fallback["key_ideas"],
        "quiz": normalized_quiz,
        "flashcards": flashcards[:10],
        "engine": material.get("engine", fallback["engine"]),
    }


async def gemini_study_material(text: str, chunks: list[dict[str, str]]) -> dict[str, Any] | None:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    source_text = "\n\n".join(f"[{chunk['ref']}] {chunk['text']}" for chunk in chunks)[:60000]
    prompt = (
        "Create an evidence-grounded study pack from the source below. Return only valid JSON with: "
        "summary (string), key_ideas (5 strings), flashcards (5-10 objects with front, back, source_ref), "
        "quiz (5-7 objects with question, options of 4 strings, correct_index 0-3, answer, concept, "
        "explanation, source_ref). Every source_ref must use a bracket label from the source. "
        "Use the source's language and do not add outside facts.\n\n" + source_text
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    try:
        async with httpx.AsyncClient(timeout=75) as client:
            response = await client.post(
                url,
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
                },
            )
            response.raise_for_status()
        raw = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        material = json.loads(raw)
        material["engine"] = f"Gemini · {model}"
        return material
    except (httpx.HTTPError, KeyError, TypeError, json.JSONDecodeError, ValueError):
        return None


def extract_document(filename: str, contents: bytes) -> tuple[str, int, list[dict[str, str]]]:
    extension = Path(filename).suffix.lower()
    chunks: list[dict[str, str]] = []

    if extension == ".pdf" and not contents.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="The file extension is PDF, but the content is not a PDF")
    if extension in {".pptx", ".docx"} and not zipfile.is_zipfile(io.BytesIO(contents)):
        raise HTTPException(status_code=400, detail=f"The uploaded {extension.upper()} file is invalid")

    try:
        if extension == ".pdf":
            reader = PdfReader(io.BytesIO(contents))
            for index, page in enumerate(reader.pages, 1):
                page_text = clean_text(page.extract_text() or "")
                if page_text:
                    chunks.append({"ref": f"Page {index}", "text": page_text})
            units = len(reader.pages)
        elif extension == ".pptx":
            presentation = Presentation(io.BytesIO(contents))
            for index, slide in enumerate(presentation.slides, 1):
                parts = [shape.text for shape in slide.shapes if hasattr(shape, "text_frame") and shape.text.strip()]
                slide_text = clean_text(" ".join(parts))
                if slide_text:
                    chunks.append({"ref": f"Slide {index}", "text": slide_text})
            units = len(presentation.slides)
        elif extension == ".docx":
            document = Document(io.BytesIO(contents))
            block = 0
            for paragraph in document.paragraphs:
                paragraph_text = clean_text(paragraph.text)
                if paragraph_text:
                    block += 1
                    chunks.append({"ref": f"Paragraph {block}", "text": paragraph_text})
            for table_index, table in enumerate(document.tables, 1):
                table_text = clean_text(" ".join(cell.text for row in table.rows for cell in row.cells))
                if table_text:
                    chunks.append({"ref": f"Table {table_index}", "text": table_text})
            units = max(block, 1)
        else:
            decoded = contents.decode("utf-8-sig", errors="replace")
            paragraphs = [clean_text(part) for part in re.split(r"\n\s*\n", decoded) if clean_text(part)]
            chunks = [{"ref": f"Section {index}", "text": part} for index, part in enumerate(paragraphs, 1)]
            units = max(len(chunks), 1)
    except Exception as error:
        raise HTTPException(status_code=422, detail="The document could not be read") from error

    text = clean_text(" ".join(chunk["text"] for chunk in chunks))
    if len(text) < 80:
        raise HTTPException(
            status_code=422,
            detail="Not enough readable text was found. Scanned PDFs need OCR before upload.",
        )
    return text, units, chunks


def seed_demo(db: sqlite3.Connection) -> None:
    sections = [
        ("Page 2", "Distributed systems coordinate independent computers over a network. The Raft consensus algorithm keeps a replicated log consistent by electing one leader."),
        ("Page 4", "Followers become candidates when they stop receiving leader heartbeats. Randomized election timeouts reduce split votes because candidates usually start elections at different moments."),
        ("Page 7", "A candidate becomes leader after receiving votes from a majority of servers. The leader accepts client commands, appends them to its log, and replicates entries with AppendEntries RPC calls."),
        ("Page 9", "An entry becomes committed after a majority stores it, then each server applies it to its state machine. Raft tolerates failures while a majority of the cluster remains available."),
        ("Page 11", "Network partitions may isolate a minority, but that minority cannot commit conflicting entries. Safety requires servers to preserve election restrictions and log matching rules."),
    ]
    chunks = [{"ref": ref, "text": value} for ref, value in sections]
    text = " ".join(value for _, value in sections)
    material = local_study_material(text, chunks)
    db.execute(
        """
        INSERT INTO lectures
        (id, title, filename, pages, word_count, text_content, summary, key_ideas, quiz, engine,
         created_at, file_type, source_chunks, flashcards)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "demo-raft", "Distributed Consensus: Raft", "demo-raft.pdf", 12, len(text.split()), text,
            material["summary"], json.dumps(material["key_ideas"], ensure_ascii=False),
            json.dumps(material["quiz"], ensure_ascii=False), "Local demo", datetime.now(UTC).isoformat(),
            "PDF", json.dumps(chunks, ensure_ascii=False), json.dumps(material["flashcards"], ensure_ascii=False),
        ),
    )


def row_to_lecture(row: sqlite3.Row, include_quiz: bool = True) -> dict[str, Any]:
    lecture = dict(row)
    lecture["key_ideas"] = json.loads(lecture["key_ideas"] or "[]")
    lecture["source_chunks"] = json.loads(lecture.get("source_chunks") or "[]")
    lecture["flashcards"] = json.loads(lecture.get("flashcards") or "[]")
    lecture["quiz"] = json.loads(lecture["quiz"]) if include_quiz else []
    lecture.pop("text_content", None)
    return lecture


def mastery_score(mistakes: int, successes: int, false_confidence: int = 0) -> int:
    if mistakes + successes == 0:
        return 0
    base = round(100 * (successes + 0.25) / (mistakes + successes + 0.5))
    return max(0, min(100, base - false_confidence * 12))


def gap_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    gap = dict(row)
    gap["mastery"] = mastery_score(gap["mistakes"], gap["successes"], gap.get("false_confidence", 0))
    gap["priority"] = max(
        0,
        gap["mistakes"] * 2 + gap.get("false_confidence", 0) * 3 - gap["successes"],
    )
    gap["is_blind_spot"] = gap.get("false_confidence", 0) > 0
    return gap


class QuizSubmission(BaseModel):
    answers: list[int | None]
    confidences: list[int | None] = Field(default_factory=list)


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class GapReview(BaseModel):
    remembered: bool


class FlashcardInput(BaseModel):
    front: str = Field(min_length=1, max_length=200)
    back: str = Field(min_length=1, max_length=2000)
    source_ref: str = Field(default="Edited", max_length=120)


class StudyPackUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    summary: str | None = Field(default=None, min_length=20, max_length=20000)
    key_ideas: list[str] | None = None
    flashcards: list[FlashcardInput] | None = None


class DefenseRequest(BaseModel):
    explanation: str = Field(min_length=20, max_length=8000)
    confidence: int = Field(default=50, ge=0, le=100)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_database()
    yield


app = FastAPI(title="StudyCloud AI", version="2.0.0", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": "2.0.0",
        "formats": sorted(extension.removeprefix(".").upper() for extension in SUPPORTED_EXTENSIONS),
    }


@app.get("/api/stats")
def stats() -> dict[str, int]:
    with connect() as db:
        lecture_stats = db.execute(
            "SELECT COUNT(*) AS count, COALESCE(SUM(word_count), 0) AS words FROM lectures"
        ).fetchone()
        quiz_stats = db.execute(
            "SELECT COUNT(*) AS count, COALESCE(SUM(score), 0) AS score, COALESCE(SUM(total), 0) AS total FROM quiz_attempts"
        ).fetchone()
        open_gaps = db.execute("SELECT COUNT(*) FROM knowledge_gaps WHERE mistakes > successes").fetchone()[0]
        blind_spots = db.execute("SELECT COUNT(*) FROM knowledge_gaps WHERE false_confidence > 0").fetchone()[0]
    accuracy = round(100 * quiz_stats["score"] / quiz_stats["total"]) if quiz_stats["total"] else 0
    return {
        "lectures": lecture_stats["count"], "words": lecture_stats["words"],
        "quizzes": quiz_stats["count"], "accuracy": accuracy, "open_gaps": open_gaps,
        "blind_spots": blind_spots,
    }


@app.get("/api/lectures")
def list_lectures() -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("SELECT * FROM lectures ORDER BY created_at DESC").fetchall()
    return [row_to_lecture(row, include_quiz=False) for row in rows]


@app.get("/api/lectures/{lecture_id}")
def get_lecture(lecture_id: str) -> dict[str, Any]:
    with connect() as db:
        row = db.execute("SELECT * FROM lectures WHERE id = ?", (lecture_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Lecture not found")
    return row_to_lecture(row)


@app.patch("/api/lectures/{lecture_id}")
def update_lecture(lecture_id: str, update: StudyPackUpdate) -> dict[str, Any]:
    values = update.model_dump(exclude_none=True)
    if not values:
        raise HTTPException(status_code=400, detail="No study-pack changes were provided")
    if "key_ideas" in values:
        values["key_ideas"] = [clean_text(item) for item in values["key_ideas"] if clean_text(item)][:10]
        if not values["key_ideas"]:
            raise HTTPException(status_code=422, detail="At least one key idea is required")
        values["key_ideas"] = json.dumps(values["key_ideas"], ensure_ascii=False)
    if "flashcards" in values:
        if not values["flashcards"]:
            raise HTTPException(status_code=422, detail="At least one flashcard is required")
        values["flashcards"] = json.dumps(values["flashcards"][:30], ensure_ascii=False)
    if "title" in values:
        values["title"] = clean_text(values["title"])
    if "summary" in values:
        values["summary"] = clean_text(values["summary"])
    allowed = {"title", "summary", "key_ideas", "flashcards"}
    values = {key: value for key, value in values.items() if key in allowed}
    assignments = ", ".join(f"{key} = ?" for key in values)
    with connect() as db:
        exists = db.execute("SELECT id FROM lectures WHERE id = ?", (lecture_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Lecture not found")
        db.execute(
            f"UPDATE lectures SET {assignments} WHERE id = ?",
            (*values.values(), lecture_id),
        )
        row = db.execute("SELECT * FROM lectures WHERE id = ?", (lecture_id,)).fetchone()
    return row_to_lecture(row)


@app.post("/api/lectures", status_code=201)
async def upload_lecture(file: UploadFile = File(...)) -> dict[str, Any]:
    filename = Path(file.filename or "lecture.txt").name
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(item.removeprefix(".").upper() for item in SUPPORTED_EXTENSIONS))
        raise HTTPException(status_code=415, detail=f"Unsupported format. Use {supported}")

    contents = await file.read(MAX_FILE_SIZE + 1)
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds the 25 MB limit")
    if not contents:
        raise HTTPException(status_code=400, detail="The uploaded file is empty")

    text, units, chunks = extract_document(filename, contents)
    fallback = local_study_material(text, chunks)
    generated = await gemini_study_material(text, chunks)
    material = normalize_material(generated or fallback, fallback)

    lecture_id = uuid.uuid4().hex[:12]
    stored_path = data_dir() / "uploads" / f"{lecture_id}{extension}"
    stored_path.write_bytes(contents)
    title = clean_text(Path(filename).stem.replace("_", " ").replace("-", " ")).title()
    created_at = datetime.now(UTC).isoformat()
    file_type = extension.removeprefix(".").upper()
    with connect() as db:
        db.execute(
            """
            INSERT INTO lectures
            (id, title, filename, pages, word_count, text_content, summary, key_ideas, quiz, engine,
             created_at, file_type, source_chunks, flashcards)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lecture_id, title, filename, units, len(text.split()), text, material["summary"],
                json.dumps(material["key_ideas"], ensure_ascii=False),
                json.dumps(material["quiz"], ensure_ascii=False), material["engine"], created_at,
                file_type, json.dumps(chunks, ensure_ascii=False),
                json.dumps(material["flashcards"], ensure_ascii=False),
            ),
        )
        row = db.execute("SELECT * FROM lectures WHERE id = ?", (lecture_id,)).fetchone()
    return row_to_lecture(row)


@app.post("/api/lectures/{lecture_id}/quiz")
def submit_quiz(lecture_id: str, submission: QuizSubmission) -> dict[str, Any]:
    now = datetime.now(UTC)
    with connect() as db:
        row = db.execute("SELECT quiz FROM lectures WHERE id = ?", (lecture_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Lecture not found")
        quiz = json.loads(row["quiz"])
        answers = submission.answers[: len(quiz)]
        answers += [None] * (len(quiz) - len(answers))
        confidences = submission.confidences[: len(quiz)]
        confidences += [50] * (len(quiz) - len(confidences))
        confidences = [max(0, min(100, int(value if value is not None else 50))) for value in confidences]
        correct = [answer == item["correct_index"] for answer, item in zip(answers, quiz)]
        score = sum(correct)
        db.execute(
            "INSERT INTO quiz_attempts (lecture_id, score, total, answers, confidences, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (lecture_id, score, len(quiz), json.dumps(answers), json.dumps(confidences), now.isoformat()),
        )

        changed_gaps = []
        blind_spots = []
        for is_correct, confidence, item in zip(correct, confidences, quiz):
            concept = str(item.get("concept") or item.get("answer") or "Key concept")[:120]
            existing = db.execute(
                "SELECT * FROM knowledge_gaps WHERE lecture_id = ? AND concept = ?", (lecture_id, concept)
            ).fetchone()
            mistakes = (existing["mistakes"] if existing else 0) + (0 if is_correct else 1)
            successes = (existing["successes"] if existing else 0) + (1 if is_correct else 0)
            previous_false_confidence = existing["false_confidence"] if existing else 0
            false_confidence = previous_false_confidence + (1 if not is_correct and confidence >= 75 else 0)
            review_days = min(30, 2 ** min(successes, 4)) if is_correct else 1
            next_review = (now + timedelta(days=review_days)).isoformat()
            db.execute(
                """
                INSERT INTO knowledge_gaps
                (lecture_id, concept, mistakes, successes, evidence, source_ref, next_review, updated_at,
                 false_confidence, last_confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(lecture_id, concept) DO UPDATE SET
                    mistakes=excluded.mistakes, successes=excluded.successes, evidence=excluded.evidence,
                    source_ref=excluded.source_ref, next_review=excluded.next_review, updated_at=excluded.updated_at,
                    false_confidence=excluded.false_confidence, last_confidence=excluded.last_confidence
                """,
                (
                    lecture_id, concept, mistakes, successes, str(item.get("explanation", "")),
                    str(item.get("source_ref", "Source")), next_review, now.isoformat(),
                    false_confidence, confidence,
                ),
            )
            gap = db.execute(
                "SELECT * FROM knowledge_gaps WHERE lecture_id = ? AND concept = ?", (lecture_id, concept)
            ).fetchone()
            if not is_correct:
                serialized = gap_to_dict(gap)
                changed_gaps.append(serialized)
                if confidence >= 75:
                    blind_spots.append(serialized)
    return {
        "score": score, "total": len(quiz), "correct": correct,
        "knowledge_gaps": changed_gaps, "blind_spots": blind_spots,
    }


def ranked_sources(question: str, chunks: list[dict[str, str]], limit: int = 3) -> list[dict[str, str]]:
    query_terms = set(keywords(question, 20))
    query_lower = {term.lower() for term in query_terms}
    scored = []
    for chunk in chunks:
        chunk_terms = set(re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", chunk["text"].lower()))
        score = len(query_lower & chunk_terms)
        scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [chunk for score, chunk in scored if score > 0][:limit]
    return selected or chunks[:limit]


async def gemini_answer(question: str, sources: list[dict[str, str]]) -> str | None:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    evidence = "\n\n".join(f"[{item['ref']}] {item['text']}" for item in sources)
    prompt = (
        "Answer the question using only the evidence. Be concise, use the evidence's language, and cite source "
        "labels in square brackets. If the evidence is insufficient, say so.\n\n"
        f"Question: {question}\n\nEvidence:\n{evidence}"
    )
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.1}},
            )
            response.raise_for_status()
        return response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (httpx.HTTPError, KeyError, TypeError):
        return None


@app.post("/api/lectures/{lecture_id}/ask")
async def ask_lecture(lecture_id: str, request: AskRequest) -> dict[str, Any]:
    with connect() as db:
        row = db.execute("SELECT source_chunks FROM lectures WHERE id = ?", (lecture_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Lecture not found")
    chunks = json.loads(row["source_chunks"] or "[]")
    sources = ranked_sources(request.question, chunks)
    answer = await gemini_answer(request.question, sources)
    if not answer:
        question_terms = set(
            re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", request.question.lower())
        ) - STOP_WORDS
        evidence_sentences = []
        for source in sources:
            candidates = split_sentences(source["text"])
            if candidates:
                best = max(
                    candidates,
                    key=lambda sentence: len(
                        question_terms
                        & set(re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", sentence.lower()))
                    ),
                )
                evidence_sentences.append(best)
        answer = " ".join(evidence_sentences[:3])
        if answer:
            answer += " " + " ".join(f"[{source['ref']}]" for source in sources[:2])
        else:
            answer = "The uploaded material does not contain enough evidence to answer this question."
    return {
        "answer": answer,
        "sources": [{"ref": item["ref"], "text": item["text"][:420]} for item in sources],
    }


@app.post("/api/lectures/{lecture_id}/defend")
def defend_lecture(lecture_id: str, request: DefenseRequest) -> dict[str, Any]:
    with connect() as db:
        row = db.execute("SELECT * FROM lectures WHERE id = ?", (lecture_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Lecture not found")
        lecture = row_to_lecture(row)
        explanation_tokens = set(
            re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", request.explanation.lower())
        ) - STOP_WORDS

        concepts: list[dict[str, str]] = []
        seen: set[str] = set()
        for card in lecture["flashcards"]:
            concept = clean_text(str(card.get("front", "")))
            if concept and concept.lower() not in seen:
                seen.add(concept.lower())
                concepts.append(
                    {
                        "concept": concept,
                        "evidence": clean_text(str(card.get("back", ""))),
                        "source_ref": str(card.get("source_ref", "Source")),
                    }
                )
        for term in keywords(" ".join(lecture["key_ideas"]), 10):
            if term.lower() not in seen:
                seen.add(term.lower())
                source = find_source(term, lecture["source_chunks"])
                concepts.append({"concept": term, "evidence": source["text"], "source_ref": source["ref"]})
        concepts = concepts[:10]

        covered: list[dict[str, str]] = []
        missing: list[dict[str, str]] = []
        explanation_lower = request.explanation.lower()
        for item in concepts:
            concept_tokens = set(
                re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", item["concept"].lower())
            ) - STOP_WORDS
            direct_match = item["concept"].lower() in explanation_lower
            token_match = bool(concept_tokens) and len(concept_tokens & explanation_tokens) >= max(1, len(concept_tokens) // 2)
            (covered if direct_match or token_match else missing).append(item)

        coverage = round(100 * len(covered) / len(concepts)) if concepts else 0
        now = datetime.now(UTC)
        blind_spots = []
        for item in missing[:6]:
            existing = db.execute(
                "SELECT * FROM knowledge_gaps WHERE lecture_id = ? AND concept = ?",
                (lecture_id, item["concept"]),
            ).fetchone()
            mistakes = (existing["mistakes"] if existing else 0) + 1
            successes = existing["successes"] if existing else 0
            false_confidence = (existing["false_confidence"] if existing else 0) + (
                1 if request.confidence >= 75 else 0
            )
            db.execute(
                """
                INSERT INTO knowledge_gaps
                (lecture_id, concept, mistakes, successes, evidence, source_ref, next_review, updated_at,
                 false_confidence, last_confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(lecture_id, concept) DO UPDATE SET
                    mistakes=excluded.mistakes, successes=excluded.successes, evidence=excluded.evidence,
                    source_ref=excluded.source_ref, next_review=excluded.next_review, updated_at=excluded.updated_at,
                    false_confidence=excluded.false_confidence, last_confidence=excluded.last_confidence
                """,
                (
                    lecture_id, item["concept"], mistakes, successes, item["evidence"], item["source_ref"],
                    (now + timedelta(days=1)).isoformat(), now.isoformat(), false_confidence, request.confidence,
                ),
            )
            if request.confidence >= 75:
                gap = db.execute(
                    "SELECT * FROM knowledge_gaps WHERE lecture_id = ? AND concept = ?",
                    (lecture_id, item["concept"]),
                ).fetchone()
                blind_spots.append(gap_to_dict(gap))

    if coverage >= 80:
        feedback = "Strong explanation. You covered most of the material's core concepts."
    elif coverage >= 50:
        feedback = "Developing explanation. The main structure is present, but several concepts need another pass."
    else:
        feedback = "The explanation is still incomplete. Review the missing concepts and try again without looking."
    prompt = (
        f"Explain how {missing[0]['concept']} connects to the main topic."
        if missing else "Explain the topic again using a concrete example."
    )
    return {
        "coverage": coverage,
        "confidence": request.confidence,
        "covered": [item["concept"] for item in covered],
        "missing": [item["concept"] for item in missing],
        "feedback": feedback,
        "sources": [
            {"ref": item["source_ref"], "text": item["evidence"][:420]}
            for item in missing[:3]
        ],
        "blind_spots": blind_spots,
        "next_prompt": prompt,
    }


@app.get("/api/radar")
def knowledge_radar() -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            """
            SELECT g.*, l.title AS lecture_title
            FROM knowledge_gaps g JOIN lectures l ON l.id = g.lecture_id
            ORDER BY (g.mistakes * 2 - g.successes) DESC, g.updated_at DESC
            """
        ).fetchall()
    return [gap_to_dict(row) for row in rows]


@app.post("/api/radar/{gap_id}/review")
def review_gap(gap_id: int, review: GapReview) -> dict[str, Any]:
    now = datetime.now(UTC)
    with connect() as db:
        row = db.execute("SELECT * FROM knowledge_gaps WHERE id = ?", (gap_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Knowledge gap not found")
        mistakes = row["mistakes"] + (0 if review.remembered else 1)
        successes = row["successes"] + (1 if review.remembered else 0)
        false_confidence = max(0, row["false_confidence"] - (1 if review.remembered else 0))
        review_days = min(30, 2 ** min(successes, 4)) if review.remembered else 1
        db.execute(
            "UPDATE knowledge_gaps SET mistakes=?, successes=?, false_confidence=?, next_review=?, updated_at=? WHERE id=?",
            (
                mistakes, successes, false_confidence,
                (now + timedelta(days=review_days)).isoformat(), now.isoformat(), gap_id,
            ),
        )
        updated = db.execute(
            "SELECT g.*, l.title AS lecture_title FROM knowledge_gaps g JOIN lectures l ON l.id=g.lecture_id WHERE g.id=?",
            (gap_id,),
        ).fetchone()
    return gap_to_dict(updated)


@app.get("/api/lectures/{lecture_id}/export")
def export_lecture(lecture_id: str) -> PlainTextResponse:
    with connect() as db:
        row = db.execute("SELECT * FROM lectures WHERE id = ?", (lecture_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Lecture not found")
    lecture = row_to_lecture(row)
    lines = [f"# {lecture['title']}", "", "## Summary", "", lecture["summary"], "", "## Key ideas", ""]
    lines.extend(f"- {idea}" for idea in lecture["key_ideas"])
    lines.extend(["", "## Flashcards", ""])
    for card in lecture["flashcards"]:
        lines.extend([f"### {card.get('front', 'Concept')}", str(card.get("back", "")), f"Source: {card.get('source_ref', 'Source')}", ""])
    lines.extend(["## Practice questions", ""])
    for index, question in enumerate(lecture["quiz"], 1):
        lines.extend([f"### {index}. {question['question']}", f"Answer: {question['answer']}", f"Source: {question.get('source_ref', 'Source')}", ""])
    filename = re.sub(r"[^A-Za-zА-Яа-яЁё0-9_-]+", "-", lecture["title"]).strip("-") or "study-pack"
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}.md"}
    return PlainTextResponse("\n".join(lines), media_type="text/markdown; charset=utf-8", headers=headers)


@app.get("/api/lectures/{lecture_id}/source")
def download_source(lecture_id: str) -> FileResponse:
    with connect() as db:
        row = db.execute("SELECT filename FROM lectures WHERE id = ?", (lecture_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Lecture not found")
    candidates = list((data_dir() / "uploads").glob(f"{lecture_id}.*"))
    if not candidates:
        raise HTTPException(status_code=404, detail="Original demo source is not stored")
    return FileResponse(candidates[0], filename=row["filename"])


@app.delete("/api/lectures/{lecture_id}", status_code=204)
def delete_lecture(lecture_id: str) -> None:
    if lecture_id == "demo-raft":
        raise HTTPException(status_code=400, detail="The built-in demo lecture cannot be deleted")
    with connect() as db:
        exists = db.execute("SELECT id FROM lectures WHERE id = ?", (lecture_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Lecture not found")
        db.execute("DELETE FROM lectures WHERE id = ?", (lecture_id,))
    for path in (data_dir() / "uploads").glob(f"{lecture_id}.*"):
        path.unlink(missing_ok=True)


@app.get("/sw.js", include_in_schema=False)
def service_worker() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
