# Verification record

12 API/integration regression tests passed in an isolated local database on 5 October 2026. JavaScript syntax and Python compilation checks also passed.

Covered:
- Authentication and CSRF checks on private routes.
- Existing content import and dynamic public rendering.
- Draft, publish, unpublish, revision, and stale-update behavior.
- Markdown/script sanitization and safe text editing.
- Video byte-range responses.
- Campaign eligibility, approval, duplicate-send prevention, and opt-out cancellation.
- Approval revocation after edits.
- Public research URL checks against private/reserved networks.
- Aggregate analytics storage and DNT exclusion.
- Compose idempotency.
- Read-only IMAP synchronization and duplicate protection using a test adapter.
- Branded multipart email and unsubscribe headers using a test SMTP adapter.
- Discovery creating drafts without sending using test search and inspection adapters.

No live email was sent and no real prospects were collected. SMTP, IMAP, AI, and search providers need end-to-end verification with the owner's accounts. No Docker daemon or browser-based visual test was available in this environment; the Docker deployment and responsive dashboard must be checked on the target VPS/browser before production use.

Run:

    pip install -r requirements-dev.txt
    python -m pytest -q

Tests use a temporary database and do not modify a deployed site's data. The test client currently emits a dependency deprecation warning; tests complete successfully.
