// Mock of the Sahaj voice backend for UI work: no Sarvam, Postgres or model needed.
// Speaks the real /ws/voice protocol (packages/contracts) and replays a scripted demo, one step per recording.
//   pnpm --filter @sahaj/web dev:mock     then open http://localhost:5173
import { createServer } from "node:http";
import { WebSocketServer } from "ws";

const PORT = Number(process.env.PORT ?? 8000);
const CONSENT = {
  conversation: { version: "2026-11-draft-1", text: "Sahaj will process your voice and what you share to answer your questions about insurance and loans. Personal identifiers such as PAN and Aadhaar numbers are masked before anything else sees them. A record of this conversation is kept for audit. You can withdraw at any time." },
  needs_analysis: { version: "2026-11-draft-1", text: "To suggest plans, Sahaj will ask about your age, income, family and existing cover. Exact details are kept only during this conversation, and what you say in answer to these questions is not recorded." },
};
const SAMPLE = " This is sample data.";

const script = [
  { user: "What is the waiting period for pre-existing diseases in Lotus Care? My PAN is [PAN_1].",
    agent: "insurance",
    text: "Lotus Care (SAMPLE) covers pre-existing diseases after a waiting period of 36 months from the first policy start date [health-lotus-care:3.2]. Claims for those conditions before then are not paid [health-lotus-care:3.3].",
    citations: [
      { id: "health-lotus-care:3.2", text: "3.2 Pre-existing diseases. Expenses related to pre-existing diseases are covered after 36 months of continuous coverage from the first policy start date." },
      { id: "health-lotus-care:3.3", text: "3.3 Claims during waiting periods. Claims arising from a condition subject to a waiting period are not payable until that period ends." },
    ] },
  { user: "Compare the Lotus and Neem health plans", agent: "insurance", kind: "compare",
    card: { type: "comparison", goal: "health", sample_data: true, premiums_included: false, plans: [
      { id: "health-lotus-care", name: "Lotus Care (SAMPLE)", insurer: "Kamal General (SAMPLE)", rows: [["waiting period for pre-existing diseases", "36 months"], ["co-payment", "none"], ["room rent", "single private room"], ["maternity", "covered up to ₹50,000 after 24 months"], ["network hospitals", "8200"]] },
      { id: "health-neem-essential", name: "Neem Essential (SAMPLE)", insurer: "Vriksha Health (SAMPLE)", rows: [["waiting period for pre-existing diseases", "48 months"], ["co-payment", "10% above age 60"], ["room rent", "1% of sum insured per day"], ["maternity", "not covered"], ["network hospitals", "6100"]] },
    ] },
    text: "Lotus Care has a shorter waiting period for pre-existing diseases, 36 months against 48 months [health-lotus-care:compare] [health-neem-essential:compare]." + SAMPLE,
    citations: [{ id: "health-lotus-care:compare", text: "Lotus Care (SAMPLE): waiting period 36 months; ..." }, { id: "health-neem-essential:compare", text: "Neem Essential (SAMPLE): waiting period 48 months; ..." }] },
  { user: "What would the EMI be on 5 lakh at 11% for 3 years?", agent: "loan", kind: "calc",
    card: { type: "loan_calculation", kind: "emi", inputs: { principal: 500000, annual_rate_percent: 11, tenure_months: 36 }, result: { emi: 16369, total_payment: 589297, total_interest: 89297 } },
    text: "For ₹5,00,000 at 11 percent a year over 36 months, the EMI is ₹16,369 and the total interest is ₹89,297 [calc:emi]. A lender's own figure can differ slightly.",
    citations: [{ id: "calc:emi", text: "Computed with the reducing-balance method." }] },
  { user: "Which health insurance should I buy for my family?", agent: "advice", consent: "needs_analysis",
    text: "To suggest plans I need to ask about your age, income and family. Is that all right?", citations: [] },
  { user: "I am 34, earn about 12 lakh, live in Bangalore with my wife and two kids, no existing cover, want maternity, lowest premium.",
    agent: "advice", kind: "confirm",
    card: { type: "profile_summary", details: ["health insurance", "age 34 (eldest)", "income ₹12,00,000 a year", "metro city", "family with 2 children", "no existing health insurance", "no existing medical condition", "wants maternity cover", "priority: low premium"] },
    text: "Here is what I understood: you are 34, earn ₹12 lakh a year, live in a metro city with your spouse and two children, have no health insurance and want maternity cover. Is that right?", citations: [] },
  { user: "Yes, that is correct.", agent: "advice", kind: "recommendation",
    card: { type: "recommendation", goal: "health", sample_data: true, indicative_premiums: true, disclosures_version: "2026-11-draft-1",
      suggested_cover: { amount: 2000000, basis: "base cover ₹10,00,000 for a metro city, scaled by 2 for family with children, less existing own cover ₹0", note: null },
      plans: [{ rank: 1, product_id: "health-peepal-family", name: "Peepal Family (SAMPLE)", insurer: "Ashwattha Insurance (SAMPLE)", cover: 2000000, annual_premium: 28400, meets_suggested_cover: true,
        highlights: ["maternity covered up to ₹75,000 after 24 months", "no co-payment", "restoration of sum insured once a year"], reasons: ["best on premium among the plans compared"],
        criteria: { premium: { value: 28400, score: 1, weight: 0.5, contribution: 0.5 }, claim_settlement: { value: 0.94, score: 1, weight: 0.3, contribution: 0.3 } } }],
      disclosures: ["These suggestions are based only on the information you gave me, and nothing else.", "Premiums shown are indicative and may change after the insurer's assessment.", "Read the policy wording before you buy.", "Plans are ranked only on the criteria shown.", "You can talk to a person at any time."] },
    text: "The suggested cover is ₹20 lakh [rec:cover]. The plan that matched is Peepal Family (SAMPLE), the only one of the 3 plans with maternity cover [rec:1]. These suggestions are based only on the information you gave me, and nothing else.",
    citations: [{ id: "rec:cover", text: "Suggested cover ₹20,00,000." }, { id: "rec:1", text: "Peepal Family (SAMPLE), indicative premium ₹28,400 a year." }] },
];

const server = createServer((req, res) => {
  if (req.url === "/health") return res.writeHead(200, { "content-type": "application/json" }).end('{"status":"ok"}');
  res.writeHead(404).end();
});
const wss = new WebSocketServer({ server, path: "/ws/voice" });

wss.on("connection", (ws) => {
  const send = (o) => ws.send(JSON.stringify(o));
  const id = Math.random().toString(36).slice(2, 10);
  const consent = { conversation: false, needs_analysis: false };
  let step = 0, handoff = null, pending = null;
  send({ type: "session", id });
  send({ type: "consent_required", purpose: "conversation", ...CONSENT.conversation });

  const reply = async (s) => {
    const trace_id = Math.random().toString(36).slice(2);
    await new Promise((r) => setTimeout(r, 1200)); // "thinking"
    if (s.card) send({ type: "card", kind: s.kind, card: s.card, trace_id });
    send({ type: "assistant", agent: s.agent, text: s.text, citations: s.citations, trace_id });
    send({ type: "done" }); // no audio chunks: the UI treats it as a text-only reply
  };

  ws.on("message", async (data, isBinary) => {
    if (isBinary) {
      console.log(`[mock] recording ${data.length} bytes (${data.subarray(4, 8).toString() === "ftyp" ? "mp4" : "webm?"})`);
      if (handoff) return send({ type: "handoff", reference: handoff });
      if (!consent.conversation) return send({ type: "consent_required", purpose: "conversation", ...CONSENT.conversation });
      const s = script[step % script.length];
      step++;
      await new Promise((r) => setTimeout(r, 400));
      send({ type: "user", text: s.user });
      if (s.consent && !consent[s.consent]) {
        send({ type: "consent_required", purpose: s.consent, ...CONSENT[s.consent] });
        pending = s;
      }
      return reply(s);
    }
    const msg = JSON.parse(data.toString());
    if (msg.type === "consent") {
      consent[msg.purpose] = msg.granted;
      send({ type: "consent", purpose: msg.purpose, status: msg.granted ? "granted" : "revoked" });
      if (msg.granted && msg.purpose === "needs_analysis" && pending) {
        pending = null;
        reply({ agent: "advice", text: "Thank you. Could you tell me the age of the eldest person who will be covered?", citations: [] });
      }
    } else if (msg.type === "handoff") {
      handoff = "SAH-" + Math.random().toString(36).slice(2, 6).toUpperCase();
      send({ type: "handoff", reference: handoff, reason: "user_requested" });
    }
  });
});

server.listen(PORT, () => console.log(`[mock] Sahaj mock backend on http://127.0.0.1:${PORT} (ws /ws/voice)`));
