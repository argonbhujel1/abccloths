/**
 * Cart persistence via localStorage.
 */
const CART_KEY = "abc_clothing_cart_v1";

const Cart = {
  items: [],

  load() {
    try {
      const raw = localStorage.getItem(CART_KEY);
      this.items = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(this.items)) this.items = [];
    } catch {
      this.items = [];
    }
    this.renderCount();
    return this.items;
  },

  save() {
    localStorage.setItem(CART_KEY, JSON.stringify(this.items));
    this.renderCount();
    window.dispatchEvent(new CustomEvent("cart:updated"));
  },

  add(product, { size = "", color = "", quantity = 1 } = {}) {
    const qty = Math.max(1, Math.min(20, Number(quantity) || 1));
    const existing = this.items.find(
      (i) => i.id === product.id && i.size === size && i.color === color
    );
    if (existing) {
      existing.quantity = Math.min(20, existing.quantity + qty);
    } else {
      this.items.push({
        id: product.id,
        name: product.name,
        price: product.price,
        image_url: product.image_url || "",
        size,
        color,
        quantity: qty,
      });
    }
    this.save();
    return this.items;
  },

  updateQty(index, quantity) {
    if (index < 0 || index >= this.items.length) return;
    const qty = Math.max(0, Math.min(20, Number(quantity) || 0));
    if (qty === 0) {
      this.items.splice(index, 1);
    } else {
      this.items[index].quantity = qty;
    }
    this.save();
  },

  remove(index) {
    if (index < 0 || index >= this.items.length) return;
    this.items.splice(index, 1);
    this.save();
  },

  clear() {
    this.items = [];
    this.save();
  },

  count() {
    return this.items.reduce((s, i) => s + i.quantity, 0);
  },

  subtotal() {
    return this.items.reduce((s, i) => s + i.price * i.quantity, 0);
  },

  renderCount() {
    document.querySelectorAll(".cart-count").forEach((el) => {
      const n = this.count();
      el.textContent = n;
      el.style.display = n > 0 ? "flex" : "none";
    });
  },
};

window.ABC_Cart = Cart;
Cart.load();
