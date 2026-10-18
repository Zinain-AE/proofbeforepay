"""
ProofBeforePay — Know what you're buying before you pay.
Gemma 4 (AI Studio API) agent + Firebase Firestore + Gradio.
"""
import os
import json
import mimetypes
from dotenv import load_dotenv
from google import genai
from google.genai import types
import firebase_admin
from firebase_admin import credentials, firestore
import gradio as gr

load_dotenv()
MODEL = os.getenv("GEMMA_MODEL", "gemma-4-26b-a4b-it")
COLLECTION = "seller_reports"

# ---------- Firebase ----------
if os.getenv("FIREBASE_JSON"):
    cred = credentials.Certificate(json.loads(os.getenv("FIREBASE_JSON")))
else:
    cred = credentials.Certificate(os.getenv("FIREBASE_KEY", "serviceAccount.json"))
firebase_admin.initialize_app(cred)
db = firestore.client()

# ---------- Gemma ----------
client = genai.Client()
TOOL_LOG = []


def _key(seller_id: str) -> str:
    """Normalize phone numbers / page names so the same seller always matches."""
    s = seller_id.strip().lower()
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) >= 10:            # phone number
        return digits[-11:]
    return " ".join(s.split())       # page name


# ---------- TOOLS ----------
def check_seller(seller_id: str) -> dict:
    """Look up community reports about a seller before the user pays.

    Args:
        seller_id: Seller's phone number, Facebook page name, or bKash/Nagad number.
    """
    k = _key(seller_id)
    TOOL_LOG.append(f"check_seller({k})")
    docs = [d.to_dict() for d in db.collection(COLLECTION).where("seller_key", "==", k).stream()]
    counts = {"scam": 0, "suspicious": 0, "genuine": 0}
    for d in docs:
        counts[d.get("verdict", "suspicious")] = counts.get(d.get("verdict", "suspicious"), 0) + 1
    return {
        "seller": k,
        "total_reports": len(docs),
        "counts": counts,
        "recent_issues": [d.get("issue", "") for d in docs[-5:]],
    }


def report_seller(seller_id: str, verdict: str, issue: str, product: str) -> dict:
    """Save a community report about a seller after a purchase or a suspicious post.

    Args:
        seller_id: Seller's phone number, Facebook page name, or bKash/Nagad number.
        verdict: One of: scam, suspicious, genuine.
        issue: Short description of what happened.
        product: What was being sold.
    """
    k = _key(seller_id)
    verdict = verdict.lower().strip()
    if verdict not in ("scam", "suspicious", "genuine"):
        verdict = "suspicious"
    TOOL_LOG.append(f"report_seller({k}, {verdict})")
    db.collection(COLLECTION).add({
        "seller_key": k,
        "seller_raw": seller_id,
        "verdict": verdict,
        "issue": issue,
        "product": product,
        "created_at": firestore.SERVER_TIMESTAMP,
    })
    return {"status": "saved", "seller": k, "verdict": verdict}


def list_flagged_sellers(limit: int = 10) -> list:
    """List the sellers with the most scam or suspicious reports.

    Args:
        limit: How many sellers to return.
    """
    TOOL_LOG.append("list_flagged_sellers()")
    tally = {}
    for d in db.collection(COLLECTION).stream():
        x = d.to_dict()
        if x.get("verdict") in ("scam", "suspicious"):
            t = tally.setdefault(x["seller_key"], {"seller": x.get("seller_raw", x["seller_key"]), "bad_reports": 0})
            t["bad_reports"] += 1
    return sorted(tally.values(), key=lambda t: -t["bad_reports"])[:limit]


TOOLS = [check_seller, report_seller, list_flagged_sellers]

SYSTEM = """You are ProofBeforePay, an AI agent that protects online shoppers in Bangladesh
(Facebook pages, F-commerce, Marketplace) from scams BEFORE they pay.

When the user shares a product post, screenshot, chat, or seller details:
1. Extract: product, price, seller name / page / phone / bKash number, payment terms.
2. ALWAYS call check_seller for any phone number or page name you find.
3. Look for red flags: price far below market, advance payment only (no cash on delivery),
   stock or AI-looking photos, no address, comments turned off, pressure ("only 2 left", "offer ends today"),
   new page, payment to personal bKash/Nagad.
4. Give a verdict card:
   VERDICT: ✅ LOOKS SAFE / ⚠️ BE CAREFUL / 🚨 HIGH RISK
   Red flags: (bullet list)
   Community reports: (from check_seller)
   What to do: (e.g. ask for cash on delivery, open the parcel in front of the rider, don't send advance)

When the user sends TWO images (the ad photo and what they actually received), compare them in detail
(colour, material, logo, size, quality) and say clearly whether they match.

When the user describes a bad or good experience with a seller, call report_seller.
When asked which sellers to avoid, call list_flagged_sellers.

Never claim certainty: base the verdict on the red flags and community reports.
LANGUAGE RULE: Always follow the reply-language note at the end of the user's message.
If there is no note, reply in English. Never reply in Banglish. Keep it short and clear."""


# ---------- Agent ----------
def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    if isinstance(content, dict):
        return content.get("text", "")
    return ""


def chat(message, history):
    TOOL_LOG.clear()
    contents = []
    for m in history:
        t = _text_of(m.get("content"))
        if t:
            role = "user" if m["role"] == "user" else "model"
            contents.append(types.Content(role=role, parts=[types.Part(text=t)]))

    text = message.get("text", "") if isinstance(message, dict) else str(message)
    files = message.get("files", []) if isinstance(message, dict) else []
    parts = []
    for f in files:
        path = f if isinstance(f, str) else f.get("path")
        mime = mimetypes.guess_type(path)[0] or "image/jpeg"
        with open(path, "rb") as fh:
            parts.append(types.Part.from_bytes(data=fh.read(), mime_type=mime))
    # Language: Bangla script in the message → reply in Bangla, otherwise English
    is_bn = any("ঀ" <= ch <= "৿" for ch in text)
    rule = "(Reply in proper Bangla script (বাংলা).)" if is_bn else "(Reply in English only.)"
    parts.append(types.Part(text=(text or "Check this product post for scam risk.") + "\n\n" + rule))
    contents.append(types.Content(role="user", parts=parts))

    resp = client.models.generate_content(
        model=MODEL,
        contents=contents,
        config=types.GenerateContentConfig(system_instruction=SYSTEM, tools=TOOLS),
    )
    reply = resp.text or "(no reply)"
    if TOOL_LOG:
        reply += "\n\n🔧 _Agent used: " + ", ".join(TOOL_LOG) + "_"
    return reply


# ---------- Demo seed data (runs once if DB is empty) ----------
def seed():
    if next(db.collection(COLLECTION).limit(1).stream(), None):
        return
    demo = [
        ("01712345678", "scam", "Took 1500 tk advance on bKash, never delivered, blocked me", "iPhone cover"),
        ("01712345678", "scam", "Same number, fake shoe page, no delivery", "Nike shoes"),
        ("01712345678", "suspicious", "Asked full advance, price too cheap", "Smart watch"),
        ("Dhaka Fashion Hub", "genuine", "Cash on delivery, product matched photo", "Panjabi"),
        ("Dhaka Fashion Hub", "genuine", "Good quality, on time", "Kurti"),
        ("Gadget Bazar BD", "suspicious", "Received product very different from photo", "Earbuds"),
    ]
    for s, v, i, p in demo:
        report_seller(s, v, i, p)
    TOOL_LOG.clear()


seed()

# ---------- UI ----------
CSS = """
.gradio-container {max-width: 1100px !important; margin: auto;}
#hero {
  background: linear-gradient(135deg, #064e3b 0%, #0f766e 55%, #0e7490 100%);
  border-radius: 20px; padding: 28px 32px; color: #fff; margin-bottom: 8px;
}
#hero h1 {font-size: 34px; margin: 0 0 6px 0; color: #fff;}
#hero .tag {font-size: 17px; opacity: .95; margin: 0;}
#hero .bn {font-size: 15px; opacity: .8; margin-top: 4px;}
#hero .chips {margin-top: 16px; display: flex; gap: 8px; flex-wrap: wrap;}
#hero .chip {background: rgba(255,255,255,.15); border: 1px solid rgba(255,255,255,.25);
  padding: 5px 12px; border-radius: 999px; font-size: 13px;}
.cards {display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 6px 0 4px;}
.card {border: 1px solid rgba(127,127,127,.25); border-radius: 14px; padding: 14px 16px;}
.card b {display: block; font-size: 15px; margin-bottom: 4px;}
.card span {font-size: 13px; opacity: .75;}
@media (max-width: 700px) {.cards {grid-template-columns: 1fr;} #hero h1 {font-size: 26px;}}
#foot {text-align: center; font-size: 12px; opacity: .6; margin-top: 6px;}
"""

HERO = """
<div id="hero">
  <h1>🛡️ ProofBeforePay</h1>
  <p class="tag">Know what you're buying <b>before</b> you pay.</p>
  <p class="bn">টাকা দেওয়ার আগে জেনে নিন — সেলার আসল নাকি প্রতারক।</p>
  <div class="chips">
    <span class="chip">🤖 Gemma 4 Agent</span>
    <span class="chip">👁️ Gemma Vision</span>
    <span class="chip">🔥 Firebase Community DB</span>
    <span class="chip">🇧🇩 English + বাংলা</span>
  </div>
</div>
"""


# ---------- Feature tab handlers ----------
def _img_part(path, max_px=1024):
    """Shrink big phone photos to a small JPEG so Gemma gets them fast and within limits."""
    try:
        from PIL import Image
        import io
        img = Image.open(path).convert("RGB")
        img.thumbnail((max_px, max_px))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg")
    except Exception:
        mime = mimetypes.guess_type(path)[0] or "image/jpeg"
        with open(path, "rb") as fh:
            return types.Part.from_bytes(data=fh.read(), mime_type=mime)


def _lang_rule(lang):
    return "Reply in proper Bangla script (বাংলা)." if lang == "বাংলা" else "Reply in clear English."


def _run(parts):
    TOOL_LOG.clear()
    try:
        resp = client.models.generate_content(
            model=MODEL,
            contents=[types.Content(role="user", parts=parts)],
            config=types.GenerateContentConfig(system_instruction=SYSTEM, tools=TOOLS),
        )
        out = resp.text or "(Gemma returned an empty reply — please try again.)"
    except Exception as e:
        print("GEMMA ERROR:", repr(e))
        return f"❌ **Error:** `{e}`\n\nTry again, or use smaller images."
    if TOOL_LOG:
        out += "\n\n🔧 _Agent used: " + ", ".join(TOOL_LOG) + "_"
    return out


def scan_post(image, note, lang):
    if not image:
        return "⚠️ Please upload a screenshot of the product post first."
    prompt = ("Scan this Facebook / online product post for scam risk. Extract the seller details and "
              "check them in the community database. Give the verdict card. "
              f"Extra info from user: {note or 'none'}. {_lang_rule(lang)}")
    return _run([_img_part(image), types.Part(text=prompt)])


def check_seller_ui(seller, deal, lang):
    if not seller or not seller.strip():
        return "⚠️ Enter a phone number, bKash/Nagad number, or Facebook page name."
    prompt = (f"Check this seller before I pay: {seller}. Deal details: {deal or 'not given'}. "
              f"Use check_seller and give the verdict card. {_lang_rule(lang)}")
    return _run([types.Part(text=prompt)])


def report_ui(seller, verdict, product, issue):
    if not seller or not seller.strip():
        return "⚠️ Enter the seller's number or page name."
    r = report_seller(seller, verdict, issue or "-", product or "-")
    TOOL_LOG.clear()
    return f"✅ Report saved for **{r['seller']}** as **{r['verdict']}**. Thank you for protecting other buyers!"


def _side_by_side(path_a, path_b, h=512):
    """Join the two photos into ONE labelled image (left = ad, right = received)."""
    from PIL import Image, ImageDraw
    import io
    a = Image.open(path_a).convert("RGB")
    b = Image.open(path_b).convert("RGB")
    a = a.resize((max(1, int(a.width * h / a.height)), h))
    b = b.resize((max(1, int(b.width * h / b.height)), h))
    gap, top = 20, 40
    canvas = Image.new("RGB", (a.width + b.width + gap, h + top), "white")
    canvas.paste(a, (0, top))
    canvas.paste(b, (a.width + gap, top))
    d = ImageDraw.Draw(canvas)
    d.text((10, 12), "LEFT: AD PHOTO", fill="black")
    d.text((a.width + gap + 10, 12), "RIGHT: RECEIVED", fill="black")
    canvas.thumbnail((1280, 1280))
    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=85)
    return types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg")


CACHE_FILE = "compare_cache.json"


def _cache_load():
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _cache_key(a, b, lang):
    import hashlib
    h = hashlib.sha1()
    for p in (a, b):
        with open(p, "rb") as f:
            h.update(f.read())
    h.update(lang.encode())
    return h.hexdigest()


def compare_ui(ad_img, got_img, seller, lang):
    if not ad_img or not got_img:
        yield "⚠️ Upload both photos: the ad photo and what you received."
        return

    key = _cache_key(ad_img, got_img, lang)
    cache = _cache_load()
    if key in cache:
        out = cache[key]                      # same photos compared before → instant result
    else:
        yield "⏳ **Gemma is comparing the two photos…** (can take 1–3 minutes on slow internet)"
        prompt = ("This image has two photos side by side. LEFT is the seller's AD photo. "
                  "RIGHT is what the buyer actually RECEIVED. "
                  "Compare product type, colour, material, logo/brand, size and quality. "
                  "First line must be exactly one of: MATCH ✅ / PARTIAL MATCH ⚠️ / DOES NOT MATCH 🚨. "
                  "Then at most 4 short bullet points of differences, then one line of advice. "
                  f"Under 100 words. {_lang_rule(lang)}")
        try:
            resp = client.models.generate_content(   # same client as Scan a post (no timeout)
                model=MODEL,
                contents=[types.Content(role="user", parts=[_side_by_side(ad_img, got_img, 384),
                                                            types.Part(text=prompt)])],
                config=types.GenerateContentConfig(temperature=0.2),
            )
            out = (resp.text or "").strip()
        except Exception as e:
            print("GEMMA ERROR (compare):", repr(e))
            yield f"❌ **Gemma could not compare right now.** `{e}`\n\nTry again in a moment."
            return
        if not out:
            yield "❌ Gemma returned an empty reply — please try again."
            return
        cache[key] = out
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
        except Exception:
            pass

    # Agent action: auto-report the seller to Firestore if it clearly doesn't match
    if seller and seller.strip() and "DOES NOT MATCH" in out.upper():
        r = report_seller(seller, "suspicious", "Received product did not match the ad photo (auto-reported by Gemma)", "-")
        TOOL_LOG.clear()
        out += f"\n\n🚩 _Auto-reported **{r['seller']}** to the community database._"
    yield out

THEME = gr.themes.Soft(primary_hue="emerald", secondary_hue="teal", neutral_hue="slate",
                       font=[gr.themes.GoogleFont("Inter"), "sans-serif"])

with gr.Blocks(title="ProofBeforePay") as demo:
    gr.HTML(HERO)
    lang = gr.Radio(["English", "বাংলা"], value="English", label="Result language / ফলাফলের ভাষা")

    with gr.Tab("💬 Ask the agent"):
      gr.ChatInterface(
        fn=chat,
        multimodal=True,
        chatbot=gr.Chatbot(height=460, label="ProofBeforePay Agent"),
        textbox=gr.MultimodalTextbox(placeholder="Paste a seller number, describe the deal, or attach screenshots…  📎",
                                     file_types=["image"], file_count="multiple"),
        examples=[
            {"text": "I want to buy an iPhone cover from seller 01712345678. They want 1500 tk advance on bKash. Is it safe?"},
            {"text": "Dhaka Fashion Hub থেকে পাঞ্জাবি অর্ডার দিতে চাই, বিশ্বাস করা যায়?"},
            {"text": "Which sellers should I avoid?"},
            {"text": "Gadget Bazar BD থেকে earbuds কিনেছি, ছবির সাথে মেলে না, ৮০০ টাকা লস। রিপোর্ট করো।"},
        ],
    )

    with gr.Tab("📸 Scan a post"):
        gr.Markdown("Upload a screenshot of a Facebook / Marketplace product post. Gemma reads it and finds the red flags.")
        with gr.Row():
            with gr.Column(scale=1):
                scan_img = gr.Image(type="filepath", label="Product post screenshot", height=320)
                scan_note = gr.Textbox(label="Anything else? (optional)", placeholder="e.g. they want full advance on bKash")
                scan_btn = gr.Button("🔍 Scan for scam risk", variant="primary")
            with gr.Column(scale=1):
                scan_out = gr.Markdown("_Result will appear here._")
        scan_btn.click(scan_post, [scan_img, scan_note, lang], scan_out)

    with gr.Tab("🔎 Check a seller"):
        gr.Markdown("Check a phone, bKash/Nagad number or page name against community reports **before** you pay.")
        with gr.Row():
            with gr.Column(scale=1):
                s_id = gr.Textbox(label="Seller number or page name", placeholder="01712345678  or  Dhaka Fashion Hub")
                s_deal = gr.Textbox(label="Deal details (optional)", placeholder="iPhone cover, 1500 tk advance")
                s_btn = gr.Button("🔎 Check seller", variant="primary")
                gr.Examples([["01712345678", "1500 tk advance for iPhone cover"],
                             ["Dhaka Fashion Hub", "Panjabi, cash on delivery"]], [s_id, s_deal])
            with gr.Column(scale=1):
                s_out = gr.Markdown("_Result will appear here._")
        s_btn.click(check_seller_ui, [s_id, s_deal, lang], s_out)

        with gr.Accordion("🚩 Report a seller (help other buyers)", open=False):
            with gr.Row():
                r_id = gr.Textbox(label="Seller number or page name")
                r_verdict = gr.Radio(["scam", "suspicious", "genuine"], value="scam", label="Your experience")
            with gr.Row():
                r_prod = gr.Textbox(label="Product")
                r_issue = gr.Textbox(label="What happened?")
            r_btn = gr.Button("Submit report")
            r_out = gr.Markdown()
            r_btn.click(report_ui, [r_id, r_verdict, r_prod, r_issue], r_out)

    with gr.Tab("⚖️ Ad vs received"):
        gr.Markdown("Upload the seller's ad photo and what you actually received. Gemma compares them side by side.")
        with gr.Row():
            ad_img = gr.Image(type="filepath", label="📢 Ad photo", height=280)
            got_img = gr.Image(type="filepath", label="📦 What I received", height=280)
        c_seller = gr.Textbox(label="Seller (optional — auto-reports if it doesn't match)", placeholder="Gadget Bazar BD")
        c_btn = gr.Button("⚖️ Compare", variant="primary")
        c_out = gr.Markdown("_Result will appear here._")
        c_btn.click(compare_ui, [ad_img, got_img, c_seller, lang], c_out)

    gr.HTML('<div id="foot">Built with Gemma 4 (Google AI Studio) · Firebase Firestore · Open source · Hacktoberfest Dhaka 2026</div>')

if __name__ == "__main__":
    demo.launch(share=True, theme=THEME, css=CSS)