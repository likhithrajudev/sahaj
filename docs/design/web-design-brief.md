# Design brief: Sahaj web app (mobile-first PWA)

> Paste everything below the line into Claude Design.

---

## What I need

Design the complete UI for **Sahaj**, a voice assistant that helps people in India understand insurance policies and loan offers in their own language. The design should be **mobile-first** and work as an installable **PWA**, then scale up to tablet and desktop. We will mainly demo it on a phone, so the phone experience has to look polished and native, not like a website squeezed onto a small screen.

Please deliver:
1. A small design system: colour tokens (light and dark), type scale, spacing, radii, elevation, iconography and motion guidelines.
2. All screens and states listed below at **390 × 844** (iPhone 14/15). Key screens also at **768 px** (tablet) and **1440 px** (desktop).
3. The components listed below, in every state.
4. PWA assets: app icon (maskable and regular), splash/launch screen, and the install prompt.

## The product in one paragraph

A person opens Sahaj, agrees to a short consent notice, then **holds a big talk button, speaks (up to 30 seconds) and lets go**. Sahaj shows what it heard, replies in text in the same language, speaks the reply aloud, and sometimes shows a structured **card**: a comparison table, a loan calculation, a summary of the person's details, or a plan recommendation. Every factual answer carries **source citations** to clauses in approved documents. The person can **ask for a human** at any time. The product's personality is *trustworthy before clever*: it never invents numbers, asks permission before using personal details, and says honestly when it can't help.

## Who uses it

- Everyday Indian adults, many buying insurance or a loan for the first time. They may not be comfortable with financial jargon or with typing. Many are on mid-range Android phones.
- They speak 22 Indian languages, including English, Hindi, Hinglish, Tamil, Telugu, Kannada, Bengali, Marathi, Gujarati, Punjabi, Malayalam and Odia. **The UI must render Devanagari, Tamil, Telugu, Bengali and other Indic scripts beautifully** (for example Noto Sans with its Indic families, or Mukta, or Hind). Text in Indic scripts is often 20–40% longer and taller than English, so leave room.
- Second audience: stakeholders and partners (insurers, lenders, investors) watching a live demo. It must look credible, regulated and calm, like a serious fintech product.

## Visual direction

- **Clean, professional, calm, warm.** Think of a modern Indian fintech or a good banking app: lots of whitespace, confident typography, restrained colour. It should feel safe to talk about money here.
- Avoid the generic "AI product" look: no purple-to-blue gradients, no sparkles, no glowing orbs, no robot mascots.
- Suggested palette direction (adjust if you have a better idea): a deep, trustworthy primary (deep teal, indigo-green or ink blue), a warm accent used sparingly (saffron, marigold or terracotta) for the talk button and key actions, and neutral warm greys. Semantic colours for success, warning, error and info. Every pair must meet WCAG AA contrast.
- Typography: one clean sans with excellent Indic support. Large, readable sizes: 16 px minimum for body text on mobile, and numbers in cards set in tabular figures.
- Rupee formatting uses Indian grouping: **₹12,00,000**, and "₹20 lakh" in prose.
- Light mode first, with a full dark mode.
- Motion should be purposeful and subtle: the talk button's recording pulse, a gentle "thinking" indicator, an audio waveform while Sahaj speaks, cards sliding in. Respect `prefers-reduced-motion`.

## Screens and states

### 1. Launch / splash (PWA)
Logo mark plus wordmark "Sahaj" and a short tagline (suggestion: "Insurance and loans, explained in your language"). Shown while the connection opens.

### 2. Welcome / empty conversation
- Header: Sahaj logo, connection status (a small dot: connected, reconnecting or offline), and a menu (language note, privacy and consent, about, install app).
- A friendly greeting and **"Try saying…" example chips**. These are spoken prompts, not buttons that send text: the backend only accepts voice. Show 4–6 examples across the journeys, for example:
  - "What is the waiting period for pre-existing diseases?"
  - "Compare the Lotus and Neem health plans"
  - "Which health insurance should I buy for my family?"
  - "What would the EMI be on 5 lakh at 11% for 3 years?"
  - "Can I repay my loan early without a penalty?"
  - A Hindi example: "टर्म इंश्योरेंस और होल लाइफ में क्या फर्क है?"
- A persistent **"Sample data" banner or badge**: every plan is fictional today, and the UI must never let it pass as real.
- The bottom dock (see component 1) with the talk button and "Talk to a human".

### 3. Consent: conversation (required before anything is processed)
A bottom sheet on mobile or a modal on desktop. It shows the server's consent text **exactly as sent** (assume about 80–120 words: Sahaj will process your voice and what you share to answer questions, personal identifiers such as PAN and Aadhaar are masked, a record is kept for audit, and you can withdraw at any time). Two clear buttons, **"I agree"** and **"Not now"**, with equal visual honesty: no dark patterns, and the decline is not hidden. Include a small version label. Also design the **declined** state: a calm empty state explaining that nothing is processed, with a "Review consent" action.

### 4. Consent: needs analysis (second permission, asked mid-conversation)
The same pattern, triggered when the person first asks for a recommendation. The text covers using their age, income, family and existing cover. Make it feel like a natural step in the conversation, not an interruption. If they decline, Sahaj keeps explaining and comparing but never asks for personal details; show a small inline note to that effect.

### 5. Conversation (the core screen)
A chat-style timeline:
- **User bubble**: the transcript of what they said. Personal identifiers arrive already masked as tokens like `[PAN_1]` and `[PHONE_1]`. Render them as subtle inline pills, for example a lock icon with "PAN hidden".
- **Assistant message**: an agent label (**Insurance**, **Loan** or **General**, each with a small icon and tint), the answer text, and **inline citation markers**. The text contains tags like `[health-lotus-care:3.2]`. Render each one as a small numbered superscript chip, and tapping it opens the citation sheet (screen 6). Under each answer show a small row with a **play/replay audio** control and **"Talk to a human"**.
- **Cards**, which appear just before the related assistant message (components 4–7).
- **The "I can't confirm that" reply**: when an answer fails the safety checks, Sahaj says "I can't confirm that from the documents I have. Would you like me to connect you to a person?" Design this as a distinct, non-alarming variant with a prominent "Connect me to a person" action. It is a feature, not an error.
- **Clarifying question** variant: Sahaj asks the person what they meant.
- **System notes** in the timeline: "Consent granted", "Personal details permission withdrawn", "Conversation reset after reconnecting".
- Long conversations: smooth scrolling and a "jump to latest" button.

### 6. Citation sheet
A bottom sheet listing the cited clauses for an answer: clause id (for example "Lotus Care · Clause 3.2"), the clause title, and the full clause text, with the cited one highlighted. Each clause comes with a document name and the full text of that clause.

### 7. Voice turn states (these matter most; design them carefully)
The talk button and the area around it go through these states:
1. **Idle**: "Hold to talk".
2. **Recording**: the button grows, a live audio level or waveform, and an elapsed timer counting up to **0:30**, with a warning near the limit. "Release to send", and slide away to cancel.
3. **Sending / transcribing**: brief.
4. **Thinking**: Sahaj can take a few seconds, especially during advice. Show a calm progress indicator, optionally with step hints ("Finding the right documents…", "Checking the answer…").
5. **Speaking**: an audio waveform, plus a stop/mute control.
6. **Done**: back to idle.
7. **Text-only language**: for Urdu, Kashmiri, Sindhi, Santali and Manipuri no audio comes back. Show a small "Text only in this language" note instead of a player.
8. **Error**: "I didn't catch that", bad audio, or a server failure. Show it inline with "Try again". The session stays open.
9. **Disabled**: while a turn is in progress, the button cannot send.

Also design the **microphone permission** flows: a first-time explainer before the browser prompt, and a "Microphone blocked" state with instructions for turning it on.

### 8. Needs analysis (the recommendation journey)
Sahaj asks **one question per turn** (age of the eldest person covered, yearly income, city, who is covered, number of children, existing cover, medical conditions, maternity, what matters most). Show a **slim progress indicator** for this journey (for example "Understanding your needs · 4 of 9") and keep "Talk to a human" visible throughout.

### 9. Handoff to a human
Triggered by the button, by the person asking, by two failed checks in a row, or by getting stuck. Show a clear full-width state: "A person will take it from here", a **reference number** in large, copyable type (for example `SAH-7F3K-92`), a short reason line, and the talk button disabled. The tone should be reassuring.

### 10. Connection states
Connecting, connected, reconnecting (a banner), and disconnected or offline (the PWA offline screen). On reconnect, show a note in the timeline that the conversation context was reset and consent will be asked again.

### 11. Menu / settings sheet
Privacy and consent (current status of both permissions, each with a "Withdraw" action and a confirmation step), languages (which have full voice, an approximate voice, or text only), about Sahaj, the sample-data notice, "Install app", and the session reference id (small, copyable, for support).

### 12. PWA install prompt
A tasteful custom install card (Android) and an "Add to Home Screen" instruction sheet (iOS Safari), offered after the first successful turn, not on first load.

## Components (design every state)

1. **Bottom dock**: the talk button (primary, large, thumb-reachable, at least 72 px) plus a secondary "Talk to a human" action. It respects iOS safe-area insets and the Android gesture bar.
2. **Message bubbles**: user, assistant (three agent variants), fallback, clarifying question and system note.
3. **Citation chip** and **citation sheet**.
4. **Profile summary card** (`profile_summary`): the heading "Here's what I understood", followed by the complete list of details as short lines. It is shown when Sahaj asks the person to confirm, with **"Yes, that's correct"** and **"Change something"** hints. (Confirmation is spoken, so these hints are visual cues or prompts, not required buttons.) Example lines: Health insurance · Eldest person covered: 34 · Yearly income: ₹12,00,000 · Metro city · Family with 2 children · No existing health insurance · No existing medical condition · Wants maternity cover · Priority: lowest premium.
5. **Recommendation card** (`recommendation`), the most important card:
   - **Suggested cover** (for example ₹20,00,000) with "How we worked this out" (the basis and a note), expandable.
   - **Up to 3 ranked plans**, never a single "best". Each shows rank, plan name, insurer, cover, **indicative annual premium**, 2–4 highlights, "Why it ranks here" reasons, and a **score breakdown per criterion** (small bars). Include a "1 of 3 plans matched your needs" line.
   - **Disclosures**: about 5 short fixed statements, always visible, not hidden behind a tap. Make them readable and dignified, not legal grey mush.
   - A "Sample data" badge and an "Indicative premiums" badge.
6. **Comparison card** (`comparison`): 2–4 plans side by side, as label/value rows (waiting periods, co-payment, room rent, maternity, restoration of sum insured, no-claim bonus, network hospitals, claim settlement ratio, and optionally an indicative premium row). On mobile, use a horizontally swipeable table with a sticky first column, or a stacked per-attribute layout; show both options.
7. **Loan calculation card** (`calc`), in two variants:
   - **EMI**: inputs (loan amount, yearly rate, tenure) and results (**monthly EMI** large, total payment, total interest), with an optional principal vs interest bar or donut.
   - **Prepayment**: inputs (outstanding, rate, months left, prepayment amount) and a before/after comparison: EMI before and after, months before and after, **months saved**, interest before and after, and **interest saved** as the highlight.
   - A footnote: "Your lender's own figure may differ slightly."
8. **Badges**: Sample data, Indicative, Agent (Insurance/Loan/General), Text only, Masked identifier.
9. **Banners/toasts**: reconnecting, offline, error, consent withdrawn.
10. **Empty, loading and skeleton states** for cards.

## Responsive behaviour

- **Mobile (default)**: a single column, the dock fixed at the bottom, and cards full-width inside the timeline.
- **Tablet**: wider timeline with a max reading width of about 680 px; the comparison table can show 3 columns without scrolling.
- **Desktop**: a centred conversation column, plus an optional right panel showing the latest card in detail (for example the full comparison or recommendation) while the timeline keeps the compact version. Push-to-talk also works with the spacebar, so show a "Hold Space to talk" hint.

## Accessibility and trust requirements

- WCAG 2.2 AA, touch targets of at least 44 px, visible focus states, screen-reader labels for every voice state, and captions always on (the text *is* the caption).
- Never rely on colour alone (for example score bars also carry numbers).
- Financial figures always appear as text on the card, and the card is the source of truth, not the spoken audio.
- No pressure patterns: no countdowns, no "limited time", no "best choice!" ribbons.
- The "Talk to a human" action is never more than one tap away.

## Sample content for the mocks

Use these fictional sample plans: **Lotus Care, Neem Essential, Peepal Family** (health), **Banyan Flex, Orchid Pure** (term life), and **Banyan Secure, Orchid Legacy** (whole life). Each should carry a "(SAMPLE)" marker in the UI. The sample conversation:

> **You:** Which health insurance should I buy for my family?
> *(needs-analysis consent → agreed)*
> **Sahaj:** Could you tell me the age of the eldest person who will be covered?
> **You:** I am 34 years old. … *(income 12 lakh, Bangalore, wife and two kids, no existing cover, no conditions, wants maternity, lowest premium matters most)*
> *(Profile summary card)* **Sahaj:** Is that right, or should anything change?
> **You:** Yes, that is correct.
> *(Recommendation card: suggested cover ₹20,00,000; 1 of 3 plans matched on age and maternity cover; indicative premium; 5 disclosures)*
> **Sahaj:** The suggested cover is ₹20 lakh. The plan that matched is Peepal Family (SAMPLE)… The full details are shown on the screen.

Loan example: "EMI on ₹5,00,000 at 11% for 36 months", which gives an EMI of about ₹16,369, a total payment of about ₹5,89,300 and total interest of about ₹89,300.

## Out of scope for now (don't design)

Login and accounts, payments, KYC, a typed-chat input, the human agent's console, and admin/audit screens.
