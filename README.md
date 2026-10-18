# 🛡️ ProofBeforePay

**Know what you're buying *before* you pay.**

ProofBeforePay is an AI agent that protects online shoppers in Bangladesh from Facebook page and F-commerce scams. It scans product posts, checks sellers against a community database, and compares the ad photo with what you actually received — in **English and বাংলা**.

Built at **Hacktoberfest Dhaka 2026** with **Gemma 4** (Google AI Studio) and **Firebase**.

---

## 🚨 The problem

Buying from Facebook pages is part of everyday life in Bangladesh, and so are the scams:

- Sellers ask for **advance payment on bKash/Nagad**, then block the buyer.
- The product that arrives looks **nothing like the photo**.
- Warnings about bad sellers are scattered across Facebook groups, so the next buyer never sees them.

Buyers have no quick way to check a seller **before** they send money.

## ✅ The solution

ProofBeforePay gives buyers proof before they pay, using Gemma for every AI step:

| Feature | What it does |
|---|---|
| 💬 **Ask the agent** | Chat in English, Bangla or Banglish. The Gemma agent decides which tools to use and answers with a verdict. |
| 📸 **Scan a post** | Upload a screenshot of a product post. Gemma vision reads the price, seller and payment terms, finds red flags, and checks the seller in the database. |
| 🔎 **Check a seller** | Enter a phone, bKash/Nagad number or page name. See community reports and a risk verdict. |
| 🚩 **Report a seller** | Share your experience (scam / suspicious / genuine) so other buyers are warned. |
| ⚖️ **Ad vs received** | Upload the ad photo and the product you received. Gemma compares them and auto-reports the seller if they don't match. |

Every result comes as a clear verdict: **✅ LOOKS SAFE / ⚠️ BE CAREFUL / 🚨 HIGH RISK**, with the reasons and what to do next.

## 🤖 How Gemma is used

All AI in this project runs on **Gemma 4** (`gemma-4-26b-a4b-it`) through Google AI Studio:

- **Vision:** reads product post screenshots and compares two product photos
- **Agent / function calling:** decides when to call `check_seller`, `report_seller` and `list_flagged_sellers`
- **Bilingual replies:** answers in English or proper Bangla script
- **Reasoning:** spots scam patterns such as advance-only payment, prices far below market and pressure tactics

Because Gemma is an open-weight model, the same app can run on local or on-premise servers, or offline with a smaller Gemma model such as E4B.

## 🏗️ Architecture

```
User (Gradio web UI)
      │  text / screenshots / photos
      ▼
Gemma 4 agent (Google AI Studio API)
      │  function calls
      ▼
Tools: check_seller · report_seller · list_flagged_sellers
      │
      ▼
Firebase Firestore  →  community seller_reports database
```

## 🧰 Tech stack

- **AI model:** Gemma 4 via Google AI Studio (`google-genai` SDK)
- **Database:** Firebase Cloud Firestore (`firebase-admin`)
- **Frontend:** Gradio
- **Language:** Python

## 🗄️ Database schema

Collection: `seller_reports`

| Field | Type | Example |
|---|---|---|
| `seller_key` | string | `01712345678` (normalized phone or page name) |
| `seller_raw` | string | `01712-345678` |
| `verdict` | string | `scam` / `suspicious` / `genuine` |
| `issue` | string | `Took advance, never delivered` |
| `product` | string | `iPhone cover` |
| `created_at` | timestamp | server time |

On first run the app adds a few demo reports so the features can be tried right away.

## 🚀 Run it locally

**1. Clone and install**
```bash
git clone https://github.com/Zinain-AE/proofbeforepay.git
cd proofbeforepay
pip install -r requirements.txt
```

**2. Get a Gemma API key**
Go to [Google AI Studio](https://aistudio.google.com), click **Get API key**, and create one.

**3. Set up Firebase**
- Create a project in the [Firebase console](https://console.firebase.google.com)
- Go to **Build → Firestore Database → Create database**
- Go to **Project settings → Service accounts → Generate new private key**
- Save the downloaded file as `serviceAccount.json` in the project folder

**4. Create a `.env` file** (see `.env.example`)
```
GEMINI_API_KEY=your_api_key_here
GEMMA_MODEL=gemma-4-26b-a4b-it
```

**5. Run**
```bash
python app.py
```
Open the local link, or the public `gradio.live` link printed in the terminal.

> ⚠️ Never commit `.env` or `serviceAccount.json`. Both are listed in `.gitignore`.

## 🧪 Try these

- `I want to buy an iPhone cover from seller 01712345678. They want 1500 tk advance on bKash. Is it safe?`
- `Dhaka Fashion Hub থেকে পাঞ্জাবি অর্ডার দিতে চাই, বিশ্বাস করা যায়?`
- `Which sellers should I avoid?`

## 🔮 Future plans

- Messenger / WhatsApp bot so buyers can check sellers without opening a website
- Offline mobile version with Gemma E4B
- Seller trust score shared with delivery companies and e-commerce platforms
- Report dashboard for consumer rights authorities

## ⚠️ Disclaimer

ProofBeforePay gives a risk estimate based on red flags and community reports. It is not a guarantee. Always prefer cash on delivery and check the parcel before paying.

## 👥 Team

- Zinain Afrin — Daffodil International University

## 📄 License

[MIT](LICENSE)
