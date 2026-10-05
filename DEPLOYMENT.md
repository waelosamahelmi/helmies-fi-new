# Helmies CMS — deploy on your VPS

This is a separate VPS application built around your current Helmies website. It does not change the version still running on ChatGPT Sites. The whole app must run on the VPS; uploading `site/` alone would omit the CMS, mailbox, analytics, and researcher.

## What is included

- The existing website and founder animation, with 12 imported journal articles.
- A private `/admin/` dashboard with password login, expiring sessions, and CSRF protection.
- Editable page text and journal drafts/publishing, with previous article versions.
- Dynamic public article pages, homepage journal cards, search index, sitemap, and metadata.
- IMAP inbox sync, SMTP compose/reply, local sent records, and optional provider Sent-folder copies.
- Aggregate website page-request analytics and campaign status counts.
- Public business website discovery with source URLs and technical observations.
- AI article and email drafts using a server-side Responses API integration.
- Two responsive email templates: Midnight and Daylight.
- Review, approval, send limits, duplicate prevention, unsubscribe, and do-not-contact records.

The researcher never sends email. Every campaign requires a review, approval, and explicit Send action. Scheduled discovery is initially disabled. External services need your credentials; none are included.

## 1. Put the project on the VPS

Extract `helmies-cms.zip`. Copy the `helmies-cms` directory to a new directory on your server, for example `/opt/helmies-cms`. Do not overwrite your n8n or Traefik folders.

You need Docker Engine and the Docker Compose plugin already installed. From the new project directory:

    cp .env.example .env
    chmod 600 .env

Edit `.env` privately on the server. At minimum, set:

    PUBLIC_URL=https://your-real-domain.fi

Use your actual public HTTPS origin without a trailing slash. The application uses it for canonical links, the sitemap, email links, and unsubscribe links. Do not use a temporary localhost address for production campaigns.

Secrets should remain in `.env` or your server's secret manager. Do not upload that file to GitHub or send passwords in chat. The Docker build excludes it from the image.

## 2. Start the app

    docker compose up -d --build
    docker compose ps
    docker compose exec helmies python scripts/admin.py

The last command prompts for your administrator email and a new password. No default account or password is provided. It also works later to reset the account password and revoke existing sessions.

For a basic health check on the VPS:

    curl http://127.0.0.1:8088/healthz

Expected result: `{"status":"ok"}`. The application binds its host port to loopback only. Expose it through your existing HTTPS reverse proxy, not directly to the internet.

## 3. Connect your existing Traefik

If you already use Docker-based Traefik, edit these values in `.env` to match its current configuration:

    SITE_HOST=your-real-domain.fi
    TRAEFIK_NETWORK=your-existing-docker-network
    TRAEFIK_ENTRYPOINT=your-existing-https-entrypoint
    TRAEFIK_CERT_RESOLVER=your-existing-certificate-resolver

The example names in `.env.example` are not guaranteed to match your server. Your Traefik container must share this external network. Then run:

    docker compose -f compose.yml -f compose.traefik.yml up -d --build

Use both `-f` files for subsequent deployment changes. Do not change the running Traefik service itself unless you know its current routing configuration. The Helmies override routes the specified hostname to internal port 8088.

Point the domain's DNS at the VPS as appropriate for your current DNS provider. Keep HTTPS enabled. If the chosen hostname already routes to your old site, prepare and test a staging subdomain first; then change the route deliberately. Only one Traefik router should own the same hostname and path combination.

If your certificate setup does not use a Traefik certificate resolver, remove that one label and apply your existing TLS method. Never share the same persistent SQLite volume between multiple running app replicas. Keep one Uvicorn worker: it owns the in-process scheduler and research lock.

### Other reverse proxies

Proxy all paths to `http://127.0.0.1:8088`, including `/admin/`, `/api/`, `/unsubscribe/`, public pages, and media. Do not serve bundled article HTML directly from `site/`, because that would bypass draft/unpublish controls. Allow up to 120 seconds for manual AI and mailbox operations. Preserve byte-range requests for the founder video. Set a request-body limit of 1 MB.

The app deliberately ignores forwarded IP headers and does not log access requests. Login rate limiting is per account plus the connected proxy address. Use your reverse proxy's own per-client rate limiting if needed, and make sure it overwrites rather than trusts caller-supplied forwarding headers. Do not turn on caching for `/admin/`, `/api/`, or `/unsubscribe/`.

## 4. Open the admin

Visit `https://your-real-domain.fi/admin/` and sign in with the account you created. The website pages and 12 journal articles are imported into the persistent database on first startup. Later restarts preserve your edits.

Use Journal to write in Markdown, save a draft, preview the saved version, and publish. A published post appears in the journal, homepage's recent articles, search, and sitemap. To remove it from the public site, set its status to Draft. Do not use this to retract sensitive data that was already public: old browser caches, search engines, or copies may still exist.

Website pages exposes text blocks from the existing design. Only changed blocks are replaced. Editing a block replaces its inline emphasis or links with plain text, so keep complex layouts in source where appropriate. Article history lets you load an earlier version as a draft; page revisions are stored for recovery in the database.

## 5. Connect email

Use a real mailbox with IMAP and SMTP access. For **Hostinger Email**, the documented defaults are:

    SMTP_HOST=smtp.hostinger.com
    SMTP_PORT=465
    SMTP_SECURITY=ssl
    IMAP_HOST=imap.hostinger.com
    IMAP_PORT=993
    MAIL_USERNAME=your-mailbox@your-domain.fi
    MAIL_FROM=your-mailbox@your-domain.fi
    MAIL_PASSWORD=your-mailbox-password

Hostinger Email is not the same product as Titan. If your mailbox is on Titan or another provider, use that provider's exact settings. For SMTP port 587 with STARTTLS, set `SMTP_SECURITY=starttls` and the correct port. Unencrypted SMTP is not used.

Optional: set `IMAP_SENT_FOLDER` to the exact existing sent-mail folder name if you want a copy in the provider mailbox. Leave it blank to keep sent records only in the CMS. Archiving failure does not retry a successfully submitted message.

After any `.env` change, recreate the app:

    docker compose up -d --force-recreate

With Traefik, include the same two `-f` arguments used above.

In the dashboard, open Mailbox > Sync inbox. First sync imports the latest 100 messages; later syncs fetch new messages in batches of 100. Messages are imported read-only and are not deleted or marked read on the provider. HTML is converted to text; remote tracking images are not loaded. Attachments are not imported. Messages above 3 MB are represented by a header and a note to view the original in your mailbox. Enable five-minute sync in Settings if desired.

Send a test to an address you control, then reply to it and sync. Confirm the From identity, reply handling, and Sent-folder behavior before sending business offers. Configure SPF, DKIM, and DMARC using the mailbox provider's DNS instructions. Check its acceptable-use policy and sending limits before outreach.

“Sent” means the SMTP server accepted the message, not that it reached the inbox or was read. If a send is marked uncertain, investigate with the provider before creating another send; automatic retry is intentionally disabled. Bounce handling and opt-out replies need manual review. Use “Stop campaigns to sender” or the do-not-contact form when a person asks you to stop by email.

## 6. Connect AI and research

Set the following on the server:

    OPENAI_API_KEY=your-api-project-key
    OPENAI_MODEL=a-model-available-to-your-project
    BRAVE_SEARCH_API_KEY=your-search-api-key

The AI integration uses the Responses API with `store:false` and JSON text output. Select a model that supports that API and JSON output. API billing is separate from a ChatGPT subscription. The key and model are configurable; no model access is assumed.

Research uses Brave Web Search and bounded requests to public websites. AI drafting sends the selected brief or prospect name, URL, and observations to the configured AI service; no mailbox-wide context is sent automatically. Review your data-processing arrangements before including confidential material. There is no live browsing tool or autonomous sending permission granted to the model.

Recreate the container, then confirm connection status in Settings. “Connected” means required configuration is present; validate actual access by generating a draft or running a research job. Provider failures are reported without displaying the keys.

## 7. Define the €1,000 offer and targeting

Open Settings:

1. Confirm your offer scope. The supplied starting draft is up to five pages, responsive design, supplied content, and one revision round, excluding hosting, maintenance, e-commerce, and custom integrations. Edit it to what you actually want to deliver.
2. Confirm the price and VAT wording. The package does not assume your tax treatment.
3. Enter your real business postal address and sender name.
4. Choose industries and locations in the search queries, one query per line.
5. Set up to 50 new candidates per discovery run and the daily hour in Europe/Helsinki.
6. Choose whether newly discovered contacts should get offer drafts automatically. AI is used when configured; otherwise a standard draft is prepared. Drafting failures leave the prospect available for manual drafting.
7. Start a manual discovery run and review its results before enabling the daily schedule.

Daily discovery runs in the app while it is running. If the app starts after the configured hour, it can run that day's job then. Failed or interrupted jobs are recorded; they are not silently retried the same day. Use Run discovery to retry after fixing the cause. Manual runs are separate from the scheduled run. Search API costs and website availability can limit results; 50 is a maximum target, not a guarantee.

The researcher checks homepage HTML for a small set of technical signals, such as missing viewport metadata or legacy presentational elements. It cannot reliably judge a visual design or prove that a site is old, losing revenue, or insecure. JavaScript-rendered sites may produce false positives. Open each candidate site for a visual review. Being static is not treated as a defect.

It reads only public homepage/contact pages, follows robots policy, blocks private-network addresses and unsafe redirects, caps page sizes, and skips previously stored domains. Emails are extracted only if actually present and on the business site's domain; it does not guess addresses or validate that a mailbox accepts delivery. Some valid businesses will have no contact found.

## 8. Review and send campaigns

Prospects > Review:

- Confirm the business and the recorded website observations.
- Verify the contact source and relevance.
- Record the applicable contact basis and jurisdiction before marking it eligible. A publicly listed email alone is not permission to market to it; national rules and individual versus corporate recipients matter.
- Save the review, then generate an AI draft or a standard draft.

Campaigns > Open:

- Review the copy and the exact package terms.
- Select Midnight or Daylight and preview the saved email.
- Save edits, approve the saved version, then explicitly send it.

Edits revoke approval. The sending check repeats eligibility and suppression checks, enforces a rolling 24-hour campaign cap, and records a single send attempt. The default cap is 10; you can set it up to 50 after confirming provider limits and contact eligibility. The daily discovery task does not send campaigns, even if drafts are approved.

Every campaign includes your identity, an unsubscribe link, and a plain-text alternative. Unsubscribe GET displays a confirmation to avoid accidental opt-outs from link scanners; POST confirms opt-out and supports one-click unsubscribe headers. Pending offers to that address are cancelled. This workflow helps implement review and opt-out, but does not certify legal eligibility or full GDPR compliance.

## 9. Analytics and privacy

The dashboard shows aggregate public page requests by day, path, referring hostname, and broad device type, plus campaign status counts. It does not track unique visitors, conversion funnels, email opens, or clicks. No analytics cookie, stored IP, full referring URL, or visitor identifier is used. Signed-in admin visits, recognized crawlers, and DNT/GPC requests are excluded. Counts can still include unidentified bots and omit offline-cached visits.

Analytics defaults to 90-day retention, configurable in Settings. Mail, campaign, and prospect records do not have an automatic deletion schedule; define your operational retention policy before production. Review the included privacy text, provider details, processing locations, and business contact information with your actual setup. Administrative cookies, mail copies, research records, and aggregate analytics are described in the VPS copy.

To erase a contact's app messages and research/campaign records after reviewing a request:

    docker compose exec helmies python scripts/maintenance.py erase-contact person@example.com

The command prompts before deletion and preserves a minimal exclusion record to prevent future campaigns. Check your provider mailbox and backups separately. This is not a blanket erase of every provider's data.

## 10. Backups and updates

All application records live in the named `helmies_data` Docker volume, in `/data/helmies.db`. Preserve this volume. Do not run `docker compose down -v` during ordinary updates.

Create a consistent snapshot:

    docker compose exec helmies python scripts/backup.py
    docker compose cp helmies:/data/helmies-backup.db ./helmies-backup.db

Move the snapshot to protected backup storage and include a separately protected copy of the deployment configuration. A database snapshot contains personal correspondence and prospect records. Do not commit it to GitHub. Test restoration on a separate staging instance before relying on the backup.

For restoration, stop the app, retain a backup of the existing volume, replace its database with the consistent snapshot using the same ownership (UID 10001), remove stale database WAL/SHM sidecars while no app process is running, and restart. Do not overwrite a running SQLite database.

For code updates, back up first, replace application code, and rebuild with the same Compose project/directory and volume. The first-start importer does not overwrite existing CMS records. This version uses an initial schema; future schema changes need explicit migrations.

The public frontend source is retained under `site-source/src/`. Runtime content edits belong in the CMS database. Rebuilding the original static templates does not overwrite the CMS database and can reintroduce old privacy copy if reimported; port intentional template changes carefully. Keep the files under `site/` because they contain maintained CSS, scripts, fonts, and media.

## Local development and verification

For a local-only preview, use `PUBLIC_URL=http://localhost:8088` and a dedicated `DATA_DIR`. With a virtual environment:

    python3 -m venv .venv
    . .venv/bin/activate
    pip install -r requirements-dev.txt
    export PUBLIC_URL=http://localhost:8088
    export DATA_DIR=./data
    python scripts/admin.py
    uvicorn app.main:app --host 127.0.0.1 --port 8088 --workers 1 --no-access-log

Open http://localhost:8088/admin/. Campaign sends require a public HTTPS origin and are blocked in this local mode. The SMTP and AI configuration is not automatically loaded by bare Uvicorn; use your shell environment or Docker Compose's env_file.

Run the included API tests with `python -m pytest -q`. They use an isolated temporary database and mocked sending. Live SMTP, IMAP, AI, search credentials, real browser layout, and your VPS routing still require end-to-end verification after configuration.

## Reference documentation

- Hostinger mailbox settings: https://www.hostinger.com/support/1575756-how-to-get-email-account-configuration-details-for-hostinger-email/
- Brave Web Search: https://api-dashboard.search.brave.com/api-reference/web/search/get
- OpenAI API: https://platform.openai.com/docs/api-reference/responses
- Individual data rights: https://commission.europa.eu/law/law-topic/data-protection/information-individuals_en
