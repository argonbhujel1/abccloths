/** Minimal storefront JS — theme, cart UI, mobile nav (~5% of stack) */
(function () {
  // Mid-page navigation loader
  var loader = document.createElement("div");
  loader.className = "page-loader";
  loader.innerHTML = '<div class="mid-spin" aria-hidden="true"></div><div class="mid-label">Loading…</div>';
  document.body.appendChild(loader);
  function startLoad() { loader.classList.remove("done"); loader.classList.add("active"); }
  function endLoad() { loader.classList.add("done"); setTimeout(function(){ loader.classList.remove("active","done"); }, 280); }
  document.addEventListener("click", function (e) {
    var a = e.target.closest("a[href]");
    if (!a) return;
    var href = a.getAttribute("href") || "";
    if (href.startsWith("#") || href.startsWith("mailto:") || href.startsWith("tel:") || a.target === "_blank") return;
    if (href.startsWith("http") && href.indexOf(location.host) === -1) return;
    startLoad();
  });
  window.addEventListener("pageshow", endLoad);

  function applyTheme(key) {
    if (!key || key === "modern") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", key);
    localStorage.setItem("abc_theme", key || "modern");
    var sel = document.getElementById("theme-select");
    if (sel) sel.value = key || "modern";
  }
  applyTheme(localStorage.getItem("abc_theme") || "modern");
  var sel = document.getElementById("theme-select");
  if (sel) sel.addEventListener("change", function () { applyTheme(sel.value); });

  function toast(msg, err) {
    var el = document.getElementById("toast");
    if (!el) return;
    el.textContent = msg;
    el.className = "toast show" + (err ? " err" : "");
    setTimeout(function () {
  // Mid-page navigation loader
  var loader = document.createElement("div");
  loader.className = "page-loader";
  loader.innerHTML = '<div class="mid-spin" aria-hidden="true"></div><div class="mid-label">Loading…</div>';
  document.body.appendChild(loader);
  function startLoad() { loader.classList.remove("done"); loader.classList.add("active"); }
  function endLoad() { loader.classList.add("done"); setTimeout(function(){ loader.classList.remove("active","done"); }, 280); }
  document.addEventListener("click", function (e) {
    var a = e.target.closest("a[href]");
    if (!a) return;
    var href = a.getAttribute("href") || "";
    if (href.startsWith("#") || href.startsWith("mailto:") || href.startsWith("tel:") || a.target === "_blank") return;
    if (href.startsWith("http") && href.indexOf(location.host) === -1) return;
    startLoad();
  });
  window.addEventListener("pageshow", endLoad);
 el.classList.remove("show"); }, 2800);
  }
  window.ABC_toast = toast;

  function openCart() {
    document.getElementById("cart-overlay") && document.getElementById("cart-overlay").classList.add("open");
    document.getElementById("cart-drawer") && document.getElementById("cart-drawer").classList.add("open");
    renderCart();
  }
  function closeCart() {
    document.getElementById("cart-overlay") && document.getElementById("cart-overlay").classList.remove("open");
    document.getElementById("cart-drawer") && document.getElementById("cart-drawer").classList.remove("open");
  }
  function renderCart() {
    var body = document.getElementById("cart-body");
    var footer = document.getElementById("cart-footer");
    if (!body || !window.ABC_Cart) return;
    var items = ABC_Cart.items;
    if (!items.length) {
      body.innerHTML = '<div class="empty-cart"><p>Your cart is empty</p><a href="/shop" class="btn btn-outline btn-sm mt-4">Shop</a></div>';
      if (footer) footer.classList.add("hidden");
      return;
    }
    body.innerHTML = items.map(function (it, i) {
      return '<div class="cart-item"><img src="' + (it.image_url || "/assets/fallback-product.svg") + '" alt="" onerror="this.src=\'/assets/fallback-product.svg\'"><div class="cart-item-info"><div class="cart-item-name">' +
        (it.name || "") + '</div><div class="cart-item-meta">' + [it.size, it.color].filter(Boolean).join(" · ") +
        " · NPR " + Number(it.price).toLocaleString() + '</div><div class="qty-row" style="margin-top:0.5rem"><button type="button" class="qty-btn" data-dec="' + i + '">−</button><span class="qty-val">' +
        it.quantity + '</span><button type="button" class="qty-btn" data-inc="' + i + '">+</button><button type="button" style="margin-left:auto;font-size:0.8rem;color:var(--color-danger)" data-rm="' + i + '">Remove</button></div></div></div>';
    }).join("");
    if (footer) {
      footer.classList.remove("hidden");
      var tv = footer.querySelector(".cart-total-val");
      if (tv) tv.textContent = "NPR " + ABC_Cart.subtotal().toLocaleString();
    }
    body.querySelectorAll("[data-dec]").forEach(function (b) {
      b.addEventListener("click", function () {
        ABC_Cart.updateQty(+b.dataset.dec, ABC_Cart.items[+b.dataset.dec].quantity - 1);
        renderCart();
      });
    });
    body.querySelectorAll("[data-inc]").forEach(function (b) {
      b.addEventListener("click", function () {
        ABC_Cart.updateQty(+b.dataset.inc, ABC_Cart.items[+b.dataset.inc].quantity + 1);
        renderCart();
      });
    });
    body.querySelectorAll("[data-rm]").forEach(function (b) {
      b.addEventListener("click", function () {
        ABC_Cart.remove(+b.dataset.rm);
        renderCart();
      });
    });
  }

  document.getElementById("cart-btn") && document.getElementById("cart-btn").addEventListener("click", openCart);
  document.getElementById("cart-close") && document.getElementById("cart-close").addEventListener("click", closeCart);
  document.getElementById("cart-overlay") && document.getElementById("cart-overlay").addEventListener("click", closeCart);
  document.getElementById("mobile-toggle") && document.getElementById("mobile-toggle").addEventListener("click", function () {
    document.getElementById("mobile-nav").classList.add("open");
  });
  document.getElementById("mobile-close") && document.getElementById("mobile-close").addEventListener("click", function () {
    document.getElementById("mobile-nav").classList.remove("open");
  });
  var topBtn = document.getElementById("scroll-top");
  window.addEventListener("scroll", function () {
    var y = window.scrollY;
    document.querySelector(".site-header") && document.querySelector(".site-header").classList.toggle("scrolled", y > 20);
    topBtn && topBtn.classList.toggle("show", y > 400);
  }, { passive: true });
  topBtn && topBtn.addEventListener("click", function () { window.scrollTo({ top: 0, behavior: "smooth" }); });

  document.querySelectorAll("[data-add-cart]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      ABC_Cart.add({
        id: +btn.dataset.id,
        name: btn.dataset.name,
        price: +btn.dataset.price,
        image_url: btn.dataset.img || ""
      }, { quantity: 1 });
      btn.classList.add("loading");
      var old = btn.textContent; btn.textContent = "…";
      setTimeout(function(){ btn.textContent = old; btn.classList.remove("loading"); }, 400);
      toast((btn.dataset.name || "Item") + " added");
      openCart();
    });
  });

  if (window.ABC_Cart) ABC_Cart.renderCount();
  window.addEventListener("cart:updated", function () {
    if (window.ABC_Cart) ABC_Cart.renderCount();
  });
})();

  // Busy state helper for forms
  window.ABC_busy = function(btn, on) {
    if (!btn) return;
    if (on) {
      btn.dataset._label = btn.textContent;
      btn.disabled = true;
      btn.classList.add("loading");
      btn.textContent = "Sending…";
    } else {
      btn.disabled = false;
      btn.classList.remove("loading");
      if (btn.dataset._label) btn.textContent = btn.dataset._label;
    }
  };
