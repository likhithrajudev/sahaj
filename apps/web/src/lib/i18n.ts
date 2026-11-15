import { useUi } from "@/store/ui";

/**
 * Interface text in English and Hindi (the design's language toggle). Spoken conversation content is never
 * translated: it stays in the language it was spoken in. Hindi strings come from the design file where it had them.
 */
const S = {
  // header / status
  connected: ["Connected", "जुड़ा हुआ"],
  connecting: ["Connecting…", "जुड़ रहे हैं…"],
  reconnectingShort: ["Reconnecting…", "फिर से जुड़ रहे हैं…"],
  offline: ["Offline", "ऑफ़लाइन"],
  withPerson: ["With a person", "एक व्यक्ति से जुड़े"],
  menu: ["Menu", "मेन्यू"],
  needsProgress: ["Understanding your needs", "आपकी ज़रूरतें समझ रहे हैं"],
  of: ["of", "/"],
  tagline: ["Insurance and loans, explained in your language", "बीमा और लोन, आपकी भाषा में"],
  connectingSecurely: ["Connecting securely…", "सुरक्षित रूप से जुड़ रहे हैं…"],

  // welcome
  greeting: ["Namaste. Ask me about insurance or loans.", "नमस्ते। बीमा या लोन के बारे में पूछिए।"],
  greetingSub: [
    "Hold the button and speak in your language. I answer only from approved documents and show you where each fact comes from.",
    "बटन दबाकर अपनी भाषा में बोलिए। मैं सिर्फ़ मंज़ूर दस्तावेज़ों से जवाब देता हूँ और हर बात का स्रोत दिखाता हूँ।",
  ],
  trySaying: ["Try saying", "ऐसे बोलकर देखें"],

  // consent
  consentTitle: ["Before we start", "शुरू करने से पहले"],
  consent2Title: ["Can I use your details?", "क्या मैं आपकी जानकारी इस्तेमाल करूँ?"],
  agree: ["I agree", "मैं सहमत हूँ"],
  notNow: ["Not now", "अभी नहीं"],
  consentNotice: ["Consent notice", "सहमति सूचना"],
  purposeConversation: ["conversation", "बातचीत"],
  purposeNeeds: ["needs analysis", "ज़रूरतों का आकलन"],
  declinedTitle: ["Nothing is being processed", "कुछ भी प्रोसेस नहीं हो रहा"],
  declinedBody: [
    "You chose not to agree, so Sahaj is not listening and has not stored anything. You can review the notice again whenever you like.",
    "आपने सहमति नहीं दी, इसलिए Sahaj सुन नहीं रहा है और कुछ भी सेव नहीं किया गया है। आप जब चाहें सूचना दोबारा देख सकते हैं।",
  ],
  reviewConsent: ["Review consent", "सहमति फिर से देखें"],
  needsDeclined: [
    "Sahaj keeps explaining and comparing plans but won't ask for personal details.",
    "Sahaj प्लान समझाता और तुलना करता रहेगा, पर आपकी निजी जानकारी नहीं पूछेगा।",
  ],

  // system notes
  consentGranted: ["Consent granted", "सहमति दी गई"],
  consentWithdrawn: ["Consent withdrawn. Nothing more will be processed.", "सहमति वापस ली गई। आगे कुछ भी प्रोसेस नहीं होगा।"],
  detailsGranted: ["Personal details permission granted", "निजी जानकारी की अनुमति दी गई"],
  detailsWithdrawn: ["Personal details permission withdrawn", "निजी जानकारी की अनुमति वापस ली गई"],
  resetTitle: ["Conversation reset after reconnecting", "दोबारा जुड़ने के बाद बातचीत नई शुरू हुई"],
  resetBody: [
    "The connection dropped, so Sahaj no longer remembers the earlier turns. Your consent and any case with the team are kept.",
    "कनेक्शन टूट गया था, इसलिए Sahaj को पिछली बातें याद नहीं हैं। आपकी सहमति और टीम के साथ कोई मामला बना रहता है।",
  ],

  // mic
  micTitle: ["Sahaj needs your microphone", "Sahaj को आपका माइक्रोफ़ोन चाहिए"],
  micBody: [
    "Sahaj only listens while you hold the button. Your browser will ask for permission next.",
    "Sahaj सिर्फ़ तब सुनता है जब आप बटन दबाकर रखते हैं। अगले कदम में ब्राउज़र अनुमति माँगेगा।",
  ],
  micPoint1: ["Listens only while you hold", "सिर्फ़ बटन दबाने पर सुनता है"],
  micPoint2: ["Up to 30 seconds at a time", "एक बार में 30 सेकंड तक"],
  micPoint3: ["Audio is not kept after the answer", "जवाब के बाद ऑडियो नहीं रखा जाता"],
  micContinue: ["Continue", "आगे बढ़ें"],
  blockedTitle: ["Microphone is blocked", "माइक्रोफ़ोन बंद है"],
  blockedIOS: [
    "Open Settings → Safari → Microphone and choose Allow. Or tap “aA” in the address bar → Website Settings → Microphone.",
    "Settings → Safari → Microphone में Allow चुनें। या एड्रेस बार में “aA” → Website Settings → Microphone पर टैप करें।",
  ],
  blockedOther: [
    "Tap the lock icon next to the address, allow the microphone, then try again.",
    "एड्रेस के पास लॉक आइकन पर टैप करें, माइक्रोफ़ोन की अनुमति दें, फिर से कोशिश करें।",
  ],
  insecure: ["The microphone only works over a secure (https) link.", "माइक्रोफ़ोन सिर्फ़ सुरक्षित (https) लिंक पर काम करता है।"],
  noMic: ["No microphone was found on this device.", "इस डिवाइस पर माइक्रोफ़ोन नहीं मिला।"],
  unsupported: ["This browser can't record audio. Please use Safari or Chrome.", "यह ब्राउज़र ऑडियो रिकॉर्ड नहीं कर सकता। Safari या Chrome इस्तेमाल करें।"],
  gotIt: ["Got it", "ठीक है"],

  // dock
  hold: ["Hold to talk", "बोलने के लिए दबाकर रखें"],
  release: ["Release to send", "भेजने के लिए छोड़ें"],
  cancel: ["Slide to cancel", "रद्द करें"],
  sending: ["Sending…", "भेज रहे हैं…"],
  thinking: ["Thinking…", "सोच रहे हैं…"],
  tapStop: ["Tap to stop", "रोकने के लिए टैप करें"],
  human: ["Talk to a human", "इंसान से बात करें"],
  replay: ["Replay", "फिर सुनें"],
  stop: ["Stop", "रोकें"],
  mute: ["Mute", "म्यूट"],
  unmute: ["Unmute", "आवाज़ चालू"],
  tryAgain: ["Try again", "फिर कोशिश करें"],
  didntCatch: ["I didn't catch that. Try speaking a little closer.", "मैं सुन नहीं पाया। थोड़ा पास से बोलकर देखें।"],
  tooShort: ["Hold the button while you speak.", "बोलते समय बटन दबाकर रखें।"],
  micSilent: [
    "Your microphone isn't picking up any sound. Check it isn't muted, the right input is selected, and your browser is allowed to use it (on a Mac: System Settings → Privacy & Security → Microphone).",
    "आपका माइक्रोफ़ोन कोई आवाज़ नहीं ले रहा। देखें कि यह म्यूट न हो, सही इनपुट चुना हो, और ब्राउज़र को अनुमति हो (Mac पर: System Settings → Privacy & Security → Microphone)।",
  ],
  textOnly: ["Text only in this language", "इस भाषा में सिर्फ़ टेक्स्ट"],
  textOnlyNoAudio: ["Text only in this language · no audio", "इस भाषा में सिर्फ़ टेक्स्ट · ऑडियो नहीं"],
  warn: ["seconds left. Sends automatically at 0:30.", "सेकंड बाकी। 0:30 पर अपने-आप भेजा जाएगा।"],
  personWillReply: ["A person will reply", "एक व्यक्ति जवाब देगा"],
  youreOffline: ["You're offline", "आप ऑफ़लाइन हैं"],
  micBlocked: ["Microphone blocked", "माइक्रोफ़ोन बंद है"],
  pleaseWait: ["Please wait…", "कृपया रुकें…"],
  listening: ["Listening…", "सुन रहे हैं…"],
  spaceHint: ["Hold Space to talk", "बोलने के लिए Space दबाकर रखें"],
  spaceSub: ["or press and hold the button · up to 30 seconds", "या बटन दबाकर रखें · 30 सेकंड तक"],
  notSent: ["not sent", "नहीं भेजा"],

  // thinking steps (status events)
  step_transcribing: ["Listening to what you said…", "आपकी बात सुन रहे हैं…"],
  step_searching: ["Finding the right documents…", "सही दस्तावेज़ ढूँढ रहे हैं…"],
  step_comparing: ["Comparing the plans…", "प्लान की तुलना कर रहे हैं…"],
  step_calculating: ["Working out the numbers…", "गणना कर रहे हैं…"],
  step_thinking: ["Thinking…", "सोच रहे हैं…"],
  step_checking: ["Checking the answer…", "जवाब जाँच रहे हैं…"],

  // messages
  agent_insurance: ["Insurance", "बीमा"],
  agent_loan: ["Loan", "लोन"],
  agent_general: ["General", "सामान्य"],
  agent_advice: ["Insurance", "बीमा"],
  question: ["Question", "सवाल"],
  connectPerson: ["Connect me to a person", "मुझे किसी व्यक्ति से जोड़ें"],
  orAskAnother: ["Or hold the button to ask another way", "या बटन दबाकर दूसरे तरीके से पूछें"],
  jumpLatest: ["Jump to latest", "नए संदेश पर जाएँ"],
  hidden: ["hidden", "छिपा"],
  source: ["Source", "स्रोत"],

  // citations
  sources: ["Sources", "स्रोत"],
  clause: ["Clause", "क्लॉज़"],
  cited: ["cited", "उद्धृत"],
  close: ["Close", "बंद करें"],

  // cards
  emiTitle: ["EMI calculation", "EMI गणना"],
  prepayTitle: ["Prepayment", "प्रीपेमेंट"],
  loanAmount: ["Loan amount", "लोन राशि"],
  rate: ["Rate a year", "सालाना ब्याज दर"],
  tenure: ["Tenure", "अवधि"],
  months: ["months", "महीने"],
  monthlyEmi: ["Monthly EMI", "मासिक EMI"],
  totalPayment: ["Total payment", "कुल भुगतान"],
  totalInterest: ["Total interest", "कुल ब्याज"],
  principal: ["Principal", "मूलधन"],
  interest: ["Interest", "ब्याज"],
  lenderNote: ["Your lender's own figure may differ slightly.", "आपके लेंडर का आँकड़ा थोड़ा अलग हो सकता है।"],
  outstanding: ["Outstanding", "बकाया"],
  monthsLeft: ["Months left", "बचे महीने"],
  prepayment: ["Prepayment", "प्रीपेमेंट"],
  interestSaved: ["Interest saved", "बचा ब्याज"],
  monthsSaved: ["Months saved", "बचे महीने"],
  before: ["Before", "पहले"],
  after: ["After", "बाद में"],
  emi: ["EMI", "EMI"],
  monthsRow: ["Months", "महीने"],
  sameEmi: ["Same EMI, shorter loan.", "वही EMI, कम अवधि।"],
  lowerEmi: ["Same tenure, lower EMI.", "वही अवधि, कम EMI।"],
  compareTitle: ["Compare {n} plans", "{n} प्लान की तुलना"],
  compareHealth: ["Compare {n} health plans", "{n} हेल्थ प्लान की तुलना"],
  compareTerm: ["Compare {n} term plans", "{n} टर्म प्लान की तुलना"],
  compareWholeLife: ["Compare {n} whole life plans", "{n} होल लाइफ प्लान की तुलना"],
  swipeMore: ["Swipe for more", "और देखने के लिए स्वाइप करें"],
  premiumsIndicative: ["Premiums are indicative", "प्रीमियम अनुमानित हैं"],
  viewTable: ["Table", "टेबल"],
  viewList: ["List", "सूची"],
  understood: ["Here's what I understood", "मैंने यह समझा"],
  sayOne: ["Say one of these", "इनमें से कुछ बोलें"],
  sayYes: ["“Yes, that's correct”", "“हाँ, यह सही है”"],
  sayChange: ["“Change something”", "“कुछ बदलना है”"],
  planSuggestions: ["Plan suggestions", "प्लान सुझाव"],
  indicativePremiums: ["Indicative premiums", "अनुमानित प्रीमियम"],
  suggestedCover: ["Suggested cover", "सुझाया गया कवर"],
  howWorked: ["How we worked this out", "हमने यह कैसे निकाला"],
  basis: ["Basis.", "आधार।"],
  note: ["Note.", "ध्यान दें।"],
  planMatched: ["1 plan matched your needs", "1 प्लान आपकी ज़रूरतों से मेल खाता है"],
  plansMatched: ["{n} plans matched your needs", "{n} प्लान आपकी ज़रूरतों से मेल खाते हैं"],
  cover: ["Cover", "कवर"],
  indicativePremium: ["Indicative premium", "अनुमानित प्रीमियम"],
  perYear: ["/ year", "/ साल"],
  meetsCover: ["Meets the suggested cover", "सुझाए गए कवर को पूरा करता है"],
  belowCover: ["Below the suggested cover", "सुझाए गए कवर से कम"],
  whyRanks: ["Why it ranks here", "यह इस स्थान पर क्यों है"],
  scoreBy: ["Score by what matters to you", "आपके लिए ज़रूरी बातों पर स्कोर"],
  detailsScores: ["Details and scores", "विवरण और स्कोर"],
  showLess: ["Show less", "कम दिखाएँ"],
  beforeDecide: ["Before you decide", "फ़ैसला करने से पहले"],
  noPlansTitle: ["No plans matched all your needs", "कोई प्लान आपकी सभी ज़रूरतों से मेल नहीं खाता"],
  noPlansBody: [
    "Sahaj won't show a plan that doesn't fit. You can change a need, or talk to a person.",
    "Sahaj ऐसा प्लान नहीं दिखाएगा जो फ़िट न हो। आप कोई ज़रूरत बदल सकते हैं, या किसी व्यक्ति से बात कर सकते हैं।",
  ],
  openInPanel: ["Open in panel", "पैनल में खोलें"],
  latestCard: ["Latest card", "नया कार्ड"],
  preparing: ["Preparing…", "तैयार कर रहे हैं…"],

  // handoff
  handoffTitle: ["A person will take it from here", "अब एक व्यक्ति आपकी मदद करेगा"],
  handoff_user_requested: [
    "You asked to talk to a person. Someone from the team will get back to you, usually within one working day.",
    "आपने किसी व्यक्ति से बात करने को कहा। टीम से कोई आपसे संपर्क करेगा, आमतौर पर एक कार्यदिवस में।",
  ],
  handoff_guardrail_failures: [
    "I couldn't confirm the last answers from the documents I have, so a person will help instead.",
    "मैं पिछले जवाबों की पुष्टि दस्तावेज़ों से नहीं कर पाया, इसलिए एक व्यक्ति मदद करेगा।",
  ],
  handoff_stuck_in_questions: [
    "We weren't getting anywhere with the questions, so a person will help you instead.",
    "सवालों में बात आगे नहीं बढ़ रही थी, इसलिए एक व्यक्ति आपकी मदद करेगा।",
  ],
  handoffDefault: ["Someone from the team will get back to you.", "टीम से कोई आपसे संपर्क करेगा।"],
  reference: ["Your reference number", "आपका रेफ़रेंस नंबर"],
  copy: ["Copy", "कॉपी करें"],
  copied: ["Copied", "कॉपी हो गया"],
  handoffShared: [
    "Your conversation so far is shared with the person so you don't have to repeat yourself.",
    "अब तक की बातचीत उस व्यक्ति के साथ साझा की गई है ताकि आपको दोहराना न पड़े।",
  ],

  // connection
  reconnectingBanner: [
    "Reconnecting… Your conversation will continue when the line is back.",
    "फिर से जुड़ रहे हैं… कनेक्शन लौटते ही बातचीत जारी रहेगी।",
  ],
  offlineTitle: ["You're offline", "आप ऑफ़लाइन हैं"],
  offlineBody: [
    "Sahaj needs an internet connection to listen and answer. Nothing you said was lost.",
    "सुनने और जवाब देने के लिए Sahaj को इंटरनेट चाहिए। आपकी कही कोई बात खोई नहीं है।",
  ],
  retry: ["Try again", "फिर कोशिश करें"],
  serverError: ["Something went wrong on our side.", "हमारी तरफ़ से कुछ गड़बड़ हुई।"],
  tooLong: ["Sahaj took too long to answer. Please try again.", "Sahaj को जवाब देने में बहुत समय लगा। फिर कोशिश करें।"],
  notConnected: ["Not connected. Please try again in a moment.", "कनेक्शन नहीं है। थोड़ी देर में फिर कोशिश करें।"],

  // menu
  menuPrivacy: ["Privacy and consent", "गोपनीयता और सहमति"],
  conversation: ["Conversation", "बातचीत"],
  personalDetails: ["Personal details", "निजी जानकारी"],
  granted: ["Granted", "दी गई"],
  notGranted: ["Not given", "नहीं दी गई"],
  withdrawn: ["Withdrawn", "वापस ली गई"],
  withdraw: ["Withdraw", "वापस लें"],
  menuLanguages: ["Languages", "भाषाएँ"],
  fullVoice: ["Full voice", "पूरी आवाज़"],
  approxVoice: ["Approximate voice", "अनुमानित आवाज़"],
  textOnlyMode: ["Text only", "सिर्फ़ टेक्स्ट"],
  interfaceLanguage: ["App language", "ऐप की भाषा"],
  appearance: ["Appearance", "रूप"],
  themeSystem: ["System", "सिस्टम"],
  themeLight: ["Light", "लाइट"],
  themeDark: ["Dark", "डार्क"],
  menuInstall: ["Install app", "ऐप इंस्टॉल करें"],
  menuAbout: ["About Sahaj", "Sahaj के बारे में"],
  aboutBody: [
    "Sahaj explains insurance and loans by voice, answering only from approved documents and citing every fact. It does not sell anything and gives information, not financial advice.",
    "Sahaj आवाज़ से बीमा और लोन समझाता है, सिर्फ़ मंज़ूर दस्तावेज़ों से जवाब देता है और हर बात का स्रोत बताता है। यह कुछ नहीं बेचता और जानकारी देता है, वित्तीय सलाह नहीं।",
  ],
  sessionRef: ["Session reference", "सेशन रेफ़रेंस"],
  withdrawTitle: ["Withdraw consent for this conversation?", "इस बातचीत के लिए सहमति वापस लें?"],
  withdrawBody: [
    "Sahaj will stop listening and won't process anything more. The audit record of what was said so far is kept, as regulation requires.",
    "Sahaj सुनना बंद कर देगा और आगे कुछ प्रोसेस नहीं करेगा। अब तक की बातचीत का ऑडिट रिकॉर्ड नियमों के अनुसार रखा जाएगा।",
  ],
  withdrawDetailsTitle: ["Withdraw permission to use your details?", "अपनी जानकारी इस्तेमाल करने की अनुमति वापस लें?"],
  withdrawDetailsBody: [
    "Sahaj will forget the details you gave for plan suggestions. It will keep explaining and comparing plans.",
    "Sahaj प्लान सुझाव के लिए दी गई आपकी जानकारी भूल जाएगा। वह प्लान समझाता और तुलना करता रहेगा।",
  ],
  keep: ["Keep", "रहने दें"],

  // install
  installTitle: ["Add Sahaj to your home screen", "Sahaj को होम स्क्रीन पर जोड़ें"],
  installBody: ["Open it in one tap, full screen, without the browser bar.", "एक टैप में, पूरी स्क्रीन पर, बिना ब्राउज़र बार के खोलें।"],
  install: ["Install", "इंस्टॉल करें"],
  later: ["Later", "बाद में"],
  iosStep1: ["Tap the Share button in Safari's toolbar", "Safari टूलबार में Share बटन पर टैप करें"],
  iosStep2: ["Scroll down and choose “Add to Home Screen”", "नीचे स्क्रॉल करके “Add to Home Screen” चुनें"],
  iosStep3: ["Tap “Add”. Sahaj opens full screen from your home screen.", "“Add” पर टैप करें। Sahaj होम स्क्रीन से पूरी स्क्रीन पर खुलेगा।"],
  shareHere: ["Share button is here", "Share बटन यहाँ है"],

  // sign-in
  signInTitle: ["Sign in to start", "शुरू करने के लिए साइन इन करें"],
  signInBody: [
    "Your consent and any case with our team stay with your account, on every device.",
    "आपकी सहमति और हमारी टीम के साथ कोई भी मामला आपके खाते में रहता है, हर डिवाइस पर।",
  ],
  signInGoogle: ["Continue with Google", "Google से जारी रखें"],
  signInUnavailable: [
    "Sign-in isn't set up on this server yet (GOOGLE_CLIENT_IDS or JWT_SECRET missing).",
    "इस सर्वर पर साइन-इन अभी सेट नहीं है (Google client id या JWT secret नहीं है)।",
  ],
  serverUnreachable: ["Can't reach Sahaj right now.", "अभी Sahaj से कनेक्ट नहीं हो पा रहा।"],
  sessionEnded: ["You were signed out. Please sign in again.", "आप साइन आउट हो गए। फिर से साइन इन करें।"],
  account: ["Account", "खाता"],
  signOut: ["Sign out", "साइन आउट"],

  // person from the team
  waitingForPerson: ["Waiting for someone from the team", "टीम से किसी का इंतज़ार"],
  withAgent: ["You're talking to {name}", "आप {name} से बात कर रहे हैं"],
  talkToPersonHint: ["Hold the button to talk to them. Sahaj isn't answering for now.", "उनसे बात करने के लिए बटन दबाकर रखें। अभी Sahaj जवाब नहीं दे रहा।"],
  cancelHandoff: ["I don't need help any more", "अब मदद की ज़रूरत नहीं"],
  agentJoined: ["{name} from the team joined", "टीम से {name} जुड़े"],
  agentLeft: ["The person stepped away. You're back in the queue.", "व्यक्ति चले गए। आप फिर से कतार में हैं।"],
  kycScheduled: ["Video KYC scheduled for {when}", "वीडियो KYC {when} के लिए तय"],
  caseResolved: ["The team closed your case. Sahaj is answering again.", "टीम ने आपका मामला बंद किया। Sahaj फिर से जवाब दे रहा है।"],
  caseCancelled: ["Back with Sahaj.", "फिर से Sahaj के साथ।"],
  fromTeam: ["Sahaj team", "Sahaj टीम"],
  holdToPerson: ["Hold to talk to them", "उनसे बात करने के लिए दबाएँ"],

  // budget
  budgetWarning: ["You've used {pct}% of this month's allowance.", "आपने इस महीने की सीमा का {pct}% इस्तेमाल किया है।"],
  budgetExceeded: ["You've used this month's allowance.", "आपने इस महीने की सीमा पूरी कर ली है।"],
  budgetResets: ["It renews on {date}.", "यह {date} को फिर शुरू होगी।"],

  // trust and feedback
  verified: ["Verified · {n} sources", "सत्यापित · {n} स्रोत"],
  verifiedOne: ["Verified · 1 source", "सत्यापित · 1 स्रोत"],
  engine: ["Calculated", "गणना से"],
  checked: ["Checked", "जाँचा गया"],
  trustTitle: ["How Sahaj checks its answers", "Sahaj अपने जवाब कैसे जाँचता है"],
  trustWhat: ["What this label means", "इस लेबल का मतलब"],
  trustThis: ["This answer", "यह जवाब"],
  trustVerifiedName: ["Verified", "सत्यापित"],
  trustVerifiedBody: [
    "Every fact comes from an approved document and was checked against it. Tap a number in the answer to see the source.",
    "हर बात किसी मंज़ूर दस्तावेज़ से ली गई है और उससे मिलाकर जाँची गई है। स्रोत देखने के लिए जवाब में दिए नंबर पर टैप करें।",
  ],
  trustEngineBody: [
    "The figures come from Sahaj's own calculator or plan comparison, not from a written answer.",
    "ये आँकड़े Sahaj के अपने कैलकुलेटर या प्लान तुलना से आए हैं, लिखे हुए जवाब से नहीं।",
  ],
  trustCheckedBody: [
    "Screened by our safety checks. It states no facts from documents, so there is no source to show.",
    "हमारी सुरक्षा जाँच से गुज़रा है। इसमें दस्तावेज़ों की कोई जानकारी नहीं है, इसलिए दिखाने के लिए कोई स्रोत नहीं है।",
  ],
  trustBlocked: [
    "If an answer fails these checks, Sahaj doesn't show it and tells you it can't confirm that.",
    "अगर कोई जवाब इन जाँचों में पास नहीं होता, तो Sahaj उसे नहीं दिखाता और बताता है कि वह इसकी पुष्टि नहीं कर सकता।",
  ],
  helpful: ["Helpful", "उपयोगी"],
  notHelpful: ["Not helpful", "उपयोगी नहीं"],
  feedbackFailed: ["Couldn't save your rating.", "आपकी रेटिंग सेव नहीं हो सकी।"],
  askNext: ["You could ask", "आप पूछ सकते हैं"],
} satisfies Record<string, [string, string]>;

export type StringKey = keyof typeof S;
export type UiLang = "en" | "hi";

export function translate(lang: UiLang, key: StringKey, vars?: Record<string, string | number>): string {
  let s = S[key][lang === "hi" ? 1 : 0];
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, String(v));
  return s;
}

/** A key of the string table (as opposed to a message from the server). */
export function isStringKey(value: string): value is StringKey {
  return Object.prototype.hasOwnProperty.call(S, value);
}

/** const t = useT(); t("hold") */
export function useT() {
  const lang = useUi((s) => s.lang);
  return (key: StringKey, vars?: Record<string, string | number>) => translate(lang, key, vars);
}
