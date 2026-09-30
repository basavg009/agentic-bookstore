// Chat panel — SSE from /api/chat/stream, tool-call chips, live cart refresh.
(async () => {
  const panelOn = document.getElementById("chat-panel");
  const panelOff = document.getElementById("chat-off");
  const messagesEl = document.getElementById("chat-messages");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const modelEl = document.getElementById("chat-model");

  const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));

  const TOOL_ICONS = {
    search_books: "🔍",
    get_book: "📖",
    add_to_cart: "🛒",
    view_cart: "👀",
    remove_from_cart: "🗑️",
    prepare_checkout: "🧾",
  };

  try {
    const health = await fetch("/api/chat/health", { credentials: "same-origin" }).then((r) => r.json());
    if (!health.available) {
      panelOff.hidden = false;
      return;
    }
    panelOn.hidden = false;
    modelEl.textContent = health.model + (health.model_pulled ? "" : " (not pulled)");
  } catch {
    panelOff.hidden = false;
    return;
  }

  // Restore the conversation the server remembers for this session.
  try {
    const { messages } = await fetch("/api/chat/history", { credentials: "same-origin" }).then((r) => r.json());
    for (const m of messages) addMsg(m.role === "user" ? "user" : "bot", m.content);
  } catch { /* history is a convenience; the chat still works without it */ }

  document.getElementById("chat-reset").addEventListener("click", async () => {
    await fetch("/api/chat/history", { method: "DELETE", credentials: "same-origin" });
    messagesEl.querySelectorAll(".msg:not(:first-child)").forEach((el) => el.remove());
  });

  function addMsg(role, text) {
    const el = document.createElement("div");
    el.className = `msg ${role}`;
    el.textContent = text;
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return el;
  }

  function addToolChip(name, summary) {
    const el = document.createElement("div");
    el.className = "msg tool";
    const icon = TOOL_ICONS[name] || "🔧";
    el.textContent = `${icon} ${name}${summary ? " — " + summary : ""}`;
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  // The agent can only prepare a quote. Placing the order takes this human click.
  function addConfirmCard(quote) {
    const el = document.createElement("div");
    el.className = "msg confirm-card";
    el.innerHTML = (window.Storefront ? window.Storefront.renderQuote(quote) : "") + `
      <div class="confirm-actions">
        <button type="button" data-act="confirm">Confirm purchase — $${(quote.total_cents / 100).toFixed(2)}</button>
        <button type="button" data-act="cancel">Cancel</button>
      </div>`;
    el.addEventListener("click", async (e) => {
      const act = e.target.closest("button")?.dataset.act;
      if (!act) return;
      el.querySelectorAll("button").forEach((b) => { b.disabled = true; });
      if (act === "cancel") { addMsg("bot", "Okay — no order was placed."); return; }
      try {
        const order = await window.Storefront.confirmQuote(quote.confirmation_token);
        addMsg("bot", `✅ Order ${order.order_id.slice(0, 8)}… placed — $${(order.total_cents / 100).toFixed(2)}.`);
      } catch (err) {
        addMsg("bot", `⚠️ ${err.message}`);
        el.querySelectorAll("button").forEach((b) => { b.disabled = false; });
      }
    });
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    addMsg("user", text);
    input.value = "";
    input.disabled = true;

    // Fetch + read the SSE stream manually so we can POST a JSON body
    // (EventSource is GET-only).
    let botEl = null;
    let botText = "";
    try {
      const res = await fetch("/api/chat/stream", {
        method: "POST",
        credentials: "same-origin",
        headers: { "content-type": "application/json", accept: "text/event-stream" },
        body: JSON.stringify({ message: text }),
      });
      if (!res.ok || !res.body) {
        addMsg("bot", `Error: ${res.statusText}`);
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let cartDirty = false;
      // Match blank line between SSE events with either \n\n or \r\n\r\n.
      const EVENT_SEP = /\r?\n\r?\n/;
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let match;
        while ((match = EVENT_SEP.exec(buffer))) {
          const raw = buffer.slice(0, match.index);
          buffer = buffer.slice(match.index + match[0].length);
          const lines = raw.split(/\r?\n/);
          let event = "message";
          let data = "";
          for (const line of lines) {
            if (line.startsWith("event:")) event = line.slice(6).trim();
            else if (line.startsWith("data:")) data += line.slice(5).trim();
          }
          if (!data) continue;
          let payload;
          try { payload = JSON.parse(data); } catch { continue; }
          if (event === "token") {
            if (!botEl) botEl = addMsg("bot", "");
            botText += payload.text || "";
            botEl.textContent = botText;
            messagesEl.scrollTop = messagesEl.scrollHeight;
          } else if (event === "tool_call") {
            addToolChip(payload.name, "");
            if (["add_to_cart", "remove_from_cart"].includes(payload.name)) {
              cartDirty = true;
            }
          } else if (event === "tool_result") {
            addToolChip(payload.name, payload.summary);
            if (payload.name === "prepare_checkout" && payload.result?.confirmation_token) {
              addConfirmCard(payload.result);
            }
            if (cartDirty && window.Storefront) {
              window.Storefront.refreshCart();
              cartDirty = false;
            }
          } else if (event === "error") {
            addMsg("bot", `⚠️ ${payload.message}`);
          }
        }
      }
      if (window.Storefront) window.Storefront.refreshCart();
    } catch (err) {
      addMsg("bot", `⚠️ ${err.message}`);
    } finally {
      input.disabled = false;
      input.focus();
    }
  });
})();
