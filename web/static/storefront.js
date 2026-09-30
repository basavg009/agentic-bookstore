// Storefront: search, cart drawer, checkout. Exposes a global `Storefront` object
// so the chat panel can nudge the cart to refresh after agent tool calls.
(() => {
  const $ = (id) => document.getElementById(id);
  const resultsEl = $("results");
  const cartCountEl = $("cart-count");
  const cartSubtotalEl = $("cart-subtotal");
  const drawerEl = $("cart-drawer");
  const drawerItemsEl = $("cart-items");
  const drawerSubtotalEl = $("drawer-subtotal");
  const openCheckoutBtn = $("open-checkout");
  const checkoutModal = $("checkout-modal");
  const checkoutForm = $("checkout-form");
  const confirmationModal = $("confirmation-modal");

  const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));

  const money = (cents) => (cents / 100).toFixed(2);

  async function fetchJSON(url, opts = {}) {
    const res = await fetch(url, { credentials: "same-origin", ...opts });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(detail.detail || res.statusText);
    }
    return res.json();
  }

  function renderBook(b) {
    const inStock = b.in_stock;
    const stockLabel = b.medium === "digital" ? "Instant download" : (b.stock > 0 ? `${b.stock} in stock` : "Out of stock");
    return `
      <article class="book" data-isbn="${escapeHtml(b.isbn13)}">
        <div class="title">${escapeHtml(b.title)}</div>
        <div class="author">by ${escapeHtml(b.author)}</div>
        <div class="meta">${escapeHtml(b.genre)} · ${escapeHtml(b.format)} · ${escapeHtml(b.year.toString())}</div>
        <div class="description">${escapeHtml(b.description.slice(0, 180))}${b.description.length > 180 ? "…" : ""}</div>
        <div class="footer">
          <div><span class="price">$${money(b.price_cents)}</span> <span class="meta">${stockLabel}</span></div>
          <button class="add" data-isbn="${escapeHtml(b.isbn13)}" ${inStock ? "" : "disabled"}>Add</button>
        </div>
      </article>`;
  }

  async function runSearch() {
    const q = $("q").value.trim();
    const params = new URLSearchParams();
    if (q) {
      if (/^\d{10,13}$/.test(q)) params.set("isbn", q);
      else params.set("query", q);
    }
    const g = $("f-genre").value; if (g) params.set("genre", g);
    const m = $("f-medium").value; if (m) params.set("medium", m);
    const maxPrice = $("f-max").value; if (maxPrice) params.set("max_price_cents", String(Math.round(parseFloat(maxPrice) * 100)));
    params.set("limit", "24");
    try {
      const data = await fetchJSON(`/api/books/search?${params}`);
      if (!data.items.length) {
        resultsEl.innerHTML = `<p class="hint">No matches. Try broader terms.</p>`;
      } else {
        resultsEl.innerHTML = data.items.map(renderBook).join("");
      }
    } catch (e) {
      resultsEl.innerHTML = `<p class="hint">Error: ${escapeHtml(e.message)}</p>`;
    }
  }

  async function refreshCart() {
    try {
      const cart = await fetchJSON("/api/cart");
      cartCountEl.textContent = cart.count;
      cartSubtotalEl.textContent = money(cart.subtotal_cents);
      drawerSubtotalEl.textContent = money(cart.subtotal_cents);
      openCheckoutBtn.disabled = cart.count === 0;
      drawerItemsEl.innerHTML = cart.items.map((i) => `
        <div class="cart-item" data-isbn="${escapeHtml(i.isbn13)}">
          <div>
            <div><strong>${escapeHtml(i.title)}</strong></div>
            <div class="meta">${escapeHtml(i.format)} · $${money(i.unit_price_cents)}</div>
            <button class="remove" data-remove="${escapeHtml(i.isbn13)}">Remove</button>
          </div>
          <div class="qty">
            <button data-delta="-1" data-isbn="${escapeHtml(i.isbn13)}">−</button>
            <span>${i.quantity}</span>
            <button data-delta="1" data-isbn="${escapeHtml(i.isbn13)}">+</button>
          </div>
        </div>`).join("") || `<p class="hint">Cart is empty.</p>`;
      return cart;
    } catch (e) {
      console.error(e);
    }
  }

  async function addToCart(isbn, qty = 1) {
    await fetchJSON("/api/cart/items", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ isbn, quantity: qty }),
    });
    await refreshCart();
  }

  async function setQty(isbn, quantity) {
    await fetchJSON(`/api/cart/items/${encodeURIComponent(isbn)}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ quantity }),
    });
    await refreshCart();
  }

  async function removeItem(isbn) {
    await fetchJSON(`/api/cart/items/${encodeURIComponent(isbn)}`, { method: "DELETE" });
    await refreshCart();
  }

  // Wire events.
  $("search-form").addEventListener("submit", (e) => { e.preventDefault(); runSearch(); });
  ["f-genre", "f-medium", "f-max"].forEach((id) => $(id).addEventListener("change", runSearch));

  resultsEl.addEventListener("click", (e) => {
    const btn = e.target.closest(".add");
    if (btn) addToCart(btn.dataset.isbn).catch((err) => alert(err.message));
  });

  $("open-cart").addEventListener("click", () => { drawerEl.hidden = false; });
  $("close-cart").addEventListener("click", () => { drawerEl.hidden = true; });

  drawerItemsEl.addEventListener("click", async (e) => {
    const rm = e.target.closest("[data-remove]");
    if (rm) return removeItem(rm.dataset.remove).catch((err) => alert(err.message));
    const q = e.target.closest("[data-delta]");
    if (q) {
      const card = q.closest(".cart-item");
      const cur = parseInt(card.querySelector(".qty span").textContent, 10);
      const next = Math.max(0, cur + parseInt(q.dataset.delta, 10));
      return setQty(q.dataset.isbn, next).catch((err) => alert(err.message));
    }
  });

  // Two-phase checkout: "Review order" locks prices into a quote, "Place order"
  // confirms that exact quote (its token is also the idempotency key).
  const reviewEl = $("order-review");
  const reviewBtn = $("review-order");
  const placeBtn = $("place-order");
  let pendingToken = null;

  function resetCheckout() {
    pendingToken = null;
    reviewEl.hidden = true;
    reviewEl.innerHTML = "";
    reviewBtn.hidden = false;
    placeBtn.hidden = true;
  }

  function renderQuote(quote) {
    return `<h3>Order summary</h3>` + quote.items.map((i) => `
      <div class="review-line"><span>${i.quantity} × ${escapeHtml(i.title)}</span>
      <span>$${money(i.line_total_cents)}</span></div>`).join("") +
      `<div class="review-line total"><span>Total</span><strong>$${money(quote.total_cents)}</strong></div>`;
  }

  async function confirmQuote(token) {
    const order = await fetchJSON("/api/checkout/confirm", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ confirmation_token: token }),
    });
    $("conf-id").textContent = order.order_id;
    $("conf-total").textContent = money(order.total_cents);
    $("conf-delivery").textContent = order.requires_shipping
      ? `Estimated delivery: ${order.estimated_delivery}` : "Digital items delivered instantly.";
    confirmationModal.showModal();
    drawerEl.hidden = true;
    await refreshCart();
    return order;
  }

  openCheckoutBtn.addEventListener("click", () => { resetCheckout(); checkoutModal.showModal(); });
  checkoutForm.addEventListener("input", () => { if (pendingToken) resetCheckout(); });

  checkoutForm.addEventListener("submit", async (e) => {
    if (e.submitter && e.submitter.value === "cancel") { resetCheckout(); return; }
    e.preventDefault();
    try {
      if (!pendingToken) {
        const fd = new FormData(checkoutForm);
        const quote = await fetchJSON("/api/checkout/prepare", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            shipping_name: fd.get("shipping_name") || "",
            shipping_address: fd.get("shipping_address") || "",
            email: fd.get("email") || "",
          }),
        });
        pendingToken = quote.confirmation_token;
        reviewEl.innerHTML = renderQuote(quote);
        reviewEl.hidden = false;
        reviewBtn.hidden = true;
        placeBtn.hidden = false;
        placeBtn.textContent = `Place order — $${money(quote.total_cents)}`;
        return;
      }
      placeBtn.disabled = true;
      await confirmQuote(pendingToken);
      checkoutModal.close();
      resetCheckout();
    } catch (err) {
      alert(err.message);
      resetCheckout();
    } finally {
      placeBtn.disabled = false;
    }
  });

  $("close-confirmation").addEventListener("click", () => confirmationModal.close());

  window.Storefront = { refreshCart, confirmQuote, renderQuote };
  refreshCart();
})();
