# @sahaj/sdk

Typed JavaScript and TypeScript client for the Sahaj API. The package has no runtime dependencies and can be installed with `npm install @sahaj/sdk` after it is published.

```ts
import { SahajClient } from "@sahaj/sdk";

const sahaj = new SahajClient({
  baseUrl: process.env.SAHAJ_API_URL!,
  tenantId: "your-tenant-id",
});

const session = await sahaj.signInWithGoogle(googleIdToken);
for await (const event of sahaj.chat({ type: "text", text: "Search for current health insurance platforms in India" })) {
  if (event.type === "assistant") console.log(event.text, event.citations);
}
console.log(await sahaj.usage());
```

`baseUrl` is the API origin, such as `https://api.example.com`; `tenantId` becomes `X-Tenant-ID`. Google sign-in uses the GIS ID-token flow and does not need a redirect URI. The SDK keeps returned tokens in memory; applications should decide where and how to persist them.

## Plugins

Plugins are installed and executed by the integrating application's server. Sahaj does not execute uploaded plugin code.

```ts
import { SahajClient, SahajPluginRegistry } from "@sahaj/sdk";

const registry = new SahajPluginRegistry();
const searchHostCatalogue = (query: string) =>
  fetch(`https://your-service.example/policies?q=${encodeURIComponent(query)}`).then((response) => response.json());

await registry.register({
  name: "policy-catalogue",
  version: "1.0.0",
  kind: "data-source",
  setup({ registerTool }) {
    registerTool({
      name: "find-policy",
      description: "Look up a policy in the host application's catalogue",
      inputSchema: { type: "object", properties: { query: { type: "string" } }, required: ["query"] },
      execute: ({ query }: { query: string }) => searchHostCatalogue(query),
    });
  },
}, sahaj);
```

Build the distributable with `pnpm --filter @sahaj/sdk build`. The package metadata is configured for public scoped npm publishing; publishing still requires an npm account with access to the `@sahaj` scope.
