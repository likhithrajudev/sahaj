# Financial partner integrations

Sahaj exposes authenticated workflow endpoints for credit checks, loan offers and applications, insurance quotes and purchases. The endpoints require the relevant versioned consent, record the selected provider and action, and require a final user confirmation for submissions. A loan offer request also requires a fresh credit check from the same provider. Applicant identity, health and income fields are passed to the selected adapter for the request; Sahaj does not store those fields or the bureau score. It stores only a user-owned provider reference and status.

There are no partner modules configured in this checkout. The endpoints return `503 provider_unavailable` until a lender, insurer or credit-bureau integration is installed. A CIBIL score is a bureau response, not a score Sahaj can calculate from PAN, income or other user-entered fields. These endpoints do not mock a score, eligibility result, quote, approval, policy or payment. The test console cannot complete these workflows until an authorised partner module is configured.

## Install an adapter

Install the partner adapter package in the API environment, set its import path in `FINANCIAL_PROVIDER_MODULES` (comma-separated for multiple modules), and restart the API. Each module exports `register(register_provider)` and registers one or more objects with a lowercase `name`. The same provider object can implement any combination of these async methods:

| Method | Input | Required result |
|---|---|---|
| `credit_check(user, identity)` | Name, PAN, date of birth and mobile, supplied only for this request | `reference`, `score` (300–900 or `null`), optional `score_status` (`scored`, `NA`, `NH`, `unavailable`), `bureau`, `checked_at` |
| `loan_offers(user, request, credit_reference)` | Requested amount, tenure, purpose and the provider's own credit-check reference | `offers`: lender-provided offer objects. Include each lender's KFS URL and version, APR, fees and repayment terms. |
| `loan_apply(user, application)` | Selected `offer_id`, accepted `kfs_version`, and user-confirmed applicant fields | `reference`, `status` (`submitted`, `pending`, `approved`, `declined`) |
| `insurance_quotes(user, request)` | Selected product and user-submitted answers | `quotes`: quote objects with insurer, premium, frequency, terms URL and terms version |
| `insurance_purchase(user, purchase)` | Selected `quote_id` and user-accepted terms version | `reference`, `status` (`redirect_required`, `pending`, `issued`), optional HTTPS `checkout_url` |

Adapters should call only partner APIs approved for Sahaj's business relationship and the user's consent. They should preserve the provider's KFS, policy wording, payment and cancellation flow; use idempotency keys for submissions; never log applicant data; and return provider references instead of report contents. For loans, the selected lender remains responsible for eligibility, disclosure and the credit decision. Sahaj does not collect or route loan payments.

## Endpoints

- `GET /financial/providers` lists installed provider capabilities.
- `POST /financial/credit-check` requires the displayed `credit_bureau` consent version and `confirmed: true`. The response includes the user's score; the stored event contains only a provider reference and status.
- `POST /financial/loan/offers` requires a credit-check event belonging to this user, from the same provider, and no older than one day. It also requires `financial_application` consent.
- `POST /financial/loan/apply` requires the selected offer, the current KFS version, `kfs_accepted: true`, applicant fields and final confirmation.
- `POST /financial/insurance/quotes` requires `financial_application` consent and applicant answers.
- `POST /financial/insurance/purchase` requires the selected quote, accepted terms version and final confirmation. Checkout links must use HTTPS.
- `GET /financial/events` lists only the signed-in user's stored provider references and statuses.
- `POST /calculators/emi` and `POST /calculators/prepayment` are local reducing-balance estimates; they do not call a lender or affect a credit decision.

Consent text is a draft and needs compliance review before production. A TransUnion CIBIL score is not an approval decision. Its marketplace describes API-based consumer score/report delivery for partners and members, and CIBIL states that it acts on the end user's explicit consent; Sahaj must obtain its own applicable partner access and approval before enabling a real adapter.
