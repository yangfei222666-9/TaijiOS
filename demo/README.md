# TaijiOS Demo v0

Single-page experience shell for the TaijiOS task execution engine.

Submit a task, watch it execute in real-time via SSE, and inspect the evidence trace.

## Live demo

- Frontend: <https://demo-one-wheat-95.vercel.app>
- Backend API: <https://taijios-production.up.railway.app>

This demo runs real LLM-backed task execution (DeepSeek) with validation, guided retry, and self-heal. Not simulated data.

## What this is

A minimal demo that connects to 4 backend endpoints:

| Method | Endpoint | Purpose |
| ------ | -------- | ------- |
| POST | `/v1/tasks` | Submit a task |
| GET | `/v1/tasks/{id}` | Query status |
| GET | `/v1/tasks/{id}/stream` | SSE live updates |
| GET | `/v1/tasks/{id}/evidence` | Trace + evidence summary |

## What this is NOT

- No login / auth
- No multi-page routing
- No task history
- No permission system

This is Demo v0, not a product.

## Prerequisites

- Node.js 18+
- TaijiOS Gateway running on port 9200

## Known issue: exFAT drives

`npm install` and `next build` will fail on exFAT volumes (no symlink support).
Run on an NTFS partition instead.

## Quick start

```bash
# 1. Start the backend gateway (port 9200)
cd taijios-oss
python -m aios.gateway

# 2. In a separate terminal — install and run the demo
cd taijios-oss/demo
npm install
npm run dev
```

Open <http://localhost:3000>

## Deploy to public URL

### Backend → Railway

1. Go to [railway.app](https://railway.app), sign in with GitHub
2. New Project → Deploy from GitHub repo → select `taijios-oss`
3. Railway auto-detects Python and uses the `Procfile`
4. Set environment variables:
   - `TAIJIOS_GATEWAY_HOST=0.0.0.0`
   - `TAIJIOS_CORS_EXTRA=https://<your-vercel-domain>` (set after Vercel deploy)
5. Railway assigns a public URL (e.g. `taijios-oss-production.up.railway.app`)
6. Verify: `curl https://<railway-url>/health`

### Frontend → Vercel

1. Go to [vercel.com](https://vercel.com), sign up with GitHub
2. Import repo → select `taijios-oss`
3. Set root directory to `demo`
4. Set environment variable: `API_URL=https://<railway-url>`
5. Deploy
6. Copy the Vercel URL, go back to Railway and set `TAIJIOS_CORS_EXTRA=https://<vercel-url>`

### Verify end-to-end

1. Open the Vercel URL
2. Submit a task
3. Confirm SSE stream shows events
4. Confirm evidence summary appears

### Known deployment caveats

**Vercel SSE limitation**: Vercel Serverless Functions have a ~30s execution timeout on the Hobby plan. The `/v1/tasks/{id}/stream` SSE endpoint is proxied via Next.js rewrites (server-side), so long-running streams may be cut off. The current demo pipeline completes in under 1 second, so this is not a blocker for v0. If future pipelines take longer, consider:

- Upgrading to Vercel Pro (longer timeout)
- Having the frontend call the Railway backend directly (requires CORS)
- Switching to client-side polling via `GET /v1/tasks/{id}`

**Public API exposure**: The Task API endpoints on Railway are publicly accessible without authentication. This is acceptable for a demo with an in-memory simulation backend, but:

- Do NOT connect a real LLM provider with API keys on this deployment
- Do NOT store sensitive data in task messages
- Consider adding rate limiting before sharing the URL widely

## Acceptance criteria

1. Open the page
2. Submit a task
3. See status changes via SSE stream
4. See final result and evidence summary
