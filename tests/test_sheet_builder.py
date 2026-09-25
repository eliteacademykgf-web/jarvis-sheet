import pytest

import sheet_builder as sb


def _v(cell):
    uv = cell.get("userEnteredValue", {})
    return uv.get("formulaValue", uv.get("stringValue", uv.get("numberValue")))


META = {"2026-09-20": [
    {"ad_id": "111", "ad_name": "Объявление A", "spend": 10.0, "impressions": 1000,
     "cpm": 10.0, "ctr": 1.5, "dm_leads": 4, "clicks": 15},
    {"ad_id": "222", "ad_name": "Объявление B", "spend": 30.0, "impressions": 2000,
     "cpm": 15.0, "ctr": 0.5, "dm_leads": 2, "clicks": 10},
]}
CRM = {"2026-09-20": {"new_request": 12, "lead": 9, "qualified": 5,
                      "consult_done": 3, "sale": 1}}
MANUAL = {"111": {"code_word": "ИТАЛИЯ 🔥", "status": "Активно"}}


@pytest.fixture
def built():
    return sb._build(META, CRM, MANUAL)


def test_header_has_meetings_between_qualified_and_sales(built):
    rows, _, _ = built
    header = [_v(c) for c in rows[1]]
    assert header[sb.P].strip() == "Квал лиды"
    assert header[sb.Q].strip() == "Встречи"
    assert header[sb.R].strip() == "Продажи"
    assert header[sb.S].strip() == "Цена квал лида"
    assert header[sb.T] == "ad_id"


def test_day_block_values(built):
    rows, merges, _ = built
    first, second, total = rows[2], rows[3], rows[4]
    # объявления по убыванию расхода
    assert _v(first[sb.B]) == "Объявление B" and _v(second[sb.B]) == "Объявление A"
    # CRM — в первой строке блока
    assert _v(first[sb.K]) == 12
    assert _v(first[sb.P]) == 5
    assert _v(first[sb.Q]) == 3
    assert _v(first[sb.R]) == 1
    assert _v(first[sb.S]) == "=IFERROR(SUM(F3:F4)/P3)"
    # код и статус из ads_manual
    assert _v(second[sb.D]) == "ИТАЛИЯ 🔥"
    # CTR: 0.5% из Meta → 0.005 на листе
    assert _v(first[sb.I]) == pytest.approx(0.005)
    # CRM-колонки объединены по высоте блока, включая «Встречи»
    for col in sb.CRM_BLOCK:
        assert (2, 4, col, col + 1) in merges
    # итог дня — сумма по блоку (в объединённой ячейке число только в верхней)
    assert _v(total[sb.Q]) == "=SUM(Q3:Q4)"
    assert _v(total[sb.R]) == "=SUM(R3:R4)"
    assert _v(total[sb.I]) == "=IFERROR(U5/G5)"
    assert _v(total[sb.U]) == "=SUM(U3:U4)"


def test_month_row_sums_meetings(built):
    rows, _, _ = built
    top = rows[0]
    assert _v(top[sb.Q]) == "=Q5"
    assert _v(top[sb.R]) == "=R5"
    assert _v(top[sb.S]) == "=IFERROR(F1/P1)"
    assert _v(top[sb.I]) == "=IFERROR(U1/G1)"


def _code(key_word, **m):
    from metrics import code_key
    return code_key(key_word), {"code_word": key_word, **{k: 0 for k in sb.CRM_METRICS}, **m}


def test_without_code_words_layout_is_one_number_per_day():
    codes = {"2026-09-20": dict([_code("", new_request=12, lead=9, qualified=5)])}
    rows, merges, _ = sb._build(META, CRM, MANUAL, codes)
    assert len(rows) == 5                                  # 2 объявления + итог
    assert _v(rows[2][sb.K]) == 12 and (2, 4, sb.K, sb.K + 1) in merges


def test_code_words_split_crm_by_ad_groups():
    manual = {"111": {"code_word": "ИТАЛИЯ 🔥", "status": "Активно"},
              "222": {"code_word": "США 💚", "status": "Активно"}}
    codes = {"2026-09-20": dict([
        _code("италия  🔥", new_request=5, lead=4, qualified=3, consult_done=2, sale=1),
        _code("США 💚", new_request=4, lead=3, qualified=1),
        _code("КИТАЙ 🔥", new_request=1),                  # кода нет ни у одного объявления
        _code("", new_request=2, lead=1),                  # без кодового слова
    ])}
    rows, merges, _ = sb._build(META, CRM, manual, codes)
    usa, italy, rest, total = rows[2], rows[3], rows[4], rows[5]
    # группы по убыванию расхода: США (222, $30) выше Италии (111, $10)
    assert _v(usa[sb.B]) == "Объявление B" and _v(usa[sb.K]) == 4 and _v(usa[sb.P]) == 1
    assert _v(italy[sb.K]) == 5 and _v(italy[sb.Q]) == 2 and _v(italy[sb.R]) == 1
    assert _v(italy[sb.S]) == "=IFERROR(SUM(F4:F4)/P4)"
    # остаток: без слова + слово без объявлений; цен нет — у строки нет расхода
    assert "без кодового слова" in _v(rest[sb.B]) and "КИТАЙ 🔥" in _v(rest[sb.B])
    assert _v(rest[sb.K]) == 3 and _v(rest[sb.M]) == 1
    assert _v(rest[sb.L]) is None and _v(rest[sb.S]) is None
    # итог дня — сумма всех строк блока: 4 + 5 + 3 = 12 = заявок за день
    assert _v(total[sb.K]) == "=SUM(K3:K5)"
    assert (2, 5, sb.A, sb.A + 1) in merges                # дата на весь блок
    assert (2, 3, sb.K, sb.K + 1) not in merges            # группы по одной строке


def test_ad_without_matching_code_has_no_crm_cells():
    manual = {"111": {"code_word": "ИТАЛИЯ 🔥"}, "222": {"code_word": ""}}
    codes = {"2026-09-20": dict([_code("ИТАЛИЯ 🔥", new_request=5), _code("", new_request=7)])}
    rows, _, _ = sb._build(META, CRM, manual, codes)
    names = [_v(r[sb.B]) for r in rows[2:5]]
    assert names[0] == "Объявление A" and names[1] == "Объявление B"
    assert _v(rows[3][sb.K]) is None                       # у B нет кода — CRM пусто
    assert _v(rows[4][sb.K]) == 7


def test_date_vertical_only_in_tall_blocks():
    assert sb._date_fmt(15)["textRotation"] == {"angle": 90}
    assert sb._date_fmt(15)["textFormat"]["fontSize"] == 32
    short = sb._date_fmt(1)
    assert "textRotation" not in short and short["textFormat"]["fontSize"] == 14
    assert short["numberFormat"] == sb.DATE


def test_rows_have_all_columns(built):
    rows, _, _ = built
    assert all(len(r) == sb.N_COLS for r in rows)


SEPT = "Сквозная аналитика Сентябрь"


class FakeWorksheet:
    def __init__(self, sheet_id, title, values=None):
        self.id, self.title = sheet_id, title
        self.values = values or []
        self.row_count, self.col_count = 200, 21

    def update(self, values, a1, value_input_option=None):
        self.values = [list(r) for r in values]

    def get_all_values(self):
        return self.values

    def append_rows(self, rows, value_input_option=None):
        self.values += [list(r) for r in rows]


class FakeSpreadsheet:
    """
    Таблица в памяти: листы {title: values}, переименование и создание
    листов через batch_update / add_worksheet, как в Google Sheets API.
    """

    def __init__(self, sheets: dict):
        self.sheets = {t: FakeWorksheet(i + 1, t, v) for i, (t, v) in enumerate(sheets.items())}
        self.requests = []

    def fetch_sheet_metadata(self, params=None):
        return {"sheets": [{"properties": {"sheetId": ws.id, "title": t,
                                           "gridProperties": {"rowCount": 200, "columnCount": 26}}}
                           for t, ws in self.sheets.items()]}

    def values_batch_get(self, ranges, params=None):
        out = []
        for r in ranges:
            title, _, a1 = r.partition("!")
            vals = self.sheets[title.strip("'")].values
            if a1 in ("T2", "S2"):
                col = "ABCDEFGHIJKLMNOPQRSTU".index(a1[0])
                v = vals[1][col] if len(vals) > 1 and len(vals[1]) > col else ""
                vals = [[v]] if v else []
            elif a1 == "B3:E":
                vals = [row[1:5] for row in vals[2:]]
            out.append({"values": vals} if vals else {})
        return {"valueRanges": out}

    def worksheet(self, title):
        if title not in self.sheets:
            raise sb.gspread.WorksheetNotFound(title)
        return self.sheets[title]

    def add_worksheet(self, title, rows, cols):
        ws = FakeWorksheet(len(self.sheets) + 100, title)
        self.sheets[title] = ws
        return ws

    def batch_update(self, body):
        for req in body["requests"]:
            self.requests.append(req)
            props = req.get("updateSheetProperties", {}).get("properties", {})
            if "title" in props:
                old = next(t for t, ws in self.sheets.items() if ws.id == props["sheetId"])
                self.sheets[props["title"]] = self.sheets.pop(old)
                self.sheets[props["title"]].title = props["title"]


def _data_sheets(meta_rows, crm_rows):
    from sheets_client import CRM_HEADERS, META_HEADERS
    return {
        "meta_daily": [META_HEADERS] + [[r.get(h, "") for h in META_HEADERS] for r in meta_rows],
        "crm_daily": [CRM_HEADERS] + [[r.get(h, "") for h in CRM_HEADERS] for r in crm_rows],
    }


# ручной лист заказчика: разметка шаблона (B — название, D — код, E — статус)
MANUAL_SHEET = [
    ["В общем"],
    ["Название объявления ", "", "", "Кодовое слово ", "Статус "],
    ["", '"Вовлеченность" РК Бахтияра (Италия)\t', "", "ИТАЛИЯ 💚", "Активно"],
    ["", '"Вовлеченность"  Новостной 2', "", "USA 🔥", "Активно"],
]
AD_ROW = {"date": "2026-09-01", "ad_id": "111", "ad_name": '"Вовлеченность" РК Бахтияра (Италия)',
          "spend": 12.5, "impressions": 1000, "clicks": 10, "ctr": 1.0, "cpm": 12.5,
          "dm_leads": 3, "site_leads": 0}
CRM_ROW = {"date": "2026-09-01", "new_request": 20, "lead": 10, "qualified": 5,
           "consult_scheduled": 4, "consult_done": 2, "sale": 1, "revenue": 0, "note": ""}


def test_manual_sheet_is_set_aside_and_codes_imported():
    ss = FakeSpreadsheet({SEPT: MANUAL_SHEET, "Общая таблица": [["Название "]],
                          **_data_sheets([AD_ROW], [CRM_ROW])})
    info = sb.rebuild_month_sheet(2026, 9, ss)

    assert info["set_aside"] == SEPT + " (вручную)"
    # ручной лист не тронут, только переименован
    assert ss.sheets[SEPT + " (вручную)"].values == MANUAL_SHEET
    assert ss.sheets[SEPT].id != ss.sheets[SEPT + " (вручную)"].id
    # код и статус перенесены в ads_manual (название совпало, несмотря на таб)
    assert ss.sheets["ads_manual"].values[1] == ["111", AD_ROW["ad_name"], "ИТАЛИЯ 💚", "Активно"]
    # и сразу попали на новый лист месяца
    cells = next(r["updateCells"]["rows"] for r in ss.requests
                 if "updateCells" in r and "rows" in r["updateCells"])
    ad_row = [_v(c) for c in cells[2]["values"]]
    assert ad_row[sb.D] == "ИТАЛИЯ 💚" and ad_row[sb.E] == "Активно"
    # в ручной лист ничего не писалось, кроме смены названия
    manual_id = ss.sheets[SEPT + " (вручную)"].id
    touching = [r for r in ss.requests if manual_id in (
        r.get("updateSheetProperties", {}).get("properties", {}).get("sheetId"),
        r.get("updateCells", {}).get("range", {}).get("sheetId"),
        r.get("updateCells", {}).get("start", {}).get("sheetId"))]
    assert len(touching) == 1 and "updateSheetProperties" in touching[0]


def test_generated_sheet_is_rebuilt_in_place():
    ss = FakeSpreadsheet({SEPT: MANUAL_SHEET, **_data_sheets([AD_ROW], [CRM_ROW])})
    sb.rebuild_month_sheet(2026, 9, ss)           # 1-й прогон: ручной отложен
    ss.sheets[SEPT].values = [[], ["" for _ in range(sb.T)] + ["ad_id"]]   # шапка листа скрипта
    info = sb.rebuild_month_sheet(2026, 9, ss)    # 2-й: лист скрипта, пересборка на месте
    assert info["set_aside"] is None
    assert SEPT + " (вручную 2)" not in ss.sheets


def test_existing_ads_manual_rows_are_not_overwritten():
    ss = FakeSpreadsheet({
        SEPT + " (вручную)": MANUAL_SHEET,
        "ads_manual": [["ad_id", "ad_name", "code_word", "status"],
                       ["111", "старое имя", "МОЙ КОД", "Пауза"]],
        **_data_sheets([AD_ROW], [CRM_ROW])})
    sb.rebuild_month_sheet(2026, 9, ss)
    assert ss.sheets["ads_manual"].values[1] == ["111", "старое имя", "МОЙ КОД", "Пауза"]
    assert len(ss.sheets["ads_manual"].values) == 2


def test_reference_check_ignores_renamed_sheet():
    ss = FakeSpreadsheet({"Сводка": [[f"='{SEPT} (вручную)'!F1"]]})
    sb._check_no_references(ss, SEPT, ["Сводка"])      # не ссылка на лист месяца
    ss.sheets["Сводка"].values = [[f"='{SEPT}'!F1"]]
    with pytest.raises(RuntimeError, match="ссылается"):
        sb._check_no_references(ss, SEPT, ["Сводка"])


@pytest.mark.parametrize("marker_col", [sb.T, sb.S])
def test_generated_sheet_is_recognised(marker_col):
    header = [""] * 21
    header[marker_col] = "ad_id"
    assert sb._is_generated(FakeSpreadsheet({SEPT: [[], header]}), SEPT)
    assert not sb._is_generated(FakeSpreadsheet({SEPT: MANUAL_SHEET}), SEPT)
