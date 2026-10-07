const products = [
  {
    id: "starlink-mini",
    title: "Starlink MINI — internet via satélite",
    hook: "Internet onde Wi‑Fi comum não chega. Compacta, portátil e o tipo de tecnologia que faz você parar o scroll.",
    category: "Tecnologia",
    image: "data:image/webp;base64,UklGRogEAABXRUJQVlA4IHwEAACwMwCdASrwAPAAPulys1OpJqSsI1FpiYAdCWlu3WBOqfZvx5uAQpub1V/urzeqv0Jph7dy9DGN+K9a5yrhTPKnzehh7z4o5KyVCOFNXK0zCoNjptDFgbavfKhxoYfYBWBJ/k7wAmdJEhaXACaYgIm9wVy1s1OJ9YnOh2NgT+esEBTQ/W2eNLsSNo23Tkh8eDInefJ1aWMXVoz/IRUCRcUsbZwMv5GpQFrNhBRBs6+F+zBgbS1fERWkQ24AqV+SNzWV7AYUwvfZg1NESkYi7Jg2RGXhnwG5ftdcqE3/Ox3os07BZPaamS78oeM7LQ+nfDaUCMlr4sJ8QC2jECStej87/VlXtu2x8zQ0aRQ0JsT+xopm77wRezrxwIlt0qkZ6eJZCxvhCwd/qUP+p/aygvE2gfpHpWT9IatP+MnxORHpjgj2u44gXHfe8eFfFTZjPWWXl22eIgz9tmv5aKaIm/kxMt6c++zSiYCEndmB0D808ORFPij/K/gHLLjut9mfl9ZERsBsmHEmARH3iirazndhAMBWhzmggJph7dzf+4ePLPN6q/3KAAD+8grO5YM8y0Doiw2nb3d9ncfnx3zPn53uq5s1Kees/WCRqsH6HWrYGZjhJbYIi8tuoNjK6Ja24YN3mqAJEu/8sMVopIiFLbP8MZprsFwO88jpqCuPts5HabjCDgh9mP/u97uXYex5UgWNZ7gUo4FWsc7IIMauTayJQqP3tAwF/NhkgjwzWf3ls1vpAF/UPORoLmqmx7XzPfN66M9JhGvKXgCSZkQYSwEFT7bbRpf//tfjBPwsVUGbiWDOrtIvSLYVOmKpVRvz6xNagbHjMN6lX0VByQiyhYNts2ZLhvlmGrarOJzcZy2UKziMK2IuuYFCp0WgWP24IY4zE4A5uSFua+vOZTxcEc1ovWPJoGWv/CdKqgHs33d/P1Y1m9vGKkEaxziLIYY3d6Q4su3Kux0ikGE3pUWb+NHMPuMEVecesEvYNgyn5xuDi30keQstdqX45wUdbP31wP0iJPD/kTm3ck6dVw7dggc0VD5xXm7e8gv5ToInK0yxO3YuEedAYpVwv/l9XlCs8T1/XsbPRhdltGbJ2hO7LkkY7HMtaCbjzTZvL3Dn2S6P3X6AGxtPajMn8iX23yinjspbB6FOWWk5skTDD2kofPUQqFmNW/aU9xT5XMJTegFRyERQQyUs0thOKPDBmE7kwK0txAmFjUxqB7Lw3jHa5bRrULGL6tCWpAdKGRcxXF7k80Mg8sqsQ+qTltGT1PYGbiHhE7ErOHpG4+00hCEHqYNNRedNr9xbMwmG766EfRkPOnQ/mcP7LXP+I87ucSv/cVQg2HJEcQAbBgs4M+MHvKoD+xyADv2+FR5z1VmE1TrWUH6FrZi3j2OHaeZqdZ+hmh0HLulFJcH3IT7G37iqycTN5PrO6reAcU825T5VoULJFeVJbxQIrt0+YX+NnI9NuiIkHwZwdmUnLQmd2SPJNi4KTEKHzuEHtwygNV+Hj3gAANxdQd/qD3Z+Q2AAAA==",
    price: 499.00,
    oldPrice: null,
    discount: null,
    installments: "9x de R$ 55,44 sem juros",
    badge: "🔥 MAIS VENDIDO",
    badge2: "achado premium",
    affiliateUrl: "https://meli.la/1E577fN",
    featured: true,
    reasons: [
      "Modelo MINI compacto para levar com mais facilidade",
      "Internet via satélite",
      "No print enviado: R$ 499 e parcelamento sem juros"
    ]
  },
  {
    id: "galaxy-a17",
    title: "Samsung Galaxy A17 256 GB • 8 GB RAM",
    hook: "256 GB, 8 GB de RAM, câmera de 50 MP, tela de 6,7” e NFC. Um celular completo sem chegar perto do preço de flagship.",
    category: "Celulares",
    image: "data:image/webp;base64,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",
    price: 1349.00,
    oldPrice: 1699.00,
    discount: 20,
    installments: "ou R$ 1.499 em 10x de R$ 149,90 sem juros",
    badge: "🔥 MAIS VENDIDO",
    badge2: "20% OFF no Pix",
    affiliateUrl: "https://meli.la/1an45Pr",
    reasons: [
      "256 GB de armazenamento e 8 GB de RAM",
      "Câmera principal de 50 MP",
      "NFC, IP54 e tela de 6,7”"
    ]
  },
  {
    id: "aspirador-britania",
    title: "Aspirador Britânia 1250 W • 1 L",
    hook: "Potência grande, corpo compacto e preço que chama atenção. Um daqueles achados úteis que você entende em dois segundos.",
    category: "Casa",
    image: "data:image/webp;base64,UklGRu4CAABXRUJQVlA4IOICAACwIACdASrwAPAAPul0tlSpJqskIfO4wWAdCWlu4XKRG/OX5i3AzPWFYOvSZa+77x/S/T21xPVJxHmdkHojHgseHK+qjgk2bpcV09g1ai6VFsCc3iMtNeyW6rotsRnUOzjjFWLhFSFHCNXZY5xZ7ozllsd9ZsEKjIyi8z3uPwvDIs3bH/lxIBhLH28W/hi5oJBJs3TLAj8G1da2UolyAzr9TeIy032xO6JM+Rvq7jxvTX5Ag8WCo08xZxQsCc3iMtOFPZEf4xkIdhX9bTKwrMWgTKnISiXpATD2jHwxDAErhzj4fJxU3iMoN91tqQIP0FV/HBzA459auoyEvim9WjH2uTLWxz7EXM9I4fArB4AA/v3YtyiUycirGfYWyWDAHvb/PyjoGEeZOXjdAWMcjNGCW5NbzXMBQbUnSxMNTsm+ruqJLOEsi50cLzazxsGvoMaJw3YKbgfIvDDV2qIO9HAV5iZva/W+46BDMd947LLUETBi7pOr3OfEpBRWT0re8uO/khcNmyhScT6VAXSJ2lUYJ1ZGTlwZ/RspBhvKTP+Xz47WEQ1NRi7+eyEE1qyDmq/5ac/JptcIQXLpw5AtekdBq8vZeSNaHKuWauC1SurD9ZzV4Y44g8fhBk7lvEpp9hWOnZWOv0DLuEkHYL6fOq1ewy+v8Gq3j7OQTTyyg9cE4XZXvOBcbkSd+W1Gyg8Bnd95Vb3+/OmvZTf8QRIEJUsr9JGPao1VBZfTJrAhiZQsiI9WG1US5XkYUduKzYsV5vLgfiT+Unkj5gfT8+1fURSO1ypdBpP0/v9xFLKQ1j6+fKBreurHfnyXgQljzIKElrgjhImx93GveXQTL9ICp1CzKd3y3FeUhVVrZ3lRYgK0G7D7K8hbM/qwnFwwW8Ki7ABwo8KJM9ya1NztsOddD1q7UKnMpJ+jMvVwJRFQYye9yUuc7o2vj93d8tnrrPZSa062hkdjHvu8Qq+kNe7ICkAAAAA=",
    price: 131.95,
    oldPrice: 234.29,
    discount: 43,
    installments: "ou R$ 138,90 em outros meios",
    badge: "🔥 MAIS VENDIDO",
    badge2: "43% OFF no Pix",
    affiliateUrl: "https://meli.la/1XKszGT",
    reasons: [
      "1250 W de potência",
      "Reservatório de 1 litro",
      "No print enviado: 43% OFF no Pix"
    ]
  },
  {
    id: "lavadora-portatil",
    title: "Lavadora portátil de pressão • 2 baterias + maleta",
    hook: "Sem ficar preso na tomada ou na mangueira. Duas baterias, maleta e acessórios — parece ferramenta de vídeo viral porque é.",
    category: "Ferramentas",
    image: "data:image/webp;base64,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",
    price: 102.26,
    oldPrice: 229.90,
    discount: 55,
    installments: "ou R$ 107,64 em outros meios",
    badge: "⚡ ACHADO FORTE",
    badge2: "55% OFF no Pix",
    affiliateUrl: "https://meli.la/24NQDPY",
    reasons: [
      "Kit portátil com 2 baterias",
      "Acompanha maleta e acessórios",
      "No print enviado: 55% OFF no Pix"
    ]
  },
  {
    id: "kit-principia",
    title: "Kit Principia para pele sensível • FPS 60",
    hook: "Rotina pronta em um kit: limpeza, cuidado e proteção solar. Menos dúvida na prateleira, mais praticidade no dia a dia.",
    category: "Beleza",
    image: "data:image/webp;base64,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",
    price: 96.31,
    oldPrice: 137.00,
    discount: 29,
    installments: "ou R$ 101,38 em outros meios",
    badge: "✦ ROTINA PRONTA",
    badge2: "29% OFF no Pix",
    affiliateUrl: "https://meli.la/2e666fK",
    reasons: [
      "Kit pensado para rotina de pele sensível",
      "Inclui protetor solar FPS 60",
      "No print enviado: 29% OFF no Pix"
    ]
  }
];

let activeCategory = 'Todos';
let query = '';
let favorites = new Set(JSON.parse(localStorage.getItem('bq:favorites') || '[]'));

const $ = s => document.querySelector(s);
const productGrid = $('#productGrid');
const categoryChips = $('#categoryChips');
const searchInput = $('#searchInput');
const productModal = $('#productModal');
const modalContent = $('#modalContent');
const toast = $('#toast');

function money(v) {
  return new Intl.NumberFormat('pt-BR', {style:'currency', currency:'BRL'}).format(v);
}
function categories() {
  return ['Todos', ...new Set(products.map(p => p.category))];
}
function renderCategories() {
  categoryChips.innerHTML = categories().map(c => `<button class="chip ${c===activeCategory?'active':''}" data-category="${c}">${c}</button>`).join('');
}
function priceBlock(p) {
  return `
    <div class="price-stack">
      ${p.oldPrice ? `<span class="old-price">${money(p.oldPrice)}</span>` : ''}
      <div class="now-price">${money(p.price)} ${p.discount ? `<em>${p.discount}% OFF</em>` : ''}</div>
      <small>${p.installments}</small>
    </div>`;
}
function productCard(p) {
  return `
    <article class="product-card" data-id="${p.id}">
      <div class="card-visual real-photo" data-open="${p.id}">
        <img src="${p.image}" alt="${p.title}" loading="lazy">
        <div class="badges">
          <span class="badge">${p.badge}</span>
          <span class="badge acid">${p.badge2}</span>
        </div>
      </div>
      <div class="card-body">
        <span class="card-category">${p.category}</span>
        <h3 class="card-title">${p.title}</h3>
        <p class="card-hook">${p.hook}</p>
        ${priceBlock(p)}
        <div class="card-footer">
          <button class="btn btn-primary" data-buy="${p.id}">Ver no Mercado Livre →</button>
          <button class="btn btn-ghost save-btn ${favorites.has(p.id)?'saved':''}" data-save="${p.id}" aria-label="Salvar produto">${favorites.has(p.id)?'♥':'♡'}</button>
        </div>
      </div>
    </article>`;
}
function renderProducts() {
  const q = query.trim().toLowerCase();
  const filtered = products.filter(p => {
    const cat = activeCategory === 'Todos' || p.category === activeCategory;
    const search = !q || `${p.title} ${p.hook} ${p.category}`.toLowerCase().includes(q);
    return cat && search;
  });
  productGrid.innerHTML = filtered.map(productCard).join('');
  $('#resultCount').textContent = filtered.length;
  $('#emptyState').hidden = filtered.length !== 0;
  bindDynamicEvents();
}
function renderFeatured() {
  const p = products.find(x => x.featured) || products[0];
  $('#featuredProduct').innerHTML = `
    <article class="featured-card featured-real">
      <div class="featured-visual real-photo" data-open="${p.id}">
        <span class="visual-tag">🔥 ESCOLHA DO DIA</span>
        <img src="${p.image}" alt="${p.title}">
      </div>
      <div class="featured-info">
        <span class="section-kicker">${p.category.toUpperCase()}</span>
        <h3>${p.title}</h3>
        <p class="product-hook">${p.hook}</p>
        ${priceBlock(p)}
        <div class="product-actions">
          <button class="btn btn-primary" data-buy="${p.id}">Quero ver essa oferta <span>→</span></button>
          <button class="btn btn-ghost save-btn ${favorites.has(p.id)?'saved':''}" data-save="${p.id}">${favorites.has(p.id)?'♥':'♡'}</button>
        </div>
        <p class="price-note">Preço visto na seleção enviada pelo proprietário. Confira preço, frete e disponibilidade atuais no Mercado Livre.</p>
      </div>
    </article>`;
  bindDynamicEvents();
}
function bindDynamicEvents() {
  document.querySelectorAll('[data-open]').forEach(el => el.onclick = () => openProduct(el.dataset.open));
  document.querySelectorAll('[data-buy]').forEach(el => el.onclick = () => goToOffer(el.dataset.buy));
  document.querySelectorAll('[data-save]').forEach(el => el.onclick = () => toggleFavorite(el.dataset.save));
}
function openProduct(id) {
  const p = products.find(x => x.id === id);
  if (!p) return;
  modalContent.innerHTML = `
    <div class="modal-grid">
      <div class="modal-visual real-photo"><img src="${p.image}" alt="${p.title}"></div>
      <div class="modal-info">
        <span class="section-kicker">${p.category.toUpperCase()}</span>
        <h3>${p.title}</h3>
        <p class="product-hook">${p.hook}</p>
        <ul class="reason-list">${p.reasons.map(r=>`<li>${r}</li>`).join('')}</ul>
        ${priceBlock(p)}
        <p class="price-note">Valores podem mudar. Confira as condições atuais no anúncio.</p>
        <div class="product-actions">
          <button class="btn btn-primary" data-buy="${p.id}">Conferir agora →</button>
          <button class="btn btn-ghost save-btn ${favorites.has(p.id)?'saved':''}" data-save="${p.id}">${favorites.has(p.id)?'♥':'♡'}</button>
        </div>
      </div>
    </div>`;
  productModal.showModal();
  bindDynamicEvents();
}
function goToOffer(id) {
  const p = products.find(x => x.id === id);
  if (!p?.affiliateUrl) return;
  window.open(p.affiliateUrl, '_blank', 'noopener,noreferrer');
}
function toggleFavorite(id) {
  favorites.has(id) ? favorites.delete(id) : favorites.add(id);
  localStorage.setItem('bq:favorites', JSON.stringify([...favorites]));
  updateFavCount();
  renderProducts();
  renderFeatured();
  if (productModal.open) openProduct(id);
  showToast(favorites.has(id) ? 'Salvo nos seus favoritos ♥' : 'Removido dos favoritos');
}
function updateFavCount() { $('#favCount').textContent = favorites.size; }
function showToast(message) {
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove('show'), 2400);
}
function setCategory(cat) {
  activeCategory = cat;
  renderCategories();
  renderProducts();
  $('#achados').scrollIntoView({behavior:'smooth', block:'start'});
}
categoryChips.addEventListener('click', e => {
  const btn = e.target.closest('[data-category]');
  if (btn) setCategory(btn.dataset.category);
});
searchInput.addEventListener('input', e => { query = e.target.value; renderProducts(); });
document.addEventListener('keydown', e => {
  if (e.key === '/' && document.activeElement !== searchInput) { e.preventDefault(); searchInput.focus(); }
  if (e.key === 'Escape' && productModal.open) productModal.close();
});
$('#surpriseBtn').onclick = () => {
  const p = products[Math.floor(Math.random()*products.length)];
  openProduct(p.id);
};
$('#modalClose').onclick = () => productModal.close();

function showFavorites() {
  const favs = products.filter(p => favorites.has(p.id));
  activeCategory = 'Todos'; query = ''; searchInput.value = '';
  renderCategories();
  productGrid.innerHTML = favs.map(productCard).join('');
  $('#resultCount').textContent = favs.length;
  $('#emptyState').hidden = favs.length !== 0;
  if (!favs.length) {
    $('#emptyState').querySelector('h3').textContent = 'Você ainda não salvou nada.';
    $('#emptyState').querySelector('p').textContent = 'Quando bater vontade, toca no coração.';
  }
  bindDynamicEvents();
  $('#achados').scrollIntoView({behavior:'smooth'});
}
$('#favTop').onclick = showFavorites;
$('#favMobile').onclick = showFavorites;
$('#mobileSearchBtn').onclick = () => {
  $('#top').scrollIntoView({behavior:'smooth'});
  setTimeout(() => searchInput.focus(), 450);
};
document.querySelectorAll('[data-filter]').forEach(el => el.onclick = () => setCategory(el.dataset.filter));

renderCategories();
renderFeatured();
renderProducts();
updateFavCount();