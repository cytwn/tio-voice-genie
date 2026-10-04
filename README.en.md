# TIO Voice Genie

**English** | [繁體中文](README.md)

A Windows tool that turns meeting speech into text you can edit — live captions, recording → transcript
(with speakers and timestamps), live bilingual captions, bilingual documents, and live voice translation
(interpreter mode). It uses Google's **Gemini API**. Everything is double-click and menu driven; no commands
to type.

This repository contains the same program in two editions. Only the language of the menus, windows and
documents differs; the program logic is identical.

| Edition | Folder | Start here |
|---|---|---|
| English | [`en/TIO_Voice_Genie_LVT`](en/TIO_Voice_Genie_LVT) | [`1_Install_Guide_READ_FIRST.md`](en/TIO_Voice_Genie_LVT/1_Install_Guide_READ_FIRST.md) |
| 繁體中文 (Traditional Chinese) | [`zh-TW/TIO語音精靈_LVT`](zh-TW/TIO語音精靈_LVT) | [`1_安裝說明（先讀這個）.md`](zh-TW/TIO語音精靈_LVT/1_安裝說明（先讀這個）.md) |

Ready-to-use zip files for both editions are on the [Releases page](https://github.com/cytwn/tio-voice-genie/releases).

Website: [introduction](https://tio-voice-genie.vercel.app/en/) · [user guide](https://tio-voice-genie.vercel.app/guide/en/)

## What it does

| # | Feature | In short |
|---|---|---|
| 1 | Live meeting captions | See captions while the meeting runs |
| 2 | Recording to transcript | A recorded file becomes a transcript with speakers and timestamps |
| 3 | Live bilingual captions | Source and translation on screen at the same time (Chinese, English, Japanese) |
| 4 | Transcript to bilingual | Translate a whole transcript at once — much better quality than live |
| 5 | Rebuild a transcript | Redo a transcript from its `.json` or rename speakers, offline and free |
| 6 | Live voice translation | Hear only the interpreter voice, not the original (interpreter mode) |

## Requirements

- Windows 10 or 11 (capturing the PC's own sound uses a Windows-only technology)
- An internet connection
- Your own Gemini API key — see `2_Get_API_Key_and_Billing.md` in the English edition
- Python 3.12 or newer — not needed in advance: the installer installs Python 3.13 if it is missing

## Quick start

1. Download the zip for your edition from the [Releases page](https://github.com/cytwn/tio-voice-genie/releases).
2. **Before unzipping**, right-click the zip → **Properties** → tick **Unblock** → **OK**.
   Otherwise Windows may block the `.bat` files, because the zip came from the internet.
3. Unzip it anywhere (C: drive, D: drive, the desktop — no paths are hard-coded).
4. Follow `1_Install_Guide_READ_FIRST.md`: get an API key, then double-click `3_Install.bat`.
5. Start the tool from the **TIO Voice Genie** shortcut on your desktop (or `4_Start.bat`).

## Privacy and cost

- Meeting audio is sent to Google for recognition. On Gemini's **free tier**, Google's terms allow the content
  to be used to improve its products and to be read by human reviewers. For real meetings (personnel,
  budgets, personal data), turn on the paid tier first — see `2_Get_API_Key_and_Billing.md`.
- The tool itself is free; Google bills your account per use. See the cost table in each edition's
  `README.md`.
- Your API key is stored as a Windows user environment variable (`GEMINI_API_KEY`), never in these files.
  `7_Uninstall.bat` can remove it.

## Questions and bug reports

Open an [issue](https://github.com/cytwn/tio-voice-genie/issues), or email cylab.contact@gmail.com.
Issues are public: before posting a screenshot (for example of `6_Diagnostics.bat`), cover your Windows user name and
folder paths, or send it by email instead.

## Terms of use and disclaimer

This tool is developed independently by CY KUO as an individual and provided free of charge under the MIT License.
It does not represent any institution or organisation. The developer provides this tool under the MIT License without
any warranty. Use it at your own discretion and risk; the developer is not liable for any damages. Before using it,
please read the full terms at the end of
[`1_Install_Guide_READ_FIRST.md`](en/TIO_Voice_Genie_LVT/1_Install_Guide_READ_FIRST.md#terms-of-use-and-disclaimer).

## License

[MIT](LICENSE) © 2026 CY KUO. This project is not affiliated with or endorsed by Google.
Gemini is a trademark of Google LLC.
