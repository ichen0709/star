# Discord Bot 設定步驟

這份教你在 Discord Developer Portal 建一個 bot、打開必要的開關、拿到 token，並用最小權限把它邀進你自己的 Server。電腦是 Windows。

先做完 `docs/discord-server-setup.md`（要有 Server 和 `#比價` 頻道）。

Discord 常改版，畫面上的字可能和這裡有一點出入，我在括號裡附了英文名稱。

---

## ⚠️ 先看這個：bot token 是密碼

bot token 是這個 bot 的密碼。誰拿到，誰就能用你的 bot 做任何事。

- **不能貼給任何人**（朋友、同學、Scorer、客服都不行）
- **不能貼進這個對話**（包括跟 Claude 的對話，我也不會跟你要）
- **不能截圖**（畫面上有 token 的時候不要截圖、不要錄影、不要分享螢幕）
- **不能 commit** 進 git（`.env` 已經被 `.gitignore` 擋住，但不要自己去改 `.gitignore`）
- 只放在你電腦上的 `.env` 檔裡

**萬一洩漏**（貼錯地方、截到圖、不小心 commit 了）：馬上到 Developer Portal → 你的 application → **Bot** → 按 **Reset Token**。舊的 token 立刻失效，再把新的填回 `.env`。不要等，不要想「應該沒人看到」。

---

## 1. 建立 application 和 bot

1. 用瀏覽器打開 <https://discord.com/developers/applications>。用你的 Discord 帳號登入。
2. 點右上角的 **New Application**（新增應用程式）。
3. 「Name」填 `單價比價員`（之後還可以改）。
4. 勾選同意條款，點 **Create**（建立）。
5. 你會進到這個 application 的頁面。左邊有一排選單：General Information、Installation、OAuth2、Bot 等。
6. 點左邊的 **Bot**。（現在建立的 application 通常會自動有一個 bot，不用另外按「Add Bot」。）

## 2. 打開 Message Content Intent（一定要）

在 **Bot** 這一頁：

1. 往下捲到 **Privileged Gateway Intents**（特權 Gateway Intent）。
2. 找到 **Message Content Intent**，把它的開關**打開**（變成藍色／綠色）。
3. 其他兩個（Presence Intent、Server Members Intent）**不要開**，這個 agent 用不到。
4. 頁面最下面會跳出一個「有未儲存的變更」的條，按 **Save Changes**（儲存）。

**為什麼一定要開：** Discord 預設不讓 bot 看到別人訊息的內容，包括文字和附加的照片。沒打開的話，bot 看到的訊息幾乎是空的：看不到照片、看不到「週報」、看不到你回覆的修正文字，所以整個 agent 都不會動。因為 bot 只在少數幾個 Server（100 個以下），這個開關自己打開就好，不需要送審。

## 3. 拿到 bot token

在同一頁（**Bot**）：

1. 找到 **Token** 這一區。
2. 按 **Reset Token**（重設 Token）。（第一次建的時候沒有「複製」，要按這個才會產生。）
3. 如果跳出確認視窗，按 **Yes, do it!**，可能還會要你輸入 Discord 密碼或兩步驟驗證碼。
4. 畫面上會出現一長串字，這就是 token。按旁邊的 **Copy**（複製）。
5. **這串字只會顯示這一次**。關掉頁面就看不到了，只能再 Reset 一次拿新的。

### 把 token 填進 .env（不要貼到別處）

1. 在 Windows 檔案總管打開這個專案資料夾 `C:\Users\PC02\star`。
2. 找到 `.env` 這個檔案。（它以點開頭，如果看不到：檔案總管上方 **檢視** → **顯示** → 勾 **隱藏的項目**。）
3. 對 `.env` 按右鍵 → **開啟檔案** → 選**記事本**。
4. 找到 `DISCORD_TOKEN=` 這一行，在等號後面按 **Ctrl + V** 貼上。等號和 token 之間**不要有空格，不要加引號**。
   例如：`DISCORD_TOKEN=貼上的那串字`
5. 按 **Ctrl + S** 存檔，關掉記事本。
6. 回到 Developer Portal 的頁面，**不要截圖**。要離開就直接關。

> 這個專案已設定 Claude 不能讀取 `.env`，所以填完以後它也不會看到你的 token。你也不用把 token 傳給它。

## 4. 這個 agent 需要的最小權限

只給這四個，不要給管理員（Administrator）：

| 權限（中文 / English） | 為什麼需要 |
|---|---|
| 檢視頻道（View Channels） | 才看得到 `#比價` |
| 傳送訊息（Send Messages） | 才能回「處理中」和結果 |
| 讀取訊息歷史（Read Message History） | 才能讀到使用者傳的照片，以及你回覆的是哪一則 bot 訊息（修正要用） |
| 嵌入連結（Embed Links） | **不需要，不要選** |
| 附加檔案（Attach Files） | **不需要，不要選**。使用者傳照片給 bot 讀，這個權限是 bot 自己要傳檔案才用 |

所以實際只勾前三個：**View Channels、Send Messages、Read Message History**。

回覆要 @ 人（週報）不需要額外權限，因為 @ 一個人只是訊息裡的一個標註；不要勾「提及 @everyone、@here 和所有身分組」（Mention Everyone）。

## 5. 把 bot 邀進你自己的 Server

1. 在 Developer Portal 左邊點 **OAuth2**。
2. 往下找到 **OAuth2 URL Generator**（OAuth2 網址產生器）。
3. 在 **Scopes**（範圍）打勾 **bot**。（只勾 bot，不要勾別的。）
4. 勾了 bot 之後，下面會出現 **Bot Permissions**（Bot 權限）。勾：
   - **View Channels**
   - **Send Messages**
   - **Read Message History**
   - 其他全部不要勾，尤其是 **Administrator**。
5. 頁面最下面有 **Generated URL**（產生的網址）。按旁邊的 **Copy**。這個網址不是機密，只是邀請 bot 用的。
6. 把網址貼到瀏覽器網址列，按 Enter。
7. 「新增至伺服器」的下拉選單，選你剛建的 Server（要有「管理伺服器」權限才看得到，你是建立者所以有）。按 **繼續**（Continue）。
8. 確認畫面上列的權限只有你勾的那三個，按 **授權**（Authorize）。可能會要你勾「我不是機器人」。

做完後，你的 Server 成員清單裡會多一個 bot，狀態是離線（因為程式還沒跑）。

## 6. 讓 bot 不被別人拉走（選用，建議做）

1. 還是在 Developer Portal，左邊點 **Bot**。
2. 找到 **Public Bot**（公開 Bot），把它**關掉**。這樣只有你自己能把這個 bot 邀進別的 Server。
3. 按 **Save Changes**。

## 7. 確認 bot 看得到 `#比價`

如果你的 `#比價` 是照 `docs/discord-server-setup.md` 建的（沒有開私人頻道），bot 預設看得到。要檢查：

1. 對 `#比價` 按右鍵 → **編輯頻道**。
2. 左邊點 **權限**（Permissions）。
3. 如果有看到「私人頻道」是開的，要把 bot 的身分組加進去並允許上面三個權限。沒開的話就不用處理。

## 完成時你應該有

- 一個叫「單價比價員」的 application，裡面有 bot
- Message Content Intent 已打開並儲存
- token 已填進 `.env` 的 `DISCORD_TOKEN=`（沒有貼到其他任何地方）
- bot 已在你的 Server 裡，只有 View Channels、Send Messages、Read Message History 三個權限
- Public Bot 已關閉
