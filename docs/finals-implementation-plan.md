# Sahaj finals implementation and verification plan

**Status:** The policy PDF library, selected-file RAG, reimbursement draft and loan draft are implemented. Section 9 records verification and the remaining live rehearsal.

**Branch:** `feat/finals-document-journeys`, forked from `feat/web-frontend` at `ffb803e`, which includes `origin/feat/enhance-ai` at `cc7504f`. The frontend branch advanced to `1dcdd1b` during implementation. Review the two commits and the active frontend work before integrating the finals changes.

**Demo outcome:** A customer asks in Kannada about reimbursement, uploads fictional claim documents, fixes a missing prescription, reviews the filled draft, and gets a simulated receipt. A judge then uploads an official insurer PDF, asks a question, and opens its exact source page. A short loan application is the final extension.

## 1. Starting point and build sequence

| Area | Already in the merged branch | Added in this worktree |
| --- | --- | --- |
| Voice and UI | Sarvam speech, authenticated PWA, consent, cards, sheets, citation excerpts | Workflow entry points, file and draft states, page links, regression checks |
| RAG | OpenAI embeddings in pgvector, Markdown auto-ingestion, English query rewrite, public and private retrieval, answer checks, optional Firecrawl | Explicit document scope, safe responses with no evidence, citation source metadata, two-policy verification scenario |
| Documents | Authenticated file storage, document-analysis consent, PDF text extraction, Sarvam OCR, background indexing and status | PDF library controls for the selected source and structured claim/payslip fields isolated from policy search |
| Operations | `/health` for liveness, `/ready` with storage and KB detail, usage and audit traces | Rehearsal procedure, index coverage feedback and a clear no-evidence reply |
| Lending | EMI and prepayment calculator and optional financial-provider endpoints | A self-contained application draft using a published illustrative offer. No live provider call in the demo path. |

Build and verify one step at a time:

1. Confirm the merged PWA and backend start in isolation.
2. Make the document answer path fail closed and bind it to a selected source.
3. Finish the reimbursement claim workflow.
4. Expose live policy upload and original-page citations in the PWA.
5. Extend the shared draft workflow to lending.
6. Run the automated checks, rehearse the entire demo, and record the outcomes.

Run the claim and live upload first. Present the optional loan draft if time permits.

## 2. Stabilize the demo baseline

**Implementation:** Check the fresh checkout, the PWA start screen, Google sign-in, conversation consent, first voice turn, and reconnect. The old Chrome blank screen was caused by an effect returning a scroll promise. The merged timeline uses a block-bodied scroll effect. Verify that behavior on this branch and fix any reproducible regression. Keep `/health` as liveness and use the existing `/ready` response for dependency checks. Its top-level `status` alone does not establish RAG or upload readiness. Review the web proxy and PWA navigation exclusions when adding routes.

**Exit check:** A fresh Chrome session opens without a console exception. The intended demonstration phone signs in over HTTPS, records and plays two turns, and handles a reconnect. With the index populated, one known RAG question produces a real citation. With search unavailable, the UI reports that state and a customer can still use an existing draft.

## 3. Make policy answers dependable

**Files to start from:** [orchestrator graph](../apps/api/orchestrator/graph.py), [retrieval](../apps/api/rag/retrieve.py), [private document index](../apps/api/storage/index.py), [citation serializer](../apps/api/orchestrator/citations.py), [session](../apps/api/orchestrator/session.py), and [shared voice contract](../packages/contracts/src/voice.ts).

1. Add explicit source selection to the conversation. The client sends a document ID and the server acknowledges the source or returns an actionable error. On selection and retrieval, verify identity, tenant, ownership, active document-analysis consent, and readiness. Offer a visible way to clear or change selection. Restore it only after revalidation on reconnect.
2. In selected-source mode, search only that file and version. Keep the built-in knowledge base, other personal documents and Firecrawl out of the answer evidence for that mode. Preserve normal general chat outside it. Include active source IDs and evidence revisions in any cache used for selected sources, or bypass the answer cache for user documents as the existing code does.
3. Short-circuit selected-source questions with zero eligible passages to an explicit localized no-evidence reply. Avoid an answer-generation call for known-empty results. Preserve general web fallback where the app already offers it and clearly label its web sources. An explicit source selection, expired consent, deletion, and indexing failure must never silently widen retrieval.
4. Carry file ID, original PDF page index, excerpt and optional version or clause from retrieval through the existing answer event. Keep legacy text-only citations compatible. Keep document text in an evidence-only context. Validate that factual document answers carry a supported citation; preserve explicit no-evidence responses and valid non-RAG reply types. The PDF link is constructed from server metadata rather than model output.
5. Rehearse the expected source and exact page in English, Kannada and Hindi. Tune ranking or the similarity threshold only after collecting reproducible misses from the live providers.

**Exit check:** The same question returns different correct results for two selected policies. An unrelated question and a customer-specific payout question lacking evidence receive an honest refusal. If the file is deleted or consent is withdrawn, the next question cannot cite it. The frontend displays the document and page used for an accepted answer.

## 4. Build the reimbursement claim

**Scope:** One Star Health reimbursement scenario. The demo checklist covers a subset of the insurer's requirements. A simulated receipt confirms that Sahaj saved the draft locally.

**Implementation steps:**

1. **Prepare a claim** is available on the welcome screen and in the menu. The attachment list, checklist, editable fields and receipt use the existing `Sheet`, buttons and light/dark tokens.
2. Add a tenant- and user-owned draft store in Postgres. Use the repo’s tenant registration and row-level security and additionally filter every draft read and write by authenticated user. Keep claim uploads out of the general document search and memory paths. Reuse file type validation, private storage, consent and the OCR adapter through a dedicated draft attachment flow. If consent is revoked, invalidate access and follow the repository's erasure pattern for stored draft attachments and extracted fields.
3. The attachment request reads PDF text or calls Sarvam OCR for images and scanned PDFs. The sheet shows “Reading document…” while it waits. It saves the attachment type and suggested fields after extraction and shows a retryable error if reading fails. The first demo uses the labeled English fixtures.
4. Apply the checklist in backend code. A discharge summary and hospital bill are required for the demo. Including a pharmacy bill adds a prescription requirement. Missing items, unprocessed files, unresolved mismatches and invalid required fields block confirmation. When a user changes a field or attachment, invalidate the previous confirmation.
5. Save draft and review state independently of the live voice connection. Submission requires confirmation of the current revision. Use an idempotency key or equivalent atomic write so retrying returns the same reference. Provide a simulated receipt with a timestamp and reference. Never call the real financial-provider endpoints from this path.

**API:** `GET/POST /drafts`, `GET /drafts/{id}`, `POST /drafts/{id}/attachments`, `GET/DELETE /drafts/{id}/attachments/{attachment_id}`, `PATCH /drafts/{id}/review`, and `POST /drafts/{id}/submit`. Draft state and attachments are stored in Postgres. The API and app shell keep responses private and out of cache.

**Exit check:** Actual PNGs populate visible fields, a missing prescription blocks submission, adding it clears that blocker, refresh retains the draft, and double submission yields one receipt. A second user in the same tenant and a user in a different tenant cannot retrieve the draft or its files.

[Star Health claims checklist](https://www.starhealth.in/claims/#claim-process) · [Star Health blank reimbursement form](https://d28c6jni2fmamz.cloudfront.net/CLAIMFORM_89ec9742bd.pdf)

## 5. Expose live PDF ingestion

Build this on the scoped RAG path from step 3 and the authenticated upload/index functions already on the branch.

1. Open **Policy documents** from the welcome screen or menu. The list shows the original filename, indexing status, passage count and known page coverage. Choose **Ask about this policy** once indexing finishes.
2. For the finals, load official public PDFs into the signed-in demo account’s document collection. This keeps the live upload behind existing authentication and separate from the Markdown index. A tenant-wide or platform-wide policy catalog can follow as an operator workflow.
3. Coverage counts pages represented by at least one saved passage. The current defaults cap extraction at 60 PDF pages and indexing at 200 passages. For the full HDFC PDF, set `DOC_MAX_PAGES=100` and `DOC_MAX_CHUNKS=500` before starting the API, then inspect the coverage shown after upload.
4. Extend the citation sheet with the exact excerpt, document title and **Open PDF on page N**. Read the original using an authenticated file request. Avoid putting bearer tokens in links. If the phone’s PDF viewer ignores a page fragment, keep the cited page number visible and rehearse an in-app or manual page fallback.

**Exit check:** The held-back PDF goes from upload to ready on screen. The user selects it, receives a scoped answer and opens the supporting page. Legacy Markdown ingestion leaves uploaded-file passages intact. A failed or partial index never appears as a fully indexed policy.

## 6. Extend the draft workflow to a loan

1. Reuse the claim draft data model, owner access, attachment state, review and simulated receipt with loan-specific fields. Keep the real provider integration intact and separate.
2. Add a **Loan costs** card from an official or organizer-approved offer source. The RBI worked example lists ₹20,000 principal, ₹400 charges deducted up front, ₹19,600 received, ₹23,274 total repayment, 24 months and 17.07% APR. Present the monthly illustration as about ₹970 and preserve RBI’s rounding note. Avoid recomputing the published total from the rounded monthly amount.
3. Open **Prepare a loan application** in the menu and click **Start draft**. The draft reads applicant name, employer and net pay from a fictional payslip. Enter the loan purpose, review and submit a simulated application. The illustrative cost card uses the same figures for every draft.
4. Keep the existing EMI calculator available without starting an application. Use the current loan card styles and shared review sheet.

**Exit check:** The financial figures match the linked source. Uploading a different payslip changes proposed fields. A failed upload leaves the offer and saved draft available. A completed review returns a clearly simulated reference.

[RBI worked example and repayment schedule](https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=12987#:~:text=Illustration%20for%20computation%20of%20APR)

## 7. Run checks locally after implementation

### Isolated setup

Run from this worktree. Use a separate database and bucket to avoid reading or changing another branch’s rehearsal data. The following starts a disposable pgvector instance. Choose a different name or port if already in use.

```sh
git branch --show-current
pnpm install --frozen-lockfile

docker run --rm -d --name sahaj-finals-db \
  -p 127.0.0.1:55441:5432 \
  -e POSTGRES_USER=sahaj -e POSTGRES_PASSWORD=local-demo-only \
  -e POSTGRES_DB=sahaj_finals pgvector/pgvector:pg18

cd apps/api
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
test -f .env.local || cp .env.example .env.local
```

Set `DATABASE_URL=postgresql://sahaj:local-demo-only@127.0.0.1:55441/sahaj_finals` and `PUBLIC_API_URL=http://127.0.0.1:5177` in the worktree's `apps/api/.env.local`. For a phone rehearsal, use the actual HTTPS URL as `PUBLIC_API_URL`. Fill in a local JWT secret and the team's approved OpenAI, Sarvam and Google client settings. Keep provider keys out of Git. OpenAI embeddings are required for the live index. Sarvam speech and the OCR adapter are needed to rehearse the corresponding live paths.

For uploads, set `AWS_S3_BUCKET` to a dedicated rehearsal bucket. For local MinIO, the repo has a `storage` Compose profile. On a free port use `docker compose --profile storage up -d minio minio-init` from the root. Set `AWS_S3_BUCKET=sahaj-local`, `AWS_ENDPOINT_URL=http://127.0.0.1:9000`, and the local S3 credentials from that Compose service. Use a dedicated bucket instead if it is already shared by the other checkout. Confirm setup against the [API environment example](../apps/api/.env.example) and [deployment guide](deployment.md).

In one terminal from the worktree:

```sh
cd apps/api
source .venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8101
```

In a second terminal from the worktree:

```sh
curl -fsS http://127.0.0.1:8101/ready
SAHAJ_API_URL=http://127.0.0.1:8101 pnpm --filter @sahaj/web exec vite --host 127.0.0.1 --port 5177
```

Check that `knowledge_base.ok` is true with a nonzero clause count, storage reports `ok` for uploads, and the Google client is configured. Use the app's exact origin in the Google OAuth allowlist. The local `/test/` console and `POST /auth/dev` can exercise backend endpoints with `ENVIRONMENT=development`, `TEST_PAGE=true` and `DEV_LOGIN=true` on loopback. The PWA uses Google sign-in. Keep development sign-in off on a hosted or tunneled demo. Use the actual HTTPS URL for the phone rehearsal.

### Automated acceptance checks

From the worktree root, run `pnpm typecheck` and `pnpm build`. Then activate the API venv and point **both** test DB variables at a disposable test database. Example using the disposable container above:

```sh
cd apps/api
source .venv/bin/activate
export TEST_DATABASE_URL=postgresql://sahaj:local-demo-only@127.0.0.1:55441/sahaj_finals
export DATABASE_URL="$TEST_DATABASE_URL"
docker exec sahaj-finals-db psql -U sahaj -d sahaj_finals -c 'CREATE EXTENSION IF NOT EXISTS vector'
python -m pytest -q tests
```

Run database tests with the demo API stopped and use a fresh test database or reset fixture state before the live rehearsal. Some existing tests skip without `TEST_DATABASE_URL`. A skipped DB case does not verify isolation or persistence.

| Test | Pass condition |
| --- | --- |
| Scoped retrieval | Only passages from the selected document; correct version/page in the answer. General questions outside selected mode still work. |
| Empty or stale scope | No fabricated fact, no unwanted web fallback, explicit state for missing evidence, consent withdrawal and deleted source. |
| Upload and citation | Multipart PDF reaches an indexed state, expected page is retrievable, authenticated preview works, another user cannot open it. |
| OCR and prefill | Provider contract test uses mocked OCR. Live fixture rehearsal uses image bytes and verifies two known extracted values and editable provenance. |
| Claim state machine | Missing prescription blocks direct API submit. Wrong or unreadable files preserve the draft. Edits invalidate confirmation. Retrying submit returns the same reference. |
| Loan facts and draft | Offer numbers equal the fixture source, payslip extraction fills only application fields, user correction persists, existing EMI route still passes. |
| Browser and phone | Fresh sign-in, no blank screen, keyboard reachability, Kannada narration on HTTPS, new file upload, refresh and receipt. Check the core states in light and dark. |

Run `python -m pytest -q tests/test_finals_workflows.py` for the new API regressions. The existing `python tests/eval_retrieval.py` evaluates the seeded knowledge base. The selected-policy questions in the next section exercise newly uploaded PDFs through the PWA.

## 8. Judge demo and self-verification checklist

Prepare the [Star Comprehensive PDF](https://d28c6jni2fmamz.cloudfront.net/Policy_Star_Comprehensive_Insurance_Policy_V_21_3a414ab104.pdf), the [HDFC ERGO my:Optima Secure PDF](https://customer-portal-assets.hdfcergo.com/documents/PolicyWordings_myOptimaSecure-76673175551.pdf), and the [five fictional PNGs](../apps/api/tests/fixtures/finals/). Upload the Star policy and blank reimbursement form to the rehearsal account and hold the HDFC PDF for the live upload. Select the reimbursement form for the paperwork question and select the policy for the coverage-period question.

1. **Voice → policy.** On the phone, ask in Kannada what paperwork is needed. Show the answer and tap its source. Confirm the transcript and spoken reply match the question.
2. **Images → editable form.** Open **Prepare a claim** and choose **Start draft**. Upload `discharge.png`, `hospital.png` and `pharmacy.png`. Show the patient name Arjun Rao and hospital bill ₹28,400 in the prefilled form. Choose **Confirm details** to show that the prescription is required.
3. **Fix → receipt.** Add the prescription. Correct a field, save, refresh, then confirm and submit. Read the demo reference. If a retry is visible, show it returns the same receipt.
4. **Fresh PDF → a different answer.** Ask “How long after discharge can eligible expenses be covered?” against Star and open **PDF page 11**. The verified clause says up to **90 days**, subject to conditions. Upload HDFC live and wait for ready. Select it, ask the same question, and open **PDF page 13, section B.1.6**. The verified wording says up to **180 days**, subject to the policy schedule and applicable terms. Return to Star once to verify scope. These are expense coverage periods, not filing deadlines.
5. **Optional loan.** Open **Prepare a loan application**, start a draft, and show the RBI example. Upload `payslip.png` and verify ₹42,000 monthly net pay. Enter a purpose, confirm and submit the demo application.

| Question | Selected file | Expected evidence |
| --- | --- | --- |
| How long after discharge can eligible expenses be covered? | Star Comprehensive | Up to 90 days, subject to the policy wording. PDF page 11. |
| ಆಸ್ಪತ್ರೆಯಿಂದ ಬಿಡುಗಡೆಯಾದ ಬಳಿಕ ಅರ್ಹ ವೈದ್ಯಕೀಯ ವೆಚ್ಚಗಳಿಗೆ ಎಷ್ಟು ದಿನಗಳವರೆಗೆ ಕವರ್ ಸಿಗುತ್ತದೆ? | HDFC ERGO my:Optima Secure | Kannada reply conveying up to 180 days, with applicable terms. PDF page 13. |
| अस्पताल से छुट्टी के बाद पात्र खर्च कितने दिनों तक कवर होते हैं? | HDFC ERGO my:Optima Secure | Hindi reply conveying up to 180 days, with applicable terms. PDF page 13. |
| Has the insurer paid my reimbursement claim? | Either policy | Say the selected document provides insufficient evidence. No payout claim. |

Record the checked commit, browser or phone, fixture files, index time, citation pages and pass/fail for each step. If the OCR or voice provider is unavailable, show the failure state and use a labeled rehearsal recording where the event permits it.

## 9. Verification record

- The PWA uses the existing Sahaj sheet, button and color tokens. The new controls and draft fields use English labels. Document answers use the conversation's selected language.
- The web typecheck and production build passed. The targeted Postgres suite passed 19 tests covering PDF indexing, source scope, reconnect, claim and loan state, OCR contracts, consent withdrawal and ownership.
- The complete API run on a fresh pgvector database reported 446 passes and four failures. All four also occurred on the base commit. The consent test expects seven purposes where the API returns nine. A Redis test requires `fakeredis`. Two legacy RAG tests attempt writes that the test role's row-level security rejects.
- The mobile-width Chrome rehearsal passed against the Vite PWA, FastAPI routes, WebSocket and pgvector. It uploaded the two insurer PDFs, showed the missing prescription, reopened a saved correction and produced claim and loan demo references. It used loopback sign-in, memory blob storage and test implementations for OCR, embeddings, chat and grounding.
- At the demo page and passage limits, Star indexed 182 passages across 47 of 48 pages. HDFC indexed 243 passages across 69 of 69 pages. The browser displayed the Star and HDFC answers with links to PDF pages 11 and 13 respectively. Coverage indicates where the index has at least one passage.
- The live rehearsal still needs the team's Google sign-in, OpenAI embeddings, Sarvam OCR and voice, configured S3 storage and the HTTPS judging device. On that device check STT/TTS in Kannada, browser PDF page navigation and the held-back PDF from a fresh demo account.
