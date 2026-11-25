const PROMO_KEY = "magnit-promo";
const params = new URLSearchParams(location.search);
const shop = params.get("shop") || "";
const bannerEl = document.querySelector("#banner");
const noteEl = document.querySelector("#note");
const listEl = document.querySelector("#promos");

boot();

async function boot() {
  const data = await api(`/api/promos?shop_code=${encodeURIComponent(shop)}`);
  if (data.error) {
    showBanner(data.error);
    return;
  }
  noteEl.textContent = "Здесь только выбор акции. Скидка и товары считаются в корзине на главной.";
  if (!data.promos?.length) {
    listEl.append(el("p", "receipt-empty", data.note || "Пока нет порога корзины для этой точки."));
    return;
  }
  const saved = readPromo();
  data.promos.forEach((promo) => listEl.append(promoCard(promo, saved && saved.id === promo.id)));
}

function promoCard(promo, chosen) {
  const card = el("article", chosen ? "promo-card selected" : "promo-card");
  card.dataset.id = promo.id;
  const title = el("h2", "", promo.title);
  const rule = el(
    "p",
    "line-meta",
    promo.discount_kind === "percent"
      ? `От ${rub(promo.threshold)} — скидка ${Math.round(promo.discount_value * 100)}%`
      : `От ${rub(promo.threshold)} — минус ${rub(promo.discount_value)}`,
  );
  const pick = button(chosen ? "Выбрана" : "Выбрать", chosen ? "primary" : "ghost");
  pick.addEventListener("click", () => selectPromo(promo, card, pick));
  card.append(title, rule, pick);
  return card;
}

function selectPromo(promo, card, pick) {
  const saved = readPromo();
  const same = saved && saved.id === promo.id;
  document.querySelectorAll(".promo-card").forEach((node) => {
    node.classList.remove("selected");
    const buttonNode = node.querySelector("button");
    if (buttonNode) {
      buttonNode.textContent = "Выбрать";
      buttonNode.className = "ghost";
    }
  });
  if (same) {
    localStorage.removeItem(PROMO_KEY);
    return;
  }
  localStorage.setItem(PROMO_KEY, JSON.stringify({ ...promo, shop }));
  card.classList.add("selected");
  pick.textContent = "Выбрана";
  pick.className = "primary";
}

function readPromo() {
  try {
    return JSON.parse(localStorage.getItem(PROMO_KEY) || "null");
  } catch {
    return null;
  }
}

async function api(url) {
  const response = await fetch(url);
  return response.json();
}

function showBanner(text) {
  bannerEl.hidden = false;
  bannerEl.textContent = text;
}

function rub(value) {
  const number = Number(value) || 0;
  const digits = Math.abs(number - Math.round(number)) < 0.05 ? 0 : 2;
  return `${new Intl.NumberFormat("ru-RU", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(number)} ₽`;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function button(text, className) {
  const node = document.createElement("button");
  node.type = "button";
  if (className) node.className = className;
  node.textContent = text;
  return node;
}
