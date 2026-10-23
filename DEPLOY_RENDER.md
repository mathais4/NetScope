# Get a lasting NetScope live link

This package includes a root Dockerfile and render.yaml. Render builds the React
dashboard and serves it from FastAPI, so the dashboard, API, and WebSocket all use
one HTTPS address. No frontend URL or proxy configuration is needed.

## Cost

The Blueprint selects a paid web instance (0.5 CPU / 512 MB) and paid PostgreSQL
(0.1 CPU / 256 MB, 5 GB storage). Review Render's current total before deploying.
Hosting is billed while these resources exist. Keep the service and database
active and paid for the link to keep working. The free Render database expires
after 30 days and is not suitable for a lasting CV deployment.

## Upload to GitHub

1. Extract this ZIP.
2. On GitHub, create a new empty repository called `netscope` (or `netscope-live`
   if you already have one). Do not initialise it with a README.
3. Choose **uploading an existing file** on the empty repository screen.
4. Open the extracted folder. Drag ALL its contents into the GitHub upload area,
   including the `backend` and `frontend` folders, `Dockerfile`, and `render.yaml`.
   Do not drag the containing folder itself: render.yaml must be at the repository root.
5. Commit the uploaded files. Check that you can see render.yaml beside backend
   and frontend on the repository's main page.

## Deploy

1. Open https://dashboard.render.com and sign in with GitHub.
2. Click **New > Blueprint**.
3. Connect the repository you just uploaded. Authorise access if asked.
4. Use `main` as the branch and `render.yaml` as the Blueprint path.
5. Review the two resources and their paid plans. Create/deploy the Blueprint
   only if you accept the displayed charges.
6. Wait for `netscope-db` and `netscope` to finish deploying.
7. Open the `netscope` WEB SERVICE. Its page shows your HTTPS `onrender.com` URL.
8. Open that URL, then open the same URL followed by `/api/health`.
   The latter should show {"status":"ok"}.

Use the actual URL Render assigns on your CV. It works with your PC off.
The address is stable while you retain the service; it is not a temporary tunnel.

## What the hosted demo does

- Runs real HTTP and TCP checks and stores results in PostgreSQL.
- Streams results to the dashboard over WebSocket.
- Seeds public websites, its own health endpoint, and the PostgreSQL TCP port.
- Includes an explicitly labelled closed-port target to demonstrate an outage.
  This target SHOULD show Down after three failed checks.
- The public version is read-only: visitors can inspect charts and incidents,
  but cannot change/delete targets or probe arbitrary destinations.
- The original local Docker Compose version still supports editing and ping.
  The cloud seed avoids ICMP because hosted-container permissions vary.
- History starts when deployed and grows over time; it isn't fabricated.

Keep one app instance and one Uvicorn worker: each app runs its own scheduler.
Local data from another installation is not copied to this new database.

## Local run

Open Docker Desktop. In this directory run:

    docker compose up --build -d

Then open http://localhost:8080.
The local database is mapped to host port 5434 to avoid the earlier Windows
PostgreSQL port conflict. Container connections still use db:5432.

## Checks before publication

The package can be checked locally with:

    cd frontend
    npm install
    npm run typecheck
    npm run build

For backend tests install backend/requirements-dev.txt, then run pytest from
backend. Database integration tests require a disposable TEST_DATABASE_URL.
Deployment itself must still be verified in your Render account.

References: https://render.com/docs/infrastructure-as-code,
https://render.com/docs/blueprint-spec, https://render.com/docs/free
