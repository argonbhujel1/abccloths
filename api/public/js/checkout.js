(function () {
  if (!window.ABC_Cart) return;
  var items = ABC_Cart.items;
  var summary = document.getElementById("order-summary-items");
  var totalEl = document.getElementById("order-total");
  var root = document.getElementById("checkout-root");
  if (!items.length) {
    if (root) root.innerHTML = '<div class="success-burst"><div class="burst-icon">✓</div><h1 style="font-family:var(--font-display);margin:0 0 .5rem">Order sent</h1><p>Ref: <strong>' + (data.order_ref || "") + '</strong></p><p style="color:var(--color-muted)">' + (data.message || "We received your request.") + '</p><a href="/" class="btn btn-primary" style="margin-top:1rem">Home</a></div>';
      } else {
        if (window.ABC_toast) ABC_toast(data.error || "Failed", true);
        btn.disabled = false;
        btn.textContent = "Place order request";
      }
    } catch (err) {
      if (window.ABC_toast) ABC_toast("Network error", true);
      btn.disabled = false;
      btn.textContent = "Place order request";
    }
  });
})();
