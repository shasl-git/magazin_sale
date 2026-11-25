const state = {
  token: null,
  picks: {},
  counts: {},
  busy: false,
};

const gapsEl = document.querySelector("#gaps");
const bannerEl = document.querySelector("#banner");
const placeEl = document.querySelector("#place");
const listEl = document.querySelector("#list");
const promoLinkEl = document.querySelector("#promos-link");
const storeEl = document.querySelector("#store");
const receiptEl = document.querySelector("#receipt");
const choicesEl = document.querySelector("#choices");
const hintEl = document.querySelector("#hint");
const buildEl = document.querySelector("#build");

const STATE_LABEL = {
  ready: "работает",
  partial: "частично",
  manual: "вручную",
  demo: "демо",
  later: "позже",
};

document.querySelector("#composer").addEventListener("submit", (event) => {
  event.preventDefault();
  runPlan();
});
storeEl.addEventListener("change", () => {
  syncPromoLink();
  if (state.token && listEl.value.trim()) runPlan();
});

choicesEl.addEventListener("click", (event) => {
  const card = event.target.closest("[data-sku]");
  if (!card || state.busy) return;
  const need = card.dataset.need;
  const sku = state.picks[need] === card.dataset.sku ? "" : card.dataset.sku;
  recalc({ picks: { [need]: sku } });
});

receiptEl.addEventListener("click", (event) => {
  const qty = event.target.closest("[data-qty]");
  if (qty && !state.busy) {
    const need = qty.dataset.need;
    const next = Math.min(30, Math.max(1, (state.counts[need] || 1) + Number(qty.dataset.qty)));
    state.counts[need] = next;
    recalc({ counts: { ...state.counts } });
    return;
  }
  const alt = event.target.closest("[data-store]");
  if (alt && !state.busy) recalc({ store: alt.dataset.store });
});

boot();

async function boot() {
  const meta = await api("/api/meta");
  placeEl.textContent = `${meta.city}, ${meta.district}`;
  listEl.value = meta.sample_list;
  fillStores(meta.stores, meta.stores[0]?.id || "");
  renderGaps(meta.gaps);
  loadNearbyStores();
}

function fillStores(stores, selected) {
  storeEl.replaceChildren(
    ...stores.map((store) => {
      const option = document.createElement("option");
      option.value = store.id;
      option.textContent = `${store.title} · ${store.address || store.detail || ""}`;
      return option;
    }),
  );
  if (selected && [...storeEl.options].some((option) => option.value === selected)) {
    storeEl.value = selected;
  }
  syncPromoLink();
}

function syncPromoLink() {
  promoLinkEl.href = `/promos.html?shop=${encodeURIComponent(storeEl.value || "")}`;
}

async function loadNearbyStores() {
  const data = await api("/api/stores");
  if (data.error) showBanner(data.error);
  if (data.stores?.length) fillStores(data.stores, storeEl.value || data.stores[0].id);
}

function currentPromo() {
  try {
    const raw = localStorage.getItem("magnit-promo");
    if (!raw) return null;
    const promo = JSON.parse(raw);
    if (!promo || !promo.threshold || !promo.discount_value) return null;
    return {
      title: promo.title,
      threshold: promo.threshold,
      discount_value: promo.discount_value,
      discount_kind: promo.discount_kind || "percent",
    };
  } catch {
    return null;
  }
}

async function runPlan() {
  setBusy(true, "Ищу цены…");
  clearBanner();
  renderLoading();
  const started = await api("/api/plan-job", {
    method: "POST",
    body: {
      text: listEl.value,
      shop_code: storeEl.value,
      manual: true,
      promo: currentPromo(),
    },
  });
  if (started.error || !started.job) {
    setBusy(false);
    showBanner(started.error || "Не удалось начать загрузку");
    hintEl.textContent = "";
    renderIdleCart();
    return;
  }
  const startedAt = Date.now();
  while (Date.now() - startedAt < 240000) {
    const job = await api(`/api/plan-job?id=${encodeURIComponent(started.job)}`);
    if (job.done) {
      setBusy(false);
      if (job.error) {
        showBanner(job.error);
        hintEl.textContent = "";
        renderIdleCart();
        return;
      }
      applyPlan(job.payload);
      return;
    }
    if (job.error) {
      setBusy(false);
      showBanner(job.error);
      hintEl.textContent = "";
      renderIdleCart();
      return;
    }
    setProgress(job.current || 0, job.total || 1, job.label || "Ищу цены…");
    await wait(400);
  }
  setBusy(false);
  showBanner("Загрузка слишком долгая.");
  hintEl.textContent = "";
  renderIdleCart();
}

async function recalc(extra) {
  setBusy(true, "Пересчитываю…");
  clearBanner();
  const payload = await api("/api/recalc", {
    method: "POST",
    body: {
      token: state.token,
      picks: extra.picks || {},
      counts: extra.counts || null,
      store: extra.store || "",
      promo: currentPromo(),
    },
  });
  setBusy(false);
  if (payload.error) {
    showBanner(payload.error);
    hintEl.textContent = "";
    return;
  }
  applyPlan(payload);
}

async function buy() {
  const paid = document.querySelector("#paid");
  setBusy(true, "Записываю…");
  clearBanner();
  const payload = await api("/api/buy", {
    method: "POST",
    body: {
      token: state.token,
      paid: paid ? Number(paid.value) : null,
    },
  });
  setBusy(false);
  if (payload.error) {
    showBanner(payload.error);
    hintEl.textContent = "";
    return;
  }
  showBanner(payload.message, payload.saved);
  if (payload.plan || payload.token) applyPlan(payload);
}

function applyPlan(payload) {
  state.token = payload.token;
  state.picks = {};
  state.counts = {};
  if (payload.plan) {
    for (const line of payload.plan.lines) {
      state.picks[line.need] = line.external_id;
      state.counts[line.need] = line.count;
    }
  }
  if (payload.list_text) listEl.value = payload.list_text;
  renderGaps(payload.gaps);
  renderReceipt(payload);
  renderChoices(payload);
  hintEl.textContent = payload.again_note || payload.source_note || "";
}

function renderGaps(gaps) {
  gapsEl.replaceChildren(
    ...gaps.map((gap) => {
      const article = el("article", "gap");
      const top = el("div", "gap-top");
      top.append(el("h2", "", gap.title), el("span", `state ${gap.state}`, STATE_LABEL[gap.state] || gap.state));
      article.append(top, el("p", "", gap.detail));
      return article;
    }),
  );
}

function renderLoading() {
  receiptEl.replaceChildren(el("h2", "cart-title", "Корзина"), progressBox(8, "Ищу цены…"));
}

function renderIdleCart() {
  receiptEl.replaceChildren(
    el("h2", "cart-title", "Корзина"),
    el("p", "receipt-empty", "Напиши список и нажми «Собрать план», потом выбери товары сам."),
  );
}

function progressBox(percent, label) {
  const box = el("div", "progress");
  box.id = "progress";
  const track = el("div", "progress-track");
  const fill = el("div", "progress-fill");
  fill.id = "progress-fill";
  fill.style.width = `${percent}%`;
  track.append(fill);
  const text = el("p", "hint", label);
  text.id = "progress-label";
  box.append(track, text);
  return box;
}

function setProgress(current, total, label) {
  const fill = document.querySelector("#progress-fill");
  const text = document.querySelector("#progress-label");
  const percent = total ? Math.max(6, Math.min(100, Math.round((current / total) * 100))) : 6;
  if (fill) fill.style.width = `${percent}%`;
  if (text) text.textContent = total ? `${current} из ${total} · ${label}` : label;
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function renderReceipt(payload) {
  const plan = payload.plan;
  receiptEl.replaceChildren(el("h2", "cart-title", "Корзина"));
  if (payload.active_promo) {
    receiptEl.append(el("p", "note", payload.active_promo.title));
  }
  if (!plan) {
    receiptEl.append(
      el("p", "receipt-kicker", "Корзина не собралась"),
      el("p", "receipt-empty", payload.missing?.length
        ? `Нет в наличии: ${payload.missing.join(", ")}.`
        : "Не у всех позиций нашёлся товар."),
    );
    return;
  }
  if (!plan.lines.length) {
    receiptEl.append(el("p", "receipt-empty", "Товары сами не подставляются. Выбери их в списке ниже."));
    if (plan.shortfall) {
      receiptEl.append(el("p", "note", `До применения скидки не хватает ${rub(plan.shortfall)}`));
    }
    return;
  }
  receiptEl.append(el("p", "store-name", plan.store_title));
  receiptEl.append(el("p", "total", rub(plan.total)));
  const save = el("p", "savings", plan.savings > 0
    ? `Экономия к обычной цене ${rub(plan.savings)}`
    : "К обычной цене этой корзины экономии нет");
  receiptEl.append(save);

  const lines = el("ul", "lines");
  for (const line of plan.lines) {
    const item = document.createElement("li");
    const text = el("div");
    text.append(el("div", "line-title", line.title));
    const prices = pricePair(line.price, line.old_price, line.delivery_price);
    if (line.count > 1) {
      prices.append(el("span", "line-meta", `× ${line.count}`));
    }
    text.append(prices);
    const qty = el("div", "qty");
    qty.append(
      button("−", { "data-qty": "-1", "data-need": line.need }),
      el("span", "", String(line.count)),
      button("+", { "data-qty": "1", "data-need": line.need }),
    );
    item.append(text, qty);
    lines.append(item);
  }
  receiptEl.append(lines);

  const math = el("div", "math");
  addRow(math, "Товары", rub(plan.subtotal));
  if (plan.discount) addRow(math, "Скидка корзины", `−${rub(plan.discount)}`);
  if (plan.delivery) addRow(math, "Доставка", rub(plan.delivery));
  if (plan.baseline && plan.baseline !== plan.total) addRow(math, "Без скидок", rub(plan.baseline));
  if (math.childElementCount) receiptEl.append(math);

  if (plan.applied_promos?.length) {
    receiptEl.append(el("p", "note", plan.applied_promos.join(" · ")));
  }
  if (plan.shortfall) {
    receiptEl.append(el("p", "note", `До применения скидки не хватает ${rub(plan.shortfall)}`));
  }
  if (plan.alternatives?.length) {
    const alts = el("div", "alts");
    for (const alt of plan.alternatives) {
      const worse = alt.worse_by > 0 ? `дороже на ${rub(alt.worse_by)}` : `дешевле на ${rub(Math.abs(alt.worse_by))}`;
      alts.append(button(`${alt.store_title}: ${rub(alt.total)}, ${worse}`, { "data-store": alt.store }));
    }
    receiptEl.append(alts);
  }

  const buyBox = el("form", "buy");
  const paid = el("label", "", "Оплатил, ₽");
  const input = document.createElement("input");
  input.id = "paid";
  input.type = "number";
  input.min = "0";
  input.step = "1";
  input.value = String(Math.round(plan.total));
  paid.append(input);
  buyBox.append(paid, button("Я купил", { id: "buy", class: "primary", type: "submit" }));
  buyBox.addEventListener("submit", (event) => {
    event.preventDefault();
    buy();
  });
  receiptEl.append(buyBox);
}

function renderChoices(payload) {
  const entries = Object.entries(payload.choices || {});
  if (!entries.length) {
    choicesEl.hidden = true;
    return;
  }
  choicesEl.hidden = false;
  choicesEl.replaceChildren(
    ...entries.map(([need, options]) => {
      const section = el("section", "choice");
      section.append(el("h2", "", need));
      const cards = el("div", "cards");
      if (!options.length) {
        cards.append(el("p", "note", "В этом магазине вариантов нет."));
      }
      for (const option of options) {
        const card = button("", { "data-sku": option.external_id, "data-need": need, class: option.selected ? "card selected" : "card" });
        card.append(el("strong", "", option.title), pricePair(option.price, option.old_price, option.delivery_price));
        card.append(el("small", "", `${perUnit(option)}${option.note ? " · " + option.note : ""}`));
        cards.append(card);
      }
      section.append(cards);
      return section;
    }),
  );
}

function pricePair(price, oldPrice, deliveryPrice) {
  const pair = el("div", "price-pair");
  const onSale = oldPrice && Number(oldPrice) > Number(price);
  if (onSale) pair.append(el("span", "was", rub(oldPrice)));
  pair.append(el("span", onSale ? "sale on-sale" : "sale", rub(price)));
  if (deliveryPrice !== undefined && deliveryPrice !== null && deliveryPrice !== "") {
    pair.append(el("span", "online-price", `онлайн ${rub(deliveryPrice)}`));
  }
  return pair;
}

function addRow(parent, name, value) {
  parent.append(el("span", "", name), el("span", "", value));
}

function perUnit(option) {
  if (option.unit === "мл") return `${(option.price_per_base * 1000).toFixed(1)} ₽/л`;
  if (option.unit === "г") return `${(option.price_per_base * 1000).toFixed(1)} ₽/кг`;
  return `${option.price_per_base.toFixed(2)} ₽/${option.unit}`;
}

function rub(value) {
  const number = Number(value) || 0;
  const digits = Math.abs(number - Math.round(number)) < 0.05 ? 0 : 2;
  return `${new Intl.NumberFormat("ru-RU", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(number)} ₽`;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function button(text, attrs) {
  const node = document.createElement("button");
  node.type = "button";
  node.textContent = text;
  for (const [key, value] of Object.entries(attrs || {})) {
    if (key === "class") node.className = value;
    else node.setAttribute(key, value);
  }
  return node;
}

function setBusy(busy, message) {
  state.busy = busy;
  buildEl.disabled = busy;
  storeEl.disabled = busy;
  if (message) hintEl.textContent = message;
}

function showBanner(message, ok) {
  bannerEl.hidden = false;
  bannerEl.textContent = message;
  bannerEl.className = ok ? "banner ok" : "banner";
}

function clearBanner() {
  bannerEl.hidden = true;
  bannerEl.textContent = "";
}

async function api(path, options) {
  try {
    const response = await fetch(path, {
      method: options?.method || "GET",
      headers: options?.body ? { "Content-Type": "application/json" } : undefined,
      body: options?.body ? JSON.stringify(options.body) : undefined,
    });
    const data = await response.json();
    if (!response.ok) return { error: data.error || "Не вышло" };
    return data;
  } catch (error) {
    return { error: "Сайт не ответил. Проверь, что python -m web.server ещё запущен." };
  }
}
