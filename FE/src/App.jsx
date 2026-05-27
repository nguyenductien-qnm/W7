import { useEffect, useMemo, useState } from "react";

const DEFAULT_API_BASE = "https://3sgavxe4c0.execute-api.ap-southeast-1.amazonaws.com";
const LOCAL_USER =
  new URLSearchParams(window.location.search).get("user") || "test-user-001";
const API_BASE = (
  new URLSearchParams(window.location.search).get("api") || DEFAULT_API_BASE
).replace(/\/$/, "");

function getSavedAuth() {
  return {
    userId: sessionStorage.getItem("studybot_user_id") || "",
    email: sessionStorage.getItem("studybot_email") || "",
  };
}

function renderQuizText(questions) {
  const lines = [];
  questions.forEach((q, idx) => {
    lines.push(`${idx + 1}. ${q.question || ""}`);
    const options = Array.isArray(q.options) ? q.options : [];
    options.forEach((op, i) => lines.push(`   ${String.fromCharCode(65 + i)}. ${op}`));
    lines.push(`   Correct: ${q.answer || ""}`);
    if (q.explanation) lines.push(`   Note: ${q.explanation}`);
    lines.push("");
  });
  return lines.join("\n").trim();
}

export default function App() {
  const [auth, setAuth] = useState(getSavedAuth());
  const [loginEmail, setLoginEmail] = useState(getSavedAuth().email || "");
  const [backendStatus, setBackendStatus] = useState({ label: "Checking API", tone: "idle" });
  const [debugText, setDebugText] = useState("No requests yet.");

  const [docs, setDocs] = useState([]);
  const [selectedDocIds, setSelectedDocIds] = useState([]);
  const [dragOver, setDragOver] = useState(false);

  const [activeTab, setActiveTab] = useState("qa");
  const [question, setQuestion] = useState("");
  const [difficulty, setDifficulty] = useState("medium");
  const [count, setCount] = useState(5);

  const [uploadResult, setUploadResult] = useState({ text: "", mode: "" });
  const [answerData, setAnswerData] = useState({ text: "", mode: "", citations: [] });
  const [summaryData, setSummaryData] = useState({ text: "", mode: "" });
  const [quizData, setQuizData] = useState({ text: "", mode: "" });

  const [busy, setBusy] = useState({
    docs: false,
    upload: false,
    login: false,
    ask: false,
    summary: false,
    quiz: false,
  });

  const currentUserId = auth.userId || LOCAL_USER;
  const primarySelectedDocId = selectedDocIds[0] || null;
  const anyBusy = Object.values(busy).some(Boolean);

  function setBusyFlag(key, value) {
    setBusy((prev) => ({ ...prev, [key]: value }));
  }

  function pushLog(label, body) {
    setDebugText((prev) => {
      const existing = prev === "No requests yet." ? "" : prev;
      const next =
        `${new Date().toLocaleTimeString()} ${label}\n` +
        `${JSON.stringify(body, null, 2)}\n\n${existing}`;
      return next.slice(0, 9000);
    });
  }

  async function call(path, opts = {}) {
    const headers = new Headers(opts.headers || {});
    headers.set("X-User-Id", currentUserId);
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

  async function loadStatus() {
    try {
      await call("/documents");
      setBackendStatus({ label: "API online", tone: "online" });
    } catch {
      setBackendStatus({ label: "API offline", tone: "offline" });
    }
  }

  async function hydrateDocStatuses(inputDocs) {
    const hydrated = [];
    for (const doc of inputDocs) {
      const status = String(doc.status || "").toUpperCase();
      if (doc.ingestion_job_id && status !== "COMPLETE" && status !== "FAILED") {
        try {
          const body = await call(`/documents/${doc.doc_id}/status`);
          hydrated.push(body.document || doc);
          continue;
        } catch (err) {
          pushLog(`GET /documents/${doc.doc_id}/status failed`, { error: err.message });
        }
      }
      hydrated.push(doc);
    }
    return hydrated;
  }

  async function refreshDocs() {
    setBusyFlag("docs", true);
    try {
      const body = await call("/docs/list");
      const nextDocs = await hydrateDocStatuses(body.docs || body.documents || []);
      setDocs(nextDocs);
      setSelectedDocIds((prev) =>
        prev.filter((id) => nextDocs.some((doc) => doc.doc_id === id))
      );
    } catch (err) {
      setDocs([]);
      setUploadResult({ text: err.message, mode: "warn" });
    } finally {
      setBusyFlag("docs", false);
    }
  }

  useEffect(() => {
    async function boot() {
      await loadStatus();
      await refreshDocs();
    }
    boot();
  }, []);

  async function login() {
    const email = loginEmail.trim().toLowerCase();
    if (!email) {
      setUploadResult({ text: "Please enter email to login.", mode: "warn" });
      return;
    }

    setBusyFlag("login", true);
    try {
      const body = await call("/login", { method: "POST", json: { email } });
      const nextAuth = { userId: body.user_id || LOCAL_USER, email };
      sessionStorage.setItem("studybot_user_id", nextAuth.userId);
      sessionStorage.setItem("studybot_email", nextAuth.email);
      setAuth(nextAuth);
      await refreshDocs();
    } catch (err) {
      setUploadResult({ text: `Login failed: ${err.message}`, mode: "warn" });
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

  async function requestUploadIntent(file) {
    const payload = {
      filename: file.name,
      title: file.name,
      content_type: file.type || "application/octet-stream",
      size: file.size,
      user_id: currentUserId,
    };
    const endpoints = ["/documents/upload-url", "/upload/presign"];
    for (const path of endpoints) {
      try {
        const body = await call(path, { method: "POST", json: payload });
        const uploadUrl = body.upload_url || body.presigned_url || body.url || "";
        if (uploadUrl) return body;
        pushLog(`Presign not returned from ${path}`, body);
      } catch (err) {
        pushLog(`Presign request failed ${path}`, { error: err.message });
      }
    }
    return null;
  }

  async function uploadWithPresignedUrl(intent, file) {
    const uploadUrl = intent.upload_url || intent.presigned_url || intent.url || "";
    if (!uploadUrl) throw new Error("Missing presigned upload URL.");
    const method = String(intent.upload_method || intent.method || "PUT").toUpperCase();

    if (method === "POST" && intent.fields && typeof intent.fields === "object") {
      const form = new FormData();
      Object.entries(intent.fields).forEach(([k, v]) => form.append(k, v));
      form.append("file", file);
      const res = await fetch(uploadUrl, { method: "POST", body: form });
      pushLog(`POST S3 ${intent.s3_key || uploadUrl}`, { status: res.status, ok: res.ok });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(`S3 POST failed: HTTP ${res.status} ${body.slice(0, 200)}`);
      }
      return;
    }

    const uploadHeaders = {
      "Content-Type": file.type || "application/octet-stream",
      ...(intent.headers || {}),
    };
    const res = await fetch(uploadUrl, { method: "PUT", headers: uploadHeaders, body: file });
    pushLog(`PUT S3 ${intent.s3_key || uploadUrl}`, { status: res.status, ok: res.ok });
    if (!res.ok) {
      const body = await res.text();
      throw new Error(`S3 PUT failed: HTTP ${res.status} ${body.slice(0, 200)}`);
    }
  }

  function extractCompletePath(intent) {
    if (intent.complete_path) return intent.complete_path;
    if (intent.complete_url) return intent.complete_url;
    if (intent.doc_id) return `/documents/${intent.doc_id}/complete`;
    return "";
  }

  async function maybeCompleteUpload(intent) {
    const completePath = extractCompletePath(intent);
    if (!completePath) return null;
    try {
      if (completePath.startsWith("http://") || completePath.startsWith("https://")) {
        const res = await fetch(completePath, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-User-Id": currentUserId,
          },
          body: JSON.stringify({ doc_id: intent.doc_id, s3_key: intent.s3_key }),
        });
        const text = await res.text();
        let body;
        try {
          body = JSON.parse(text);
        } catch {
          body = { raw: text };
        }
        pushLog(`POST complete ${completePath}`, body);
        if (!res.ok) throw new Error(body?.detail || body?.message || `HTTP ${res.status}`);
        return body;
      }
      return await call(completePath, {
        method: "POST",
        json: { doc_id: intent.doc_id, s3_key: intent.s3_key },
      });
    } catch (err) {
      pushLog("Complete upload skipped", { error: err.message });
      return null;
    }
  }

  async function directUpload(file) {
    const form = new FormData();
    form.append("file", file);
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

    pushLog("POST /upload", body);
    if (!res.ok) throw new Error(body?.detail || body?.message || `Upload failed: HTTP ${res.status}`);
    return body;
  }

  async function upload(file) {
    setBusyFlag("upload", true);
    setUploadResult({ text: `Uploading ${file.name}...`, mode: "warn" });
    try {
      const intent = await requestUploadIntent(file);
      if (intent) {
        await uploadWithPresignedUrl(intent, file);
        const complete = await maybeCompleteUpload(intent);
        const message = complete?.ingestion_job_id
          ? `${file.name} uploaded. Ingestion job: ${complete.ingestion_job_id}`
          : `${file.name} uploaded to S3 successfully.`;
        setUploadResult({ text: message, mode: "ok" });
        if (intent.doc_id) {
          setSelectedDocIds((prev) => [intent.doc_id, ...prev.filter((id) => id !== intent.doc_id)]);
        }
      } else {
        const body = await directUpload(file);
        setUploadResult({
          text: `${body.filename || file.name} uploaded through API.`,
          mode: "ok",
        });
        if (body.doc_id) {
          setSelectedDocIds((prev) => [body.doc_id, ...prev.filter((id) => id !== body.doc_id)]);
        }
      }
      await refreshDocs();
    } catch (err) {
      setUploadResult({ text: err.message, mode: "warn" });
    } finally {
      setBusyFlag("upload", false);
    }
  }

  async function ask() {
    if (!question.trim()) return;
    if (!selectedDocIds.length) {
      setAnswerData({
        text: "Please select at least one document first.",
        mode: "warn",
        citations: [],
      });
      return;
    }

    setBusyFlag("ask", true);
    setAnswerData({ text: "Searching selected documents...", mode: "warn", citations: [] });
    try {
      const body = await call("/ask", {
        method: "POST",
        json: {
          user_id: currentUserId,
          doc_id: primarySelectedDocId,
          selected_doc_ids: selectedDocIds,
          question: question.trim(),
        },
      });
      setAnswerData({ text: body.answer || "", mode: "ok", citations: body.citations || [] });
    } catch (err) {
      setAnswerData({ text: err.message, mode: "warn", citations: [] });
    } finally {
      setBusyFlag("ask", false);
    }
  }

  async function summarize() {
    if (!primarySelectedDocId) {
      setSummaryData({ text: "Please select at least one document first.", mode: "warn" });
      return;
    }

    setBusyFlag("summary", true);
    setSummaryData({ text: "Building summary from selected docs...", mode: "warn" });
    try {
      const body = await call("/summary", {
        method: "POST",
        json: {
          user_id: currentUserId,
          doc_id: primarySelectedDocId,
          selected_doc_ids: selectedDocIds,
        },
      });
      const concepts =
        (body.testable_concepts || []).map((c, i) => `${i + 1}. ${c}`).join("\n") ||
        "No concepts yet.";
      const summaryText = `${body.summary || "No summary yet."}\n\nTestable concepts:\n${concepts}`;
      setSummaryData({ text: summaryText, mode: "ok" });
    } catch (err) {
      setSummaryData({ text: err.message, mode: "warn" });
    } finally {
      setBusyFlag("summary", false);
    }
  }

  async function quiz() {
    if (!primarySelectedDocId) {
      setQuizData({ text: "Please select at least one document first.", mode: "warn" });
      return;
    }

    setBusyFlag("quiz", true);
    setQuizData({ text: "Generating quiz from selected docs...", mode: "warn" });
    try {
      const body = await call("/quiz", {
        method: "POST",
        json: {
          user_id: currentUserId,
          doc_id: primarySelectedDocId,
          selected_doc_ids: selectedDocIds,
          difficulty,
          count: Number(count || 5),
        },
      });
      const questions = Array.isArray(body.questions) ? body.questions : [];
      if (!questions.length) {
        setQuizData({ text: "No quiz questions returned.", mode: "warn" });
        return;
      }
      setQuizData({ text: renderQuizText(questions), mode: "ok" });
    } catch (err) {
      setQuizData({ text: err.message, mode: "warn" });
    } finally {
      setBusyFlag("quiz", false);
    }
  }

  const userPill = useMemo(() => {
    if (auth.userId) return `${auth.email} (${auth.userId})`;
    return `Local: ${LOCAL_USER}`;
  }, [auth]);

  const selectedDocChips = useMemo(() => docs.filter((doc) => selectedDocIds.includes(doc.doc_id)), [docs, selectedDocIds]);

  return (
    <div className="page-shell">
      <div className="ambient ambient-a" />
      <div className="ambient ambient-b" />
      <div className="ambient ambient-c" />

      {anyBusy && (
        <div className="sync-bar">
          <span className="spinner" />
          <span>Processing request...</span>
        </div>
      )}

      <header className="topbar">
        <div className="brand">
          <p className="eyebrow">Study Assistant</p>
          <h1>StudyBot Workspace</h1>
          <p>Upload documents, choose multiple sources, then run Q&amp;A, summary, and quiz.</p>
        </div>
        <div className="auth">
          <span className={`pill ${backendStatus.tone}`}>{backendStatus.label}</span>
          <span className="pill user-pill">{userPill}</span>
          {!auth.userId && (
            <input
              type="email"
              value={loginEmail}
              onChange={(e) => setLoginEmail(e.target.value)}
              placeholder="demo@studybot.com"
              className="login-input"
            />
          )}
          {!auth.userId ? (
            <button className="secondary" onClick={login} disabled={busy.login}>
              {busy.login ? "Signing in..." : "Fake Login"}
            </button>
          ) : (
            <button className="secondary" onClick={logout}>
              Log out
            </button>
          )}
        </div>
      </header>

      <main className="layout">
        <aside className="stack">
          <section className="panel lift">
            <div className="panel-head">
              <h2>Upload</h2>
              <p>Direct to S3 via presigned URL</p>
            </div>
            <label
              className={`drop ${dragOver ? "dragover" : ""}`}
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                const file = e.dataTransfer.files?.[0];
                if (file) upload(file);
              }}
            >
              <strong>{busy.upload ? "Uploading..." : "Drop PDF/TXT/MD or click to choose"}</strong>
              <span>File is uploaded to S3, then processed for knowledge retrieval.</span>
              <input
                type="file"
                accept=".pdf,.docx,.pptx,.txt,.md,.markdown,.vtt"
                disabled={busy.upload}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) upload(file);
                  e.target.value = "";
                }}
              />
            </label>
            {uploadResult.text && <div className={`result ${uploadResult.mode}`}>{uploadResult.text}</div>}
          </section>

          <section className="panel lift">
            <div className="row">
              <div style={{ flex: 1 }}>
                <h2 style={{ margin: 0 }}>Documents</h2>
                <p className="meta">Selected: {selectedDocIds.length}</p>
              </div>
              <button className="secondary" onClick={refreshDocs} disabled={busy.docs}>
                {busy.docs ? "Loading..." : "Refresh"}
              </button>
            </div>

            {selectedDocChips.length > 0 && (
              <div className="chip-list">
                {selectedDocChips.map((doc) => (
                  <button
                    key={`chip-${doc.doc_id}`}
                    className="chip"
                    onClick={() =>
                      setSelectedDocIds((prev) => prev.filter((id) => id !== doc.doc_id))
                    }
                  >
                    {doc.filename || doc.doc_id} ×
                  </button>
                ))}
              </div>
            )}

            <div className="doc-list">
              {busy.docs ? (
                <>
                  <div className="doc-skeleton" />
                  <div className="doc-skeleton" />
                  <div className="doc-skeleton" />
                </>
              ) : docs.length ? (
                docs.map((doc) => (
                  <button
                    key={doc.doc_id}
                    className={`doc ${selectedDocIds.includes(doc.doc_id) ? "selected" : ""}`}
                    onClick={() =>
                      setSelectedDocIds((current) =>
                        current.includes(doc.doc_id)
                          ? current.filter((id) => id !== doc.doc_id)
                          : [doc.doc_id, ...current]
                      )
                    }
                  >
                    <span className="doc-name">{doc.filename || doc.name || doc.doc_id}</span>
                    <span className="meta">{doc.doc_id || ""}</span>
                    <span
                      className={`status ${
                        String(doc.status || "").toLowerCase().includes("complete")
                          ? "complete"
                          : ""
                      }`}
                    >
                      {doc.status || "UNKNOWN"}
                    </span>
                  </button>
                ))
              ) : (
                <div className="empty">No documents yet.</div>
              )}
            </div>
          </section>
        </aside>

        <section className="stack">
          <section className="panel lift">
            <div className="tabs">
              <button
                className={`secondary tab ${activeTab === "qa" ? "active" : ""}`}
                onClick={() => setActiveTab("qa")}
              >
                Q&amp;A
              </button>
              <button
                className={`secondary tab ${activeTab === "summary" ? "active" : ""}`}
                onClick={() => setActiveTab("summary")}
              >
                Summary
              </button>
              <button
                className={`secondary tab ${activeTab === "quiz" ? "active" : ""}`}
                onClick={() => setActiveTab("quiz")}
              >
                Quiz
              </button>
            </div>

            {activeTab === "qa" && (
              <div>
                <div className="panel-head">
                  <h2>Ask a Question</h2>
                  <p>Searches only the selected documents.</p>
                </div>
                <div className="row">
                  <input
                    type="text"
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") ask();
                    }}
                    placeholder="What should I remember from these notes?"
                  />
                  <button className="primary" onClick={ask} disabled={busy.ask}>
                    {busy.ask ? "Thinking..." : "Ask"}
                  </button>
                </div>
                {answerData.text && <div className={`result ${answerData.mode}`}>{answerData.text}</div>}
                {answerData.citations?.length > 0 ? (
                  answerData.citations.map((c, i) => (
                    <div className="citation" key={`${c.chunk_id || "c"}-${i}`}>
                      <strong>Source {i + 1}</strong>
                      <div className="meta">
                        {c.document || c.doc_id || ""}
                        {c.slide ? ` · slide ${c.slide}` : ""}
                      </div>
                      <div>{c.text || c.chunk_id || ""}</div>
                    </div>
                  ))
                ) : (
                  answerData.text && <div className="empty">No citations returned.</div>
                )}
              </div>
            )}

            {activeTab === "summary" && (
              <div>
                <div className="panel-head">
                  <h2>Build Summary</h2>
                  <p>Generates concise notes + testable concepts from selected docs.</p>
                </div>
                <button className="primary" onClick={summarize} disabled={busy.summary}>
                  {busy.summary ? "Summarizing..." : "Summarize Selected"}
                </button>
                {summaryData.text && <div className={`result ${summaryData.mode}`}>{summaryData.text}</div>}
              </div>
            )}

            {activeTab === "quiz" && (
              <div>
                <div className="panel-head">
                  <h2>Generate Quiz</h2>
                  <p>Creates 5-10 MCQs from selected docs.</p>
                </div>
                <div className="row wrap">
                  <select
                    value={difficulty}
                    onChange={(e) => setDifficulty(e.target.value)}
                    style={{ maxWidth: 160 }}
                  >
                    <option value="easy">Easy</option>
                    <option value="medium">Medium</option>
                    <option value="hard">Hard</option>
                  </select>
                  <input
                    type="number"
                    min="1"
                    max="10"
                    value={count}
                    onChange={(e) => setCount(e.target.value)}
                    style={{ maxWidth: 120 }}
                  />
                  <button className="primary" onClick={quiz} disabled={busy.quiz}>
                    {busy.quiz ? "Generating..." : "Generate"}
                  </button>
                </div>
                {quizData.text && <div className={`result ${quizData.mode}`}>{quizData.text}</div>}
              </div>
            )}
          </section>

          <section className="panel debug-panel">
            <div className="panel-head">
              <h2>Debug Feed</h2>
              <p>Last API events and payload snapshots</p>
            </div>
            <pre className="debug">{debugText}</pre>
          </section>
        </section>
      </main>
    </div>
  );
}
