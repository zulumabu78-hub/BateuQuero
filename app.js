let activeCategory = "Todos";
let query = "";
let sortMode = "featured";
let priceMode = "all";
let quickMode = "all";
let favoritesOnly = false;
let favorites = new Set(JSON.parse(localStorage.getItem("bq:favorites") || "[]"));

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const grid = $("#productGrid");
const chips = $("#categoryChips");
const search = $("#searchInput");
const sortSelect = $("#sortSelect");
const priceSelect = $("#priceSelect");
const modal = $("#productModal");
const modalContent = $("#modalContent");
const toast = $("#toast");

const money = (value) => new Intl.NumberFormat("pt-BR", {style:"currency",currency:"BRL"}).format(value);
const styleVars = (p) => `--a:${p.theme[0]};--b:${p.theme[1]}`;
const normalize = (s="") => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
const beautyCategories = new Set(["Skincare","Cabelo","Corpo","Maquiagem","Perfume","Acessórios","Beleza","Moda"]);
const photoIds = new Set(["tapete-felpudo-cinza","tshirts-oversized-clea","bike-spinning","bola-fifa-2026"]);
const imageMode = (p) => photoIds.has(p.id) ? "photo" : "isolated";

function categories(){
  return ["Todos", ...new Set(products.map(p => p.category))];
}

function isNew(p){ return p.seenAt === "08/10/2026"; }
function productShareUrl(p){ return `${location.origin}${location.pathname}?produto=${encodeURIComponent(p.id)}`; }

function renderHeroPreview(){
  const featured = products.find(p => p.featured) || products[0];
  const extras = products
    .filter(p => p.id !== featured.id && beautyCategories.has(p.category))
    .sort((a,b)=>(b.discount||0)-(a.discount||0))
    .slice(0,2);
  const stack = [featured, ...extras];
  $("#heroProductPreview").innerHTML = stack.map((p,i) => `
    <figure class="hero-preview-item preview-${i+1} ${imageMode(p)}" style="${styleVars(p)}">
      <img src="${p.image}" alt="${p.title}" ${i===0?'fetchpriority="high"':'loading="lazy"'} decoding="async">
      <figcaption>${i===0?"destaque":"radar"}</figcaption>
    </figure>`).join("");
}

function priceHTML(p){
  return `
    <div class="price-stack">
      ${p.oldPrice ? `<span class="old-price">${money(p.oldPrice)}</span>` : ""}
      <div class="price-row">
        <strong>${money(p.price)}</strong>
        ${p.discount ? `<span class="discount-pill">${p.discount}% OFF</span>` : ""}
      </div>
      <span class="installments">${p.installments}</span>
    </div>`;
}

function freshnessStamp(p){
  return `<span class="price-stamp">Preço visto em ${p.seenAt || "06/10/2026"}</span>`;
}

function renderFeatured(){
  const p = products.find(x => x.featured) || products[0];
  $("#featuredProduct").innerHTML = `
    <article class="featured-card" style="${styleVars(p)}">
      <div class="featured-media">
        <span class="visual-code">BQ / DESTAQUE • ${p.category.toUpperCase()}</span>
        <span class="visual-chip">${p.badge2}</span>
        <div class="featured-shot ${imageMode(p)}"><img src="${p.image}" alt="${p.title}" fetchpriority="high" decoding="async"></div>
        <div class="featured-deco">${p.icon}</div>
      </div>
      <div class="featured-info">
        <div class="featured-meta"><span class="section-kicker">${p.badge}</span>${isNew(p)?'<span class="new-pill">NOVO</span>':''}</div>
        <h3>${p.title}</h3>
        <p class="hook">${p.hook}</p>
        ${priceHTML(p)}
        <div class="product-actions">
          <a class="btn btn-primary" href="${p.link}" target="_blank" rel="sponsored noopener noreferrer" data-outbound="${p.id}">Conferir no Mercado Livre <span>→</span></a>
          <button class="btn btn-secondary icon-save ${favorites.has(p.id)?"saved":""}" data-save="${p.id}" aria-label="Salvar">${favorites.has(p.id)?"♥":"♡"}</button>
          <button class="btn btn-secondary icon-share" data-share="${p.id}" aria-label="Compartilhar">↗</button>
        </div>
        <p class="price-note">${freshnessStamp(p)} Confira preço, frete, vendedor e disponibilidade atuais no anúncio.</p>
      </div>
    </article>`;
  bindActions();
}

function cardHTML(p, index){
  return `
    <article class="product-card ${isNew(p)?"is-new":""}" style="${styleVars(p)}" data-product="${p.id}">
      <div class="product-stage" data-open="${p.id}">
        <div class="stage-top">
          <span class="tag">${p.badge}</span>
          <span class="tag acid">${p.badge2}</span>
        </div>
        ${isNew(p)?'<span class="new-corner">NOVO</span>':''}
        <div class="product-shot ${imageMode(p)}"><img src="${p.image}" alt="${p.title}" loading="lazy" decoding="async"></div>
        <span class="stage-label">BQ / ${String(index + 1).padStart(2,"0")} • CURADORIA</span>
        <span class="stage-symbol">${p.icon}</span>
      </div>
      <div class="product-body">
        <span class="product-category">${p.category}</span>
        <h3 class="product-title">${p.title}</h3>
        <p class="product-short">${p.short}</p>
        ${priceHTML(p)}
        <div class="card-meta-row">${freshnessStamp(p)}</div>
        <div class="card-actions">
          <a class="btn btn-primary" href="${p.link}" target="_blank" rel="sponsored noopener noreferrer" data-outbound="${p.id}">Ver oferta →</a>
          <button class="btn btn-secondary icon-save ${favorites.has(p.id)?"saved":""}" data-save="${p.id}" aria-label="Salvar">${favorites.has(p.id)?"♥":"♡"}</button>
          <button class="btn btn-secondary icon-share" data-share="${p.id}" aria-label="Compartilhar">↗</button>
        </div>
      </div>
    </article>`;
}

function matchesQuick(p){
  if(quickMode === "new") return isNew(p);
  if(quickMode === "under50") return p.price <= 50;
  if(quickMode === "deal50") return (p.discount||0) >= 50;
  if(quickMode === "premium") return p.price >= 250;
  if(quickMode === "beauty") return beautyCategories.has(p.category);
  return true;
}

function matchesPrice(p){
  if(priceMode === "50") return p.price <= 50;
  if(priceMode === "100") return p.price <= 100;
  if(priceMode === "200") return p.price <= 200;
  if(priceMode === "200plus") return p.price > 200;
  return true;
}

function filteredProducts(){
  const q = normalize(query.trim());
  let result = products.filter(p => {
    const categoryOk = activeCategory === "Todos" || p.category === activeCategory;
    const haystack = normalize([p.title,p.short,p.hook,p.category,...(p.reasons||[])].join(" "));
    const searchOk = !q || haystack.includes(q);
    const favOk = !favoritesOnly || favorites.has(p.id);
    return categoryOk && searchOk && matchesQuick(p) && matchesPrice(p) && favOk;
  });
  if(sortMode === "discount") result.sort((a,b)=>(b.discount||0)-(a.discount||0));
  if(sortMode === "low") result.sort((a,b)=>a.price-b.price);
  if(sortMode === "high") result.sort((a,b)=>b.price-a.price);
  if(sortMode === "new") result.sort((a,b)=>(b.seenAt||"").localeCompare(a.seenAt||""));
  if(sortMode === "featured") result.sort((a,b)=>Number(!!b.featured)-Number(!!a.featured) || (b.discount||0)-(a.discount||0));
  return result;
}

function renderProducts(list=filteredProducts()){
  grid.innerHTML = list.map(cardHTML).join("");
  $("#resultCount").textContent = list.length;
  $("#resultLabel").textContent = favoritesOnly ? "favoritos encontrados" : "achados encontrados";
  $("#emptyState").hidden = list.length > 0;
  bindActions();
}

function renderChips(){
  chips.innerHTML = categories().map(c => `<button class="chip ${c===activeCategory?"active":""}" data-category="${c}">${c}</button>`).join("");
}

function renderQuickFilters(){
  const items = [
    ["all","Tudo"],["new","Novidades"],["beauty","Para elas"],["under50","Até R$ 50"],["deal50","50%+ OFF"],["premium","Premium"]
  ];
  $("#quickFilters").innerHTML = items.map(([key,label]) => `<button class="quick-chip ${quickMode===key?"active":""}" data-quick="${key}">${label}</button>`).join("");
}

function renderBeautyRail(){
  const list = products.filter(p => beautyCategories.has(p.category)).sort((a,b)=>Number(isNew(b))-Number(isNew(a)) || (b.discount||0)-(a.discount||0)).slice(0,10);
  $("#beautyRail").innerHTML = list.map(p => `
    <button class="beauty-mini" data-open="${p.id}" style="${styleVars(p)}">
      <span class="beauty-mini-media ${imageMode(p)}"><img src="${p.image}" alt="" loading="lazy" decoding="async"></span>
      <span class="beauty-mini-copy"><small>${p.category}</small><strong>${p.title}</strong><b>${money(p.price)}</b></span>
    </button>`).join("");
  bindActions();
}

function renderCategoryCards(){
  const data = categories().filter(c => c !== "Todos").map(c => {
    const list = products.filter(p => p.category === c);
    return {name:c,count:list.length,glow:list[0].theme[0]};
  });
  $("#categoryCards").innerHTML = data.map(c => `
    <article class="category-card" data-jump-category="${c.name}" style="--glow:${c.glow}">
      <span>${c.count} ${c.count === 1 ? "achado" : "achados"}</span>
      <h3>${c.name}</h3>
      <b>abrir categoria →</b>
    </article>`).join("");
  $$('[data-jump-category]').forEach(el => {
    el.onclick = () => {
      favoritesOnly = false; quickMode = "all"; activeCategory = el.dataset.jumpCategory;
      renderChips(); renderQuickFilters(); renderProducts();
      $("#achados").scrollIntoView({behavior:"smooth"});
    };
  });
}

function relatedHTML(p){
  const related = products.filter(x => x.id !== p.id && (x.category === p.category || (beautyCategories.has(x.category) && beautyCategories.has(p.category))))
    .sort((a,b)=>(b.discount||0)-(a.discount||0)).slice(0,3);
  if(!related.length) return "";
  return `<div class="related-block"><span class="section-kicker">VOCÊ TAMBÉM PODE GOSTAR</span><div class="related-grid">${related.map(r => `
    <button class="related-item" data-open="${r.id}" style="${styleVars(r)}">
      <span class="related-media ${imageMode(r)}"><img src="${r.image}" alt="" loading="lazy"></span>
      <span><small>${r.category}</small><strong>${r.title}</strong><b>${money(r.price)}</b></span>
    </button>`).join("")}</div></div>`;
}

function openProduct(id){
  const p = products.find(x => x.id === id);
  if(!p) return;
  history.replaceState(null,"",`${location.pathname}?produto=${encodeURIComponent(p.id)}`);
  modalContent.innerHTML = `
    <div class="modal-grid" style="${styleVars(p)}">
      <div class="modal-media">
        <div class="modal-shot ${imageMode(p)}"><img src="${p.image}" alt="${p.title}" decoding="async"></div>
      </div>
      <div class="modal-info">
        <div class="featured-meta"><span class="section-kicker">${p.category} • ${p.badge}</span>${isNew(p)?'<span class="new-pill">NOVO</span>':''}</div>
        <h3>${p.title}</h3>
        <p class="hook">${p.hook}</p>
        <ul class="reason-list">${(p.reasons||[]).map(r => `<li>${r}</li>`).join("")}</ul>
        ${priceHTML(p)}
        <div class="product-actions modal-actions">
          <a class="btn btn-primary" href="${p.link}" target="_blank" rel="sponsored noopener noreferrer" data-outbound="${p.id}">Ver no Mercado Livre →</a>
          <button class="btn btn-secondary icon-save ${favorites.has(p.id)?"saved":""}" data-save="${p.id}">${favorites.has(p.id)?"♥":"♡"}</button>
          <button class="btn btn-secondary icon-share" data-share="${p.id}">↗</button>
        </div>
        <p class="price-note">${freshnessStamp(p)} Preço, frete e disponibilidade podem mudar.</p>
        ${relatedHTML(p)}
      </div>
    </div>`;
  modal.showModal();
  bindActions();
}

function closeModal(){
  if(modal.open) modal.close();
  history.replaceState(null,"",location.pathname);
}

function toggleFavorite(id){
  if(favorites.has(id)) favorites.delete(id); else favorites.add(id);
  localStorage.setItem("bq:favorites", JSON.stringify([...favorites]));
  updateFavCount();
  renderFeatured(); renderProducts(); renderBeautyRail();
  showToast(favorites.has(id) ? "Salvo nos seus favoritos ♥" : "Removido dos favoritos");
}

function updateFavCount(){ $("#favCount").textContent = favorites.size; }

function showFavorites(){
  favoritesOnly = true; activeCategory = "Todos"; quickMode = "all"; priceMode = "all"; query = "";
  search.value = ""; priceSelect.value = "all";
  renderChips(); renderQuickFilters(); renderProducts();
  if(!favorites.size){
    $("#emptyState").hidden = false;
    $("#emptyState h3").textContent = "Você ainda não salvou nada.";
    $("#emptyState p").textContent = "Quando bater vontade, toca no coração.";
  }
  $("#achados").scrollIntoView({behavior:"smooth"});
}

function resetFilters(){
  activeCategory="Todos"; query=""; sortMode="featured"; priceMode="all"; quickMode="all"; favoritesOnly=false;
  search.value=""; sortSelect.value="featured"; priceSelect.value="all";
  renderChips(); renderQuickFilters(); renderProducts();
}

async function shareProduct(id){
  const p = products.find(x=>x.id===id); if(!p) return;
  const url = productShareUrl(p);
  const data = {title:`BateuQuero • ${p.title}`, text:`Olha esse achado no BateuQuero: ${p.title}`, url};
  try{
    if(navigator.share) await navigator.share(data);
    else { await navigator.clipboard.writeText(url); showToast("Link do produto copiado ↗"); }
  }catch(err){ if(err?.name !== "AbortError") showToast("Não consegui compartilhar agora."); }
}

function showToast(message){
  toast.textContent = message; toast.classList.add("show");
  clearTimeout(showToast.timer); showToast.timer=setTimeout(()=>toast.classList.remove("show"),2200);
}

function trackOutbound(id){
  const key="bq:clicks"; const clicks=JSON.parse(localStorage.getItem(key)||"{}");
  clicks[id]=(clicks[id]||0)+1; localStorage.setItem(key,JSON.stringify(clicks));
}

function bindActions(){
  $$('[data-open]').forEach(el => el.onclick = () => openProduct(el.dataset.open));
  $$('[data-save]').forEach(el => el.onclick = e => {e.preventDefault();e.stopPropagation();toggleFavorite(el.dataset.save);});
  $$('[data-share]').forEach(el => el.onclick = e => {e.preventDefault();e.stopPropagation();shareProduct(el.dataset.share);});
  $$('[data-outbound]').forEach(el => el.onclick = () => trackOutbound(el.dataset.outbound));
}

function revealRandom(){
  const p=products[Math.floor(Math.random()*products.length)]; const card=$("#mysteryCard");
  card.classList.add("revealed");
  card.innerHTML=`<span class="mystery-index">BQ / REVELADO</span><div class="mystery-image ${imageMode(p)}"><img src="${p.image}" alt="${p.title}"></div><a class="btn btn-primary" style="position:absolute;left:18px;right:18px;bottom:18px" href="${p.link}" target="_blank" rel="sponsored noopener noreferrer" data-outbound="${p.id}">Ver ${p.category.toLowerCase()} →</a>`;
  bindActions();
}

chips.addEventListener("click", e => {
  const btn=e.target.closest("[data-category]"); if(!btn) return;
  favoritesOnly=false; quickMode="all"; activeCategory=btn.dataset.category;
  renderChips(); renderQuickFilters(); renderProducts();
});

$("#quickFilters").addEventListener("click", e => {
  const btn=e.target.closest("[data-quick]"); if(!btn) return;
  favoritesOnly=false; activeCategory="Todos"; quickMode=btn.dataset.quick;
  renderChips(); renderQuickFilters(); renderProducts();
});

search.addEventListener("input", e => {favoritesOnly=false;query=e.target.value;renderProducts();});
sortSelect.addEventListener("change", e => {sortMode=e.target.value;renderProducts();});
priceSelect.addEventListener("change", e => {priceMode=e.target.value;favoritesOnly=false;renderProducts();});
$("#clearFiltersBtn").addEventListener("click", resetFilters);

document.addEventListener("keydown", e => {
  if(e.key==="/" && document.activeElement!==search){e.preventDefault();search.focus();}
  if(e.key==="Escape" && modal.open) closeModal();
});

$("#surpriseBtn").onclick=()=>openProduct(products[Math.floor(Math.random()*products.length)].id);
$("#randomReveal").onclick=revealRandom;
$("#modalClose").onclick=closeModal;
modal.addEventListener("click",e=>{if(e.target===modal) closeModal();});
$("#favTop").onclick=showFavorites;
$("#favMobile").onclick=showFavorites;
$("#mobileSearchBtn").onclick=()=>{$("#achados").scrollIntoView({behavior:"smooth"});setTimeout(()=>search.focus(),500);};

renderHeroPreview();
renderFeatured();
renderChips();
renderQuickFilters();
renderProducts();
renderBeautyRail();
renderCategoryCards();
updateFavCount();

const deepLink = new URLSearchParams(location.search).get("produto");
if(deepLink && products.some(p=>p.id===deepLink)) setTimeout(()=>openProduct(deepLink),150);