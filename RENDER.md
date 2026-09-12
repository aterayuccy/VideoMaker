# Render deployment

Deploy `render.yaml` as a Blueprint from `aterayuccy/VideoMaker`, branch
`codex/video-workflow-updates`. The repository Dockerfile builds the React UI,
installs FFmpeg and Chinese fonts, collects static assets, and applies Django
migrations before starting Gunicorn. No Railway database is required.

The default Blueprint is a **free preview**, using SQLite and local media.
Render deletes local changes on restart, redeploy, or idle spin-down. Download
finished videos immediately; saved works are temporary. Free compute may be
insufficient for large video compositions. Existing Railway data is not migrated.

Render generates `DJANGO_SECRET_KEY`; the app trusts the exact hostname supplied
by `RENDER_EXTERNAL_HOSTNAME`. Add `PIXABAY_API_KEY` as a secret in Render to use
Pixabay search. Do not put secrets in the repository.

After deployment verify `/api/health/`, `/new-task`, `/works`, and a short video
composition. Use the same browser to access saved works. A new domain creates a
new browser workspace; old account works are not automatically reassigned.

## Persistent storage (paid, optional)

Before retaining real work, choose an appropriate paid web instance and attach
a persistent disk at `/var/data`. Set `SQLITE_PATH=/var/data/db.sqlite3` and
`MEDIA_ROOT=/var/data/media`. Keep one service instance for this SQLite setup.
Configure this before saving work; changing paths does not migrate old files.
Back up both the database and media. A managed database plus object storage is
needed to scale beyond a single instance.

References:
- https://render.com/docs/blueprint-spec
- https://render.com/docs/free
- https://render.com/docs/disks
