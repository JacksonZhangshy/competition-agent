/* 后端接口封装 */
(function () {
  const BASE = "";

  async function request(path, options = {}) {
    const res = await fetch(BASE + path, options);
    const type = res.headers.get("content-type") || "";
    let data;
    if (type.includes("application/json")) {
      data = await res.json();
    } else {
      data = await res.text();
    }
    if (!res.ok) {
      const msg = (data && data.detail) || (typeof data === "string" ? data : "请求失败");
      throw new Error(msg);
    }
    return data;
  }

  const qs = (params) => {
    const p = new URLSearchParams();
    Object.entries(params || {}).forEach(([k, v]) => {
      if (v !== "" && v !== null && v !== undefined && v !== false) p.append(k, v);
    });
    const s = p.toString();
    return s ? "?" + s : "";
  };

  window.API = {
    get: (path, params) => request(path + qs(params)),
    post: (path, body) =>
      request(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
      }),
    put: (path, body) =>
      request(path, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
      }),
    del: (path) => request(path, { method: "DELETE" }),
    upload: (path, formData) => request(path, { method: "POST", body: formData }),

    // 业务封装
    health: () => request("/api/health"),
    ask: (question, conversationId) =>
      request("/api/chat/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, conversation_id: conversationId || null }),
      }),
    conversations: () => request("/api/chat/conversations"),
    conversation: (id) => request("/api/chat/conversations/" + id),
    delConversation: (id) => request("/api/chat/conversations/" + id, { method: "DELETE" }),

    knowledgeDocs: () => request("/api/knowledge/docs"),
    knowledgeSearch: (query, topK = 6) =>
      request("/api/knowledge/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, top_k: topK }),
      }),
    knowledgeRebuild: () => request("/api/knowledge/rebuild", { method: "POST" }),
    knowledgeDelete: (id) => request("/api/knowledge/docs/" + id, { method: "DELETE" }),
    chunk: (id) => request("/api/knowledge/chunks/" + id),

    overview: () => request("/api/data/overview"),
    competitions: (params) => request("/api/data/competitions" + qs(params)),
    competition: (id) => request("/api/data/competitions/" + id),
    teams: (params) => request("/api/data/teams" + qs(params)),
    statistics: (params) => request("/api/data/statistics" + qs(params)),
    statisticsAsk: (question) =>
      request("/api/data/statistics/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      }),
    dimensions: () => request("/api/data/dimensions"),
    students: (params) => request("/api/data/students" + qs(params)),

    runWorkflow: (workflow, payload) =>
      request("/api/agent/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workflow, payload: payload || {} }),
      }),
    workflows: () => request("/api/agent/workflows"),
    tools: () => request("/api/agent/tools"),
    runs: () => request("/api/agent/runs"),
    runDetail: (id) => request("/api/agent/runs/" + id),

    budgetRules: () => request("/api/finance/rules"),
    budgetCompute: (payload) =>
      request("/api/finance/budget/compute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    budgetExport: (payload) =>
      request("/api/finance/budget/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    loanBuild: (payload) =>
      request("/api/finance/loan/build", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    loanExport: (payload) =>
      request("/api/finance/loan/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    reimburseCheck: (payload) =>
      request("/api/finance/reimburse/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    reimburseExport: (payload) =>
      request("/api/finance/reimburse/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    teamsOptions: (keyword) => request("/api/finance/teams-options" + qs({ keyword })),
  };
})();
