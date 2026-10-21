# 單價比價員

Discord agent：指定頻道裡的人傳標價牌或商品照片，它辨識品名、價格、容量，換算成每 100g／100ml／個的單價，並和同一個人的歷史同類商品比較。

設計見 `docs/architecture.md`，需求見 `docs/requirements.md`。

> 目前進度：**階段 2（連 Discord、看圖、換算單價）**。bot 會回辨識結果和單價，但**還不存檔，也還不會和歷史比較**（階段 3、4 才加）。

## 安裝

需要 Python 3.12 和 [uv](https://docs.astral.sh/uv/)，另外要裝好 Claude Code（指令 `claude` 要能在終端機執行，而且已經登入）。

在這個資料夾（repo 根目錄）執行：

```
uv sync
```

## 設定 .env

1. `.env.example` 列出所有設定的名稱。專案裡已經有一份 `.env`（不會進版本控制）。
2. 用記事本打開 `.env`，填值：
   - `DISCORD_TOKEN`、`CHANNEL_ID`：必填。怎麼拿見 `docs/discord-bot-setup.md`、`docs/discord-server-setup.md`
   - `CLAUDE_MODEL`、`DATA_DIR`：已經填好（`haiku`、`./data`）
   - 其他留空就用預設值（每人每小時 30 張、白話 60 次、`claude` 逾時 90 秒、圖片 10MB、週報 `SUN 20:00`）
3. **`DISCORD_TOKEN` 是密碼，不能貼給任何人、不能貼進對話、不能截圖、不能 commit。** 洩漏了就到 Developer Portal → Bot → Reset Token。

程式不會把 token 或任何設定的值印出來；缺設定時只會說缺哪個名稱。

## 啟動、停止

在 repo 根目錄：

```
uv run python -m unit_price_agent
```

- 看到 `已連線，開始監聽指定頻道` 就表示 bot 上線了。這個終端機視窗要一直開著。
- **停止**：在那個終端機按 **Ctrl + C**，會看到「已停止。」bot 關掉就不處理任何訊息。
- 設定缺了、token 不對、沒打開 Message Content Intent、找不到頻道時，會印出清楚的中文說明然後結束。訊息裡不會有 token 或任何設定的值。

## 測試

### 單元測試（不需要 Discord，也不需要 claude）

```
uv run pytest
```

### 自我檢查（不連 Discord）

```
uv run python -m unit_price_agent.selfcheck
```

不呼叫 claude，檢查防護 1、3、4。想連 claude 一起測：

```
uv run python -m unit_price_agent.selfcheck --live 圖片路徑.png
uv run python -m unit_price_agent.selfcheck --pipeline 圖片路徑.png
uv run python -m unit_price_agent.selfcheck --timeout-test
```

- `--live`：真的呼叫 `claude -p` 三次（看圖、「忽略以上指示」、讀不到資料夾外的檔案）。
- `--pipeline`：跑一遍「辨識 → 驗證 → 換算單價 → 回覆範本」，印出 bot 會回的字，不經過 Discord。
- 這些會用掉一點 Claude 額度（haiku，很少）。

## 四段防護在哪裡

每一段程式裡都用註解標出「開始／結束」，一開始全部開著：

| 防護 | 檔案 | 大約行數 | 內容 |
|---|---|---|---|
| 防護 1：暫存資料夾與工具權限限制 | `src/unit_price_agent/claude_client.py` | 31～103 | 每次處理建全新的系統暫存資料夾、`claude -p` 在裡面跑、只給 Read（或完全不給工具）、處理完刪掉 |
| 防護 2：使用者打的字、照片上的字只當資料 | `src/unit_price_agent/claude_client.py` | 106～185 | 隨機標記包住使用者的字、提示裡明講只是資料、只收固定格式 JSON |
| 防護 2（續）：模型給的文字清洗（說明、品名、品牌、店家） | `src/unit_price_agent/validate.py` | 151～189 | 同一個函式 `clean_model_text`：去掉換行、提及（`<@…>`、`@everyone`）、網址、Markdown 符號，合併空白。品名、品牌、店家限 60 字；說明限 80 字並去掉結尾標點。品名清完是空的就當辨識失敗，品牌或店家清完是空的就當沒有；類別不走這裡，照類別規則 |
| 防護 3：檔名與路徑清洗 | `src/unit_price_agent/validate.py` | 36～77 | 去掉路徑符號、`..`、控制字元、Windows 保留字，限制長度，確認路徑在 `photos/` 底下 |
| 防護 4：Excel 文字欄位一律存成純文字 | `src/unit_price_agent/store.py` | 14～28 | 儲存格明確設成文字型別，不靠補撇號 |

行數會隨修改而變，以搜尋 `==== 防護` 為準。

## 資料夾

```
src/unit_price_agent/   程式
tests/                  單元測試
docs/                   需求、架構、Discord 設定步驟
data/                   執行時產生，不進版本控制
```
