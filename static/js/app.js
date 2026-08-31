document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.flash').forEach((element) => {
    window.setTimeout(() => {
      element.style.opacity = '0';
      element.style.transform = 'translateY(-8px)';
      window.setTimeout(() => element.remove(), 180);
    }, 4200);
  });

  const currency = (value) =>
    new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value);
  const cart = document.querySelector('[data-cart-open]');
  const panel = document.querySelector('#carrinho');
  const backdrop = document.querySelector('.cart-backdrop');
  let totalFrame;

  const cartRows = () => document.querySelectorAll('.cart-row[data-unit-price]');

  const updateCartTotal = () => {
    let subtotal = 0;
    let itemCount = 0;
    cartRows().forEach((row) => {
      const input = row.querySelector('input');
      const quantity = Math.max(0, Math.min(99, Number(input?.value || 0)));
      subtotal += Number(row.dataset.unitPrice || 0) * quantity;
      itemCount += quantity;
    });
    const subtotalNode = document.querySelector('[data-cart-subtotal]');
    const totalNode = document.querySelector('[data-cart-total]');
    if (subtotalNode) subtotalNode.textContent = currency(subtotal);
    if (totalNode) totalNode.textContent = currency(subtotal);
    document.querySelectorAll('[data-cart-count]').forEach((node) => { node.textContent = itemCount; });
    document.querySelectorAll('.cart-title-count').forEach((node) => { node.textContent = `(${itemCount})`; });
  };

  const scheduleTotal = () => {
    window.cancelAnimationFrame(totalFrame);
    totalFrame = window.requestAnimationFrame(updateCartTotal);
  };

  const setCartOpen = (open) => {
    if (!panel) return;
    panel.classList.toggle('is-open', open);
    panel.setAttribute('aria-hidden', String(!open));
    backdrop?.classList.toggle('is-visible', open);
    document.body.classList.toggle('cart-open', open);
    cart?.setAttribute('aria-expanded', String(open));
    if (open) panel.querySelector('.cart-close')?.focus({ preventScroll: true });
  };

  cart?.addEventListener('click', () => setCartOpen(true));
  document.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (target.closest('[data-cart-close]')) setCartOpen(false);

    const quantityButton = target.closest('.qty-minus, .qty-plus, .cart-qty-minus, .cart-qty-plus');
    if (quantityButton) {
      const control = quantityButton.closest('.quantity-control, .cart-qty-control');
      const input = control?.querySelector('input');
      if (!input) return;
      const current = Number(input.value || 1);
      const minimum = input.closest('.cart-qty-control') ? 0 : 1;
      input.value = String(Math.max(minimum, Math.min(99, current + (quantityButton.classList.contains('qty-minus') || quantityButton.classList.contains('cart-qty-minus') ? -1 : 1))));
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }

    const removeButton = target.closest('[data-remove-cart-item]');
    if (removeButton) {
      const row = removeButton.closest('[data-product-row]');
      const input = row?.querySelector('input');
      if (row && input) {
        input.value = '0';
        row.classList.add('is-removing');
        row.setAttribute('aria-hidden', 'true');
        row.style.display = 'none';
        scheduleTotal();
      }
    }
  });

  backdrop?.addEventListener('click', () => setCartOpen(false));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && panel?.classList.contains('is-open')) setCartOpen(false);
  });
  document.addEventListener('input', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    if (!target.closest('.cart-row')) return;
    target.value = String(Math.max(0, Math.min(99, Number(target.value || 0))));
    scheduleTotal();
  });

  updateCartTotal();

  document.querySelectorAll('form[action*="/admin/pedido/"]').forEach((form) => {
    form.addEventListener('submit', (event) => {
      const button = form.querySelector('button');
      if (button && !window.confirm(`${button.textContent.trim()} este pedido?`)) {
        event.preventDefault();
      }
    });
  });
});
