document.addEventListener('DOMContentLoaded', () => {
  // 1. Esconder mensagens Flash automaticamente
  document.querySelectorAll('.flash').forEach((element) => {
    window.setTimeout(() => {
      element.style.opacity = '0';
      element.style.transform = 'translateY(-8px)';
      window.setTimeout(() => element.remove(), 180);
    }, 4200);
  });

  // 2. Botões de Quantidade (+ e -) no Cardápio e no Carrinho
  document.querySelectorAll('.quantity-control').forEach((control) => {
    const input = control.querySelector('input');
    if (!input) return;

    control.querySelector('.qty-minus')?.addEventListener('click', () => {
      input.value = Math.max(1, Number(input.value || 1) - 1);
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });

    control.querySelector('.qty-plus')?.addEventListener('click', () => {
      input.value = Math.min(99, Number(input.value || 1) + 1);
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
  });

  // 3. Formatador e Atualizador do Carrinho
  const currency = (value) =>
    new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value);

  const updateCartTotal = () => {
    let subtotal = 0;

    // Sumariza apenas as linhas válidas do carrinho
    document.querySelectorAll('.cart-row[data-unit-price]').forEach((row) => {
      const unit = Number(row.dataset.unitPrice || 0);
      const quantity = Number(row.querySelector('input')?.value || 0);
      subtotal += unit * quantity;
    });

    const subtotalNode = document.querySelector('[data-cart-subtotal]');
    const totalNode = document.querySelector('[data-cart-total]');
    
    // Busca elemento com [data-delivery] se existir, senão assume taxa 0
    const deliveryNode = document.querySelector('[data-delivery]');
    const delivery = deliveryNode ? Number(deliveryNode.dataset.delivery || 0) : 0;

    if (subtotalNode) subtotalNode.textContent = currency(subtotal);
    if (totalNode) totalNode.textContent = currency(subtotal + delivery);
  };

  // Recalcular quando digita ou altera o número no input do carrinho
  document.querySelectorAll('.cart-row input').forEach((input) => {
    input.addEventListener('input', updateCartTotal);
    input.addEventListener('change', updateCartTotal);
  });

  // Roda o cálculo inicial ao carregar a página
  updateCartTotal();

  // 4. Confirmação nos botões do Painel Administrativo
  document.querySelectorAll('form[action*="/admin/pedido/"]').forEach((form) => {
    form.addEventListener('submit', (event) => {
      const button = form.querySelector('button');
      if (button && !window.confirm(`${button.textContent.trim()} este pedido?`)) {
        event.preventDefault();
      }
    });
  });
});