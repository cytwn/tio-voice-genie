# Getting a Gemini API key and topping up

> This is something you **must do before you use the tool for the first time**. It's best to finish it before you run `3_Install.bat` (you can also leave the key field blank during installation; it asks again the first time you use the tool).
> It takes about 10 minutes in all (2 minutes to get the key, 5–8 minutes to set up billing).

---

## What this is, and why you need it

The tool itself charges nothing; it sends the audio to **Google's Gemini** to be recognised.
You need a "key" (an API key) so that Google knows who is using it and whose account the costs go to.

**The key is as good as the password to your Google account**: don't give it to anyone, and don't paste it into a group chat.

---

## Step 1: Get an API key (free, 2 minutes)

1. Open **[aistudio.google.com/apikey](https://aistudio.google.com/apikey)** in your browser
2. Sign in with your Google account
3. The first time, it asks you to accept the terms of service; tick the box and continue
4. Click **"Create API key"**
5. It produces a long string beginning with `AQ.` (new keys) or `AIza` (older keys) → **click copy**

Once you've copied it, run `3_Install.bat`; the Setup Wizard will ask whether you want to paste it in.

> 💡 It's fine if you haven't got a key yet: you can leave that field in the Setup Wizard blank and skip it,
> and the program will ask you again the first time you actually start using it.

### A few things to know

- **Everyone should get their own key, with their own Google account.**
  A key's usage and costs are charged to the account that created it, so sharing one key puts the whole bill on one person.
- Every key is tied to a **Google Cloud project**. The first time, AI Studio creates one for you automatically.
- Quotas **belong to the project, not to the key**. If one project hands out several keys to different people,
  they all share the same quota and crowd each other out.

---

## Step 2: Turn on billing (important, please don't skip this)

### Why you must use the paid tier

The free tier **really doesn't charge you**, but the price you pay instead is written into Google's terms of service:

| | Free tier | Paid tier |
|---|---|---|
| Cost | No charge | You pay for what you use |
| **Is the meeting audio you send used to improve Google's products?** | **Yes** | No |
| **Can human reviewers read your meeting content?** | **Possibly** | No |
| Quota | Google no longer publishes the actual figures | Much higher |

University meetings deal with personnel, budgets, review comments and students' personal data.
**Anything of that kind should not go through the free tier.**

There's also a practical problem: Google **no longer publishes the free tier's actual quotas**
(the official rate-limits page has removed its per-model quota table), so nobody can work out in advance
"whether the free tier will last this meeting", not even the developer of this tool.
Running out of quota halfway through a meeting can't be prevented.

### How to turn it on

1. Open **[aistudio.google.com/apikey](https://aistudio.google.com/apikey)**
2. Find the project your key belongs to; that row shows **Free**
3. Click **"Set up Billing"** on that row
4. Follow the on-screen instructions to create or choose a **Cloud Billing account** (you'll need a credit card)
   - Never set up Google billing before → just follow the wizard step by step to create one
   - Set it up before → it lets you choose one of your existing billing accounts
5. New accounts are **prepaid (Prepay)** by default, and you'll be asked to **top up at least US$5 first**
   before you can finish setting up
6. When you're done, go back to AI Studio: that row will have changed from **Free** to **Paid**

> Google's official wording:
> "Asked to prepay a minimum of $5 to complete billing"
> — [ai.google.dev/gemini-api/docs/billing](https://ai.google.dev/gemini-api/docs/billing)
> (checked 2026-09-08)

---

## Step 3: Understand how prepay works (so your meeting isn't cut off)

New accounts default to **Prepay**: you top up first, usage is deducted as you go, and when the balance runs out, everything stops.

### 🔴 The most important point

> "When your Prepay credit balance on the billing account hits $0, all API keys in
> all projects linked to that billing account will stop working simultaneously."
> — the official billing page

**The moment the balance hits zero, every key under the same billing account stops working at once.**
If that happens halfway through a meeting, the captions simply stop.

### How to avoid it

**① Check the balance is enough before the meeting**

Use this table to work it out (checked against real tests, 2026-09-19; for which model each feature uses, see "How much does it cost?" in `5_User_Guide`):

| Use | Approx. cost per hour | What a US$5 top-up covers |
|---|---|---|
| Recording to transcript | US$0.62 (about NT$20) | about 8 hours |
| Live meeting captions | US$0.54 (about NT$17) | about 9 hours |
| Live bilingual captions · Accurate mode | US$0.57 (about NT$18) | about 9 hours |
| Live bilingual captions · Fast mode | **US$2.21 (about NT$71)** | **about 2.3 hours** |
| Live voice translation | **US$2.21 (about NT$71)** | **about 2.3 hours** |
| Transcript to bilingual (you already have the transcript) | US$0.51 (about NT$16) | about 10 hours of transcript |

**A US$5 top-up (about NT$160) covers roughly 8–10 hours of the features that output text (transcripts, live captions, bilingual captions in Accurate mode, transcript to bilingual),
but only about 2.3 hours of the features that output speech (bilingual captions in Fast mode, live voice translation).**
For ten two-hour meetings a month: budget around US$15 if you only use the text features, or around US$45 if you use voice translation throughout.

**② Turn on automatic top-up (Auto-reload)**

On the Google Cloud billing page you can set "when the balance falls below X, automatically add Y",
and set a **monthly cap on automatic charges**, so that unusual usage can't max out your card.
Then you don't need to check the balance by hand before each meeting. This is the least effort.

**③ Set up a budget alert**

Google Cloud Console → Billing → Budgets & alerts: set a monthly budget,
and you'll get an email when spending passes a threshold.

> ⚠️ Google points out that prepay charges have a **delay of about 10 minutes**,
> so the balance can briefly go slightly over. For long jobs, leave a little extra in the balance.

---

## Step 4 (optional): Check your current quota

Google no longer lists the quota figures for each tier in its public documentation. You can only sign in and check your own:

**[aistudio.google.com/rate-limit](https://aistudio.google.com/rate-limit)**

> Google states: "Specified rate limits are not guaranteed and actual capacity may vary."
> (In other words, the published quotas are not a promise, and what you actually get may differ.)

One more thing people run into in practice:
**the daily quota resets at "midnight US Pacific time", which is about 3–4 pm Taiwan time**
(depending on US daylight saving time), not at midnight in Taiwan.
If you use up the quota in the morning, you have to wait until that afternoon for it to come back.

---

## Frequently asked questions

| Question | Answer |
|---|---|
| What does a key look like? | A string of letters and numbers: new keys begin with `AQ.`, older ones with `AIza` (39 characters). When you paste it into the program, the screen shows a row of `*`; after you press Enter, only the first and last few characters are shown so you can check it |
| I've lost my key. Can I see it again? | Yes: go back to aistudio.google.com/apikey and it's there |
| I accidentally pasted it into a group chat. What now? | Go to AI Studio immediately, create a new key and disable the old one. Then open the TIO menu and choose **9 "API key settings" → 1**, paste the new key, and choose "Yes" when asked "Remember this key so you don't have to paste it next time?" |
| I don't have a credit card | Then you can only use the free tier. **Please don't use it to record meetings involving personal data or confidential matters** |
| Could I be charged a huge amount? | Not with prepay: when the balance runs out it stops. Charges lag by about 10 minutes, though, so the balance can briefly go slightly negative (see the official note above). Prepay is also the default plan |
| I already have a Google Cloud account | AI Studio won't create a project for you automatically; you have to import an existing project yourself, then create the key |
| My work PC says I don't have permission to create a key | That Google Cloud project belongs to an organisation, so an administrator has to give you permission; or use a personal project that doesn't belong to an organisation instead |

---

## All done?

Go back to the folder and double-click **`3_Install.bat`**.

---

*The official information in this document was checked on 2026-09-08. Sources:*
*[ai.google.dev/gemini-api/docs/billing](https://ai.google.dev/gemini-api/docs/billing),*
*[ai.google.dev/gemini-api/docs/api-key](https://ai.google.dev/gemini-api/docs/api-key),*
*[ai.google.dev/gemini-api/docs/rate-limits](https://ai.google.dev/gemini-api/docs/rate-limits).*
*Google adjusts its interface and plans from time to time. If what you see doesn't match this document, follow the instructions actually shown on the website.*
