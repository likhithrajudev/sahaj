# @sahaj/web

The Sahaj web app: chat (voice and text), documents, privacy, offers and usage for customers; dashboard, desk, users and campaigns for staff.

```bash
pnpm install
pnpm dev:api          # the API on :8000
pnpm --filter @sahaj/web dev   # http://localhost:5173/app/ (API calls are proxied)
pnpm --filter @sahaj/web build # dist/, served by the API at /app in production
```
