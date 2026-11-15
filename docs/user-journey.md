# Sahaj: the user journey and how the application flows

This document describes Sahaj from the person's point of view first, then explains what happens behind each step. It is written for product, compliance, design and engineering readers alike. Where something is not built yet, it says so.

> **Sample data.** Every insurance plan, premium and loan offer in Sahaj today is **fictional sample data** (every plan name carries "(SAMPLE)"). The flows below are real; the products are placeholders until real insurer and lender data replaces them.

---

## 1. What Sahaj is

Sahaj is a **voice assistant for insurance and loans in India**. A person talks to it in their own language, and it talks back. It can:

| For insurance | For loans |
|---|---|
| Explain what a policy term means (waiting periods, exclusions, premiums, claims) | Explain what a loan offer says (fees, interest rate, prepayment, how to complain) |
| Explain the difference between kinds of insurance (for example term and whole life) | Work out an EMI, or the interest saved by paying part of a loan early |
| Compare plans side by side | Explain in general how loans work, and the kinds of loans |
| **Recommend plans**, but only after asking about the person's needs and confirming them | Say honestly when it *cannot* help (for example comparing banks' rates) |

At any point the person can **ask for a human**.

Sahaj is built to be trustworthy before it is clever: it answers only from approved documents, never invents a number, asks permission before using personal details, and keeps an audit trail.

---

## 2. The big picture

```
   Person                 Sahaj backend                                 Outside services
 ┌────────┐         ┌──────────────────────────────────────────┐
 │  App   │  voice  │  1. Hear      speech → text   ───────────┼──►  Sarvam (speech to text)
 │ (mic + │ ──────► │  2. Protect   mask personal identifiers  │
 │speaker)│         │  3. Decide    work out what they want    │
 │        │         │  4. Answer    find the right documents,  │──►  Sarvam (language model)
 │        │ ◄────── │               write a reply              │
 │        │  voice  │  5. Check     is every claim backed up?  │
 │        │  + cards│  6. Speak     text → speech   ───────────┼──►  Sarvam (text to speech)
 └────────┘         │  7. Record    audit trail (no personal   │
                    │               answers)                   │
                    └───────┬──────────────────────┬───────────┘
                            │                      │
                     Postgres + pgvector      Audit ledger
                     (approved documents)     (consent, turns, handoffs)
```

The app and the backend talk over one **WebSocket** connection that stays open for the whole conversation. The person presses a button to talk (**push-to-talk**), speaks for up to 30 seconds, and releases. Sahaj replies with text, sometimes a card (a table or recommendation), and speech.

---

## 3. A person's journey, step by step

### Step 1: Opening the app

The app connects. Sahaj creates a **session**, a private conversation with its own reference number. Nothing is processed yet.

### Step 2: Giving permission to talk

Before Sahaj listens to anything, the person sees a short consent message and must tap **agree**. It says, in plain words, that Sahaj will process their voice and what they share to answer questions, that personal identifiers like PAN and Aadhaar are masked, that a record is kept for audit, and that they can withdraw at any time.

- **Agree:** the conversation starts.
- **Decline:** nothing is processed. They can change their mind later.

Every consent is written to a tamper-evident ledger with the exact wording they saw.

### Step 3: Talking

The person holds the talk button, speaks, and lets go. They see what Sahaj heard ("You: ...") and then Sahaj's reply, which is also spoken aloud. Answers about policies and loans show **source tags** (like `[concepts-insurance-basics:4.3]`) so the answer can be traced to a specific clause. The tags are shown on screen but never read aloud.

### Step 4: Getting what they came for

What happens next depends on what they ask. The sections below follow the main journeys.

### Step 5: Finishing or getting a person

They can close the app, withdraw consent, or ask for a human at any time (section 4.8).

---

## 4. The main journeys

### 4.1 "What does this mean?" (explaining insurance)

> *"What is the difference between term insurance and whole life insurance?"*
> *"What is the waiting period for pre-existing diseases?"*

Sahaj finds the relevant clauses in its approved documents, writes a short answer in the person's language, and cites the clause. If the question is about a **named plan** ("the Lotus plan"), it only looks at that plan's wording. If **no plan is named**, it answers only from the general explanations, so it never presents one plan's figures as if they were general. After a comparison or recommendation, "the first one" means those plans.

If the documents do not contain the answer, Sahaj says so and offers a person. It does not guess.

### 4.2 "Compare these plans"

> *"Compare the Lotus plan and the Neem plan."*

The screen shows a **comparison table** built from the plan data (waiting periods, co-payment, room rent, maternity, claim settlement ratio and so on), and Sahaj narrates the main differences. If the person has already given their details (see 4.3), the table also shows an indicative premium for each plan.

### 4.3 "Which plan should I buy?" (the recommendation journey)

This is the most careful journey. Sahaj will not recommend anything until it has **understood the person and they have confirmed it**.

```
 Ask for advice
      │
      ▼
 Permission to use personal details  ──decline──►  Sahaj keeps explaining and comparing,
      │ agree                                      but asks nothing personal
      ▼
 Questions, one at a time  ◄──────────────┐
      │                                    │ correction: "no, three children"
      ▼                                    │
 Read-back of everything understood ───────┘
      │ person says "yes, that is correct"
      ▼
 Recommendation + disclosures
```

**The permission.** A second consent covers using their age, income, family and existing cover. It says exact details are kept only during the conversation and that what they say in answer to the questions is not kept.

**The questions.** Sahaj asks one question per turn, in their language. For health insurance it asks about: which person is eldest, yearly income, the city, who is to be covered, how many children, existing health insurance, any existing medical condition, maternity cover, and what matters most (lowest price, reliable claims, shorter waiting periods, or nothing in particular). For life insurance: age, income, dependents, existing life cover, loans owed, whether they smoke, and what matters most. A person can answer several things at once ("I'm 34 and earn about 12 lakh"), and Sahaj only asks for what is still missing.

**Every answer is double-checked.** Sahaj never assumes. A figure is accepted only if it matches the person's own words, so "12 lakh" can never silently become 12 crore. A yes/no is accepted only for the question just asked.

**The read-back.** Sahaj reads back everything it understood, and the screen shows the **complete list**. The person must say yes. If they correct something, Sahaj updates it and asks again. A recommendation is impossible until this step is confirmed. This is enforced in code and tested.

**The recommendation.** Sahaj suggests an amount of cover (and shows how it was worked out), then up to **three ranked plans**, never just one "best". Each shows its premium, highlights, why it ranks where it does, and a score for each criterion. The ranking is calculated by fixed rules, not by the language model, so the same details always give the same answer. A need for maternity cover, for example, removes plans without it, and Sahaj says how many plans matched.

**The disclosures.** Fixed wording is shown with every recommendation: the suggestions rest only on the information given, premiums are indicative, read the policy wording before buying, plans are ranked only on the criteria shown, and a person is available. The first two are also spoken.

**If the person gets stuck.** After three turns of making no progress, Sahaj offers a person instead of looping.

### 4.4 "Explain my loan offer"

> *"What is the processing fee on my loan?"* · *"Can I repay early without a penalty?"* · *"Who do I complain to?"*

Sahaj answers from the lender's Key Facts Statement (KFS) and cites the clause, exactly as for insurance.

### 4.5 "Work out my EMI"

> *"What would the EMI be on 5 lakh at 11 percent for 3 years?"*
> *"If I prepay 1 lakh, how much interest do I save?"*

Sahaj asks only for the numbers it is missing (amount, yearly rate, time left, extra payment). The **arithmetic is done by code, never by the model**, and shown on a card. The answer notes that a lender's own figure can differ slightly.

### 4.6 "How do loans work?"

> *"What is the difference between a personal loan and a home loan?"* · *"How can I get my application processed faster?"*

Answered from a general loan explanation document, with citations.

### 4.7 Things Sahaj says it cannot do

- *"Which bank has the lowest home loan rate?"*, *"Will my loan get approved?"* → Sahaj has no bank rate data and cannot predict approval. It says so and offers to explain their offer, work out an EMI, or connect a person.
- Anything unrelated (jokes, general knowledge, medical or tax questions, or an instruction to ignore its rules) → a fixed polite message that it only helps with insurance and loans.

These replies are written text, not generated, so an instruction hidden in a message cannot talk Sahaj into anything.

### 4.8 Getting a person

A person can ask for a human in four ways, and the conversation is **handed over**:

| How | What triggers it |
|---|---|
| They tap **Talk to a human** | A button at any time |
| They say so | "I want to talk to a person", a complaint, or clear frustration. This is never second-guessed. |
| Sahaj cannot verify its own answers | Two replies in a row fail the safety checks |
| They are stuck | Three turns of the questions without progress |

On handover the screen shows a **reference number**. Sahaj stops answering. A summary (recent messages with personal answers replaced by a placeholder, which permissions are active, and the trace id) is recorded and sent to the human team's system. *The live console for the human to reply is not built yet.*

### 4.9 Changing their mind: withdrawing consent

They can withdraw either permission at any time. Withdrawing the **personal-details permission** wipes the analysis; asking for advice again asks permission again. Withdrawing the **conversation permission** also clears the conversation memory.

### 4.10 When it does not understand

- **Silence or noise:** "I didn't catch that."
- **A vague message** ("what about that one?"): Sahaj asks a clarifying question instead of guessing.
- **A message in the middle of the questions that is a question itself** ("what is a waiting period?"): Sahaj answers it, and the questions can continue.

---

## 5. Inside one turn: what happens in the few seconds after they speak

```mermaid
flowchart TD
    A[Person speaks and releases the button] --> B[Speech to text<br/>language detected]
    B --> C[Mask personal identifiers<br/>PAN, Aadhaar-like numbers, phone, email, UPI, accounts]
    C --> D[Is an advice or calculator<br/>conversation under way?]
    D -- yes, and it is an answer --> J
    D -- no --> E[Classify intent<br/>10 intents, with a confidence]
    E -- low confidence --> F[Ask a clarifying question]
    E -- asks for a person --> H[Hand over to a human]
    E -- insurance / loan question --> G[Find clauses in approved documents,<br/>write an answer]
    E -- advice --> G2[Needs-analysis questions]
    E -- compare --> G3[Comparison table]
    E -- calculator --> G4[Exact arithmetic]
    E -- cannot help --> G5[Fixed honest message]
    F --> J
    G --> J
    G2 --> J
    G3 --> J
    G4 --> J
    G5 --> J
    J[Safety checks] -- passed --> K[Send text, cards and speech]
    J -- failed --> L[Safe fallback message:<br/>I can not confirm that, offer a person]
    L --> K
    K --> M[Record in the audit trail]
```

In words:

1. **Hear.** Their speech is turned into text and the language is detected (English, Hindi, Hinglish and other Indian languages).
2. **Protect.** Personal identifiers are replaced with placeholders such as `[PAN_1]` before anything else sees the text. This includes identifiers the speech recogniser spells out letter by letter, and digits written in Indian scripts.
3. **Decide.** If a recommendation or loan calculation is already under way, that conversation reads the message first, because a short reply like "34" is almost certainly an answer to the last question. Otherwise a classifier decides what they want, with a confidence.
4. **Answer.** The right specialist handles it. For insurance and loan questions this means searching approved documents by meaning (not keywords), so a Hindi question can find an English clause, and writing a short reply from only those clauses.
5. **Check.** See section 6. Nothing reaches the person without passing.
6. **Speak.** The reply is turned into speech in the person's language (see section 8) and sent with any card.
7. **Record.** The turn is saved to the audit trail (section 7).

Repeated, non-personal questions are served from a short-lived in-memory cache of answers that already passed the checks, which makes them near-instant. Nothing personal is ever cached.

---

## 6. The safety checks every reply passes

| Check | In plain words |
|---|---|
| **Backed by a clause** | Every statement must carry a source tag for a clause that was actually retrieved |
| **Numbers must match** | Any figure in a reply must appear in the clause it cites. A computed or invented number is blocked |
| **Nothing added** | A second check asks whether the reply adds any condition, exception or reason the documents do not state |
| **On the point** | A third check asks whether the reply actually answers the question, so a true but irrelevant clause is not offered as an answer |
| **No advice outside the advice journey** | Phrases like "I recommend" are blocked everywhere except in text built from the recommendation engine. Pressure phrases ("you must buy", "guaranteed", "limited time") are blocked everywhere |
| **Personal details masked** | The model's reply is masked again on the way out |

If a reply fails, the person hears: *"I can't confirm that from the documents I have. Would you like me to connect you to a person?"* Two failures in a row hand over to a human. The checks are strict on purpose, so occasionally a correct answer is replaced by this message. That is the safe direction.

---

## 7. What Sahaj records, and what it deliberately does not

**Recorded in the audit trail** (a tamper-evident, append-only ledger):

- every consent, with the version and a fingerprint of the exact wording shown;
- each turn: what was masked of what they said, what Sahaj decided they wanted, the route taken, the clauses used, the check results, and timings;
- each handover, with its reason;
- each recommendation, using **ranges** (for example "age 30 to 34", "income 10 to 15 lakh"), the rules version, the catalogue version, and the score breakdown.

**Deliberately not recorded:**

- the person's exact answers to the needs-analysis questions (age, income, family, loans, health). Those turns are stored as "withheld", and in the conversation memory they are replaced by a placeholder;
- the read-back of their details;
- raw PAN, Aadhaar, phone, email, UPI or account numbers.

A team member can request a **workflow report** for any conversation (intents, routes, timings, cache use, check results, handovers, recommendations in ranges), and can verify that the ledger has not been altered.

---

## 8. Languages

Sahaj replies in the language the person spoke. Mixed speech such as Hinglish is answered in Hindi.

| Level | Languages | What the person gets |
|---|---|---|
| Full voice | English, Hindi, Bengali, Tamil, Telugu, Kannada, Marathi, Gujarati, Punjabi, Malayalam, Odia | Text and speech in a voice for that language |
| Spoken by a related voice | Nepali, Maithili, Dogri, Konkani, Sanskrit, Bodo (Hindi voice); Assamese (Bengali voice) | Text in their language; pronunciation is approximate |
| Text only | Urdu, Kashmiri, Sindhi, Santali, Manipuri | Text in their language, no audio |

Some fixed messages (the declines, the disclosures, the fallback line) exist in English and Hindi; other languages receive them via model phrasing or in English.

---

## 9. A sample conversation (health insurance)

Everything below is sample data. Sahaj's questions were generated live; figures come from the recommendation engine.

| | |
|---|---|
| **Person** | Which health insurance should I buy for my family? |
| **Screen** | *(permission request: use my age, income and family details)* → person agrees |
| **Sahaj** | Could you tell me the age of the eldest person who will be covered? |
| **Person** | I am 34 years old. |
| **Sahaj** | What is your approximate income per year? |
| **Person** | About 12 lakh a year. |
| **Sahaj** | Do you live in a large metro city, or in another city or town? |
| **Person** | I live in Bangalore. |
| **Sahaj** | Who is the cover for: yourself, you and a spouse, or a family with children? |
| **Person** | Me, my wife and our two kids. |
| **Sahaj** | Do you already have health insurance, and is it from an employer or your own? |
| **Person** | No, we don't have any. |
| **Sahaj** | Does anyone to be covered have an existing medical condition? |
| **Person** | No. |
| **Sahaj** | Would you like maternity expenses covered? |
| **Person** | Yes, we would like maternity cover. |
| **Sahaj** | Does anything matter most to you, such as the lowest price? |
| **Person** | The lowest premium matters most. |
| **Screen** | *Details card:* health insurance · age 34 (eldest) · income Rs 12,00,000 · metro city · family with 2 children · no existing health insurance · no existing medical condition · wants maternity cover · priority: low premium |
| **Sahaj** | *(reads the details back)* Is that right, or should anything change? |
| **Person** | Yes, that is correct. |
| **Screen** | *Recommendation card:* suggested cover Rs 20,00,000 and how it was worked out; the plan that matched (the only one with maternity cover), its indicative yearly premium, why it ranks there and its score breakdown; all five disclosures |
| **Sahaj** | *(speaks)* The suggested cover is Rs 20 lakh. The plan that matched is ... One of the 3 plans in the catalogue matched on age and maternity cover. The full details are shown on the screen. These suggestions are based only on the information you gave me, and nothing else. Premiums shown are indicative... |

---

## 10. What is built, and what is not yet

**Built and tested:** consent and the audit ledger; personal-detail masking; the document search and the safety checks; explanation, comparison and recommendation for insurance; EMI and prepayment calculators; the loan question journeys; handover to a human (recorded and sent to a webhook); the orchestrator with intent classification; caching; the workflow report; 11 voice languages.

**Not built yet:**

| Missing | Why it matters |
|---|---|
| **Real plans and real lender documents** | Everything is sample data until supplied |
| **User login** | A session is anonymous; consent belongs to the connection |
| **Video KYC and identity verification** | The permission wording exists; no vendor is integrated |
| **Payments** (UPI autopay, cards) | Planned with Razorpay; money flow must go directly to the lender |
| **KFS delivery and acceptance step** | Sahaj explains a KFS but does not yet present and record acceptance of one |
| **Data deletion on request, retention rules, grievance register** | Needed for RBI and data-protection compliance |
| **A console for the human who takes over** | The handover is recorded and delivered, but there is no live chat tool yet |
| **Interrupting Sahaj while it speaks, or automatic end-of-speech detection** | Today it is push-to-talk |
| **IRDAI advice rules mapped** | The recommendation feature is built, but the regulatory mapping is an open item |

See `docs/compliance.md` for the regulatory detail and `docs/orchestration.md` for the technical design.

---

## 11. Glossary

| Term | Meaning |
|---|---|
| **Session** | One conversation with its own reference number and permissions |
| **Intent** | What a message is asking for (explain, advise, compare, calculate, ...) |
| **Needs analysis** | The questions Sahaj asks before recommending, followed by the read-back |
| **Clause** | One numbered section of an approved document, the unit Sahaj cites |
| **Card** | Structured data the app displays (details, recommendation, comparison, loan calculation) |
| **Handover (handoff)** | Passing the conversation to a human, with a reference number |
| **KFS** | Key Facts Statement: a lender's plain-language summary of a loan's main terms |
| **EMI** | Equated monthly instalment: the fixed monthly repayment of a loan |
| **Audit ledger** | The tamper-evident record of consents, turns, handovers and recommendations |
| **Masking** | Replacing personal identifiers with placeholders before anything else sees them |
