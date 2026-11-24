# DynamoDB model for the current StudyCloud features

One on-demand table stores account and learning records. Keys below are logical examples; backend integration should centralize key construction so every endpoint uses the same rules.

| Record | Partition key (`PK`) | Sort key (`SK`) | Stored data |
|---|---|---|---|
| User profile | `USER#<userId>` | `PROFILE` | username, email, display name, password hash, active state, created time |
| Username lookup | `LOGIN#USERNAME#<sha256(normalizedUsername)>` | `OWNER` | user ID |
| Email lookup | `LOGIN#EMAIL#<sha256(normalizedEmail)>` | `OWNER` | user ID |
| Lecture | `USER#<userId>` | `LECTURE#<lectureId>` | title, original filename, type, timestamps, status, summary, ideas, quiz, flashcards, storage keys |
| Quiz attempt | `USER#<userId>` | `ATTEMPT#<createdAt>#<attemptId>` | lecture ID, score, answers, confidence values |
| Knowledge gap/review | `USER#<userId>` | `GAP#<lectureId>#<conceptHash>` | mistakes, successes, evidence, source ref, next review, confidence-trap state |

The username and email lookup records let sign-in fetch the profile without a scan. Registration writes the profile and both lookup records using a conditional transaction so duplicate names/emails are rejected safely. Normalize lookup values consistently and hash them before placing them in keys; keep actual profile values in the profile item.

The authenticated user ID from the JWT determines the user partition key. A lecture endpoint must fetch `PK=USER#<token subject>`, `SK=LECTURE#<requested id>`; it must never accept a user ID supplied by the browser as proof of ownership. To list a user's lectures, attempts, or review records, query that partition with `begins_with(SK, ...)`. The expected semester dataset is small enough for the API to sort review/history results in memory; a larger product would add purpose-built indexes.

Store the original document at `uploads/<userId>/<lectureId>/<safe-extension>` and extracted text/source chunks at `extracted/<userId>/<lectureId>/content.json`. Keep both objects private. The lecture item stores these keys and status. Do not put full extracted documents in DynamoDB; item size is limited. Keep bounded summaries, quiz content, and flashcards in the lecture record, with a size check before writing.

The S3 worker must be idempotent because object notifications can be delivered more than once. It updates the lecture's `UPLOADED -> PROCESSING -> READY|FAILED` status with conditional writes, writes extracted output to the key for that same lecture, and records a safe error code/message on failure. The API returns current status so the frontend can continue the established upload flow while processing runs.

Lecture deletion spans S3 and DynamoDB, so it cannot be one atomic AWS transaction. The API should verify ownership, delete the source/extracted objects and all `ATTEMPT#`/`GAP#` records referencing that lecture, and make retries safe if one part fails. The lecture must not be reported as successfully deleted while its private source remains accessible.

This data model deliberately has no secondary index: all core records are scoped to one user, and exact account lookups use deterministic partition keys. If backend query analysis shows a required cross-user lookup, add only the index needed for that query before deployment.
