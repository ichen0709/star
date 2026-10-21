"""Excel 與照片資料夾的讀寫。

階段 1 先放防護 4（寫進 Excel 的文字一律當純文字）；紀錄的讀寫在階段 3 加。
"""

from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE, Cell
from openpyxl.worksheet.worksheet import Worksheet


# ==== 防護 4：Excel 文字欄位一律存成純文字　開始 ====
def set_text_cell(ws: Worksheet, row: int, column: int, text: str) -> Cell:
    """把文字寫進儲存格，並明確設成「純文字」。

    Excel 會把以 = + - @ 開頭（或開頭是 Tab、換行）的文字當成公式。這裡不靠補撇號，
    而是把儲存格的資料型別設成文字（'s'）、格式設成文字（'@'），內容原樣保留。
    所有文字欄位（品名、品牌、店家、類別、上傳者顯示名稱、照片位置）都要走這個函式。
    """
    text = ILLEGAL_CHARACTERS_RE.sub("", str(text))  # openpyxl 不收的控制字元
    cell = ws.cell(row=row, column=column)
    cell.value = text  # openpyxl 這時可能把 '=' 開頭的字串判成公式
    cell.data_type = "s"  # 明確改回文字
    cell.number_format = "@"
    return cell
# ==== 防護 4 結束 ====
