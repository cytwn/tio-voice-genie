# TIO語音精靈（TIO Voice Genie）

[English](README.en.md) | **繁體中文**

把會議裡講的話變成可以編輯的文字的 Windows 工具——會議即時字幕、錄音檔轉逐字稿（含講者與時間軸）、即時雙語字幕、雙語對照文件，以及即時語音翻譯（口譯模式）。使用 Google 的 **Gemini API**。全部點兩下、看選單操作，不需要打任何指令。

這個 repo 收錄同一套程式的兩個版本：只有選單、視窗與說明文件的語言不同，程式邏輯完全一樣。

| 版本 | 資料夾 | 從這裡開始 |
|---|---|---|
| 繁體中文 | [`zh-TW/TIO語音精靈_LVT`](zh-TW/TIO語音精靈_LVT) | [`1_安裝說明（先讀這個）.md`](zh-TW/TIO語音精靈_LVT/1_安裝說明（先讀這個）.md) |
| English（英文版） | [`en/TIO_Voice_Genie_LVT`](en/TIO_Voice_Genie_LVT) | [`1_Install_Guide_READ_FIRST.md`](en/TIO_Voice_Genie_LVT/1_Install_Guide_READ_FIRST.md) |

兩個版本的 zip 都放在 [Releases 頁面](https://github.com/cytwn/tio-voice-genie/releases)，下載就能用。

網站：[介紹頁](https://tio-voice-genie.vercel.app/)・[使用說明](https://tio-voice-genie.vercel.app/guide/)

## 六項功能

| # | 功能 | 簡述 |
|---|---|---|
| 1 | 會議即時字幕 | 開會當下就看到字幕 |
| 2 | 錄音檔轉逐字稿 | 已錄好的檔案轉成含講者、時間軸的逐字稿 |
| 3 | 即時雙語字幕 | 同時出原文＋譯文（可翻中英日文） |
| 4 | 逐字稿轉雙語對照 | 整份翻，品質比即時翻好很多 |
| 5 | 逐字稿重新排版 | 從 `.json` 重做／改講者名字，不連網、不花錢 |
| 6 | 即時語音翻譯 | 只聽口譯，不聽原音（口譯模式） |

## 電腦需求

- Windows 10 / 11（「錄電腦播放的聲音」用的是 Windows 專屬技術）
- 網路連線
- 自己申請的 Gemini API 金鑰——做法見中文版的 `2_申請金鑰與儲值（第一次必做）.md`
- Python 3.12 以上——不用先裝：沒有的話安裝程式會自動裝 Python 3.13

## 快速開始

1. 到 [Releases 頁面](https://github.com/cytwn/tio-voice-genie/releases) 下載你要的版本的 zip。
2. **解壓縮之前**，對 zip 按右鍵 →「**內容**」→ 勾「**解除封鎖**」→「確定」。不先做的話，因為 zip 是從網路下載的，Windows 可能會擋下裡面的 `.bat`。
3. 解壓縮到任何位置（C 槽、D 槽、桌面都可以，程式沒有寫死路徑）。
4. 照 `1_安裝說明（先讀這個）.md` 做：先申請金鑰，再點兩下 `3_安裝.bat`。
5. 之後從桌面的「**TIO語音精靈**」捷徑開啟（或點 `4_開始使用.bat`）。

## 隱私與費用

- 會議聲音會送到 Google 辨識。Gemini **免費層**依 Google 條款，內容可能被拿去改進產品、也可能被人工審閱者讀到。真實會議（人事、經費、個資）請先開通付費層——見 `2_申請金鑰與儲值（第一次必做）.md`。
- 工具本身免費；Google 依用量向你的帳號計費。各功能每小時費用見各版本資料夾裡的 `README.md`。
- API 金鑰存在 Windows 使用者環境變數（`GEMINI_API_KEY`），不會寫進這些檔案；`7_解除安裝.bat` 可以把它移除。

## 問題回報與聯絡

到 [Issues](https://github.com/cytwn/tio-voice-genie/issues) 開一則，或寄信到 cylab.contact@gmail.com。Issues 是公開的：貼截圖（例如 `6_診斷.bat` 的畫面）之前，請先把 Windows 使用者名稱和資料夾路徑遮起來，或改用寄信。

## 使用須知與免責聲明

本工具由 CY KUO 個人獨立開發，以 MIT 授權免費提供，不代表任何機構或單位。開發者MIT授權，亦不做任何保證，請自行判斷使用並自行負責，開發者不負賠償責任。使用前請先讀 [`1_安裝說明（先讀這個）.md`](zh-TW/TIO語音精靈_LVT/1_安裝說明（先讀這個）.md#使用須知與免責聲明) 最後一節的完整說明。

## 授權

[MIT](LICENSE) © 2026 CY KUO。本專案與 Google 無關，也未經 Google 背書。Gemini 是 Google LLC 的商標。
