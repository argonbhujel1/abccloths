/**
 * API client with short timeouts and graceful fallback handling.
 */
const API = {
  timeout: 6000,

  async fetch(path, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);
    try {
      const res = await fetch(path, {
        ...options,
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          ...(options.headers || {}),
        },
      });
      clearTimeout(timer);
      const data = await res.json().catch(() => ({}));
      return { ok: res.ok, status: res.status, data };
    } catch (err) {
      clearTimeout(timer);
      return { ok: false, status: 0, data: { error: err.name === "AbortError" ? "timeout" : "network" } };
    }
  },

  async getProducts() {
    const r = await this.fetch("/api/products");
    if (r.ok && r.data.products && r.data.products.length) {
      return { products: r.data.products.filter(p => p.active !== false), source: r.data.source || "live" };
    }
    return { products: (window.ABC_FALLBACK?.products || []).filter(p => p.active), source: "fallback" };
  },

  async getNotice() {
    const r = await this.fetch("/api/notice");
    if (r.ok && r.data.notice) {
      return { notice: r.data.notice, source: r.data.source || "live" };
    }
    return { notice: window.ABC_FALLBACK?.notice || null, source: "fallback" };
  },

  async getSettings() {
    const r = await this.fetch("/api/settings");
    if (r.ok) {
      return {
        logo_url: r.data.logo_url || "",
        favicon_url: r.data.favicon_url || "",
        brand_name: r.data.brand_name || "ABC Clothing",
        facebook_url: r.data.facebook_url || "",
        instagram_url: r.data.instagram_url || "",
        whatsapp: r.data.whatsapp || "",
        source: r.data.source || "live",
      };
    }
    return {
      logo_url: "",
      favicon_url: "",
      brand_name: "ABC Clothing",
      facebook_url: "",
      instagram_url: "",
      whatsapp: "",
      source: "fallback",
    };
  },

  async submitOrder(payload) {
    return this.fetch("/api/order", { method: "POST", body: JSON.stringify(payload) });
  },

  async submitContact(payload) {
    return this.fetch("/api/contact", { method: "POST", body: JSON.stringify(payload) });
  },
};

window.ABC_API = API;
