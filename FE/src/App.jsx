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
};

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
  const [messagesBySession, setMessagesBySession] = useState(() =>
    loadJson(storageKey(currentUserId, "messages"), {})
  );

  const [docs, setDocs] = useState([]);
  const [selectedDocIds, setSelectedDocIds] = useState(() =>
    loadJson(storageKey(currentUserId, "selected-docs"), [])
  );
  const [contextLimit, setContextLimit] = useState(() =>
    Number(localStorage.getItem(storageKey(currentUserId, "context-limit")) || 5)
  );

  const [activeFeature, setActiveFeature] = useState("chat");
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
  });

  const chatRef = useRef(null);
  const fileInputRef = useRef(null);

  const activeSession = sessions.find((session) => session.id === activeSessionId) || sessions[0];
  const messages = messagesBySession[activeSessionId] || [];
  const selectedDocs = docs.filter((doc) => selectedDocIds.includes(doc.doc_id));
  const readyDocs = docs.filter(isReady);
  const selectedReadyCount = selectedDocs.filter(isReady).length;
  const canSend = input.trim() && selectedDocIds.length && !busy.send;

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("studybot-theme", theme);
  }, [theme]);

  useEffect(() => {
    localStorage.setItem(storageKey(currentUserId, "sessions"), JSON.stringify(sessions));
  }, [sessions, currentUserId]);

  useEffect(() => {
    localStorage.setItem(storageKey(currentUserId, "messages"), JSON.stringify(messagesBySession));
  }, [messagesBySession, currentUserId]);

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
  }, [messages]);

  useEffect(() => {
    async function boot() {
      await refreshSessions();
      await refreshDocs();
    }
    boot();
  }, [currentUserId]);

  useEffect(() => {
    refreshDocs();
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

  function renderAnswerWithCitations(text, citations, messageId) {
    if (!text) return null;
    const parts = String(text).split(/(\[(?:\d+(?:,\s*)?)+\])/g);
    return parts.map((part, index) => {
      const match = part.match(/^\[((?:\d+(?:,\s*)?)+)\]$/);
      if (!match) return <span key={`${messageId}-text-${index}`}>{part}</span>;
      const numbers = match[1]
        .split(",")
        .map((value) => Number(value.trim()))
        .filter((value) => Number.isInteger(value) && value >= 1 && value <= citations.length);
      if (!numbers.length) return <span key={`${messageId}-text-${index}`}>{part}</span>;
      return (
        <span className="citation-inline" key={`${messageId}-cite-${index}`}>
          {numbers.map((number) => (
            <button key={number} type="button" onClick={() => openCitation(messageId, number - 1)}>
              [{number}]
            </button>
          ))}
        </span>
      );
    });
  }

  async function send() {
    const prompt = input.trim();
    if (!prompt || busy.send) return;
    if (!selectedDocIds.length) {
      showToast("Select at least one document for context.");
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
      } else {
        const body = await call("/quiz", {
          method: "POST",
          json: {
            user_id: currentUserId,
            session_id: activeSessionId,
            doc_id: scopedDocIds[0],
            selected_doc_ids: scopedDocIds,
            difficulty: "easy",
            count: 6,
          },
        });
        const cards = safeArray(body.questions).map((q) => ({
          id: uid("card"),
          front: q.question || "",
          back: `${q.answer || ""}${q.explanation ? `\n\n${q.explanation}` : ""}`,
        }));
        updateMessage(botId, {
          text: cards.length ? `Created ${cards.length} flash cards.` : "No flash cards returned.",
          cards,
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
                  ) : message.citations?.length ? (
                    renderAnswerWithCitations(message.text, message.citations, message.id)
                  ) : (
                    message.text
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
                        {message.flippedCards?.[card.id] ? card.back : card.front}
                      </button>
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
                  <button onClick={() => fileInputRef.current?.click()}>Upload files</button>
                  <button onClick={() => setFileModalOpen(true)}>Choose context</button>
                  <button onClick={clearChat}>Clear chat</button>
                  <div className="menu-divider" />
                  {Object.entries(FEATURES).map(([key, feature]) => (
                    <button
                      className={activeFeature === key ? "active" : ""}
                      key={key}
                      onClick={() => {
                        setActiveFeature(key);
                        setPlusOpen(false);
                      }}
                    >
                      {feature.label}
                    </button>
                  ))}
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
