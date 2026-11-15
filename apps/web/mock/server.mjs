// Mock of the Sahaj voice backend for UI work: no Sarvam, Postgres or model needed.
// Speaks the real /ws/voice protocol (packages/contracts) and replays a scripted demo, one step per recording,
// covering every state in the design: citations, cards, clarify, fallback, text-only, needs analysis, handoff.
//   pnpm dev:mock     then open http://localhost:5173
import { createServer } from "node:http";
import { WebSocketServer } from "ws";

const PORT = Number(process.env.PORT ?? 8000);
const CONSENT = {
  conversation: { title: "Before we start", required: true, requires: null, withdrawal: "Sahaj stops listening and forgets this conversation.", version: "2026-11-draft-1", text: "Sahaj will process your voice and the information you share in this conversation to answer your questions about insurance and loans. Personal identifiers such as PAN, Aadhaar and phone numbers are masked before anything is processed. A record of this conversation is kept for audit, as regulation requires. Your audio is not kept after your answer is ready. You can withdraw consent at any time from the menu, and Sahaj will stop processing straight away. Sahaj gives information, not financial advice." },
  needs_analysis: { title: "Can I use your details?", required: false, requires: "conversation", withdrawal: "Sahaj forgets the details you gave for plan suggestions.", version: "2026-11-draft-1", text: "To suggest plans that fit you, Sahaj will ask about and use your age, yearly income, city, family members, existing cover and health conditions. These details are used only in this conversation, are masked in audit records where possible, and are not shared with insurers. You can withdraw this permission at any time." },
};

const clause = (doc, docName, num, title, body) =>
  ({ id: `${doc}:${num}`, text: `${num} ${title}\n${body}`, doc: docName, clause: num, title, body });
const fact = (id, doc, body) => ({ id, text: body, doc, clause: null, title: null, body });

const LOTUS = "Lotus Care (SAMPLE)";
const plan = (rank, id, name, insurer, premium, meets, highlights, reasons, criteria) =>
  ({ rank, product_id: id, name, insurer, cover: 2000000, annual_premium: premium, meets_suggested_cover: meets, highlights, reasons, criteria });
const crit = (score, weight) => ({ value: score, score, weight, contribution: +(score * weight).toFixed(4) });

const script = [
  { user: "What would the EMI be on 5 lakh at 11% for 3 years?", agent: "loan", kind: "calc", steps: ["thinking", "calculating", "checking"],
    card: { type: "loan_calculation", kind: "emi", inputs: { principal: 500000, annual_rate_percent: 11, tenure_months: 36 }, result: { emi: 16369, total_payment: 589291, total_interest: 89291 } },
    text: "Your EMI would be about ₹16,369 a month. Over 3 years you would pay ₹89,291 in interest [calc:emi].",
    citations: [fact("calc:emi", "Loan calculation", "For a loan of ₹5,00,000 at 11 percent a year over 36 months: the monthly instalment (EMI) is ₹16,369, the total repayment is ₹5,89,291 and the total interest is ₹89,291. This uses the reducing-balance method; a lender's own figure can differ slightly.")] },

  { user: "What is the waiting period for pre-existing diseases in Lotus Care? My PAN is [PAN_1]", agent: "insurance", steps: ["thinking", "searching", "checking"],
    text: "Lotus Care covers pre-existing diseases only after 36 months of continuous cover [health-lotus-care:3.2]. Some listed conditions, like cataract, have a 24-month wait [health-lotus-care:3.4].",
    citations: [
      clause("health-lotus-care", LOTUS, "3.2", "Pre-existing disease waiting period", "Expenses for the treatment of a pre-existing disease and its direct complications are excluded until 36 months of continuous coverage have passed since the start of the first policy with the insurer. If the sum insured is increased, this exclusion applies again to the increase."),
      clause("health-lotus-care", LOTUS, "3.4", "Specified disease waiting period", "Expenses for the listed conditions, including cataract, hernia and joint replacement, are excluded until 24 months of continuous coverage have passed, unless they arise from an accident."),
    ] },

  { user: "Compare the Lotus, Neem and Peepal health plans", agent: "insurance", kind: "compare", steps: ["thinking", "comparing", "checking"],
    card: { type: "comparison", goal: "health", sample_data: true, premiums_included: true, plans: [
      { id: "health-lotus-care", name: "Lotus Care (SAMPLE)", insurer: "Kaveri General (SAMPLE)", rows: [["pre-existing disease wait", "3 years"], ["initial wait", "30 days"], ["co-payment", "none"], ["room rent", "single private room"], ["maternity", "not covered"], ["restoration of sum insured", "yes, once a year"], ["no-claim bonus", "10% a year, up to 50%"], ["network hospitals", "7,200"], ["claim settlement ratio", "96.2 percent (sample data)"], ["indicative yearly premium", "Rs 21,400"]] },
      { id: "health-neem-essential", name: "Neem Essential (SAMPLE)", insurer: "Godavari Assurance (SAMPLE)", rows: [["pre-existing disease wait", "4 years"], ["initial wait", "30 days"], ["co-payment", "20%"], ["room rent", "1% of cover a day"], ["maternity", "not covered"], ["restoration of sum insured", "no"], ["no-claim bonus", "5% a year, up to 25%"], ["network hospitals", "5,400"], ["claim settlement ratio", "93.8 percent (sample data)"], ["indicative yearly premium", "Rs 18,900"]] },
      { id: "health-peepal-family", name: "Peepal Family (SAMPLE)", insurer: "Sahyadri Health (SAMPLE)", rows: [["pre-existing disease wait", "2 years"], ["initial wait", "30 days"], ["co-payment", "none"], ["room rent", "no limit"], ["maternity", "covered up to Rs 50,000 after 24 months"], ["restoration of sum insured", "yes, once a year"], ["no-claim bonus", "20% a year, up to 100%"], ["network hospitals", "8,100"], ["claim settlement ratio", "97.1 percent (sample data)"], ["indicative yearly premium", "Rs 24,800"]] },
    ] },
    text: "Peepal Family has the shortest wait for pre-existing diseases and is the only one with maternity cover [health-peepal-family:compare]. Neem Essential has the lowest premium but a 20% co-payment [health-neem-essential:compare].",
    citations: [fact("health-peepal-family:compare", "Peepal Family (SAMPLE)", "Peepal Family (SAMPLE): pre-existing disease wait 2 years; maternity covered up to ₹50,000 after 24 months."), fact("health-neem-essential:compare", "Neem Essential (SAMPLE)", "Neem Essential (SAMPLE): co-payment 20%; indicative yearly premium ₹18,900.")] },

  { user: "If I prepay 1 lakh now, how much do I save?", agent: "loan", kind: "calc", steps: ["thinking", "calculating", "checking"],
    card: { type: "loan_calculation", kind: "prepayment", inputs: { principal: 400000, annual_rate_percent: 11, tenure_months: 28, prepay_amount: 100000, mode: "reduce_tenure" },
      result: { emi_before: 16262, emi_after: 16262, months_before: 28, months_after: 21, months_saved: 7, interest_before: 55336, interest_after: 30144, interest_saved: 25192 } },
    text: "Paying ₹1,00,000 now saves about ₹25,192 in interest and ends the loan 7 months sooner, with the same EMI [calc:prepay].",
    citations: [fact("calc:prepay", "Loan calculation", "Same EMI, shorter loan: interest goes from ₹55,336 to ₹30,144, a saving of ₹25,192. A lender's own figure can differ slightly.")] },

  { user: "Tell me about the Orchid plan", agent: "insurance", kind: "ask", steps: ["thinking"],
    text: "There are two Orchid plans: Orchid Pure, a term life plan, and Orchid Legacy, a whole life plan. Which one do you mean?", citations: [] },

  { user: "Orchid Legacy. Does it pay out if I move abroad?", agent: "insurance", fallback: true, steps: ["thinking", "searching", "checking"],
    text: "I can't confirm that from the documents I have. Would you like me to connect you to a person?", citations: [] },

  { user: "ای ایم آئی کیا ہوتی ہے؟", agent: "loan", textOnly: true, steps: ["thinking", "searching", "checking"],
    text: "ای ایم آئی وہ مقررہ رقم ہے جو آپ ہر مہینے قرض واپس کرنے کے لیے ادا کرتے ہیں۔", citations: [] },

  { user: "Which health insurance should I buy for my family?", agent: "advice", kind: "ask", consent: "needs_analysis", steps: ["thinking"],
    text: "I can suggest plans, but first I need your permission to use a few personal details.", citations: [],
    afterConsent: { agent: "advice", kind: "ask", progress: { step: 2, total: 9 }, text: "Thank you. Could you tell me the age of the eldest person who will be covered?", citations: [] } },

  { user: "I am 34", agent: "advice", kind: "ask", progress: { step: 3, total: 9 }, steps: ["thinking"],
    text: "What is your approximate income per year?", citations: [] },

  { user: "About 12 lakh, we live in Bangalore, me, my wife and two kids, no cover, no conditions, want maternity, lowest premium", agent: "advice", kind: "confirm", progress: { step: 9, total: 9 }, steps: ["thinking", "checking"],
    card: { type: "profile_summary", details: ["looking for health insurance", "age 34 for the eldest person covered", "yearly income Rs 12,00,000 (12 lakh)", "metro city", "family with 2 children", "no existing health insurance", "no existing medical condition", "wants maternity cover", "priority: lowest premium"] },
    text: "Is that right, or should anything change?", citations: [] },

  { user: "Yes, that is correct.", agent: "advice", kind: "recommendation", steps: ["thinking", "checking"],
    card: { type: "recommendation", goal: "health", sample_data: true, indicative_premiums: true, disclosures_version: "2026-11-draft-1",
      suggested_cover: { amount: 2000000, basis: "base cover Rs 10,00,000 for a metro city, scaled by 2 for family with children, less existing own cover Rs 0", note: "Treatment costs at private hospitals in Bangalore are higher than average. A larger cover may suit you if your budget allows." },
      plans: [
        plan(1, "health-peepal-family", "Peepal Family (SAMPLE)", "Sahyadri Health Insurance (SAMPLE)", 24800, true,
          ["maternity cover up to Rs 50,000 after 2 years", "full cover restored once a year if used up", "no limit on room rent"],
          ["best on waiting period for pre-existing diseases among the plans compared", "best on network hospitals among the plans compared"],
          { premium: crit(0.6, 0.45), ped_waiting: crit(1, 0.15), cost_sharing: crit(1, 0.1), claim_ratio: crit(0.8, 0.1), restoration_bonus: crit(1, 0.1), network: crit(1, 0.1) }),
      ],
      disclosures: ["These suggestions are based only on the information you gave me, and nothing else.", "Premiums shown are indicative. The insurer sets the final premium after reviewing your details.", "Sahaj does not sell insurance and earns nothing from any plan.", "The policy wording is the final word. Read it before you buy.", "This is guidance to help you compare. It does not guarantee that a claim will be paid."] },
    text: "The suggested cover is ₹20 lakh [rec:cover]. The plan that matched is Peepal Family (SAMPLE), because it covers maternity [rec:health-peepal-family]. The full details are shown on the screen.",
    citations: [fact("rec:cover", "Recommendation engine", "Suggested cover: ₹20,00,000. Worked out from base cover ₹10,00,000 for a metro city, scaled by 2 for a family with children."), fact("rec:health-peepal-family", "Recommendation engine", "Peepal Family (SAMPLE) by Sahyadri Health Insurance (SAMPLE): cover ₹20,00,000, indicative yearly premium ₹24,800.")] },
];

/** A silent WAV of `seconds`, standing in for speech so the speaking state and replay can be designed. */
function silence(seconds) {
  const rate = 8000, n = Math.round(rate * seconds);
  const b = Buffer.alloc(44 + n, 128);
  b.write("RIFF", 0); b.writeUInt32LE(36 + n, 4); b.write("WAVEfmt ", 8); b.writeUInt32LE(16, 16);
  b.writeUInt16LE(1, 20); b.writeUInt16LE(1, 22); b.writeUInt32LE(rate, 24); b.writeUInt32LE(rate, 28);
  b.writeUInt16LE(1, 32); b.writeUInt16LE(8, 34); b.write("data", 36); b.writeUInt32LE(n, 40);
  return b;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const SUGGEST = {
  loan: ["What if I prepay 1 lakh?", "Explain the processing fee"],
  insurance: ["Compare it with Neem Essential", "What is not covered?"],
  advice: ["What does the waiting period mean?"],
};

// ---------- REST: just enough of the real API for the app (sign-in, consents, feedback) ----------
const USER = { id: "mock-user", email: "demo@sahaj.local", name: "Demo", picture: null, language: "en-IN", platform: "web", role: "user" };
const accounts = { conversation: false, needs_analysis: false }; // consent carries over between connections, like the real API
const tokens = () => ({ access_token: "mock-access-" + Date.now(), refresh_token: "mock-refresh-" + Math.random().toString(36).slice(2),
  token_type: "bearer", expires_in: 900, user: USER });
const body = (req) => new Promise((resolve) => { let b = ""; req.on("data", (c) => (b += c)); req.on("end", () => resolve(b ? JSON.parse(b) : {})); });

const server = createServer(async (req, res) => {
  const json = (status, data) => res.writeHead(status, { "content-type": "application/json" }).end(JSON.stringify(data));
  const path = req.url.split("?")[0];
  if (path === "/health") return json(200, { status: "ok" });
  if (path === "/auth/config") return json(200, { google_client_id: null, dev_login: true });
  if (path === "/auth/dev" && req.method === "POST") {
    const { email, name } = await body(req);
    Object.assign(USER, { email, name: name || email.split("@")[0] });
    return json(200, tokens());
  }
  if (path === "/auth/refresh" && req.method === "POST") return json(200, tokens());
  if (path === "/auth/logout") return res.writeHead(204).end();
  if (path === "/consents") {
    return json(200, { missing_required: accounts.conversation ? [] : ["conversation"], items: ["conversation", "needs_analysis"].map((p) => ({
      purpose: p, title: CONSENT[p].title, text: CONSENT[p].text, version: CONSENT[p].version, required: CONSENT[p].required,
      requires: CONSENT[p].requires, withdrawal: CONSENT[p].withdrawal, granted: accounts[p], granted_at: accounts[p] ? Date.now() / 1000 : null,
      expires_at: null, granted_version: accounts[p] ? CONSENT[p].version : null, action: accounts[p] ? "none" : "ask" })) });
  }
  if (path === "/feedback") return res.writeHead(204).end();
  res.writeHead(404).end();
});
const wss = new WebSocketServer({ server, path: "/ws/voice" });

wss.on("connection", (ws) => {
  const send = (o) => ws.readyState === ws.OPEN && ws.send(JSON.stringify(o));
  const id = "ses_" + Math.random().toString(36).slice(2, 6).toUpperCase() + "-" + Math.random().toString(36).slice(2, 6).toUpperCase();
  const consent = accounts;
  let step = 0, handoff = null, pending = null, failures = 0;
  // The real server needs a signed-in user (Authorization / ?access_token); the mock accepts anyone as a demo user.
  send({ type: "session", id, memory: false, case: null, user: USER, consents: { ...accounts } });
  if (!accounts.conversation) send({ type: "consent_required", purpose: "conversation", ...CONSENT.conversation });

  const reply = async (s) => {
    const trace_id = Math.random().toString(36).slice(2);
    for (const st of s.steps ?? ["thinking"]) {
      send({ type: "status", stage: st });
      await sleep(700);
    }
    if (s.card) send({ type: "card", kind: s.kind, card: s.card, trace_id });
    const level = s.fallback ? "blocked" : s.kind === "calc" || s.kind === "recommendation" ? "engine" : s.citations.length ? "verified" : "checked";
    send({ type: "assistant", agent: s.agent, text: s.text, citations: s.citations, trace_id,
      kind: s.kind ?? "answer", fallback: !!s.fallback, ...(s.progress ? { progress: s.progress } : {}),
      verification: { level, sources: s.citations.length, from_cache: false, checks: ["guardrails", "fact_check"] },
      suggestions: s.kind === "ask" || s.fallback ? [] : SUGGEST[s.agent] ?? [] });
    if (!s.textOnly) ws.send(silence(Math.min(12, 2 + s.text.length / 40)));
    send({ type: "done" });
    failures = s.fallback ? failures + 1 : 0;
  };

  ws.on("message", async (data, isBinary) => {
    if (isBinary) {
      console.log(`[mock] recording ${data.length} bytes (${data.subarray(4, 8).toString() === "ftyp" ? "mp4" : "webm"})`);
      if (handoff) { // a person is handling it: the message goes to them (and the mock person answers)
        send({ type: "user", text: "Message for the team (recorded " + data.length + " bytes)" });
        if (!handoff.joined) return send({ type: "status", stage: "waiting_for_executive" });
        await sleep(1500);
        return send({ type: "agent_message", case_id: handoff.case.id, agent: { name: "Priya" }, text: "Thanks, I've noted that. I'll call you back today with the details.", at: new Date().toISOString() });
      }
      if (!consent.conversation) return send({ type: "consent_required", purpose: "conversation", ...CONSENT.conversation });
      const s = script[step % script.length];
      step++;
      await sleep(900); // speech to text
      send({ type: "user", text: s.user });
      if (s.consent && !consent[s.consent]) {
        send({ type: "consent_required", purpose: s.consent, ...CONSENT[s.consent] });
        pending = s.afterConsent;
      }
      return reply(s);
    }
    const msg = JSON.parse(data.toString());
    if (msg.type === "text") {
      send({ type: "user", text: msg.text });
      return reply({ agent: "general", text: "This is the mock backend: it answers the chips with a fixed reply. Hold to talk to continue the scripted demo.", citations: [], steps: ["thinking", "checking"] });
    }
    if (msg.type === "consent") {
      consent[msg.purpose] = msg.granted;
      send({ type: "consent", purpose: msg.purpose, status: msg.granted ? "granted" : "revoked" });
      if (msg.granted && msg.purpose === "needs_analysis" && pending) {
        const next = pending;
        pending = null;
        reply({ ...next, steps: ["thinking"] });
      }
    } else if (msg.type === "handoff") {
      if (handoff) return;
      const reference = "SAH-" + Math.random().toString(36).slice(2, 6).toUpperCase() + "-" + String(Math.floor(Math.random() * 90) + 10);
      handoff = { joined: false, case: { id: "case-" + reference, reference, kind: "handoff", status: "waiting", priority: "normal" } };
      send({ type: "handoff", reference, reason: "user_requested", case: handoff.case });
      setTimeout(() => { // someone from the team picks it up
        if (!handoff) return;
        handoff.joined = true;
        send({ type: "agent_joined", case_id: handoff.case.id, agent: { name: "Priya" } });
        send({ type: "agent_message", case_id: handoff.case.id, agent: { name: "Priya" }, text: "Hi, I'm Priya from the Sahaj team. How can I help?", at: new Date().toISOString() });
      }, 4000);
    } else if (msg.type === "handoff_cancel") {
      handoff = null;
      send({ type: "handoff_closed", status: "cancelled" });
    }
  });
});

server.listen(PORT, () => console.log(`[mock] Sahaj mock backend on http://127.0.0.1:${PORT} (ws /ws/voice)`));
