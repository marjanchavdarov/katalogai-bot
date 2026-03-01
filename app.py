from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import requests
import os

app = Flask(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

def search_database(query):
    """Search Supabase for relevant products"""
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    
    # Search by product name (case insensitive)
    response = requests.get(
        f"{SUPABASE_URL}/rest/v1/products?product=ilike.*{query}*&limit=10",
        headers=headers
    )
    
    if response.status_code == 200:
        return response.json()
    return []

def get_all_deals(store=None):
    """Get all current deals, optionally filtered by store"""
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    
    url = f"{SUPABASE_URL}/rest/v1/products?limit=20"
    if store:
        url += f"&store=ilike.*{store}*"
    
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        return response.json()
    return []

def format_products(products):
    """Format products list for display"""
    if not products:
        return "Nema pronađenih proizvoda."
    
    result = ""
    for p in products:
        result += f"🏪 {p.get('store', '')}\n"
        result += f"📦 {p.get('product', '')}\n"
        if p.get('original_price') and p.get('original_price') != 'null':
            result += f"💰 {p.get('original_price')} → {p.get('sale_price')}\n"
        else:
            result += f"💰 {p.get('sale_price')}\n"
        if p.get('valid_until') and p.get('valid_until') != 'null':
            result += f"📅 Vrijedi do: {p.get('valid_until')}\n"
        result += "\n"
    
    return result.strip()

def ask_gemini(user_message, db_context=""):
    """Send message to Gemini with database context"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    system = """Ti si katalog.ai asistent - pametni shopping asistent za Hrvatsku.
Pomažeš korisnicima pronaći najbolje cijene i popuste u hrvatskim trgovinama.
Za sva pitanja (vrijeme, recepti, savjeti, opće znanje) - odgovori normalno i korisno.
Budi prijateljski, kratak i koristan. Odgovori na jeziku na kojem te korisnik pita."""

    if db_context:
        full_prompt = f"{system}\n\nTrenutni podaci iz kataloga:\n{db_context}\n\nKorisnik pita: {user_message}\n\nOdgovori koristeći podatke iz kataloga gdje je relevantno."
    else:
        full_prompt = f"{system}\n\nKorisnik pita: {user_message}"

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": full_prompt}
                ]
            }
        ]
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
    
    # Search database for relevant products
    db_context = ""
    
    # Keywords that suggest price/catalogue search
    search_keywords = ["cijena", "popust", "akcija", "jeftino", "gdje", "koliko", 
                      "price", "cheap", "deal", "sale", "katalog", "tjedan",
                      "konzum", "lidl", "kaufland", "dm", "bauhaus", "spar"]
    
    message_lower = incoming_message.lower()
    should_search = any(keyword in message_lower for keyword in search_keywords)
    
    if should_search:
        # Try to search by product name
        search_term = incoming_message.replace("?", "").strip()
        products = search_database(search_term)
        
        if not products:
            # If no specific results, get general deals
            products = get_all_deals()
        
        if products:
            db_context = format_products(products)
    
    # Get AI response
    ai_response = ask_gemini(incoming_message, db_context)
    
    # Send response back via Twilio
    resp = MessagingResponse()
    resp.message(ai_response)
    
    return str(resp)

@app.route("/", methods=["GET"])
def home():
    return "katalog.ai bot is running! 🚀"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
