"""
sheet_builder.py — пересборка листа «Сквозная аналитика <Месяц>».

Лист полностью генерируется из meta_daily, crm_daily и ads_manual:
  строка 1  — «В общем за месяц» (сумма итоговых строк всех дней)
  строка 2  — шапка
  дальше    — блоки дней, новые сверху:
                строка на каждое объявление из meta_daily (по расходу),
                K–S объединены по высоте блока: CRM одно число на день,
                строка «В общем» — итог дня.
Скрытые колонки: T — ad_id (связь с ads_manual), U — клики (для CTR итогов).

Всё пишется ОДНИМ spreadsheets.batchUpdate: очистка, значения, форматы,
объединения, размеры и условное форматирование. Запрос атомарный —
заказчик не увидит лист наполовину собранным.

Формулы без разделителей аргументов (+, /, IFERROR с одним аргументом):
у таблицы локаль ru_RU, где разделитель «;», а не «,».

Запуск: python sheet_builder.py 2026-09
"""

import re
import sys
from collections import defaultdict
from datetime import date

import gspread

from sheets_client import (META_SHEET, META_HEADERS, CRM_SHEET, CRM_HEADERS,
                           _access_errors, get_client, open_spreadsheet,
                           read_ads_manual)

MONTHS_RU = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль",
             "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]


def month_sheet_title(year: int, month: int) -> str:
    return f"Сквозная аналитика {MONTHS_RU[month - 1]}"


# ============================================================
# РАЗМЕТКА
# ============================================================
# Q «Встречи» (консультации проведены) вставлена между «Квал лиды» и «Продажи»
# по просьбе заказчика; остальные колонки шаблона сдвинуты на одну вправо.
(A, B, C, D, E, F, G, H, I, J, K, L, M, N, O, P, Q, R, S, T, U) = range(21)
N_COLS = 21
COL = "ABCDEFGHIJKLMNOPQRSTU"

HEADERS = {
    A: "Название объявления ", D: "Кодовое слово ", E: "Статус ", F: "Рассход ",
    G: "Показы ", H: "CPM ", I: "CTR ", J: "Заявки с FB ", K: "Заявки с AmoCrm",
    L: "Цена за заявку ", M: "Лиды ", N: "CR2 ", O: "Цена лида ", P: "Квал лиды ",
    Q: "Встречи ", R: "Продажи ", S: "Цена квал лида ", T: "ad_id", U: "clicks",
}
CRM_BLOCK = [K, L, M, N, O, P, Q, R, S]   # объединяются по высоте блока дня
SUMMED = [F, G, J, K, M, P, Q, R, U]      # складываются в итоге месяца

USD  = {"type": "NUMBER", "pattern": "$#,##0.00"}
USD2 = {"type": "NUMBER", "pattern": "[$$]#,##0.00"}
INT  = {"type": "NUMBER", "pattern": "#,##0"}
PCT  = {"type": "PERCENT", "pattern": "0.00%"}
DATE = {"type": "DATE", "pattern": "dd.mm.yyyy"}
NUM_FORMAT = {F: USD, G: INT, H: USD, I: PCT, J: INT, K: INT, L: USD2, M: INT,
              N: PCT, O: USD2, P: INT, Q: INT, R: INT, S: USD2, U: INT}

COL_WIDTHS = [130, 100, 496, 192, 192, 123, 120, 121, 153, 114,
              158, 153, 123, 131, 107, 135, 135, 135, 130]       # A–S: шаблон + «Встречи»
H_MONTH, H_HEADER, H_AD, H_TOTAL, H_DEFAULT = 48, 73, 35, 52, 21

BLUE_TEXT  = {"red": 0.07, "green": 0.33, "blue": 0.8}
GREEN_TEXT = {"red": 0.22, "green": 0.46, "blue": 0.11}
TOTAL_BG   = {"red": 0.37, "green": 0.56, "blue": 0.73}
TAB_GREEN  = {"green": 1}
_SOLID = {"style": "SOLID"}
BORDERS = {side: _SOLID for side in ("top", "bottom", "left", "right")}


def _rgb(red=0, green=0, blue=0):
    return {"red": red, "green": green, "blue": blue}


# Условное форматирование — правила из шаблона как есть. Поменяны только
# диапазоны: L — на все строки данных (было 3–17), «Цена квал лида» (теперь S,
# после вставки «Встречи») — только она
# (было R–Z, а там теперь скрытые ad_id и клики). Числа — с запятой
# (локаль ru_RU): «0.80%» из шаблона API отвергает как невалидное.
def _bool_rule(cond_type, values, bg):
    return {"booleanRule": {
        "condition": {"type": cond_type,
                      "values": [{"userEnteredValue": v} for v in values]},
        "format": {"backgroundColorStyle": {"rgbColor": bg}},
    }}


COND_RULES = [
    (L, "data", _bool_rule("NUMBER_LESS_THAN_EQ", ["0,8"], _rgb(0.42, 0.66, 0.31))),
    (I, "all",  _bool_rule("NUMBER_GREATER_THAN_EQ", ["1%"], _rgb(0.58, 0.77, 0.49))),
    (S, "all",  _bool_rule("NUMBER_GREATER_THAN_EQ", ["5"], _rgb(0.88, 0.4, 0.4))),
    (S, "all",  _bool_rule("NUMBER_LESS_THAN_EQ", ["4,5"], _rgb(0.42, 0.66, 0.31))),
    (S, "all",  _bool_rule("NUMBER_BETWEEN", ["4,6", "5"], _rgb(1, 0.85, 0.4))),
    (S, "all",  _bool_rule("NUMBER_GREATER_THAN_EQ", ["7"], _rgb(1))),
    (O, "all",  {"gradientRule": {
        "minpoint": {"type": "NUMBER", "value": "1,9",
                     "colorStyle": {"rgbColor": _rgb(0.34, 0.73, 0.54)}},
        "midpoint": {"type": "NUMBER", "value": "2,7",
                     "colorStyle": {"rgbColor": _rgb(1, 0.84, 0.4)}},
        "maxpoint": {"type": "NUMBER", "value": "2,7",
                     "colorStyle": {"rgbColor": _rgb(0.9, 0.49, 0.45)}},
    }}),
    (I, "all",  _bool_rule("NUMBER_BETWEEN", ["0,8%", "0,9%"], _rgb(1, 0.9, 0.6))),
    (I, "all",  _bool_rule("NUMBER_LESS", ["0,6%"], _rgb(0.88, 0.4, 0.4))),
]


def _fmt(col=None, *, font="Nunito", size=14, bold=False, italic=False,
         color=None, bg=None, h="CENTER", v="BOTTOM", wrap=False, num=True) -> dict:
    f = {
        "horizontalAlignment": h,
        "verticalAlignment": v,
        "borders": BORDERS,
        "textFormat": {"fontFamily": font, "fontSize": size, "bold": bold,
                       "italic": italic},
    }
    if color:
        f["textFormat"]["foregroundColorStyle"] = {"rgbColor": color}
    if bg:
        f["backgroundColorStyle"] = {"rgbColor": bg}
    if wrap:
        f["wrapStrategy"] = "WRAP"
    if num and col in NUM_FORMAT:
        f["numberFormat"] = NUM_FORMAT[col]
    return f


def _value(x) -> dict:
    if x is None or x == "":
        return {}
    if isinstance(x, str):
        return {"formulaValue": x} if x.startswith("=") else {"stringValue": x}
    return {"numberValue": x}


def _cell(x=None, fmt=None) -> dict:
    c = {"userEnteredFormat": fmt or {}}
    v = _value(x)
    if v:
        c["userEnteredValue"] = v
    return c


def _serial(d: date) -> int:
    """Дата → серийный номер Sheets (дни от 30.12.1899)."""
    return (d - date(1899, 12, 30)).days


def _div(num: str, den: str, mult: str = "") -> str:
    return f"=IFERROR({num}/{den}{mult})"


# ============================================================
# ДАННЫЕ
# ============================================================
def _records(values: list, headers: list) -> list:
    """Строки листа (UNFORMATTED_VALUE) → dict по headers; проверка шапки."""
    if not values or values[0][:len(headers)] != headers:
        raise RuntimeError(f"Шапка листа не совпадает с {headers}")
    out = []
    for r in values[1:]:
        r = list(r) + [""] * (len(headers) - len(r))
        out.append(dict(zip(headers, r)))
    return out


def _num(x) -> float:
    return x if isinstance(x, (int, float)) else 0


def _load_month(spreadsheet: gspread.Spreadsheet, year: int, month: int):
    """meta по дням {date: [row]}, crm {date: row} за месяц."""
    resp = spreadsheet.values_batch_get(
        [f"'{META_SHEET}'", f"'{CRM_SHEET}'"],
        params={"valueRenderOption": "UNFORMATTED_VALUE"})
    meta_vals, crm_vals = (vr.get("values", []) for vr in resp["valueRanges"])
    prefix = f"{year}-{month:02d}-"

    meta = defaultdict(list)
    for r in _records(meta_vals, META_HEADERS):
        if str(r["date"]).startswith(prefix):
            meta[r["date"]].append(r)
    crm = {r["date"]: r for r in _records(crm_vals, CRM_HEADERS)
           if str(r["date"]).startswith(prefix)}
    return meta, crm


def _check_no_references(spreadsheet: gspread.Spreadsheet, title: str, others: list):
    """
    Пересборка сдвигает строки, поэтому формулы других листов, ссылающиеся
    на этот лист, сломались бы. Если такие есть — не пересобираем.
    """
    if not others:
        return
    # ссылка в формуле — 'Название'!A1 (с пробелами имя всегда в кавычках);
    # «'Сквозная аналитика Сентябрь (вручную)'!A1» ссылкой на этот лист не считается
    refs = (f"'{title}'!", f"{title}!")
    resp = spreadsheet.values_batch_get([f"'{t}'" for t in others],
                                        params={"valueRenderOption": "FORMULA"})
    for t, vr in zip(others, resp["valueRanges"]):
        for i, row in enumerate(vr.get("values", []), 1):
            for j, v in enumerate(row):
                if isinstance(v, str) and v.startswith("=") and any(r in v for r in refs):
                    raise RuntimeError(
                        f"Лист «{t}», ячейка {COL[j] if j < N_COLS else j + 1}{i} "
                        f"ссылается на «{title}». Пересборка сломала бы ссылку, "
                        f"лист не тронут")


# ============================================================
# СБОРКА
# ============================================================
def _build(meta: dict, crm: dict, manual: dict):
    """
    -> (rows, merges, row_kinds): rows — список строк ячеек с 1-й строки
    листа, merges — (r0, r1, c0, c1) 0-based полуинтервалы,
    row_kinds — тип строки для высоты.
    """
    merges, kinds = [], []

    # строка 2 — шапка (строку 1 соберём в конце, когда известны итоги дней)
    header = []
    for col in range(N_COLS):
        header.append(_cell(HEADERS.get(col), _fmt(
            font="Arial", size=16, bold=True, italic=True, v="MIDDLE", wrap=True,
            color=BLUE_TEXT if col == A else None, num=False)))
    merges.append((1, 2, A, C + 1))

    body, total_rows = [], []
    r = 3                                          # 1-based номер текущей строки
    for day in sorted(set(meta) | set(crm), reverse=True):
        ads = sorted(meta.get(day, []), key=lambda x: -_num(x["spend"])) or [None]
        c = crm.get(day) or {}
        s, e = r, r + len(ads) - 1                 # строки объявлений
        t = e + 1                                  # итог дня

        for i, ad in enumerate(ads):
            row = [_cell(None, _fmt(col)) for col in range(N_COLS)]
            if i == 0:
                row[A] = _cell(_serial(date.fromisoformat(day)), {
                    **_fmt(size=32, bold=True, color=BLUE_TEXT, v="MIDDLE", wrap=True,
                           num=False),
                    "numberFormat": DATE})
                row[K] = _cell(c.get("new_request"), _fmt(K, v="MIDDLE"))
                row[L] = _cell(_div(f"F{t}", f"K{s}"), _fmt(L, v="MIDDLE"))
                row[M] = _cell(c.get("lead"), _fmt(M, v="MIDDLE"))
                row[N] = _cell(_div(f"M{s}", f"K{s}"), _fmt(N, v="MIDDLE"))
                row[O] = _cell(_div(f"F{t}", f"M{s}"), _fmt(O, v="MIDDLE"))
                row[P] = _cell(c.get("qualified"), _fmt(P, v="MIDDLE"))
                row[Q] = _cell(c.get("consult_done"), _fmt(Q, v="MIDDLE"))
                row[R] = _cell(c.get("sale"), _fmt(R, v="MIDDLE"))
                row[S] = _cell(_div(f"F{t}", f"P{s}"), _fmt(S, v="MIDDLE"))
            name_fmt = _fmt(h="LEFT", v="MIDDLE", wrap=True, num=False)
            if ad is None:
                row[B] = _cell("нет данных Meta за день", name_fmt)
            else:
                ad_id = str(ad["ad_id"])
                man = manual.get(ad_id, {})
                row[B] = _cell(ad["ad_name"], name_fmt)
                row[D] = _cell(man.get("code_word"), _fmt(wrap=True))
                row[E] = _cell(man.get("status"), _fmt(bold=True, color=GREEN_TEXT, wrap=True))
                row[F] = _cell(_num(ad["spend"]), _fmt(F))
                row[G] = _cell(_num(ad["impressions"]), _fmt(G))
                row[H] = _cell(_num(ad["cpm"]), _fmt(H))
                row[I] = _cell(_num(ad["ctr"]) / 100, _fmt(I))   # Meta: 0.577 = 0.577%
                row[J] = _cell(_num(ad["dm_leads"]), _fmt(J))
                row[T] = _cell(ad_id, _fmt(num=False))
                row[U] = _cell(_num(ad["clicks"]), _fmt(U))
            row[C] = _cell(None, name_fmt)
            body.append(row)
            kinds.append(H_AD)
            merges.append((r - 1, r, B, C + 1))
            r += 1

        if e > s:
            merges.append((s - 1, e, A, A + 1))
            merges.extend((s - 1, e, col, col + 1) for col in CRM_BLOCK)

        # итог дня
        tot = {
            F: f"=SUM(F{s}:F{e})", G: f"=SUM(G{s}:G{e})",
            H: _div(f"F{t}", f"G{t}", "*1000"), I: _div(f"U{t}", f"G{t}"),
            J: f"=SUM(J{s}:J{e})", K: f"=K{s}", L: _div(f"F{t}", f"K{t}"),
            M: f"=M{s}", N: _div(f"M{t}", f"K{t}"), O: _div(f"F{t}", f"M{t}"),
            P: f"=P{s}", Q: f"=Q{s}", R: f"=R{s}", S: _div(f"F{t}", f"P{t}"),
            U: f"=SUM(U{s}:U{e})",
        }
        row = [_cell(tot.get(col), _fmt(col, bg=TOTAL_BG)) for col in range(N_COLS)]
        row[A] = _cell("В общем", _fmt(size=21, bold=True, bg=TOTAL_BG, wrap=True, num=False))
        body.append(row)
        kinds.append(H_TOTAL)
        merges.append((t - 1, t, A, C + 1))
        total_rows.append(t)
        r += 1

    # строка 1 — итог месяца: сумма итоговых строк дней
    month = {}
    for col in SUMMED:
        month[col] = "=" + "+".join(f"{COL[col]}{t}" for t in total_rows) if total_rows else 0
    month.update({
        H: _div("F1", "G1", "*1000"), I: _div("U1", "G1"), L: _div("F1", "K1"),
        N: _div("M1", "K1"), O: _div("F1", "M1"), S: _div("F1", "P1"),
    })
    top = [_cell(month.get(col), _fmt(col, font="Arial", size=19, bold=True, italic=True,
                                      v="MIDDLE", wrap=True))
           for col in range(N_COLS)]
    top[A] = _cell("В общем за месяц", _fmt(font="Arial", size=19, bold=True, italic=True,
                                            v="MIDDLE", wrap=True, num=False))
    merges.append((0, 1, A, C + 1))

    return [top, header] + body, merges, [H_MONTH, H_HEADER] + kinds


# Скрытая служебная колонка шапки: по ней видно, что лист собран скриптом.
# S2 — так было до вставки «Встречи»; такие листы тоже наши.
_GENERATED_MARKERS = ("T2", "S2")


MANUAL_SUFFIX = " (вручную)"


def _is_generated(spreadsheet: gspread.Spreadsheet, title: str) -> bool:
    """Лист собран скриптом: в шапке скрытая колонка ad_id."""
    resp = spreadsheet.values_batch_get([f"'{title}'!{a1}" for a1 in _GENERATED_MARKERS])
    return any((vr.get("values") or [[""]])[0][0] == HEADERS[T]
               for vr in resp["valueRanges"])


def _norm_name(name) -> str:
    """Название объявления для сравнения: в ручном листе встречаются хвостовые
    табы и двойные пробелы, которых нет в Meta."""
    return re.sub(r"\s+", " ", str(name or "")).strip().casefold()


def _manual_codes(spreadsheet: gspread.Spreadsheet, title: str) -> dict:
    """
    Кодовые слова и статусы с ручного листа (разметка шаблона: B — название
    объявления, D — кодовое слово, E — статус). -> {название: (код, статус)}.
    Если объявление встречается в нескольких днях, берётся последнее
    заполненное значение сверху вниз.
    """
    resp = spreadsheet.values_batch_get([f"'{title}'!B3:E"])
    out = {}
    for row in resp["valueRanges"][0].get("values", []):
        row = list(row) + [""] * (4 - len(row))
        name, code, status = _norm_name(row[0]), str(row[2]).strip(), str(row[3]).strip()
        if name and (code or status):
            out[name] = (code, status)
    return out


def _set_aside_manual(spreadsheet: gspread.Spreadsheet, sheet: dict, titles: set) -> str:
    """
    Переименовывает ручной лист месяца, ничего в нём не меняя, чтобы на его
    месте собрать лист скрипта. Формулы, ссылавшиеся на него, Google
    переписывает на новое имя сам. -> новое название.
    """
    title = sheet["properties"]["title"]
    new, n = title + MANUAL_SUFFIX, 2
    while new in titles:
        new, n = f"{title} (вручную {n})", n + 1
    spreadsheet.batch_update({"requests": [{"updateSheetProperties": {
        "properties": {"sheetId": sheet["properties"]["sheetId"], "title": new},
        "fields": "title"}}]})
    return new


def rebuild_month_sheet(year: int, month: int,
                        spreadsheet: gspread.Spreadsheet = None) -> dict:
    """
    Пересобирает лист «Сквозная аналитика <Месяц>» из meta_daily, crm_daily
    и ads_manual. Лист месяца создаётся, если его нет. Другие листы не
    меняются (кроме дописывания новых ad_id в ads_manual).

    Лист с тем же названием, заполненный вручную, не стирается: он
    переименовывается в «… (вручную)», а его кодовые слова и статусы
    подставляются в ads_manual для новых объявлений (по названию).
    -> {"title", "days", "ad_rows", "rows", "set_aside"}
    """
    spreadsheet = spreadsheet or open_spreadsheet()
    title = month_sheet_title(year, month)

    with _access_errors():
        sheets = spreadsheet.fetch_sheet_metadata(params={
            "fields": "sheets(properties(sheetId,title,gridProperties),conditionalFormats)"
        })["sheets"]
        titles = {s["properties"]["title"] for s in sheets}
        target = next((s for s in sheets if s["properties"]["title"] == title), None)
        set_aside = None
        if target is not None and not _is_generated(spreadsheet, title):
            set_aside = _set_aside_manual(spreadsheet, target, titles)
            titles.add(set_aside)
            target = None
        if target is not None:
            own = {title, META_SHEET, CRM_SHEET}
            _check_no_references(spreadsheet, title,
                                 [t for t in titles if t not in own])

        meta, crm = _load_month(spreadsheet, year, month)
        ads = {str(a["ad_id"]): a["ad_name"] for rows in meta.values() for a in rows}
        # коды с отложенных ручных листов этого месяца — только для объявлений,
        # которых ещё нет в ads_manual (существующие строки не меняются)
        imported = {}
        for t in sorted(t for t in titles if t.startswith(f"{title} (вручную")):
            imported.update(_manual_codes(spreadsheet, t))
        defaults = {ad_id: imported[_norm_name(name)] for ad_id, name in ads.items()
                    if _norm_name(name) in imported}
        manual = read_ads_manual(spreadsheet, ads, defaults)
        rows, merges, heights = _build(meta, crm, manual)

        if target is None:
            ws = spreadsheet.add_worksheet(title=title, rows=max(len(rows) + 50, 200),
                                           cols=N_COLS)
            sheet_id, cur_rows, cur_cols, n_cf = ws.id, ws.row_count, ws.col_count, 0
        else:
            p = target["properties"]
            sheet_id = p["sheetId"]
            cur_rows = p["gridProperties"]["rowCount"]
            cur_cols = p["gridProperties"]["columnCount"]
            n_cf = len(target.get("conditionalFormats", []))

        n_rows = max(cur_rows, len(rows) + 50)
        grid = {"sheetId": sheet_id}
        requests = [
            {"updateSheetProperties": {
                "properties": {"sheetId": sheet_id,
                               "tabColorStyle": {"rgbColor": TAB_GREEN},
                               "gridProperties": {"rowCount": n_rows,
                                                  "columnCount": max(cur_cols, N_COLS),
                                                  "frozenRowCount": 2,
                                                  "frozenColumnCount": 3}},
                "fields": "tabColorStyle,gridProperties(rowCount,columnCount,"
                          "frozenRowCount,frozenColumnCount)"}},
            {"unmergeCells": {"range": grid}},
            {"updateCells": {"range": grid,
                             "fields": "userEnteredValue,userEnteredFormat,note,dataValidation"}},
        ]
        requests += [{"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": 0}}
                     for _ in range(n_cf)]
        requests.append({"updateCells": {
            "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": 0},
            "rows": [{"values": row} for row in rows],
            "fields": "userEnteredValue,userEnteredFormat"}})
        requests += [{"mergeCells": {"mergeType": "MERGE_ALL", "range": {
            "sheetId": sheet_id, "startRowIndex": r0, "endRowIndex": r1,
            "startColumnIndex": c0, "endColumnIndex": c1}}} for r0, r1, c0, c1 in merges]

        def dim(kind, start, end, props, fields):
            return {"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": kind,
                          "startIndex": start, "endIndex": end},
                "properties": props, "fields": fields}}

        requests += [dim("COLUMNS", i, i + 1, {"pixelSize": w, "hiddenByUser": False},
                         "pixelSize,hiddenByUser") for i, w in enumerate(COL_WIDTHS)]
        requests.append(dim("COLUMNS", T, U + 1, {"hiddenByUser": True}, "hiddenByUser"))
        i = 0
        while i < len(heights):                    # подряд идущие одинаковые высоты
            j = i
            while j + 1 < len(heights) and heights[j + 1] == heights[i]:
                j += 1
            requests.append(dim("ROWS", i, j + 1, {"pixelSize": heights[i]}, "pixelSize"))
            i = j + 1
        requests.append(dim("ROWS", len(heights), n_rows, {"pixelSize": H_DEFAULT}, "pixelSize"))

        last = len(rows)
        for idx, (col, scope, rule) in enumerate(COND_RULES):
            rng = {"sheetId": sheet_id, "startColumnIndex": col, "endColumnIndex": col + 1,
                   "startRowIndex": 2 if scope == "data" else 0}
            if scope == "data":
                rng["endRowIndex"] = last
            requests.append({"addConditionalFormatRule": {
                "index": idx, "rule": {"ranges": [rng], **rule}}})

        spreadsheet.batch_update({"requests": requests})

    return {"title": title, "days": len(set(meta) | set(crm)),
            "ad_rows": sum(len(v) for v in meta.values()), "rows": len(rows),
            "set_aside": set_aside}


if __name__ == "__main__":
    y, m = map(int, sys.argv[1].split("-"))
    client = get_client()
    info = rebuild_month_sheet(y, m, open_spreadsheet(client))
    print(f"«{info['title']}»: дней {info['days']}, строк объявлений {info['ad_rows']}, "
          f"всего строк {info['rows']}. Запросов к Google API: {client.request_count}")
