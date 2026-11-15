# @sahaj/console

The Sahaj console, served at `/app`: chat (voice and text), documents, privacy, offers and usage for customers; dashboard,
desk, users and campaigns for staff. The customer voice app is a separate package, `apps/web`, served at `/`.

```bash
pnpm install
pnpm dev:api                        # the API on :8000
pnpm --filter @sahaj/console dev    # http://localhost:5174/app/ (API calls are proxied)
pnpm --filter @sahaj/console build  # dist/, served by the API at /app in production
```
