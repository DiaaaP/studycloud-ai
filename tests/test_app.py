import io
import os
import tempfile
import uuid
import zipfile

os.environ["STUDYCLOUD_DATA_DIR"] = tempfile.mkdtemp(prefix="studycloud-tests-")
os.environ["STUDYCLOUD_SEED_DEMO"] = "1"
os.environ["STUDYCLOUD_SECRET_KEY"] = "tests-only-secret-key-with-more-than-32-characters"

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.main import app


def register(client: TestClient, prefix: str = "student") -> tuple[dict[str, str], dict]:
    suffix = uuid.uuid4().hex[:8]
    response = client.post(
        "/api/auth/register",
        json={
            "username": f"{prefix}_{suffix}",
            "email": f"{prefix}_{suffix}@example.com",
            "full_name": f"{prefix.title()} User",
            "password": "Correct-Horse-42",
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    return {"Authorization": f"Bearer {payload['access_token']}"}, payload["user"]


def upload_text(client: TestClient, headers: dict[str, str], name: str = "photosynthesis.txt") -> dict:
    text = (
        "Photosynthesis converts light energy into chemical energy inside chloroplasts. "
        "Chlorophyll absorbs light while the light-dependent reactions produce ATP and NADPH. "
        "The Calvin cycle uses ATP and NADPH to fix carbon dioxide into sugars. "
        "Stomata regulate gas exchange and influence the rate of photosynthesis. "
        "Temperature, light intensity, and carbon dioxide concentration can limit the process. "
        "Plants balance carbon fixation with water loss under changing environmental conditions."
    )
    response = client.post(
        "/api/lectures",
        headers=headers,
        files={"file": (name, text.encode(), "text/plain")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_health_auth_and_swagger_security():
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["version"] == "2.1.0"
        assert "PPTX" in health.json()["formats"]
        assert client.get("/api/lectures").status_code == 401

        headers, user = register(client, "auth")
        profile = client.get("/api/auth/me", headers=headers)
        assert profile.status_code == 200
        assert profile.json()["id"] == user["id"]

        login = client.post(
            "/api/auth/login",
            json={"username": user["username"], "password": "Correct-Horse-42"},
        )
        assert login.status_code == 200
        assert login.json()["token_type"] == "bearer"
        assert client.post(
            "/api/auth/login",
            json={"username": user["username"], "password": "wrong-password"},
        ).status_code == 401

        swagger_login = client.post(
            "/api/auth/token",
            data={"username": user["username"], "password": "Correct-Horse-42"},
        )
        assert swagger_login.status_code == 200
        scheme = client.get("/openapi.json").json()["components"]["securitySchemes"]
        assert scheme["OAuth2PasswordBearer"]["flows"]["password"]["tokenUrl"] == "/api/auth/token"


def test_seeded_library_is_available_to_signed_in_users():
    with TestClient(app) as client:
        headers, _ = register(client, "library")
        lectures = client.get("/api/lectures", headers=headers).json()
        assert any(lecture["id"] == "demo-raft" for lecture in lectures)


def test_users_only_see_their_own_uploaded_materials():
    with TestClient(app) as client:
        first_headers, _ = register(client, "owner")
        second_headers, _ = register(client, "other")
        lecture = upload_text(client, first_headers, "private-notes.txt")

        first_ids = {item["id"] for item in client.get("/api/lectures", headers=first_headers).json()}
        second_ids = {item["id"] for item in client.get("/api/lectures", headers=second_headers).json()}
        assert lecture["id"] in first_ids
        assert lecture["id"] not in second_ids
        assert client.get(f"/api/lectures/{lecture['id']}", headers=second_headers).status_code == 404
        assert client.patch(
            "/api/lectures/demo-raft",
            headers=first_headers,
            json={"title": "Cannot edit public demo"},
        ).status_code == 404


def test_txt_upload_builds_full_study_pack():
    with TestClient(app) as client:
        headers, _ = register(client, "text")
        lecture = upload_text(client, headers)
        assert lecture["file_type"] == "TXT"
        assert len(lecture["quiz"]) >= 5
        assert len(lecture["flashcards"]) >= 3
        assert lecture["source_chunks"][0]["ref"].startswith("Section")


def test_html_and_csv_uploads_keep_source_locations():
    html = b"""<!doctype html><html><body><h1>Cell biology</h1><p>Cells contain organelles with specialized functions and membranes regulate transport.</p><p>Mitochondria generate ATP while ribosomes synthesize proteins from messenger RNA instructions.</p></body></html>"""
    csv_data = b"concept,definition\nNeuron,A specialized cell that transmits electrical and chemical signals through the nervous system\nSynapse,A junction where one neuron communicates with another cell using neurotransmitters\nMyelin,An insulating layer that increases the speed of signal transmission along an axon\n"
    with TestClient(app) as client:
        headers, _ = register(client, "formats")
        html_response = client.post("/api/lectures", headers=headers, files={"file": ("biology.html", html, "text/html")})
        assert html_response.status_code == 201
        assert html_response.json()["file_type"] == "HTML"
        assert html_response.json()["source_chunks"][0]["ref"].startswith("Section")

        csv_response = client.post("/api/lectures", headers=headers, files={"file": ("neuroscience.csv", csv_data, "text/csv")})
        assert csv_response.status_code == 201
        assert csv_response.json()["file_type"] == "CSV"
        assert csv_response.json()["source_chunks"][0]["ref"].startswith("Row")


def test_epub_upload_extracts_chapters():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "OEBPS/chapter1.xhtml",
            "<html><body><h1>Distributed systems</h1><p>A consensus protocol coordinates independent nodes despite delays and failures.</p><p>Quorum decisions prevent isolated minorities from committing conflicting state transitions.</p></body></html>",
        )
    with TestClient(app) as client:
        headers, _ = register(client, "epub")
        response = client.post(
            "/api/lectures",
            headers=headers,
            files={"file": ("consensus.epub", buffer.getvalue(), "application/epub+zip")},
        )
        assert response.status_code == 201
        assert response.json()["file_type"] == "EPUB"
        assert response.json()["source_chunks"][0]["ref"] == "Chapter 1"


def test_grounded_question_returns_sources():
    with TestClient(app) as client:
        headers, _ = register(client, "questions")
        response = client.post(
            "/api/lectures/demo-raft/ask",
            headers=headers,
            json={"question": "Why are randomized election timeouts useful?"},
        )
        assert response.status_code == 200
        assert response.json()["answer"]
        assert response.json()["sources"][0]["ref"].startswith("Page")


def test_wrong_answers_create_user_specific_proofloop_debts_and_reviews():
    with TestClient(app) as client:
        first_headers, _ = register(client, "quiz_a")
        second_headers, _ = register(client, "quiz_b")
        lecture = client.get("/api/lectures/demo-raft", headers=first_headers).json()
        result = client.post(
            "/api/lectures/demo-raft/quiz",
            headers=first_headers,
            json={"answers": [-1] * len(lecture["quiz"]), "confidences": [100] * len(lecture["quiz"])},
        )
        assert result.status_code == 200
        assert result.json()["score"] == 0
        assert result.json()["knowledge_gaps"]
        assert result.json()["blind_spots"]
        radar = client.get("/api/radar", headers=first_headers).json()
        assert radar[0]["mistakes"] >= 1
        assert radar[0]["is_blind_spot"] is True
        assert client.get("/api/radar", headers=second_headers).json() == []
        reviewed = client.post(
            f"/api/radar/{radar[0]['id']}/review",
            headers=first_headers,
            json={"remembered": True},
        )
        assert reviewed.status_code == 200
        assert reviewed.json()["successes"] >= 1


def test_export_feynman_and_owned_pack_edit():
    with TestClient(app) as client:
        headers, _ = register(client, "tools")
        export = client.get("/api/lectures/demo-raft/export", headers=headers)
        assert export.status_code == 200
        assert "## Flashcards" in export.text
        assert "Source:" in export.text

        defense = client.post(
            "/api/lectures/demo-raft/defend",
            headers=headers,
            json={
                "explanation": "Raft coordinates servers and uses a leader to keep a replicated log consistent.",
                "confidence": 100,
            },
        )
        assert defense.status_code == 200
        assert defense.json()["missing"]
        assert defense.json()["blind_spots"]

        lecture = upload_text(client, headers, "editable.txt")
        updated = client.patch(
            f"/api/lectures/{lecture['id']}",
            headers=headers,
            json={
                "title": "Photosynthesis Lab",
                "summary": "A revised summary about energy conversion and carbon fixation in plants.",
                "key_ideas": ["Light reactions", "Calvin cycle", "Gas exchange"],
            },
        )
        assert updated.status_code == 200
        assert updated.json()["title"] == "Photosynthesis Lab"


def test_pwa_assets_and_auth_ui_are_available():
    with TestClient(app) as client:
        assert client.get("/static/manifest.webmanifest").status_code == 200
        assert client.get("/static/i18n.js").status_code == 200
        shell = client.get("/").text
        assert 'id="login-form"' in shell
        assert 'id="register-form"' in shell
        assert 'id="language-select"' in shell
        assert 'id="voice-ask"' in shell
        service_worker = client.get("/sw.js")
        assert service_worker.status_code == 200
        assert service_worker.headers["service-worker-allowed"] == "/"


def test_rejects_unsupported_and_blank_pdf():
    with TestClient(app) as client:
        headers, _ = register(client, "invalid")
        unsupported = client.post(
            "/api/lectures",
            headers=headers,
            files={"file": ("notes.exe", b"hello", "application/octet-stream")},
        )
        assert unsupported.status_code == 415

        buffer = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=300)
        writer.write(buffer)
        blank_pdf = client.post(
            "/api/lectures",
            headers=headers,
            files={"file": ("blank.pdf", buffer.getvalue(), "application/pdf")},
        )
        assert blank_pdf.status_code == 422
