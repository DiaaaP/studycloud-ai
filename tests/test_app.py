import io
import os
import tempfile

os.environ["STUDYCLOUD_DATA_DIR"] = tempfile.mkdtemp(prefix="studycloud-tests-")
os.environ["STUDYCLOUD_SEED_DEMO"] = "1"

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.main import app


def test_health_and_seeded_library():
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["version"] == "2.0.0"
        assert "PPTX" in health.json()["formats"]
        lectures = client.get("/api/lectures").json()
        assert any(lecture["id"] == "demo-raft" for lecture in lectures)


def test_txt_upload_builds_full_study_pack():
    text = (
        "Photosynthesis converts light energy into chemical energy inside chloroplasts. "
        "Chlorophyll absorbs light while the light-dependent reactions produce ATP and NADPH. "
        "The Calvin cycle uses ATP and NADPH to fix carbon dioxide into sugars. "
        "Stomata regulate gas exchange and influence the rate of photosynthesis. "
        "Temperature, light intensity, and carbon dioxide concentration can limit the process. "
        "Plants balance carbon fixation with water loss under changing environmental conditions."
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/lectures",
            files={"file": ("photosynthesis.txt", text.encode(), "text/plain")},
        )
        assert response.status_code == 201
        lecture = response.json()
        assert lecture["file_type"] == "TXT"
        assert len(lecture["quiz"]) >= 5
        assert len(lecture["flashcards"]) >= 3
        assert lecture["source_chunks"][0]["ref"].startswith("Section")


def test_grounded_question_returns_sources():
    with TestClient(app) as client:
        response = client.post(
            "/api/lectures/demo-raft/ask",
            json={"question": "Why are randomized election timeouts useful?"},
        )
        assert response.status_code == 200
        assert response.json()["answer"]
        assert response.json()["sources"]
        assert response.json()["sources"][0]["ref"].startswith("Page")


def test_wrong_answers_create_proofloop_debts_and_reviews():
    with TestClient(app) as client:
        lecture = client.get("/api/lectures/demo-raft").json()
        result = client.post(
            "/api/lectures/demo-raft/quiz",
            json={"answers": [-1] * len(lecture["quiz"]), "confidences": [100] * len(lecture["quiz"])},
        )
        assert result.status_code == 200
        assert result.json()["score"] == 0
        assert result.json()["knowledge_gaps"]
        assert result.json()["blind_spots"]
        radar = client.get("/api/radar").json()
        assert radar[0]["mistakes"] >= 1
        assert radar[0]["is_blind_spot"] is True
        reviewed = client.post(f"/api/radar/{radar[0]['id']}/review", json={"remembered": True})
        assert reviewed.status_code == 200
        assert reviewed.json()["successes"] >= 1


def test_markdown_export_contains_sources_and_flashcards():
    with TestClient(app) as client:
        response = client.get("/api/lectures/demo-raft/export")
        assert response.status_code == 200
        assert "## Flashcards" in response.text
        assert "Source:" in response.text


def test_feynman_defense_finds_confident_omissions():
    with TestClient(app) as client:
        response = client.post(
            "/api/lectures/demo-raft/defend",
            json={
                "explanation": "Raft coordinates servers and uses a leader to keep a replicated log consistent.",
                "confidence": 100,
            },
        )
        assert response.status_code == 200
        result = response.json()
        assert 0 <= result["coverage"] <= 100
        assert result["missing"]
        assert result["blind_spots"]
        assert result["next_prompt"]


def test_study_pack_can_be_edited():
    with TestClient(app) as client:
        response = client.patch(
            "/api/lectures/demo-raft",
            json={
                "title": "Raft Consensus Lab",
                "summary": "A revised summary that keeps the core Raft consensus concepts available for study.",
                "key_ideas": ["Leader election", "Replicated log", "Majority commitment"],
            },
        )
        assert response.status_code == 200
        assert response.json()["title"] == "Raft Consensus Lab"
        assert response.json()["key_ideas"][0] == "Leader election"


def test_pwa_assets_are_available():
    with TestClient(app) as client:
        assert client.get("/static/manifest.webmanifest").status_code == 200
        service_worker = client.get("/sw.js")
        assert service_worker.status_code == 200
        assert service_worker.headers["service-worker-allowed"] == "/"


def test_rejects_unsupported_format():
    with TestClient(app) as client:
        response = client.post("/api/lectures", files={"file": ("notes.exe", b"hello", "application/octet-stream")})
        assert response.status_code == 415


def test_rejects_pdf_without_extractable_text():
    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.write(buffer)
    with TestClient(app) as client:
        response = client.post(
            "/api/lectures",
            files={"file": ("blank.pdf", buffer.getvalue(), "application/pdf")},
        )
        assert response.status_code == 422
