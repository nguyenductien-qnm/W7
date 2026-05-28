import { useEffect, useMemo, useRef, useState } from "react";

const DEFAULT_API_BASE = "https://3sgavxe4c0.execute-api.ap-southeast-1.amazonaws.com";
const LOCAL_USER = new URLSearchParams(window.location.search).get("user") || "test-user-001";
const API_BASE = (
  new URLSearchParams(window.location.search).get("api") || DEFAULT_API_BASE
).replace(/\/$/, "");

const FEATURES = {
  chat: { label: "Chat", placeholder: "Ask about the selected documents..." },
  summary: { label: "Summary", placeholder: "Summarize the selected documents..." },
  quiz: { label: "Quiz", placeholder: "Quiz me on the selected documents..." },
  flashcards: { label: "Flash Cards", placeholder: "Create review cards from the selected documents..." },
  planning: { label: "Exam Planner", placeholder: "Exam date and hours, e.g. 2026-06-20, 2 hours daily..." },
};

const FEATURE_MENU = [
  { key: "chat", label: "Chat with Docs", icon: "chat" },
  { key: "summary", label: "Summarize Docs", icon: "summary" },
  { key: "flashcards", label: "Flash Cards", icon: "cards" },
  { key: "quiz", label: "Quiz", icon: "quiz" },
  { key: "planning", label: "Exam Planner", icon: "calendar" },
];

function uid(prefix) {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

function nowLabel(value) {
  return new Date(value || Date.now()).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function getSavedAuth() {
  return {
    userId: sessionStorage.getItem("studybot_user_id") || "",
    email: sessionStorage.getItem("studybot_email") || "",
  };
}

function safeArray(value) {
  return Array.isArray(value) ? value : [];
}

function docTitle(doc) {
  return doc?.filename || doc?.name || doc?.title || doc?.doc_id || "Untitled";
}

function isReady(doc) {
  const status = String(doc?.status || "").toUpperCase();
  const kbStatus = String(doc?.kb_status || "").toUpperCase();
  return status === "COMPLETE" || kbStatus === "READY";
}

function storageKey(userId, name) {
  return `studybot:${name}:${userId || LOCAL_USER}`;
}

function loadJson(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key) || "") || fallback;
  } catch {
    return fallback;
  }
}

function renderQuizText(questions) {
  return questions
    .map((q, idx) => {
      const options = safeArray(q.options)
        .map((op, i) => `${String.fromCharCode(65 + i)}. ${op}`)
        .join("\n");
      const note = q.explanation ? `\nNote: ${q.explanation}` : "";
      return `${idx + 1}. ${q.question || ""}\n${options}\nAnswer: ${q.answer || ""}${note}`;
    })
    .join("\n\n");
}

function answerIndex(question) {
  const options = safeArray(question.options);
  if (Number.isInteger(question.answer_index)) return question.answer_index;
  const answer = String(question.answer || "").trim();
  const letter = answer.match(/^[A-D]$/i);
  if (letter) return letter[0].toUpperCase().charCodeAt(0) - 65;
  const exact = options.findIndex((option) => String(option).trim() === answer);
  return exact >= 0 ? exact : 0;
}

function renderInlineMarkdown(text, keyPrefix, citations = [], messageId = "", onOpenCitation = null) {
  if (!text) return null;
  const citationPattern = /(\[(?:\d+(?:,\s*)?)+\])/g;
  const citationParts = String(text).split(citationPattern);
  const nodes = [];
  const inlinePattern = /\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g;

  citationParts.forEach((part, partIndex) => {
    const citationMatch = part.match(/^\[((?:\d+(?:,\s*)?)+)\]$/);
    if (citationMatch) {
      const numbers = citationMatch[1]
        .split(",")
        .map((value) => Number(value.trim()))
        .filter((value) => Number.isInteger(value) && value >= 1 && value <= citations.length);
      if (numbers.length) {
        nodes.push(
          <span className="citation-inline" key={`${keyPrefix}-cite-${partIndex}`}>
            {numbers.map((number) => (
              <button
                key={`${keyPrefix}-cite-btn-${number}`}
                type="button"
                onClick={() => onOpenCitation?.(messageId, number - 1)}
              >
                [{number}]
              </button>
            ))}
          </span>
        );
        return;
      }
    }

    let cursor = 0;
    let match;
    while ((match = inlinePattern.exec(part)) !== null) {
      if (match.index > cursor) {
        nodes.push(<span key={`${keyPrefix}-txt-${partIndex}-${cursor}`}>{part.slice(cursor, match.index)}</span>);
      }
      if (match[1]) {
        nodes.push(<strong key={`${keyPrefix}-b-${partIndex}-${match.index}`}>{match[1]}</strong>);
      } else if (match[2]) {
        nodes.push(<code key={`${keyPrefix}-c-${partIndex}-${match.index}`}>{match[2]}</code>);
      } else if (match[3] && match[4]) {
        nodes.push(
          <a
            key={`${keyPrefix}-a-${partIndex}-${match.index}`}
            href={match[4]}
            target="_blank"
            rel="noreferrer noopener"
          >
            {match[3]}
          </a>
        );
      }
      cursor = match.index + match[0].length;
    }
    if (cursor < part.length) {
      nodes.push(<span key={`${keyPrefix}-tail-${partIndex}`}>{part.slice(cursor)}</span>);
    }
    inlinePattern.lastIndex = 0;
  });

  return nodes;
}

function renderMarkdownText(text, messageId, citations = [], onOpenCitation = null) {
  if (!text) return null;
  const blocks = [];
  const lines = String(text).replace(/\r\n/g, "\n").split("\n");
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i += 1;
      continue;
    }

    if (line.startsWith("```")) {
      i += 1;
      const codeLines = [];
      while (i < lines.length && !lines[i].startsWith("```")) {
        codeLines.push(lines[i]);
        i += 1;
      }
      if (i < lines.length) i += 1;
      blocks.push(
        <pre key={`pre-${blocks.length}`}>
          <code>{codeLines.join("\n")}</code>
        </pre>
      );
      continue;
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      const level = Math.min(3, heading[1].length);
      const Tag = `h${level}`;
      blocks.push(
        <Tag key={`h-${blocks.length}`}>
          {renderInlineMarkdown(heading[2], `h-${blocks.length}`, citations, messageId, onOpenCitation)}
        </Tag>
      );
      i += 1;
      continue;
    }

    if (/^[-*]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^[-*]\s+/, ""));
        i += 1;
      }
      blocks.push(
        <ul key={`ul-${blocks.length}`}>
          {items.map((item, idx) => (
            <li key={`ul-${blocks.length}-${idx}`}>
              {renderInlineMarkdown(item, `ul-${blocks.length}-${idx}`, citations, messageId, onOpenCitation)}
            </li>
          ))}
        </ul>
      );
      continue;
    }

    if (/^\d+\.\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\d+\.\s+/, ""));
        i += 1;
      }
      blocks.push(
        <ol key={`ol-${blocks.length}`}>
          {items.map((item, idx) => (
            <li key={`ol-${blocks.length}-${idx}`}>
              {renderInlineMarkdown(item, `ol-${blocks.length}-${idx}`, citations, messageId, onOpenCitation)}
            </li>
          ))}
        </ol>
      );
      continue;
    }

    const paragraphLines = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !lines[i].startsWith("```") &&
      !/^(#{1,3})\s+/.test(lines[i]) &&
      !/^[-*]\s+/.test(lines[i]) &&
      !/^\d+\.\s+/.test(lines[i])
    ) {
      paragraphLines.push(lines[i]);
      i += 1;
    }
    const paragraphText = paragraphLines.join("\n");
    blocks.push(
        <p key={`p-${blocks.length}`}>
          {renderInlineMarkdown(paragraphText, `p-${blocks.length}`, citations, messageId, onOpenCitation)}
        </p>
      );
  }

  return <div className="markdown-body">{blocks}</div>;
}

function flashcardBack(question) {
  const options = safeArray(question.options);
  const correctIndex = answerIndex(question);
  const answerText = options[correctIndex] || String(question.answer || "").trim();
  const explanation = String(question.explanation || "").trim();
  return [answerText, explanation].filter(Boolean).join("\n\n");
}

function cleanFlashcardBack(value) {
  return String(value || "").replace(/^[A-D](?:[.)-]|\s+)+/i, "").trimStart();
}

function parsePlannerPrompt(prompt) {
  const text = String(prompt || "");
  const examDate = text.match(/\b(20\d{2}-\d{2}-\d{2})\b/)?.[1] || "";
  const daily = text.match(/(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\s*(?:per\s+day|daily|\/\s*day)/i);
  const weekly = text.match(/(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\s*(?:per\s+week|weekly|\/\s*week)/i);
  const sessionLength = text.match(/(\d+)\s*(?:minutes?|mins?|m)\s*(?:sessions?|session length)/i);
  const weakTopics = text.match(/weak topics?\s*:\s*([^.;]+)/i)?.[1];
  const excludedDays = text.match(/(?:exclude|excluded days?)\s*:\s*([^.;]+)/i)?.[1];
  const targetGrade = text.match(/(?:target grade|goal)\s*:\s*([^.;]+)/i)?.[1]?.trim();
  return {
    exam_date: examDate,
    daily_study_hours: daily ? Number(daily[1]) : undefined,
    weekly_study_hours: weekly ? Number(weekly[1]) : undefined,
    preferred_session_length: sessionLength ? Number(sessionLength[1]) : undefined,
    weak_topics: weakTopics ? weakTopics.split(",").map((item) => item.trim()).filter(Boolean) : undefined,
    excluded_days: excludedDays ? excludedDays.split(",").map((item) => item.trim()).filter(Boolean) : undefined,
    target_grade: targetGrade,
  };
}

function renderPlanText(plan) {
  const tasks = safeArray(plan?.tasks);
  const lines = [plan?.summary || "Exam plan ready.", ""];
  tasks.slice(0, 12).forEach((task) => {
    lines.push(`${task.date}: ${task.duration_minutes} min ${task.activity} - ${task.topic}`);
  });
  if (tasks.length > 12) lines.push(`...and ${tasks.length - 12} more sessions.`);
  return lines.join("\n").trim();
}

function dateLabel(value) {
  if (!value) return "";
  return new Date(value).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
}

function MenuIcon({ name }) {
  const common = {
    className: "menu-icon",
    viewBox: "0 0 24 24",
    "aria-hidden": "true",
  };
  if (name === "summary") {
    return (
      <svg {...common}>
        <path d="M7 3h7l4 4v14H7z" />
        <path d="M14 3v5h5" />
        <path d="M9 12h6" />
        <path d="M9 16h6" />
      </svg>
    );
  }
  if (name === "cards") {
    return (
      <svg {...common}>
        <rect x="4" y="7" width="12" height="10" rx="2" />
        <path d="M8 7V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2" />
        <path d="M8 12h4" />
      </svg>
    );
  }
  if (name === "quiz") {
    return (
      <svg {...common}>
        <path d="M21 12a9 9 0 1 1-3-6.7" />
        <path d="M21 4l-9 9" />
        <path d="M12 13l-3-3" />
      </svg>
    );
  }
  if (name === "calendar") {
    return (
      <svg {...common}>
        <rect x="4" y="5" width="16" height="15" rx="2" />
        <path d="M8 3v4" />
        <path d="M16 3v4" />
        <path d="M4 10h16" />
      </svg>
    );
  }
  if (name === "upload") {
    return (
      <svg {...common}>
        <path d="M12 16V4" />
        <path d="M7 9l5-5 5 5" />
        <path d="M5 20h14" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z" />
    </svg>
  );
}

export default function App() {
  const [auth, setAuth] = useState(getSavedAuth());
  const [loginEmail, setLoginEmail] = useState(getSavedAuth().email || "");
  const [apiStatus, setApiStatus] = useState({ label: "Checking API", tone: "idle" });
  const [theme, setTheme] = useState(localStorage.getItem("studybot-theme") || "light");

  const currentUserId = auth.userId || LOCAL_USER;
  const [sessions, setSessions] = useState(() =>
    loadJson(storageKey(currentUserId, "sessions"), [
      { id: "default", name: "Default Session", createdAt: new Date().toISOString() },
    ])
  );
  const [activeSessionId, setActiveSessionId] = useState(() =>
    localStorage.getItem(storageKey(currentUserId, "active-session")) || "default"
  );
  const [messagesBySession, setMessagesBySession] = useState({});

  const [docs, setDocs] = useState([]);
  const [plans, setPlans] = useState([]);
  const [activePlan, setActivePlan] = useState(null);
  const [selectedDocIds, setSelectedDocIds] = useState(() =>
    loadJson(storageKey(currentUserId, "selected-docs"), [])
  );
  const [contextLimit, setContextLimit] = useState(() =>
    Number(localStorage.getItem(storageKey(currentUserId, "context-limit")) || 5)
  );

  const [activeFeature, setActiveFeature] = useState("chat");
  const [plannerOpen, setPlannerOpen] = useState(false);
  const [input, setInput] = useState("");
  const [plusOpen, setPlusOpen] = useState(false);
  const [fileModalOpen, setFileModalOpen] = useState(false);
  const [sessionModalOpen, setSessionModalOpen] = useState(false);
  const [newSessionName, setNewSessionName] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [toast, setToast] = useState("");
  const [debugOpen, setDebugOpen] = useState(false);
  const [debugText, setDebugText] = useState("No requests yet.");
  const [busy, setBusy] = useState({
    docs: false,
    upload: false,
    login: false,
    send: false,
    plans: false,
  });

  const chatRef = useRef(null);
  const fileInputRef = useRef(null);

  const activeSession = sessions.find((session) => session.id === activeSessionId) || sessions[0];
  const messages = messagesBySession[activeSessionId] || [];
  const selectedDocs = docs.filter((doc) => selectedDocIds.includes(doc.doc_id));
  const readyDocs = docs.filter(isReady);
  const selectedReadyCount = selectedDocs.filter(isReady).length;
  const canSend =
    input.trim() &&
    !busy.send &&
    (activeFeature === "planning" ? readyDocs.length > 0 : selectedDocIds.length > 0);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("studybot-theme", theme);
  }, [theme]);

  useEffect(() => {
    localStorage.setItem(storageKey(currentUserId, "sessions"), JSON.stringify(sessions));
  }, [sessions, currentUserId]);

  useEffect(() => {
    localStorage.setItem(storageKey(currentUserId, "active-session"), activeSessionId);
  }, [activeSessionId, currentUserId]);

  useEffect(() => {
    localStorage.setItem(storageKey(currentUserId, "selected-docs"), JSON.stringify(selectedDocIds));
  }, [selectedDocIds, currentUserId]);

  useEffect(() => {
    localStorage.setItem(storageKey(currentUserId, "context-limit"), String(contextLimit));
  }, [contextLimit, currentUserId]);

  useEffect(() => {
    chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight, behavior: "smooth" });
  }, [activeSessionId, messages.length]);

  useEffect(() => {
    async function boot() {
      setMessagesBySession({});
      await refreshSessions();
      await refreshDocs();
      await refreshPlans(activeSessionId);
    }
    boot();
  }, [currentUserId]);

  useEffect(() => {
    refreshDocs();
    refreshHistory(activeSessionId);
    refreshPlans(activeSessionId);
  }, [activeSessionId]);

  useEffect(() => {
    function onKeyDown(event) {
      if ((event.ctrlKey || event.metaKey) && event.key === "`") {
        event.preventDefault();
        setDebugOpen((prev) => !prev);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  function setBusyFlag(key, value) {
    setBusy((prev) => ({ ...prev, [key]: value }));
  }

  function showToast(message) {
    setToast(message);
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => setToast(""), 3200);
  }

  function pushLog(label, body) {
    setDebugText((prev) => {
      const existing = prev === "No requests yet." ? "" : prev;
      const next =
        `${new Date().toLocaleTimeString()} ${label}\n` +
        `${JSON.stringify(body, null, 2)}\n\n${existing}`;
      return next.slice(0, 12000);
    });
  }

  async function call(path, opts = {}) {
    const headers = new Headers(opts.headers || {});
    headers.set("X-User-Id", currentUserId);
    headers.set("X-Session-Id", activeSessionId);
    if (opts.json) headers.set("Content-Type", "application/json");

    const fetchOptions = { ...opts, headers };
    if (opts.json) {
      fetchOptions.body = JSON.stringify(opts.json);
      delete fetchOptions.json;
    }

    const res = await fetch(`${API_BASE}${path}`, fetchOptions);
    const text = await res.text();
    let body;
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
    pushLog(`${opts.method || "GET"} ${path}`, body);
    if (!res.ok) throw new Error(body?.detail || body?.message || `HTTP ${res.status}`);
    return body;
  }

  async function refreshDocs() {
    setBusyFlag("docs", true);
    try {
      const body = await call(`/docs/list?session_id=${encodeURIComponent(activeSessionId)}`);
      const nextDocs = safeArray(body.docs || body.documents);
      setDocs(nextDocs);
      setSelectedDocIds((prev) => prev.filter((id) => nextDocs.some((doc) => doc.doc_id === id)));
      setApiStatus({ label: "API online", tone: "online" });
    } catch (err) {
      setApiStatus({ label: "API offline", tone: "offline" });
      showToast(err.message);
    } finally {
      setBusyFlag("docs", false);
    }
  }

  function normalizeHistoryMessages(value) {
    return safeArray(value).map((message) => ({
      id: message.id || uid("msg"),
      role: message.role || "bot",
      feature: message.feature || "chat",
      text: message.text || "",
      citations: safeArray(message.citations),
      quiz: safeArray(message.quiz),
      cards: safeArray(message.cards),
      plan: message.plan || null,
      createdAt: message.createdAt || message.created_at || new Date().toISOString(),
    }));
  }

  async function refreshHistory(sessionId = activeSessionId) {
    try {
      const body = await call(`/history?session_id=${encodeURIComponent(sessionId)}`);
      const historyMessages = normalizeHistoryMessages(body.messages);
      setMessagesBySession((prev) => ({ ...prev, [sessionId]: historyMessages }));
    } catch (err) {
      showToast(`History load failed: ${err.message}`);
    }
  }

  async function refreshSessions() {
    try {
      const body = await call("/session/list");
      const nextSessions = safeArray(body.sessions).map((session) => ({
        id: session.session_id || session.id,
        name: session.session_name || session.name || "Study Session",
        createdAt: session.created_at || new Date().toISOString(),
      }));
      if (nextSessions.length) {
        setSessions(nextSessions);
        setActiveSessionId((prev) =>
          nextSessions.some((session) => session.id === prev) ? prev : nextSessions[0].id
        );
      }
    } catch (err) {
      showToast(err.message);
    }
  }

  async function login() {
    const email = loginEmail.trim().toLowerCase();
    if (!email) {
      showToast("Enter an email to sign in.");
      return;
    }
    setBusyFlag("login", true);
    try {
      const body = await call("/login", { method: "POST", json: { email } });
      const nextAuth = { userId: body.user_id || LOCAL_USER, email };
      sessionStorage.setItem("studybot_user_id", nextAuth.userId);
      sessionStorage.setItem("studybot_email", nextAuth.email);
      setAuth(nextAuth);
      showToast("Signed in.");
    } catch (err) {
      showToast(`Login failed: ${err.message}`);
    } finally {
      setBusyFlag("login", false);
    }
  }

  function logout() {
    sessionStorage.removeItem("studybot_user_id");
    sessionStorage.removeItem("studybot_email");
    setAuth({ userId: "", email: "" });
    setLoginEmail("");
  }

  function addMessage(message) {
    const next = { id: uid("msg"), createdAt: new Date().toISOString(), ...message };
    setMessagesBySession((prev) => ({
      ...prev,
      [activeSessionId]: [...(prev[activeSessionId] || []), next],
    }));
    return next.id;
  }

  function updateMessage(messageId, patch) {
    setMessagesBySession((prev) => ({
      ...prev,
      [activeSessionId]: (prev[activeSessionId] || []).map((message) =>
        message.id === messageId ? { ...message, ...patch } : message
      ),
    }));
  }

  function clearChat() {
    setMessagesBySession((prev) => ({ ...prev, [activeSessionId]: [] }));
  }

  function selectFeature(key) {
    setActiveFeature(key);
    if (key === "planning") setPlannerOpen(true);
    setPlusOpen(false);
  }

  async function refreshPlans(sessionId = activeSessionId) {
    setBusyFlag("plans", true);
    try {
      const body = await call(`/planner?session_id=${encodeURIComponent(sessionId)}`);
      const nextPlans = safeArray(body.plans);
      setPlans(nextPlans);
      setActivePlan((prev) => {
        if (prev && nextPlans.some((plan) => plan.plan_id === prev.plan_id)) return prev;
        return nextPlans[0] || null;
      });
    } catch (err) {
      showToast(`Planner load failed: ${err.message}`);
    } finally {
      setBusyFlag("plans", false);
    }
  }

  async function openPlan(planId) {
    if (!planId) return;
    try {
      const body = await call(`/planner/${encodeURIComponent(planId)}?session_id=${encodeURIComponent(activeSessionId)}`);
      setActivePlan(body);
      setPlannerOpen(true);
    } catch (err) {
      showToast(err.message);
    }
  }

  function applyPlanDocIds(docIds, label = "Plan documents selected.") {
    const readyDocIds = new Set(readyDocs.map((doc) => doc.doc_id));
    const nextIds = safeArray(docIds)
      .map((docId) => String(docId || ""))
      .filter((docId) => docId && readyDocIds.has(docId))
      .slice(0, contextLimit || 99);
    if (!nextIds.length) {
      showToast("No ready documents from this plan are available in the active session.");
      return;
    }
    setSelectedDocIds(nextIds);
    setActiveFeature("chat");
    showToast(label);
  }

  async function recommendPlanDocs(planId) {
    if (!planId) return;
    setBusyFlag("plans", true);
    try {
      const body = await call(
        `/planner/${encodeURIComponent(planId)}/recommend-docs?session_id=${encodeURIComponent(activeSessionId)}`,
        {
          method: "POST",
          json: { user_id: currentUserId, session_id: activeSessionId, limit: contextLimit || 5 },
        }
      );
      const recommendedDocs = safeArray(body.recommended_documents);
      const recommendedIds = safeArray(body.recommended_doc_ids);
      setActivePlan((prev) =>
        prev?.plan_id === planId
          ? { ...prev, recommended_documents: recommendedDocs, recommended_doc_ids: recommendedIds }
          : prev
      );
      applyPlanDocIds(recommendedIds, `Selected ${recommendedIds.length} relevant plan document${recommendedIds.length === 1 ? "" : "s"}.`);
    } catch (err) {
      showToast(err.message);
    } finally {
      setBusyFlag("plans", false);
    }
  }

  async function deletePlan(planId) {
    if (!planId) return;
    try {
      await call(`/planner/${encodeURIComponent(planId)}?session_id=${encodeURIComponent(activeSessionId)}`, {
        method: "DELETE",
      });
      setPlans((prev) => prev.filter((plan) => plan.plan_id !== planId));
      setActivePlan((prev) => (prev?.plan_id === planId ? null : prev));
      showToast("Plan deleted.");
    } catch (err) {
      showToast(err.message);
    }
  }

  async function createSession(name) {
    const desiredName = name.trim() || "New Session";
    try {
      const body = await call("/session/create", {
        method: "POST",
        json: { user_id: currentUserId, session_name: desiredName },
      });
      const saved = body.session || {};
      const session = {
        id: saved.session_id || saved.id || uid("session"),
        name: saved.session_name || saved.name || desiredName,
        createdAt: saved.created_at || new Date().toISOString(),
      };
      setSessions((prev) => [session, ...prev.filter((item) => item.id !== session.id)]);
      setActiveSessionId(session.id);
      setSelectedDocIds([]);
      setSessionModalOpen(false);
      setNewSessionName("");
    } catch (err) {
      showToast(err.message);
    }
  }

  async function deleteSession(sessionId) {
    try {
      await call(`/session/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
    } catch (err) {
      showToast(err.message);
      return;
    }
    const nextSessions = sessions.filter((session) => session.id !== sessionId);
    if (!nextSessions.length) return;
    setSessions(nextSessions);
    setMessagesBySession((prev) => {
      const next = { ...prev };
      delete next[sessionId];
      return next;
    });
    if (sessionId === activeSessionId) {
      setActiveSessionId(nextSessions[0].id);
      setSelectedDocIds([]);
    }
  }

  function toggleDoc(docId) {
    setSelectedDocIds((prev) => {
      if (prev.includes(docId)) return prev.filter((id) => id !== docId);
      if (contextLimit && prev.length >= contextLimit) {
        showToast(`Context limit is ${contextLimit} document${contextLimit === 1 ? "" : "s"}.`);
        return prev;
      }
      return [...prev, docId];
    });
  }

  function autoSelectReady() {
    const max = contextLimit || readyDocs.length;
    setSelectedDocIds(readyDocs.slice(0, max).map((doc) => doc.doc_id));
  }

  async function requestUploadIntent(file) {
    const payload = {
      filename: file.name,
      title: file.name,
      content_type: file.type || "application/octet-stream",
      size: file.size,
      user_id: currentUserId,
      session_id: activeSessionId,
    };
    const endpoints = ["/documents/upload-url", "/upload/presign"];
    for (const path of endpoints) {
      try {
        const body = await call(path, { method: "POST", json: payload });
        if (body.upload_url || body.presigned_url || body.url) return body;
      } catch {
        // Try the compatibility route before falling back.
      }
    }
    return null;
  }

  async function uploadWithPresignedUrl(intent, file) {
    const uploadUrl = intent.upload_url || intent.presigned_url || intent.url || "";
    const method = String(intent.upload_method || intent.method || "PUT").toUpperCase();
    if (!uploadUrl) throw new Error("Missing presigned upload URL.");

    if (method === "POST" && intent.fields && typeof intent.fields === "object") {
      const form = new FormData();
      Object.entries(intent.fields).forEach(([key, value]) => form.append(key, value));
      form.append("file", file);
      const res = await fetch(uploadUrl, { method: "POST", body: form });
      pushLog(`POST S3 ${intent.s3_key || uploadUrl}`, { status: res.status, ok: res.ok });
      if (!res.ok) throw new Error(`S3 POST failed: HTTP ${res.status}`);
      return;
    }

    const res = await fetch(uploadUrl, {
      method: "PUT",
      headers: {
        "Content-Type": file.type || "application/octet-stream",
        ...(intent.headers || {}),
      },
      body: file,
    });
    pushLog(`PUT S3 ${intent.s3_key || uploadUrl}`, { status: res.status, ok: res.ok });
    if (!res.ok) throw new Error(`S3 PUT failed: HTTP ${res.status}`);
  }

  async function completeUpload(intent) {
    const completePath =
      intent.complete_path || intent.complete_url || (intent.doc_id ? `/documents/${intent.doc_id}/complete` : "");
    if (!completePath) return null;
    if (completePath.startsWith("http://") || completePath.startsWith("https://")) {
      const res = await fetch(completePath, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-User-Id": currentUserId },
        body: JSON.stringify({ doc_id: intent.doc_id, s3_key: intent.s3_key, session_id: activeSessionId }),
      });
      if (!res.ok) throw new Error(`Complete upload failed: HTTP ${res.status}`);
      const body = await res.json();
      pushLog(`POST complete ${completePath}`, body);
      return body;
    }
    return call(completePath, {
      method: "POST",
      json: { doc_id: intent.doc_id, s3_key: intent.s3_key, session_id: activeSessionId },
    });
  }

  async function directUpload(file) {
    const form = new FormData();
    form.append("file", file);
    form.append("user_id", currentUserId);
    form.append("session_id", activeSessionId);
    const res = await fetch(`${API_BASE}/upload`, {
      method: "POST",
      headers: { "X-User-Id": currentUserId },
      body: form,
    });
    const text = await res.text();
    let body;
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
    if (!res.ok) throw new Error(body?.detail || body?.message || `Upload failed: HTTP ${res.status}`);
    pushLog("POST /upload", body);
    return body;
  }

  async function uploadFiles(files) {
    const list = [...files];
    if (!list.length) return;
    setBusyFlag("upload", true);
    setPlusOpen(false);
    try {
      for (const file of list) {
        showToast(`Uploading ${file.name}...`);
        const intent = await requestUploadIntent(file);
        let docId = "";
        if (intent) {
          await uploadWithPresignedUrl(intent, file);
          const complete = await completeUpload(intent);
          docId = intent.doc_id || complete?.doc_id || "";
        } else {
          const body = await directUpload(file);
          docId = body.doc_id || "";
        }
        if (docId) {
          setSelectedDocIds((prev) => [docId, ...prev.filter((id) => id !== docId)].slice(0, contextLimit || 99));
        }
      }
      await refreshDocs();
      showToast("Upload complete. Processing may take a minute.");
    } catch (err) {
      showToast(err.message);
    } finally {
      setBusyFlag("upload", false);
    }
  }

  function openCitation(messageId, index) {
    updateMessage(messageId, {
      openCitations: {
        ...(messages.find((message) => message.id === messageId)?.openCitations || {}),
        [index]: true,
      },
    });
    window.requestAnimationFrame(() => {
      document.getElementById(`source-${messageId}-${index + 1}`)?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    });
  }

  function toggleCitation(messageId, index) {
    const message = messages.find((item) => item.id === messageId);
    updateMessage(messageId, {
      openCitations: {
        ...(message?.openCitations || {}),
        [index]: !message?.openCitations?.[index],
      },
    });
  }

  async function send() {
    const prompt = input.trim();
    if (!prompt || busy.send) return;
    if (activeFeature !== "planning" && !selectedDocIds.length) {
      showToast("Select at least one document for context.");
      setFileModalOpen(true);
      return;
    }
    if (activeFeature === "planning" && !readyDocs.length) {
      showToast("Upload documents and wait for processing before planning.");
      setFileModalOpen(true);
      return;
    }

    const scopedDocIds = selectedDocIds.slice(0, contextLimit || selectedDocIds.length);
    setInput("");
    setBusyFlag("send", true);
    addMessage({ role: "user", feature: activeFeature, text: prompt });
    const botId = addMessage({
      role: "bot",
      feature: activeFeature,
      text: "Working from the selected documents...",
      citations: [],
      loading: true,
    });

    try {
      if (activeFeature === "chat") {
        const body = await call("/ask", {
          method: "POST",
          json: {
            user_id: currentUserId,
            session_id: activeSessionId,
            doc_id: scopedDocIds[0],
            selected_doc_ids: scopedDocIds,
            question: prompt,
          },
        });
        updateMessage(botId, {
          text: body.answer || "No answer returned.",
          citations: safeArray(body.citations || body.citation),
          loading: false,
        });
      } else if (activeFeature === "summary") {
        const body = await call("/summary", {
          method: "POST",
          json: {
            user_id: currentUserId,
            session_id: activeSessionId,
            doc_id: scopedDocIds[0],
            selected_doc_ids: scopedDocIds,
            question: prompt,
          },
        });
        const concepts = safeArray(body.testable_concepts);
        updateMessage(botId, {
          text: `${body.summary || "No summary returned."}${
            concepts.length ? `\n\nTestable concepts:\n${concepts.map((c, i) => `${i + 1}. ${c}`).join("\n")}` : ""
          }`,
          loading: false,
        });
      } else if (activeFeature === "quiz") {
        const body = await call("/quiz", {
          method: "POST",
          json: {
            user_id: currentUserId,
            session_id: activeSessionId,
            doc_id: scopedDocIds[0],
            selected_doc_ids: scopedDocIds,
            feature: "quiz",
            question: prompt,
            difficulty: "medium",
            count: 5,
          },
        });
        const questions = safeArray(body.questions);
        updateMessage(botId, {
          text: questions.length ? "Quiz ready." : "No quiz questions returned.",
          quiz: questions,
          loading: false,
        });
      } else if (activeFeature === "flashcards") {
        const body = await call("/quiz", {
          method: "POST",
          json: {
            user_id: currentUserId,
            session_id: activeSessionId,
            doc_id: scopedDocIds[0],
            selected_doc_ids: scopedDocIds,
            feature: "flashcards",
            question: prompt,
            difficulty: "easy",
            count: 6,
          },
        });
        const cards = safeArray(body.questions).map((q) => ({
          id: uid("card"),
          front: q.question || "",
          back: flashcardBack(q),
        }));
        updateMessage(botId, {
          text: cards.length ? `Created ${cards.length} flash cards.` : "No flash cards returned.",
          cards,
          loading: false,
        });
      } else {
        const plannerInput = parsePlannerPrompt(prompt);
        if (!plannerInput.exam_date || (!plannerInput.daily_study_hours && !plannerInput.weekly_study_hours)) {
          throw new Error("Include an exam date as YYYY-MM-DD and daily or weekly study hours.");
        }
        const readyDocIds = new Set(readyDocs.map((doc) => doc.doc_id));
        const plannerDocIds = scopedDocIds.filter((docId) => readyDocIds.has(docId));
        const body = await call("/planner", {
          method: "POST",
          json: {
            ...plannerInput,
            user_id: currentUserId,
            session_id: activeSessionId,
            ...(plannerDocIds.length
              ? { doc_id: plannerDocIds[0], selected_doc_ids: plannerDocIds }
              : {}),
          },
        });
        setActivePlan(body);
        setPlannerOpen(true);
        await refreshPlans(activeSessionId);
        updateMessage(botId, {
          text: renderPlanText(body),
          plan: body,
          loading: false,
        });
      }
    } catch (err) {
      updateMessage(botId, { text: `Error: ${err.message}`, loading: false, error: true });
    } finally {
      setBusyFlag("send", false);
    }
  }

  function toggleCard(messageId, cardId) {
    const message = messages.find((item) => item.id === messageId);
    updateMessage(messageId, {
      flippedCards: {
        ...(message?.flippedCards || {}),
        [cardId]: !message?.flippedCards?.[cardId],
      },
    });
  }

  function chooseQuizAnswer(messageId, questionIndex, optionIndex) {
    const message = messages.find((item) => item.id === messageId);
    if (message?.quizAnswers?.[questionIndex] !== undefined) return;
    updateMessage(messageId, {
      quizAnswers: {
        ...(message?.quizAnswers || {}),
        [questionIndex]: optionIndex,
      },
    });
  }

  const userLabel = useMemo(() => {
    if (auth.userId) return `${auth.email} (${auth.userId})`;
    return `Local: ${LOCAL_USER}`;
  }, [auth]);

  return (
    <div
      className={`app-shell ${dragOver ? "dragging" : ""}`}
      onDragEnter={(event) => {
        event.preventDefault();
        setDragOver(true);
      }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={(event) => {
        if (event.currentTarget === event.target) setDragOver(false);
      }}
      onDrop={(event) => {
        event.preventDefault();
        setDragOver(false);
        uploadFiles(event.dataTransfer.files);
      }}
    >
      {!auth.userId && (
        <div className="login-overlay">
          <div className="login-box">
            <div className="login-brand">StudyBot</div>
            <p>Sign in to load your document workspace.</p>
            <input
              type="email"
              value={loginEmail}
              onChange={(event) => setLoginEmail(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") login();
              }}
              placeholder="demo@studybot.com"
            />
            <button onClick={login} disabled={busy.login}>
              {busy.login ? "Signing in..." : "Continue"}
            </button>
            <button className="ghost" onClick={() => setAuth({ userId: LOCAL_USER, email: "" })}>
              Use local test user
            </button>
          </div>
        </div>
      )}

      {toast && <div className="toast">{toast}</div>}
      {dragOver && <div className="drag-overlay">Drop files to upload</div>}

      <aside className="sidebar">
        <div className="sidebar-head">
          <div>
            <div className="brand-small">StudyBot</div>
            <div className="user-label">{userLabel}</div>
          </div>
          <button className="icon-btn" onClick={() => setSessionModalOpen(true)} title="New session">
            +
          </button>
        </div>

        <div className="session-list">
          <div className="section-label">Sessions</div>
          {sessions.map((session) => (
            <button
              className={`session-chip ${session.id === activeSessionId ? "active" : ""}`}
              key={session.id}
              onClick={() => setActiveSessionId(session.id)}
            >
              <span>{session.name}</span>
              {sessions.length > 1 && (
                <span
                  className="delete-session"
                  onClick={(event) => {
                    event.stopPropagation();
                    deleteSession(session.id);
                  }}
                >
                  x
                </span>
              )}
            </button>
          ))}
        </div>

        <div className="sidebar-foot">
          <span className={`api-pill ${apiStatus.tone}`}>{apiStatus.label}</span>
          {auth.userId ? (
            <button className="link-btn" onClick={logout}>
              Log out
            </button>
          ) : null}
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <h1>{activeSession?.name || "Study Session"}</h1>
            <p>
              {selectedReadyCount}/{selectedDocIds.length || 0} selected docs ready
            </p>
          </div>
          <div className="top-actions">
            <button className="soft-btn" onClick={() => setFileModalOpen(true)}>
              {selectedDocIds.length === 1 ? "Using 1 doc" : `Using ${selectedDocIds.length} docs`}
            </button>
            <button
              className={`soft-btn ${plannerOpen ? "active" : ""}`}
              onClick={() => {
                setPlannerOpen((prev) => !prev);
                if (!plannerOpen) refreshPlans(activeSessionId);
              }}
            >
              Plans
            </button>
            <button className="soft-btn" onClick={refreshDocs} disabled={busy.docs}>
              {busy.docs ? "Refreshing..." : "Refresh"}
            </button>
            <button
              className="soft-btn"
              onClick={() => setDebugOpen((prev) => !prev)}
              title="Toggle debug console (Ctrl+`)"
            >
              Debug
            </button>
            <button
              className="icon-btn"
              onClick={() => setTheme((prev) => (prev === "dark" ? "light" : "dark"))}
              title="Toggle theme"
            >
              {theme === "dark" ? "☀" : "☾"}
            </button>
          </div>
        </header>

        {plannerOpen && (
          <section className="planner-view" aria-label="Exam planner">
            <div className="planner-list">
              <div className="planner-view-head">
                <div>
                  <h2>Saved Plans</h2>
                  <p>{busy.plans ? "Loading plans..." : `${plans.length} plan${plans.length === 1 ? "" : "s"}`}</p>
                </div>
                <button className="soft-btn" onClick={() => refreshPlans(activeSessionId)} disabled={busy.plans}>
                  Refresh
                </button>
              </div>
              {plans.length ? (
                plans.map((plan) => (
                  <button
                    className={`plan-row ${activePlan?.plan_id === plan.plan_id ? "active" : ""}`}
                    key={plan.plan_id}
                    onClick={() => openPlan(plan.plan_id)}
                  >
                    <span>
                      <strong>{dateLabel(plan.exam_date) || plan.exam_date}</strong>
                      <small>{dateLabel(plan.created_at || plan.generated_at)}</small>
                    </span>
                    <em>
                      {plan.selected_doc_count ?? safeArray(plan.selected_doc_ids).length} docs /{" "}
                      {plan.task_count ?? safeArray(plan.tasks).length} tasks
                    </em>
                  </button>
                ))
              ) : (
                <div className="empty-state">No saved plans in this session.</div>
              )}
            </div>
            <div className="planner-detail">
              {activePlan ? (
                <>
                  <div className="planner-detail-head">
                    <div>
                      <h2>{dateLabel(activePlan.exam_date) || activePlan.exam_date}</h2>
                      <p>{activePlan.summary}</p>
                    </div>
                    <div className="planner-actions">
                      <button
                        className="soft-btn"
                        onClick={() => applyPlanDocIds(activePlan.selected_doc_ids, "Selected the plan source documents.")}
                      >
                        Use Sources
                      </button>
                      <button
                        className="soft-btn"
                        onClick={() => recommendPlanDocs(activePlan.plan_id)}
                        disabled={busy.plans}
                      >
                        Find Docs
                      </button>
                      <button className="soft-btn danger" onClick={() => deletePlan(activePlan.plan_id)}>
                        Delete
                      </button>
                    </div>
                  </div>
                  <div className="plan-meta-grid">
                    <div>
                      <span>Sources</span>
                      <strong>{safeArray(activePlan.selected_documents).length || safeArray(activePlan.selected_doc_ids).length}</strong>
                    </div>
                    <div>
                      <span>Tasks</span>
                      <strong>{safeArray(activePlan.tasks).length}</strong>
                    </div>
                    <div>
                      <span>Created</span>
                      <strong>{dateLabel(activePlan.created_at || activePlan.generated_at)}</strong>
                    </div>
                  </div>
                  <div className="source-strip">
                    {safeArray(activePlan.selected_documents).length
                      ? safeArray(activePlan.selected_documents).map((doc) => (
                          <span key={doc.doc_id}>{doc.title || doc.doc_id}</span>
                        ))
                      : safeArray(activePlan.selected_doc_ids).map((docId) => <span key={docId}>{docId}</span>)}
                  </div>
                  {safeArray(activePlan.weak_topics).length ? (
                    <div className="weak-topic-strip">
                      {safeArray(activePlan.weak_topics).slice(0, 8).map((topic, index) => (
                        <span key={`${topic}-${index}`}>{topic}</span>
                      ))}
                    </div>
                  ) : null}
                  {safeArray(activePlan.recommended_documents).length ? (
                    <div className="recommended-docs">
                      {safeArray(activePlan.recommended_documents).map((doc) => (
                        <div className="recommended-doc" key={doc.doc_id}>
                          <strong>{doc.title || doc.doc_id}</strong>
                          <span>{safeArray(doc.reasons).join(" / ")}</span>
                        </div>
                      ))}
                    </div>
                  ) : null}
                  <div className="planner-panel full">
                    {safeArray(activePlan.tasks).map((task, taskIndex) => (
                      <div className="planner-task" key={`${activePlan.plan_id}-task-${taskIndex}`}>
                        <time>{task.date}</time>
                        <strong>{task.topic}</strong>
                        <span>
                          {task.duration_minutes} min - {task.activity}
                        </span>
                        {task.reason ? <small>{task.reason}</small> : null}
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <div className="empty-state">Create or select a plan to inspect its sources and schedule.</div>
              )}
            </div>
          </section>
        )}

        <section className="chat-area" ref={chatRef}>
          {!messages.length ? (
            <div className="welcome">
              <h2>Start with a question or upload notes.</h2>
              <p>Choose documents for context, then ask, summarize, quiz, or make cards.</p>
            </div>
          ) : (
            messages.map((message) => (
              <article className={`message ${message.role} ${message.error ? "error" : ""}`} key={message.id}>
                <div className="message-label">
                  <span>{message.role === "user" ? "You" : "StudyBot"}</span>
                  <span>{FEATURES[message.feature]?.label || "Chat"}</span>
                </div>
                <div className="message-body">
                  {message.loading ? (
                    <span className="typing">
                      <span />
                      <span />
                      <span />
                    </span>
                  ) : (
                    renderMarkdownText(message.text, message.id, safeArray(message.citations), openCitation)
                  )}
                </div>
                {message.quiz?.length ? (
                  <div className="quiz-panel">
                    {message.quiz.map((question, questionIndex) => {
                      const correct = answerIndex(question);
                      const selected = message.quizAnswers?.[questionIndex];
                      return (
                        <div className="quiz-question" key={`${message.id}-q-${questionIndex}`}>
                          <h3>
                            {questionIndex + 1}. {question.question}
                          </h3>
                          <div className="quiz-options">
                            {safeArray(question.options).map((option, optionIndex) => {
                              const answered = selected !== undefined;
                              const stateClass = answered
                                ? optionIndex === correct
                                  ? "correct"
                                  : optionIndex === selected
                                    ? "wrong"
                                    : ""
                                : "";
                              return (
                                <button
                                  className={stateClass}
                                  key={`${message.id}-q-${questionIndex}-op-${optionIndex}`}
                                  onClick={() => chooseQuizAnswer(message.id, questionIndex, optionIndex)}
                                >
                                  <span>{String.fromCharCode(65 + optionIndex)}.</span>
                                  {option}
                                </button>
                              );
                            })}
                          </div>
                          {selected !== undefined && question.explanation ? (
                            <p className="quiz-explain">{question.explanation}</p>
                          ) : null}
                        </div>
                      );
                    })}
                    <div className="quiz-score">
                      Score:{" "}
                      {Object.entries(message.quizAnswers || {}).filter(
                        ([index, selected]) => Number(selected) === answerIndex(message.quiz[Number(index)])
                      ).length}
                      /{message.quiz.length}
                    </div>
                  </div>
                ) : null}
                {message.cards?.length ? (
                  <div className="flash-grid">
                    {message.cards.map((card) => (
                      <button
                        className={`flash-card ${message.flippedCards?.[card.id] ? "flipped" : ""}`}
                        key={card.id}
                        onClick={() => toggleCard(message.id, card.id)}
                      >
                        <span className="flash-face flash-front">{card.front}</span>
                        <span className="flash-face flash-back">{cleanFlashcardBack(card.back)}</span>
                      </button>
                    ))}
                  </div>
                ) : null}
                {message.plan?.tasks?.length ? (
                  <div className="planner-panel">
                    {message.plan.tasks.map((task, taskIndex) => (
                      <div className="planner-task" key={`${message.id}-plan-${taskIndex}`}>
                        <time>{task.date}</time>
                        <strong>{task.topic}</strong>
                        <span>
                          {task.duration_minutes} min - {task.activity}
                        </span>
                        {task.reason ? <small>{task.reason}</small> : null}
                      </div>
                    ))}
                  </div>
                ) : null}
                {message.citations?.length ? (
                  <div className="citations">
                    {message.citations.map((citation, index) => (
                      <div
                        className={`citation ${message.openCitations?.[index] ? "open" : ""}`}
                        id={`source-${message.id}-${index + 1}`}
                        key={`${citation.chunk_id || citation.doc_id || "source"}-${index}`}
                      >
                        <button type="button" onClick={() => toggleCitation(message.id, index)}>
                          <span>
                            Source {index + 1}
                            <small>{citation.document || citation.doc_id || ""}</small>
                          </span>
                          <strong>{message.openCitations?.[index] ? "Hide chunk" : "Show chunk"}</strong>
                        </button>
                        {message.openCitations?.[index] && (
                          <p>{citation.text || citation.chunk_id || "No chunk text returned."}</p>
                        )}
                      </div>
                    ))}
                  </div>
                ) : null}
                <div className="message-time">{nowLabel(new Date(message.createdAt))}</div>
              </article>
            ))
          )}
        </section>

        <footer className="composer">
          <div className="composer-shell">
            <div className="plus-wrap">
              <button className="round-btn" onClick={() => setPlusOpen((prev) => !prev)}>
                +
              </button>
              {plusOpen && (
                <div className="plus-menu">
                  <div className="plus-menu-label">Feature</div>
                  {FEATURE_MENU.map((feature) => (
                    <button
                      className={`feature-opt ${activeFeature === feature.key ? "active" : ""}`}
                      key={feature.key}
                      onClick={() => selectFeature(feature.key)}
                    >
                      <MenuIcon name={feature.icon} />
                      <span>{feature.label}</span>
                    </button>
                  ))}
                  <div className="menu-divider" />
                  <button
                    className="feature-opt"
                    onClick={() => {
                      setPlusOpen(false);
                      fileInputRef.current?.click();
                    }}
                  >
                    <MenuIcon name="upload" />
                    <span>Upload File</span>
                  </button>
                </div>
              )}
            </div>
            <input
              ref={fileInputRef}
              className="hidden-file"
              type="file"
              multiple
              accept=".pdf,.docx,.pptx,.txt,.md,.markdown,.vtt"
              onChange={(event) => {
                uploadFiles(event.target.files);
                event.target.value = "";
              }}
            />
            <span className="feature-badge">{FEATURES[activeFeature].label}</span>
            <input
              type="text"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") send();
              }}
              placeholder={FEATURES[activeFeature].placeholder}
            />
            <button className="send-btn" onClick={send} disabled={!canSend} title="Send">
              {busy.send ? "..." : "↑"}
            </button>
          </div>
        </footer>
      </main>

      {debugOpen && (
        <section className="debug-console" role="dialog" aria-label="Debug console">
          <div className="debug-head">
            <div>
              <h2>Debug Console</h2>
              <p>Recent API and upload events. Toggle with Ctrl+`.</p>
            </div>
            <div className="debug-actions">
              <button className="soft-btn" onClick={() => setDebugText("No requests yet.")}>
                Clear
              </button>
              <button className="icon-btn" onClick={() => setDebugOpen(false)} title="Close debug console">
                x
              </button>
            </div>
          </div>
          <pre>{debugText}</pre>
        </section>
      )}

      {fileModalOpen && (
        <div className="modal-backdrop" onMouseDown={() => setFileModalOpen(false)}>
          <div className="modal" onMouseDown={(event) => event.stopPropagation()}>
            <div className="modal-head">
              <div>
                <h2>Document Context</h2>
                <p>Only checked documents are sent to RAG.</p>
              </div>
              <button className="icon-btn" onClick={() => setFileModalOpen(false)}>
                x
              </button>
            </div>
            <div className="context-row">
              <label>
                RAG limit
                <select value={contextLimit} onChange={(event) => setContextLimit(Number(event.target.value))}>
                  <option value={1}>1 doc</option>
                  <option value={3}>3 docs</option>
                  <option value={5}>5 docs</option>
                  <option value={10}>10 docs</option>
                </select>
              </label>
              <button className="soft-btn" onClick={autoSelectReady}>
                Auto-select ready
              </button>
            </div>
            <div className="doc-picker">
              {docs.length ? (
                docs.map((doc) => {
                  const checked = selectedDocIds.includes(doc.doc_id);
                  const disabled = !checked && contextLimit && selectedDocIds.length >= contextLimit;
                  return (
                    <label className={`doc-row ${checked ? "checked" : ""}`} key={doc.doc_id}>
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={disabled}
                        onChange={() => toggleDoc(doc.doc_id)}
                      />
                      <span>
                        <strong>{docTitle(doc)}</strong>
                        <small>{doc.doc_id}</small>
                      </span>
                      <em className={isReady(doc) ? "ready" : ""}>{doc.kb_status || doc.status || "UNKNOWN"}</em>
                    </label>
                  );
                })
              ) : (
                <div className="empty-state">No documents yet.</div>
              )}
            </div>
            <div className="modal-actions">
              <button onClick={() => fileInputRef.current?.click()}>Upload</button>
              <button className="primary" onClick={() => setFileModalOpen(false)}>
                Done
              </button>
            </div>
          </div>
        </div>
      )}

      {sessionModalOpen && (
        <div className="modal-backdrop" onMouseDown={() => setSessionModalOpen(false)}>
          <div className="modal small" onMouseDown={(event) => event.stopPropagation()}>
            <div className="modal-head">
              <h2>New Session</h2>
              <button className="icon-btn" onClick={() => setSessionModalOpen(false)}>
                x
              </button>
            </div>
            <input
              value={newSessionName}
              onChange={(event) => setNewSessionName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") createSession(newSessionName);
              }}
              placeholder="Midterm review"
            />
            <div className="modal-actions">
              <button onClick={() => setSessionModalOpen(false)}>Cancel</button>
              <button className="primary" onClick={() => createSession(newSessionName)}>
                Create
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
