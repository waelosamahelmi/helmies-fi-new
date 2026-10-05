# Helmies Studio Desk

A private CMS, mailbox, analytics dashboard, and review-first AI outreach workspace for the existing Helmies website.

Start with **DEPLOYMENT.md**. This is a Docker-ready VPS application, not a static upload. The current ChatGPT Sites website is unchanged.

## Stack

Python 3.12, FastAPI, SQLite with WAL, semantic HTML/CSS/JavaScript admin, and the existing Three.js public website. One app instance / one worker. Persistent records are stored in a Docker volume, not browser local storage.

## Project

- `app/main.py`: authenticated API, public dynamic routes, scheduler.
- `app/core.py`: storage, password/session authentication, settings.
- `app/content.py`: first-start import, content rendering, safe Markdown.
- `app/integrations.py`: public website research, AI, SMTP and IMAP.
- `app/admin/`: responsive studio dashboard.
- `site/`: existing public website and maintained assets.
- `site-source/`: original static frontend source for reference.
- `scripts/`: administrator setup, consistent database backup, contact erasure.
- `tests/`: critical workflow and security regression checks.
- `.env.example`: connection settings without credentials.
- `compose.yml`, `compose.traefik.yml`: VPS deployment.

No real prospects, emails, API keys, passwords, or runtime database are included. Research and inbox schedules start disabled. Approval and explicit sending are required for campaigns. Connections must be configured and tested on the target VPS.
