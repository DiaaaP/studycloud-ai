# StudyCloud product roadmap

## Implemented in 2.0

- PDF, PPTX, DOCX, EPUB, HTML, CSV, SRT, VTT, TXT, and Markdown ingestion up to 25 MB.
- Source-aware extraction by page, slide, paragraph, table, chapter, row, subtitle cue, or text section.
- Summaries, key ideas, 5-7 quiz questions, and flashcards.
- Grounded Q&A that returns evidence excerpts from the uploaded material.
- Markdown study-pack export.
- ProofLoop knowledge radar: quiz errors become source-linked knowledge debts.
- BlindSpot Detector: every quiz answer records confidence and prioritizes confident mistakes.
- Feynman Defense: scores a learner's explanation against source-derived concepts and exposes confident omissions.
- Adaptive review intervals with “Again” and “Got it” recall feedback.
- Human-in-the-loop editing for generated study packs and live library search.
- English, Russian, and Kazakh interface localization with persisted language selection.
- Language-aware browser dictation for grounded questions and Feynman explanations.
- Original-source access and safe lecture deletion with cascading study-history cleanup.
- Installable PWA shell with network-first caching and offline navigation.
- SQLite persistence, responsive UI, API documentation, automated tests, Docker, and CI.
- Optional Gemini generation with a local offline fallback.

## Implemented in 2.1

- Registration and login with Argon2 password hashing.
- Expiring JWT Bearer tokens for the browser and API clients.
- OAuth2 password flow integrated with Swagger's Authorize button.
- Per-user ownership for lectures, quiz attempts, confidence traps, and ProofLoop review history.
- Automatic first-account migration of existing local materials and progress.
- Dedicated multilingual sign-in/registration UI and profile/logout menu.

## What still separates a local product from a production SaaS

1. Cloud object storage and a managed database.
2. OCR for scanned documents and images.
3. Background processing for large uploads.
4. Email verification, password reset, sessions/devices, and optional social login.
5. Billing, quotas, moderation, observability, backups, and abuse protection.
6. Mobile push/email reminders and shared courses.
7. Formal evaluation of summary accuracy and quiz quality.

## Recommended production sequence

1. Move uploads to S3-compatible storage and SQLite records to PostgreSQL.
2. Add email verification, password reset, refresh-token rotation, and session revocation.
3. Run extraction and AI generation in a durable job queue.
4. Add OCR as an explicit fallback with page-level confidence.
5. Add automated evaluations before enabling paid plans.
6. Deploy behind HTTPS with rate limiting and encrypted backups.

