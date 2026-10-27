/**
 * ABC Clothing — core storefront logic
 */
(function () {
  "use strict";

  const FALLBACK_IMG = "/assets/fallback-product.svg";
  let products = [];
  let productsSource = "fallback";

  // ---------- Theme ----------
  const THEMES = {
    modern: "Modern Colorful",
    luxury: "Luxury Black & Gold",
    beige: "Minimal Beige",
    street: "Streetwear Black & Red",
    pastel: "Pastel Playful",
  };

  function applyTheme(key) {
    if (!THEMES[key]) key = "modern";
    if (key === "modern") {
      document.documentElement.removeAttribute("data-theme");
    } else {
      document.documentElement.setAttribute("data-theme", key);
    }
    localStorage.setItem("abc_theme", key);
    const sel = document.getElementById("theme-select");
    if (sel) sel.value = key;
  }

  function initTheme() {
    const saved = localStorage.getItem("abc_theme") || "modern";
    applyTheme(saved);
    const sel = document.getElementById("theme-select");
    if (sel) {
      sel.innerHTML = Object.entries(THEMES)
        .map(([k, v]) => `<option value="${k}">${v}</option>`)
        .join("");
      sel.value = saved;
      sel.addEventListener("change", () => applyTheme(sel.value));
    }
  }

  // ---------- Branding + socials ----------
  let siteSettings = {
    brand_name: "ABC Clothing",
    logo_url: "",
    favicon_url: "",
    facebook_url: "",
    instagram_url: "",
    whatsapp: "",
  };

  function applyBrandName(name) {
    const n = (name || "ABC Clothing").trim() || "ABC Clothing";
    document.querySelectorAll(".logo-text, .footer-brand, [data-brand]").forEach((el) => {
      el.textContent = n;
    });
    document.title = document.title.replace(/ABC Clothing/g, n);
    // Update page title if it still has old name
    if (!document.title.includes(n) && document.title.includes("—")) {
      const parts = document.title.split("—");
      if (parts.length > 1) document.title = parts[0].trim() + " — " + n;
    }
  }

  function renderFloatingSocials(s) {
    const wa = (s.whatsapp || "").replace(/[^0-9]/g, "");
    const ig = (s.instagram_url || "").trim();
    const fb = (s.facebook_url || "").trim();

    const waBtn = document.getElementById("abc-float-wa");
    const igBtn = document.getElementById("abc-float-ig");

    if (waBtn) {
      if (wa) {
        waBtn.href = "https://wa.me/" + wa;
        waBtn.style.display = "flex";
        waBtn.setAttribute("aria-hidden", "false");
      } else {
        waBtn.href = "#";
        waBtn.style.display = "none";
        waBtn.setAttribute("aria-hidden", "true");
      }
    }
    if (igBtn) {
      if (ig) {
        igBtn.href = ig;
        igBtn.style.display = "flex";
        igBtn.setAttribute("aria-hidden", "false");
      } else {
        igBtn.href = "#";
        igBtn.style.display = "none";
        igBtn.setAttribute("aria-hidden", "true");
      }
    }

    const fs = document.getElementById("footer-social");
    if (fs) {
      let html = "";
      if (ig) html += '<a href="' + ig.replace(/"/g, "") + '" target="_blank" rel="noopener noreferrer" aria-label="Instagram" title="Instagram">IG</a>';
      if (fb) html += '<a href="' + fb.replace(/"/g, "") + '" target="_blank" rel="noopener noreferrer" aria-label="Facebook" title="Facebook">FB</a>';
      if (wa) html += '<a href="https://wa.me/' + wa + '" target="_blank" rel="noopener noreferrer" aria-label="WhatsApp" title="WhatsApp">WA</a>';
      fs.innerHTML = html;
    }
  }

  async function loadBranding() {
    let s = await ABC_API.getSettings();
    if (!s || typeof s !== "object") s = {};
    s.instagram_url = (s.instagram_url || "").trim();
    s.whatsapp = (s.whatsapp || "").trim();
    s.facebook_url = (s.facebook_url || "").trim();
    s.brand_name = (s.brand_name || "ABC Clothing").trim();
    siteSettings = { ...siteSettings, ...s };
    applyBrandName(s.brand_name);
    if (s.logo_url) {
      document.querySelectorAll(".logo-img").forEach((img) => {
        img.src = s.logo_url;
        img.classList.remove("hidden");
      });
      document.querySelectorAll(".logo-text").forEach((el) => el.classList.add("hidden"));
    } else {
      document.querySelectorAll(".logo-img").forEach((img) => img.classList.add("hidden"));
      document.querySelectorAll(".logo-text").forEach((el) => el.classList.remove("hidden"));
    }
    if (s.favicon_url) {
      let link = document.querySelector("link[rel*='icon']");
      if (!link) {
        link = document.createElement("link");
        link.rel = "icon";
        document.head.appendChild(link);
      }
      link.href = s.favicon_url;
    }
    renderFloatingSocials(s);
  }

  // ---------- Notice ----------
  async function loadNotice() {
    const { notice } = await ABC_API.getNotice();
    if (!notice || !notice.enabled) return;

    if (notice.notice_type === "banner") {
      const bar = document.getElementById("announcement");
      if (!bar) return;
      const dismissed = localStorage.getItem("abc_notice_dismissed");
      if (dismissed === notice.title + notice.message) return;
      bar.innerHTML = `
        <span>${esc(notice.message)}${notice.button_text ? ` — <a href="${escAttr(notice.button_url || "/shop.html")}">${esc(notice.button_text)}</a>` : ""}</span>
        <button type="button" class="close-ann" aria-label="Dismiss">&times;</button>
      `;
      bar.classList.remove("hidden");
      bar.querySelector(".close-ann")?.addEventListener("click", () => {
        bar.classList.add("hidden");
        localStorage.setItem("abc_notice_dismissed", notice.title + notice.message);
      });
    } else if (notice.notice_type === "modal") {
      const dismissed = localStorage.getItem("abc_notice_modal");
      if (dismissed === notice.title + notice.message) return;
      showNoticeModal(notice);
    }
  }

  function showNoticeModal(n) {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay notice-modal open";
    overlay.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true">
        <button type="button" class="modal-close" aria-label="Close">&times;</button>
        ${n.image_url ? `<img src="${escAttr(n.image_url)}" alt="" onerror="this.style.display='none'">` : ""}
        <h2 style="font-family:var(--font-display);margin-bottom:0.5rem;">${esc(n.title)}</h2>
        <p style="color:var(--color-muted);margin-bottom:1.25rem;">${esc(n.message)}</p>
        ${n.button_text ? `<a class="btn btn-primary" href="${escAttr(n.button_url || "/shop.html")}">${esc(n.button_text)}</a>` : ""}
      </div>
    `;
    document.body.appendChild(overlay);
    const close = () => {
      overlay.classList.remove("open");
      setTimeout(() => overlay.remove(), 300);
      localStorage.setItem("abc_notice_modal", n.title + n.message);
    };
    overlay.querySelector(".modal-close").addEventListener("click", close);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
  }

  // ---------- Products ----------
  async function loadProducts() {
    const res = await ABC_API.getProducts();
    products = res.products;
    productsSource = res.source;
    return products;
  }

  function getProduct(id) {
    return products.find((p) => String(p.id) === String(id));
  }

  function productCardHTML(p, index = 0) {
    const img = p.image_url || FALLBACK_IMG;
    return `
      <article class="product-card" style="animation-delay:${(index % 8) * 0.05}s" data-id="${p.id}">
        <div class="product-img-wrap">
          <a href="/product.html?id=${p.id}">
            <img src="${escAttr(img)}" alt="${escAttr(p.name)}" loading="lazy"
                 onerror="this.src='${FALLBACK_IMG}'">
          </a>
          <button type="button" class="quick-view-btn" data-quick="${p.id}">Quick view</button>
        </div>
        <div class="product-info">
          <div class="product-cat">${esc(p.category)}</div>
          <a href="/product.html?id=${p.id}" class="product-name">${esc(p.name)}</a>
          <div class="product-price">NPR ${Number(p.price).toLocaleString()}</div>
        </div>
      </article>
    `;
  }

  function renderProductGrid(el, list) {
    if (!el) return;
    if (!list.length) {
      el.innerHTML = `<p class="text-center" style="grid-column:1/-1;color:var(--color-muted);padding:3rem;">No products found.</p>`;
      return;
    }
    el.innerHTML = list.map((p, i) => productCardHTML(p, i)).join("");
    el.querySelectorAll("[data-quick]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        openQuickView(btn.dataset.quick);
      });
    });
  }

  // ---------- Quick view ----------
  function openQuickView(id) {
    const p = getProduct(id);
    if (!p) return;
    const colors = p.colors || [];
    const sizes = p.sizes || [];
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay open";
    overlay.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true">
        <div class="modal-body">
          <div class="modal-img">
            <img src="${escAttr(p.image_url || FALLBACK_IMG)}" alt="${escAttr(p.name)}"
                 onerror="this.src='${FALLBACK_IMG}'">
          </div>
          <div class="modal-info">
            <button type="button" class="modal-close" aria-label="Close">&times;</button>
            <div class="product-cat">${esc(p.category)}</div>
            <h2 style="font-family:var(--font-display);font-size:1.5rem;margin:0.25rem 0 0.5rem;">${esc(p.name)}</h2>
            <div class="pdp-price" style="font-size:1.25rem;">NPR ${Number(p.price).toLocaleString()}</div>
            <p class="pdp-desc" style="font-size:0.9rem;">${esc(p.description || "")}</p>
            ${colors.length ? `<div class="swatches" id="qv-colors">${colors.map((c, i) => `<button type="button" class="swatch${i === 0 ? " active" : ""}" data-color="${escAttr(c)}">${esc(c)}</button>`).join("")}</div>` : ""}
            ${sizes.length ? `<div class="size-grid" id="qv-sizes">${sizes.map((s, i) => `<button type="button" class="size-btn${i === 0 ? " active" : ""}" data-size="${escAttr(s)}">${esc(s)}</button>`).join("")}</div>` : ""}
            <button type="button" class="btn btn-primary" id="qv-add" style="width:100%;margin-top:1rem;">Add to cart</button>
            <a href="/product.html?id=${p.id}" style="display:block;text-align:center;margin-top:0.75rem;font-size:0.9rem;text-decoration:underline;">View full details</a>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    const close = () => { overlay.classList.remove("open"); setTimeout(() => overlay.remove(), 300); };
    overlay.querySelector(".modal-close").addEventListener("click", close);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });

    overlay.querySelectorAll("#qv-colors .swatch").forEach((b) => {
      b.addEventListener("click", () => {
        overlay.querySelectorAll("#qv-colors .swatch").forEach((x) => x.classList.remove("active"));
        b.classList.add("active");
      });
    });
    overlay.querySelectorAll("#qv-sizes .size-btn").forEach((b) => {
      b.addEventListener("click", () => {
        overlay.querySelectorAll("#qv-sizes .size-btn").forEach((x) => x.classList.remove("active"));
        b.classList.add("active");
      });
    });
    overlay.querySelector("#qv-add").addEventListener("click", () => {
      const color = overlay.querySelector("#qv-colors .swatch.active")?.dataset.color || "";
      const size = overlay.querySelector("#qv-sizes .size-btn.active")?.dataset.size || "";
      ABC_Cart.add(p, { color, size, quantity: 1 });
      toast(`${p.name} added to cart`);
      close();
      openCart();
    });
  }

  // ---------- Cart UI ----------
  function openCart() {
    document.getElementById("cart-overlay")?.classList.add("open");
    document.getElementById("cart-drawer")?.classList.add("open");
    renderCartDrawer();
  }
  function closeCart() {
    document.getElementById("cart-overlay")?.classList.remove("open");
    document.getElementById("cart-drawer")?.classList.remove("open");
  }

  function renderCartDrawer() {
    const body = document.getElementById("cart-body");
    const footer = document.getElementById("cart-footer");
    if (!body) return;
    const items = ABC_Cart.items;
    if (!items.length) {
      body.innerHTML = `<div class="empty-cart"><p>Your cart is empty</p><a href="/shop.html" class="btn btn-outline btn-sm mt-4">Continue shopping</a></div>`;
      if (footer) footer.classList.add("hidden");
      return;
    }
    body.innerHTML = items.map((it, i) => `
      <div class="cart-item">
        <img src="${escAttr(it.image_url || FALLBACK_IMG)}" alt="" onerror="this.src='${FALLBACK_IMG}'">
        <div class="cart-item-info">
          <div class="cart-item-name">${esc(it.name)}</div>
          <div class="cart-item-meta">${[it.size, it.color].filter(Boolean).join(" · ")} · NPR ${Number(it.price).toLocaleString()}</div>
          <div class="qty-row" style="margin:0.5rem 0 0;">
            <button type="button" class="qty-btn" data-dec="${i}">−</button>
            <span class="qty-val">${it.quantity}</span>
            <button type="button" class="qty-btn" data-inc="${i}">+</button>
            <button type="button" style="margin-left:auto;font-size:0.8rem;color:var(--color-danger);" data-rm="${i}">Remove</button>
          </div>
        </div>
      </div>
    `).join("");
    if (footer) {
      footer.classList.remove("hidden");
      footer.querySelector(".cart-total-val").textContent = "NPR " + ABC_Cart.subtotal().toLocaleString();
    }
    body.querySelectorAll("[data-dec]").forEach((b) => b.addEventListener("click", () => {
      ABC_Cart.updateQty(+b.dataset.dec, ABC_Cart.items[+b.dataset.dec].quantity - 1);
      renderCartDrawer();
    }));
    body.querySelectorAll("[data-inc]").forEach((b) => b.addEventListener("click", () => {
      ABC_Cart.updateQty(+b.dataset.inc, ABC_Cart.items[+b.dataset.inc].quantity + 1);
      renderCartDrawer();
    }));
    body.querySelectorAll("[data-rm]").forEach((b) => b.addEventListener("click", () => {
      ABC_Cart.remove(+b.dataset.rm);
      renderCartDrawer();
    }));
  }

  // ---------- Search ----------
  function openSearch() {
    document.getElementById("search-overlay")?.classList.add("open");
    document.getElementById("search-input")?.focus();
  }
  function closeSearch() {
    document.getElementById("search-overlay")?.classList.remove("open");
  }
  function runSearch(q) {
    const el = document.getElementById("search-results");
    if (!el) return;
    q = (q || "").trim().toLowerCase();
    if (!q) { el.innerHTML = ""; return; }
    const hits = products.filter(
      (p) => p.name.toLowerCase().includes(q) || (p.category || "").toLowerCase().includes(q) || (p.description || "").toLowerCase().includes(q)
    ).slice(0, 8);
    if (!hits.length) {
      el.innerHTML = `<p style="color:var(--color-muted);padding:1rem;">No results for “${esc(q)}”</p>`;
      return;
    }
    el.innerHTML = hits.map((p) => `
      <a href="/product.html?id=${p.id}" class="search-result-item">
        <img src="${escAttr(p.image_url || FALLBACK_IMG)}" alt="" onerror="this.src='${FALLBACK_IMG}'">
        <div>
          <div style="font-weight:600;">${esc(p.name)}</div>
          <div style="font-size:0.85rem;color:var(--color-muted);">NPR ${Number(p.price).toLocaleString()}</div>
        </div>
      </a>
    `).join("");
  }

  // ---------- Mobile nav ----------
  function initMobileNav() {
    const toggle = document.getElementById("mobile-toggle");
    const nav = document.getElementById("mobile-nav");
    const close = document.getElementById("mobile-close");
    toggle?.addEventListener("click", () => nav?.classList.add("open"));
    close?.addEventListener("click", () => nav?.classList.remove("open"));
  }

  // ---------- Scroll ----------
  function initScroll() {
    const header = document.querySelector(".site-header");
    const topBtn = document.getElementById("scroll-top");
    window.addEventListener("scroll", () => {
      const y = window.scrollY;
      header?.classList.toggle("scrolled", y > 20);
      topBtn?.classList.toggle("show", y > 400);
    }, { passive: true });
    topBtn?.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
  }

  // ---------- Toast ----------
  function toast(msg, isErr) {
    let el = document.getElementById("toast");
    if (!el) {
      el = document.createElement("div");
      el.id = "toast";
      el.className = "toast";
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.className = "toast show" + (isErr ? " err" : "");
    setTimeout(() => el.classList.remove("show"), 3000);
  }
  window.ABC_toast = toast;

  // ---------- Helpers ----------
  function esc(s) {
    const d = document.createElement("div");
    d.textContent = s ?? "";
    return d.innerHTML;
  }
  function escAttr(s) {
    return String(s ?? "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
  }

  // ---------- Shared header/footer injection ----------
  function buildHeader() {
    return `
      <div id="announcement" class="announcement hidden"></div>
      <header class="site-header">
        <div class="header-inner">
          <a href="/" class="logo">
            <img class="logo-img hidden" src="" alt="ABC Clothing">
            <span class="logo-text">ABC Clothing</span>
          </a>
          <nav class="nav-links" aria-label="Main">
            <a href="/">Home</a>
            <a href="/shop.html">Shop</a>
            <a href="/shop.html?cat=men">Men</a>
            <a href="/shop.html?cat=women">Women</a>
            <a href="/shop.html?cat=streetwear">Streetwear</a>
            <a href="/contact.html">Contact</a>
          </nav>
          <div class="header-actions">
            <select id="theme-select" class="theme-select" aria-label="Theme"></select>
            <button type="button" class="icon-btn" id="search-btn" aria-label="Search">
              <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><circle cx="9" cy="9" r="6"/><path d="M14 14l4 4"/></svg>
            </button>
            <button type="button" class="icon-btn" id="cart-btn" aria-label="Cart">
              <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 6h15l-1.5 9h-12z"/><circle cx="9" cy="19" r="1"/><circle cx="17" cy="19" r="1"/><path d="M6 6L5 2H2"/></svg>
              <span class="cart-count" style="display:none">0</span>
            </button>
            <button type="button" class="icon-btn mobile-toggle" id="mobile-toggle" aria-label="Menu">
              <svg width="22" height="22" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h16M3 12h16M3 18h16"/></svg>
            </button>
          </div>
        </div>
      </header>
      <div id="mobile-nav" class="mobile-nav">
        <button type="button" id="mobile-close" style="align-self:flex-end;font-size:1.75rem;padding:0.5rem;" aria-label="Close">&times;</button>
        <a href="/">Home</a>
        <a href="/shop.html">Shop</a>
        <a href="/shop.html?cat=men">Men</a>
        <a href="/shop.html?cat=women">Women</a>
        <a href="/shop.html?cat=streetwear">Streetwear</a>
        <a href="/shop.html?cat=accessories">Accessories</a>
        <a href="/contact.html">Contact</a>
      </div>
      <div id="search-overlay" class="search-overlay">
        <div class="search-box">
          <input type="search" id="search-input" placeholder="Search products…" autocomplete="off">
          <button type="button" class="search-close" id="search-close" aria-label="Close">&times;</button>
        </div>
        <div id="search-results" class="search-results"></div>
      </div>
      <div id="cart-overlay" class="cart-overlay"></div>
      <aside id="cart-drawer" class="cart-drawer" aria-label="Shopping cart">
        <div class="cart-header">
          <strong>Your Cart</strong>
          <button type="button" id="cart-close" aria-label="Close" style="font-size:1.5rem;">&times;</button>
        </div>
        <div id="cart-body" class="cart-body"></div>
        <div id="cart-footer" class="cart-footer hidden">
          <div class="cart-total"><span>Subtotal</span><span class="cart-total-val">NPR 0</span></div>
          <a href="/checkout.html" class="btn btn-primary" style="width:100%;">Checkout</a>
        </div>
      </aside>
      <button type="button" id="scroll-top" class="scroll-top" aria-label="Scroll to top">↑</button>
      <div id="toast" class="toast"></div>

      <!-- Hardcoded floating socials — href updated from /api/settings -->
      <a id="abc-float-wa" class="float-btn wa" href="#" target="_blank" rel="noopener noreferrer"
         aria-label="WhatsApp" title="WhatsApp" style="display:none;position:fixed;left:16px;bottom:88px;z-index:9999;width:54px;height:54px;border-radius:50%;align-items:center;justify-content:center;background:linear-gradient(145deg,#25d366,#128c7e);color:#fff;text-decoration:none;box-shadow:0 6px 20px rgba(0,0,0,.28);border:2px solid rgba(255,255,255,.4);">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="#fff" aria-hidden="true"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.435 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg>
      </a>
      <a id="abc-float-ig" class="float-btn ig" href="#" target="_blank" rel="noopener noreferrer"
         aria-label="Instagram" title="Instagram" style="display:none;position:fixed;right:16px;bottom:88px;z-index:9999;width:54px;height:54px;border-radius:50%;align-items:center;justify-content:center;background:linear-gradient(45deg,#f09433,#e6683c,#dc2743,#cc2366,#bc1888);color:#fff;text-decoration:none;box-shadow:0 6px 20px rgba(0,0,0,.28);border:2px solid rgba(255,255,255,.4);">
        <svg width="26" height="26" viewBox="0 0 24 24" fill="#fff" aria-hidden="true"><path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 100 12.324 6.162 6.162 0 000-12.324zM12 16a4 4 0 110-8 4 4 0 010 8zm6.406-11.845a1.44 1.44 0 100 2.881 1.44 1.44 0 000-2.881z"/></svg>
      </a>
    `;
  }

  function buildFooter() {
    const year = new Date().getFullYear();
    return `
      <footer class="site-footer">
        <div class="container">
          <div class="footer-grid">
            <div>
              <div class="footer-brand" data-brand>ABC Clothing</div>
              <p style="opacity:0.8;max-width:280px;font-size:0.95rem;">Premium fashion for every expression — menswear, womenswear, streetwear and accessories.</p>
              <div class="footer-social" id="footer-social"></div>
            </div>
            <div class="footer-links">
              <h4>Shop</h4>
              <a href="/shop.html?cat=men">Men</a>
              <a href="/shop.html?cat=women">Women</a>
              <a href="/shop.html?cat=streetwear">Streetwear</a>
              <a href="/shop.html?cat=accessories">Accessories</a>
            </div>
            <div class="footer-links">
              <h4>Help</h4>
              <a href="/contact.html">Contact</a>
              <a href="/shop.html">Shipping</a>
              <a href="/shop.html">Returns</a>
            </div>
            <div class="footer-links">
              <h4>Connect</h4>
              <a href="/contact.html">Contact us</a>
            </div>
          </div>
          <div class="footer-bottom">
            <span>© ${year} <span data-brand>ABC Clothing</span></span>
            <span class="footer-credit">Technology by <a href="https://bamstudio.argan.com.np/" target="_blank" rel="noopener noreferrer">BAM Studio</a></span>
          </div>
        </div>
      </footer>
    `;
  }

  // ---------- Page inits ----------
  async function initHome() {
    const grid = document.getElementById("featured-grid");
    const newGrid = document.getElementById("new-grid");
    const trendGrid = document.getElementById("trend-grid");
    await loadProducts();
    const active = products.filter((p) => p.active !== false);
    renderProductGrid(grid, active.slice(0, 4));
    renderProductGrid(newGrid, active.slice(0, 4));
    renderProductGrid(trendGrid, active.slice(4, 8).length ? active.slice(4, 8) : active.slice(0, 4));
  }

  async function initShop() {
    await loadProducts();
    const params = new URLSearchParams(location.search);
    let cat = params.get("cat") || "all";
    let sort = "featured";
    let maxPrice = Infinity;
    let query = (params.get("q") || "").toLowerCase();

    const grid = document.getElementById("shop-grid");
    const countEl = document.getElementById("result-count");

    function applyFilters() {
      let list = products.filter((p) => p.active !== false);
      if (cat && cat !== "all") list = list.filter((p) => (p.category || "").toLowerCase() === cat);
      if (query) list = list.filter((p) => p.name.toLowerCase().includes(query) || (p.description || "").toLowerCase().includes(query));
      if (maxPrice < Infinity) list = list.filter((p) => p.price <= maxPrice);
      if (sort === "price-asc") list = [...list].sort((a, b) => a.price - b.price);
      else if (sort === "price-desc") list = [...list].sort((a, b) => b.price - a.price);
      else if (sort === "name") list = [...list].sort((a, b) => a.name.localeCompare(b.name));
      renderProductGrid(grid, list);
      if (countEl) countEl.textContent = list.length + " product" + (list.length !== 1 ? "s" : "");
    }

    document.querySelectorAll(".filter-chip").forEach((chip) => {
      if (chip.dataset.cat === cat) chip.classList.add("active");
      chip.addEventListener("click", () => {
        document.querySelectorAll(".filter-chip").forEach((c) => c.classList.remove("active"));
        chip.classList.add("active");
        cat = chip.dataset.cat;
        applyFilters();
      });
    });
    document.getElementById("sort-select")?.addEventListener("change", (e) => {
      sort = e.target.value;
      applyFilters();
    });
    document.getElementById("price-filter")?.addEventListener("change", (e) => {
      const v = e.target.value;
      maxPrice = v === "all" ? Infinity : Number(v);
      applyFilters();
    });
    applyFilters();
  }

  async function initProduct() {
    await loadProducts();
    const id = new URLSearchParams(location.search).get("id");
    const p = getProduct(id);
    const root = document.getElementById("pdp-root");
    if (!p || !root) {
      if (root) root.innerHTML = `<p class="text-center" style="padding:4rem;">Product not found. <a href="/shop.html">Back to shop</a></p>`;
      return;
    }
    const colors = p.colors || [];
    const sizes = p.sizes || [];
    root.innerHTML = `
      <div class="pdp container">
        <div class="pdp-gallery">
          <img src="${escAttr(p.image_url || FALLBACK_IMG)}" alt="${escAttr(p.name)}" onerror="this.src='${FALLBACK_IMG}'">
        </div>
        <div class="pdp-info">
          <div class="product-cat">${esc(p.category)}</div>
          <h1>${esc(p.name)}</h1>
          <div class="pdp-price">NPR ${Number(p.price).toLocaleString()}</div>
          <p class="pdp-desc">${esc(p.description || "")}</p>
          ${colors.length ? `<label style="font-weight:600;font-size:0.85rem;">Color</label><div class="swatches" id="pdp-colors">${colors.map((c, i) => `<button type="button" class="swatch${i === 0 ? " active" : ""}" data-color="${escAttr(c)}">${esc(c)}</button>`).join("")}</div>` : ""}
          ${sizes.length ? `<label style="font-weight:600;font-size:0.85rem;">Size</label><div class="size-grid" id="pdp-sizes">${sizes.map((s, i) => `<button type="button" class="size-btn${i === 0 ? " active" : ""}" data-size="${escAttr(s)}">${esc(s)}</button>`).join("")}</div>` : ""}
          <label style="font-weight:600;font-size:0.85rem;">Quantity</label>
          <div class="qty-row">
            <button type="button" class="qty-btn" id="qty-dec">−</button>
            <span class="qty-val" id="qty-val">1</span>
            <button type="button" class="qty-btn" id="qty-inc">+</button>
          </div>
          <button type="button" class="btn btn-primary" id="add-cart-btn" style="width:100%;max-width:280px;">Add to cart</button>
        </div>
      </div>
      <div class="container section">
        <h2 class="section-title">You may also like</h2>
        <div class="product-grid" id="related-grid"></div>
      </div>
    `;
    let qty = 1;
    document.getElementById("qty-dec").addEventListener("click", () => { qty = Math.max(1, qty - 1); document.getElementById("qty-val").textContent = qty; });
    document.getElementById("qty-inc").addEventListener("click", () => { qty = Math.min(20, qty + 1); document.getElementById("qty-val").textContent = qty; });
    document.querySelectorAll("#pdp-colors .swatch").forEach((b) => b.addEventListener("click", () => {
      document.querySelectorAll("#pdp-colors .swatch").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
    }));
    document.querySelectorAll("#pdp-sizes .size-btn").forEach((b) => b.addEventListener("click", () => {
      document.querySelectorAll("#pdp-sizes .size-btn").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
    }));
    document.getElementById("add-cart-btn").addEventListener("click", () => {
      const color = document.querySelector("#pdp-colors .swatch.active")?.dataset.color || "";
      const size = document.querySelector("#pdp-sizes .size-btn.active")?.dataset.size || "";
      ABC_Cart.add(p, { color, size, quantity: qty });
      toast(`${p.name} added to cart`);
      openCart();
    });
    const related = products.filter((x) => x.id !== p.id && x.category === p.category).slice(0, 4);
    renderProductGrid(document.getElementById("related-grid"), related.length ? related : products.filter((x) => x.id !== p.id).slice(0, 4));
  }

  async function initCheckout() {
    await loadProducts();
    const items = ABC_Cart.items;
    const summary = document.getElementById("order-summary-items");
    const totalEl = document.getElementById("order-total");
    if (!items.length) {
      document.getElementById("checkout-root").innerHTML = `<p class="text-center" style="padding:4rem;">Your cart is empty. <a href="/shop.html">Continue shopping</a></p>`;
      return;
    }
    summary.innerHTML = items.map((it) => `
      <div class="summary-line">
        <span>${esc(it.name)} × ${it.quantity}${it.size || it.color ? ` (${[it.size, it.color].filter(Boolean).join(", ")})` : ""}</span>
        <span>NPR ${(it.price * it.quantity).toLocaleString()}</span>
      </div>
    `).join("");
    totalEl.textContent = "NPR " + ABC_Cart.subtotal().toLocaleString();

    document.getElementById("checkout-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = document.getElementById("place-order");
      btn.disabled = true;
      btn.textContent = "Submitting…";
      const payload = {
        name: document.getElementById("c-name").value.trim(),
        email: document.getElementById("c-email").value.trim(),
        phone: document.getElementById("c-phone").value.trim(),
        address: document.getElementById("c-address").value.trim(),
        city: document.getElementById("c-city").value.trim(),
        notes: document.getElementById("c-notes").value.trim(),
        items: items.map((it) => ({
          id: it.id,
          quantity: it.quantity,
          size: it.size,
          color: it.color,
        })),
      };
      const res = await ABC_API.submitOrder(payload);
      if (res.ok && res.data.ok) {
        ABC_Cart.clear();
        document.getElementById("checkout-root").innerHTML = `
          <div class="text-center" style="padding:4rem 1rem;max-width:480px;margin:0 auto;">
            <h1 style="font-family:var(--font-display);margin-bottom:1rem;">Order Request Received</h1>
            <p style="margin-bottom:0.75rem;">Reference: <strong>${esc(res.data.order_ref)}</strong></p>
            <p style="color:var(--color-muted);margin-bottom:1.5rem;">${esc(res.data.message || "We will confirm your order shortly. No payment has been processed.")}</p>
            <a href="/" class="btn btn-primary">Back to home</a>
          </div>
        `;
      } else {
        toast(res.data.error || "Could not submit order. Please try again.", true);
        btn.disabled = false;
        btn.textContent = "Place order request";
      }
    });
  }

  async function initContact() {
    document.getElementById("contact-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = e.target.querySelector("button[type=submit]");
      btn.disabled = true;
      const res = await ABC_API.submitContact({
        name: document.getElementById("ct-name").value.trim(),
        email: document.getElementById("ct-email").value.trim(),
        message: document.getElementById("ct-message").value.trim(),
      });
      if (res.ok && res.data.ok) {
        toast(res.data.message || "Message sent");
        e.target.reset();
      } else {
        toast(res.data.error || "Could not send message", true);
      }
      btn.disabled = false;
    });
  }

  // ---------- Boot ----------
  function injectChrome() {
    const headerMount = document.getElementById("site-header-mount");
    const footerMount = document.getElementById("site-footer-mount");
    if (headerMount) headerMount.innerHTML = buildHeader();
    if (footerMount) footerMount.innerHTML = buildFooter();
  }

  function bindGlobal() {
    document.getElementById("cart-btn")?.addEventListener("click", openCart);
    document.getElementById("cart-close")?.addEventListener("click", closeCart);
    document.getElementById("cart-overlay")?.addEventListener("click", closeCart);
    document.getElementById("search-btn")?.addEventListener("click", openSearch);
    document.getElementById("search-close")?.addEventListener("click", closeSearch);
    document.getElementById("search-input")?.addEventListener("input", (e) => runSearch(e.target.value));
    document.getElementById("search-overlay")?.addEventListener("click", (e) => {
      if (e.target.id === "search-overlay") closeSearch();
    });
    initMobileNav();
    initScroll();
    window.addEventListener("cart:updated", () => {
      ABC_Cart.renderCount();
      if (document.getElementById("cart-drawer")?.classList.contains("open")) renderCartDrawer();
    });
  }

  document.addEventListener("DOMContentLoaded", async () => {
    injectChrome();
    initTheme();
    bindGlobal();
    ABC_Cart.renderCount();
    await loadBranding();
    loadNotice();

    const page = document.body.dataset.page;
    if (page === "home") await initHome();
    else if (page === "shop") await initShop();
    else if (page === "product") await initProduct();
    else if (page === "checkout") await initCheckout();
    else if (page === "contact") await initContact();
    else await loadProducts(); // still load for search
  });
})();
