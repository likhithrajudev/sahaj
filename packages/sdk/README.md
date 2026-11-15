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
console.log(await sahaj.financialProviders());
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

## Insurance and lending workflows

The client also exposes `searchWeb`, `calculateEmi`, `calculatePrepayment`, `financialInventory`, `setFinancialInventoryConsent`, `replaceFinancialInventory`, `deleteFinancialInventoryItem`, `files`, `uploadFile`, `downloadFile`, `deleteFile`, `checkCredit`, `loanOffers`, `applyForLoan`, `insuranceQuotes`, `purchaseInsurance`, and `financialEvents`. File uploads use `multipart/form-data`; only the signed-in owner's inventory and file content are returned. PDF, PNG and JPEG content can be indexed for questions after the separate document-analysis consent; office documents and UTF-8 text are parsed locally after the same consent.

The financial inventory is separate from lender integrations. After granting `financial_profile` consent, a person can use the typed `/inventory` shortcut or ask in plain language to track cards and EMIs. They review the parsed items and confirm saving. Only the last four card digits are permitted; full card numbers and security codes must not be entered. The API returns no inventory when consent is inactive and withdrawing that consent erases saved items.

Video KYC helpers are `setVideoKycConsent()`, `requestVideoKyc()`, `cases()`, `cancelCase()` and (for an executive/admin client) `scheduleVideoKyc()`. Sahaj records the request and schedules an appointment; an authorised official of the regulated provider must conduct and verify the session. Sahaj itself does not conduct or verify it.

The API requires versioned, explicit consent for bureau access and product requests, and requires an additional confirmation when an application or purchase is submitted. Loan offers require a recent credit-check event from the same provider. A CIBIL score is returned by an authorised bureau adapter; Sahaj does not calculate or simulate one.

These SDK methods call Sahaj's API. Actual credit checks, lender decisions, quotes and policy purchases require a separately installed, authorised server-side provider adapter; a TypeScript plugin registered in the host application cannot replace that partner integration. See [financial provider adapters](../../docs/financial-integrations.md). Until a partner adapter is configured, financial action endpoints return `503` rather than sample data.
