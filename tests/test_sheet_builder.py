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
    assert _v(first[sb.S]) == "=IFERROR(F5/P3)"
    # код и статус из ads_manual
    assert _v(second[sb.D]) == "ИТАЛИЯ 🔥"
    # CTR: 0.5% из Meta → 0.005 на листе
    assert _v(first[sb.I]) == pytest.approx(0.005)
    # CRM-колонки объединены по высоте блока, включая «Встречи»
    for col in sb.CRM_BLOCK:
        assert (2, 4, col, col + 1) in merges
    # итог дня
    assert _v(total[sb.Q]) == "=Q3"
    assert _v(total[sb.R]) == "=R3"
    assert _v(total[sb.I]) == "=IFERROR(U5/G5)"
    assert _v(total[sb.U]) == "=SUM(U3:U4)"


def test_month_row_sums_meetings(built):
    rows, _, _ = built
    top = rows[0]
    assert _v(top[sb.Q]) == "=Q5"
    assert _v(top[sb.R]) == "=R5"
    assert _v(top[sb.S]) == "=IFERROR(F1/P1)"
    assert _v(top[sb.I]) == "=IFERROR(U1/G1)"


def test_rows_have_all_columns(built):
    rows, _, _ = built
    assert all(len(r) == sb.N_COLS for r in rows)


class FakeSpreadsheet:
    def __init__(self, marker_values, existing=True):
        self.marker_values = marker_values
        self.existing = existing
        self.batch_update_called = False

    def fetch_sheet_metadata(self, params=None):
        sheets = []
        if self.existing:
            sheets.append({"properties": {"sheetId": 1, "title": "Сквозная аналитика Сентябрь",
                                          "gridProperties": {"rowCount": 100, "columnCount": 26}}})
        return {"sheets": sheets}

    def values_batch_get(self, ranges, params=None):
        return {"valueRanges": [{"values": [[self.marker_values.get(r.split("!")[1], "")]]}
                                if self.marker_values.get(r.split("!")[1]) else {}
                                for r in ranges]}

    def batch_update(self, body):
        self.batch_update_called = True


def test_refuses_to_overwrite_manual_sheet():
    ss = FakeSpreadsheet({})
    with pytest.raises(RuntimeError, match="заполнен вручную"):
        sb.rebuild_month_sheet(2026, 9, ss)
    assert not ss.batch_update_called


@pytest.mark.parametrize("marker", ["T2", "S2"])
def test_generated_sheet_is_recognised(marker):
    sb._check_generated(FakeSpreadsheet({marker: "ad_id"}), "Сквозная аналитика Сентябрь")
