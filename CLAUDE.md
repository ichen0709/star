# CLAUDE.md

## 這是什麼
單價比價員：一個 Discord agent，收標價牌或商品的照片，換算單價，並和同一個人的歷史同類商品比較。

## 開始工作前
先讀 `docs/architecture.md` 和 `docs/requirements.md`，照裡面的決定做。

## 防護
`docs/architecture.md` 的防護 1～4，在程式裡各自用「開始／結束」註解標起來，例如：

```python
# === 防護 1 開始：暫存資料夾 ===
...
# === 防護 1 結束 ===
```

一開始四段全部開啟。

## 不可以 commit
- `.env`（`.env.example` 可以，只放名稱、不放值）
- `data/`（DATA_DIR）裡的照片、`records.xlsx`、`state.json`

## 金鑰
- 不要要求我貼 `DISCORD_TOKEN`
- 不要把任何 token 或金鑰寫進任何檔案
