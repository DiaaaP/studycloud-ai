# StudyCloud AWS infrastructure

This Terraform configuration deploys the StudyCloud semester environment. Local development continues to use SQLite; setting `STUDYCLOUD_STORAGE_BACKEND=aws` switches the integrated API to DynamoDB and S3. The Terraform resources are separate from the application code so the team can review the plan before creating the runtime stack.

## Target flow

```text
Browser -> API Gateway HTTPS -> FastAPI Lambda -> frontend + /api/*
Browser -> short-lived upload authorization -> private documents S3
S3 uploads event -> private-subnet worker Lambda -> S3 extracted text + DynamoDB status
API Lambda <-> DynamoDB + private S3 objects
```

The API Lambda stays outside the VPC so Gemini HTTPS calls do not require a NAT gateway. The existing FastAPI app serves `index.html`, `/static/*`, and `/sw.js` from the Lambda package, while API routes use `/api/*` on the same HTTPS API Gateway origin. This avoids a separate static hosting service and browser CORS between the app and its API. The worker runs in two private subnets with S3 and DynamoDB gateway endpoints and no internet route. The documents bucket remains private and allows browser uploads only from the API Gateway site origin. The DynamoDB table is on-demand and uses a single-table key model described in `DYNAMODB_MODEL.md`.

## Application integration included in this repository

- `backend/app/aws_store.py` provides AWS persistence while retaining SQLite locally.
- The API uses a Mangum Lambda entry point, private S3 upload/download flows, DynamoDB accounts and study progress, and Secrets Manager for runtime keys.
- The S3 event worker parses the app's supported document formats and records processing status; the existing study-material fallback remains available without a Gemini key.
- `infra/package-lambdas.ps1` creates Linux Python 3.12 ZIPs at the paths configured in Terraform.
- `infra/set-runtime-secret.ps1` creates a fresh JWT signing key and optionally accepts a Gemini API key without printing it or putting it in Terraform state.

## Acceptance target: complete core product, intentionally unpolished

The cloud version is ready when the established product flows still work with persistent AWS data:

- Register/sign in, keep each user's lectures and learning records isolated, and handle an expired/invalid session clearly.
- Upload every format supported by the existing app (PDF, PPTX, DOCX, TXT, Markdown, HTML, EPUB, CSV, SRT, and VTT), retain the original privately, parse it, and show completion or a useful processing failure.
- Preserve summaries, key ideas, quizzes, flashcards, source-grounded questions, Feynman Defense, confidence tracking, knowledge radar/review, history, study-pack export, source access, and lecture deletion.
- Keep records and source files after page reloads, API Lambda cold starts, and worker retries. Deleting a lecture removes its private objects and related learning records.
- Keep the current English/Russian/Kazakh frontend and PWA behavior. Keep the local extractive engine as the documented fallback when Gemini is unavailable or not configured.
- Handle expected operational failures (unsupported/empty file, unreadable/scanned file, parser error, unavailable Gemini, and expired login) with a recoverable message and no partial or cross-user data exposure.

This scope includes basic ownership checks and ordinary input limits. It does not require production-grade abuse prevention, elaborate moderation, or exhaustive handling of deliberately hostile traffic for the short project period.

## Initial data

The current repository seeds a built-in sample lecture in local SQLite. The AWS version must either seed an equivalent sample record and source object during setup or import the team's chosen starting data. Decide whether any developer-local users or uploads need migration; do not copy personal test files into the shared deployment by default.

## Next deployment steps

1. Install Terraform 1.6+ and configure AWS CLI profile `project` in the environment running Terraform.
2. From the repository root, run `./infra/package-lambdas.ps1` with Python and internet access available.
3. Review the Terraform plan. It adds API Gateway, two Lambda functions, a Secrets Manager secret, logging, and supporting IAM/configuration to the already-applied document S3 bucket, DynamoDB, and VPC foundation. It also removes the unused private frontend bucket and unused CloudFront policies created during the earlier attempt.
4. After reviewing the plan and expected charges, apply the runtime stack.
5. Set the runtime secret using the ARN from `terraform output -raw runtime_secret_arn`: `./infra/set-runtime-secret.ps1 -SecretArn <ARN>`.
6. Open `terraform output -raw website_url` (the API Gateway HTTPS endpoint) and exercise every established workflow end to end.
7. At the end of the semester, export any needed project data, empty the document bucket, destroy the semester stack, and verify no billable resources remain.

The scripts can be run from PowerShell. Keep `infra/terraform/terraform.tfstate` and all generated ZIPs private; never commit AWS state, runtime secrets, or uploaded documents.

Terraform state is local by default and must not be committed. Document-bucket deletion is intentionally protected by `force_destroy = false`; empty it only after the team confirms it no longer needs the stored files.
