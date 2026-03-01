from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import requests
import os

app = Flask(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

def get_all_products():
    """Get all products from Supabase"""
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    response = requests.get(
        f"{SUPABASE_URL}/rest/v1/products?limit=500&order=store",
        headers=headers
    )
    if response.status_code == 200:
        return response.json()
    return []

def format_products_for_ai(products):
    """Format products into a simple text list for AI"""
    if not products:
        return "Baza podataka je prazna."
    
    result = ""
    for p in products:
        result += f"{p.get('store')} | {p.get('product')} | {p.get('sale_price')}"
        if p.get('original_price') and p.get('original_price') != 'null':
            result += f" (bilo {p.get('original_price')})"
        if p.get('valid_until') and p.get('valid_until') != 'null':
            result += f" | do {p.get('valid_until')}"
        result += "\n"
    return result

def ask_gemini(user_message, products_context=""):
    """Send message to Gemini with full product context"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    if products_context:
        full_prompt = f"""Ti si katalog.ai - shopping asistent za Hrvatsku.
Imaš pristup trenutnim katalozima hrvatskih trgovina.

TRENUTNI KATALOZI (Trgovina | Proizvod | Cijena | Vrijedi do):
{products_context}

Korisnik pita: {user_message}

Odgovori korisno koristeći podatke iz kataloga. Budi kratak i prijateljski.
Ako pitanje nije o kupovini - odgovori normalno.
Odgovori na jeziku na kojem te korisnik pita."""
    else:
        full_prompt = f"""Ti si katalog.ai - shopping asistent za Hrvatsku.
Pomažeš pronaći najbolje cijene u hrvatskim trgovinama.
Korisnik pita: {user_message}
Odgovori korisno i prijateljski na jeziku na kojem te korisnik pita."""

    payload = {
        "contents": [{"parts": [{"text": full_prompt}]}]
    }
    
    response = requests.post(url, json=payload, timeout=30)
    data = response.json()
    
    try:
        if "candidates" in data:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            return f"Greška: {data.get('error', {}).get('message', 'Unknown error')}"
    except Exception as e:
        print(f"Gemini error: {e}, Response: {data}")
        return "Oprostite, došlo je do greške. Pokušajte ponovno! 🙏"

@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_message = request.form.get("Body", "").strip()
    sender = request.form.get("From", "")
    print(f"Message from {sender}: {incoming_message}")
    
    # Always load products and let Gemini figure out what's relevant
    products = get_all_products()
    products_context = format_products_for_ai(products)
    
    # Get smart AI response
    ai_response = ask_gemini(incoming_message, products_context)
    
    resp = MessagingResponse()
    resp.message(ai_response)
    return str(resp)

@app.route("/", methods=["GET"])
def home():
    return "katalog.ai bot is running! 🚀"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
