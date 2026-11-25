"""Тексты 6 экранов бота (пока для консоли / будущего aiogram)."""

from __future__ import annotations

STORE_TITLE = {
    "magnit": "Магнит",
    "pyaterochka": "Пятёрочка",
    "samokat": "Самокат",
}


def screen_start() -> str:
    return (
        "🛒 Что купить сегодня?\n\n"
        "Можешь списком:\n"
        "молоко, хлеб, сахар, чипсы, кола\n\n"
        "или кнопками: [На неделю] [Быстрое] [Повторить прошлый]"
    )


def screen_promos(lines: list[str], recommendation: str) -> str:
    body = "\n".join(lines)
    return f"🔥 Акции сегодня\n\n{body}\n\nРекомендация алгоритма:\n👉 {recommendation}"


def screen_plan(store: str, items: list[str], subtotal: float, total: float, alts: list[str]) -> str:
    block = "\n".join(items)
    alt = "\n".join(alts) if alts else "—"
    return (
        f"📦 План закупки\n\n"
        f"{STORE_TITLE.get(store, store)}\n"
        f"{block}\n"
        f"Итого до акций: {subtotal:.0f} ₽\n"
        f"К оплате: {total:.0f} ₽\n\n"
        f"Альтернатива:\n{alt}"
    )


def screen_sku(need: str, variants: list[str], store: str) -> str:
    body = "\n\n".join(variants)
    return (
        f"🥛 {need.capitalize()} — что взять?\n\n"
        f"{body}\n\n"
        f"Магазин: {STORE_TITLE.get(store, store)}"
    )


def screen_final(
    store: str,
    items: list[str],
    subtotal: float,
    discount: float,
    delivery: float,
    total: float,
    baseline: float,
    saved: float,
) -> str:
    body = "\n".join(items)
    return (
        f"✅ Твой заказ ({STORE_TITLE.get(store, store)})\n\n"
        f"{body}\n"
        f"────────────────────────────\n"
        f"Сумма до скидки: {subtotal:.0f} ₽\n"
        f"Скидка: −{discount:.0f} ₽\n"
        f"Доставка: {delivery:.0f} ₽\n"
        f"К ОПЛАТЕ: {total:.0f} ₽\n\n"
        f"База: {baseline:.0f} ₽\n"
        f"Экономия этой покупки: {saved:.0f} ₽"
    )


def screen_saved(today: float, month: float, half: float, year: float | None) -> str:
    year_s = f"{year:.0f} ₽" if year is not None else "— (мало данных)"
    return (
        f"✅ Записал\n"
        f"Экономия сегодня: {today:.0f} ₽\n\n"
        f"В этом месяце: {month:.0f} ₽\n"
        f"За 6 месяцев: {half:.0f} ₽\n"
        f"За год: {year_s}"
    )


def screen_stats(week: float, month: float, half: float, year: float, recent: list[str]) -> str:
    recent_block = "\n".join(recent) if recent else "пока пусто"
    return (
        "💰 Экономия\n\n"
        f"За неделю:   {week:.0f} ₽\n"
        f"За месяц:  {month:.0f} ₽\n"
        f"За 6 мес:  {half:.0f} ₽\n"
        f"За год:   {year:.0f} ₽\n\n"
        f"Последние покупки:\n{recent_block}"
    )
