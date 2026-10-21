import pytest
from openpyxl import Workbook, load_workbook

from unit_price_agent.store import set_text_cell

DANGEROUS = ["=1+1", "+1", "-1", "@SUM(A1)", "\t=1+1", "\n=1+1", "\r=1", "=HYPERLINK(\"http://x\")"]


@pytest.mark.parametrize("text", DANGEROUS + ["普通文字"])
def test_text_cells_stay_plain_text_after_save_and_reload(tmp_path, text):
    wb = Workbook()
    set_text_cell(wb.active, 1, 1, text)
    path = tmp_path / "t.xlsx"
    wb.save(path)
    cell = load_workbook(path).active.cell(row=1, column=1)
    assert cell.data_type == "s"
    # XML 會把 \r 讀成 \n，這是檔案格式的特性，不影響它還是純文字
    assert cell.value == text.replace("\r", "\n")


def test_text_cell_uses_text_number_format():
    cell = set_text_cell(Workbook().active, 1, 1, "=1+1")
    assert cell.number_format == "@" and cell.data_type == "s"


def test_illegal_control_characters_do_not_crash():
    cell = set_text_cell(Workbook().active, 1, 1, "品名\x00\x07")
    assert cell.value == "品名"
