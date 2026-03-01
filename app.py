from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import requests
import os
from datetime import date, timedelta

app = Flask(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

def get_products(days_ahead=7):
    """Get active products today AND upcoming products in next X days"""
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    
    today = date.today().strftime("%Y-%m-%d")
    future = (date.today() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    
    # Get ACTIVE products (valid today)
    active_response = requests.get(
        f"{SUPABASE_URL}/rest/v1/products"
        f"?valid_from=lte.{today}"
        f"&valid_until=gte.{today}"
        f"&is_expired=eq.false"
        f"&limit=300"
        f"&order=store",
        headers=headers
    )
    
    # Get UPCOMING products (starts in next 7 days)
    upcoming_response = requests.get(
        f"{SUPABASE_URL}/rest/v1/products"
        f"?valid_from=gt.{today}"
        f"&valid_from=lte.{future}"
        f"&is_expired=eq.false"
        f"&limit=100"
        f"&order=valid_from",
        headers=headers
    )
    
    active = active_response.json() if active_response.status_code == 200 else []
    upcoming = upcoming_response.json() if upcoming_response.status_code == 200 else []
    
    return active, upcoming

def get_or_create_user(phone):
    """Get existing user or create new profile"""
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    
    # Try to get existing user
    response = requests.get(
        f"{SUPABASE_URL}/rest/v1/users?phone=eq.{phone}&limit=1",
        headers=headers
    )
    
    if response.status_code == 200 and response.json():
        return response.json()[0]
    
    # Create new user
    new_user = {
        "phone": phone,
        "total_searches": 0,
        "money_saved": 0,
        "conversation_history": ""
    }
    
    create_response = requests.post(
        f"{SUPABASE_URL}/rest/v1/users",
        headers={**headers, "Prefer": "return=representation"},
        json=new_user
    )
    
    if create_response.status_code in [200, 201]:
        return create_response.json()[0]
    
    return new_user

def update_user(phone, updates):
    """Update user profile"""
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/users?phone=eq.{phone}",
        headers=headers,
        json=updates
    )

def format_products_for_ai(active_products, upcoming_products):
    """Format both active and upcoming products for Gemini"""
    result = ""
    
    if active_products:
        result += "=== TRENUTNO AKTIVNE AKCIJE ===\n"
        for p in active_products:
            result += f"{p.get('store')} | {p.get('product')}"
            if p.get('brand'):
                result += f" ({p.get('brand')})"
            if p.get('quantity'):
                result += f" {p.get('quantity')}"
            result += f" | {p.get('sale_price')}"
            if p.get('original_price'):
                result += f" (bilo {p.get('original_price')})"
            if p.get('discount_percent'):
                result += f" -{p.get('discount_percent')}"
            result += f" | kategorija: {p.get('category')}"
            result += f" | vrijedi do: {p.get('valid_until')}\n"
    
    if upcoming_products:
        result += "\n=== NADOLAZEĆE AKCIJE (uskoro) ===\n"
        for p in upcoming_products:
            result += f"{p.get('store')} | {p.get('product')}"
            if p.get('brand'):
                result += f" ({p.get('brand')})"
            if p.get('quantity'):
                result += f" {p.get('quantity')}"
            result += f" | {p.get('sale_price')}"
            if p.get('original_price'):
                result += f" (bilo {p.get('original_price')})"
            result += f" | POČINJE: {p.get('valid_from')} | vrijedi do: {p.get('valid_until')}\n"
    
    return result if result else "Baza podataka je trenutno prazna."

def ask_gemini(user_message, products_context, user_profile):
    """Send message to Gemini with full context"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    today = date.today().strftime("%d.%m.%Y.")
    
    # Build user context
    user_context = ""
    if user_profile.get('name'):
        user_context += f"Korisnikovo ime: {user_profile.get('name')}\n"
    if user_profile.get('preferred_stores'):
        user_context += f"Preferira trgovine: {user_profile.get('preferred_stores')}\n"
    if user_profile.get('favourite_products'):
        user_context += f"Omiljeni proizvodi: {user_profile.get('favourite_products')}\n"
    if user_profile.get('total_searches'):
        user_context += f"Ukupno pretraga: {user_profile.get('total_searches')}\n"
    
    prompt = f"""Ti si katalog.ai - osobni shopping asistent za Hrvatsku.
Danas je {today}.

{f"PROFIL KORISNIKA:{chr(10)}{user_context}" if user_context else ""}

KATALOZI I AKCIJE:
{products_context}

VAŽNA PRAVILA:
1. Ako korisnik traži proizvod koji JE u aktivnim akcijama - odmah reci gdje i po kojoj cijeni
2. Ako korisnik traži proizvod koji NEMA u aktivnim akcijama, ali je u nadolazećim - reci kada će biti na akciji i gdje (npr. "Trenutno nema popusta, ali za X dana od Y datuma bit će na akciji u Z trgovini za W cijenu!")
3. Ako ne postoji ni aktivna ni nadolazeća akcija - reci da trenutno nema popusta
4. Maksimalno 4-5 proizvoda po odgovoru - ne piši dugačke liste
5. NIKAD ne koristi markdown, zvjezdice (*), crtice ili bullet points - samo običan tekst
6. Budi kao prijatelj koji zna sve cijene - toplo, kratko, korisno
7. Za sva ostala pitanja (vrijeme, recepti, savjeti) - odgovori normalno
8. Ako korisnik kaže svoje ime - zapamti ga i koristi ga
9. Odgovori na jeziku na kojem te korisnik pita (hrvatski ili engleski)

Korisnik pita: {user_message}"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3}
    }
    
    response = requests.post(url, json=payload, timeout=30)
    data = response.json()
    
    try:
        if "candidates" in data:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            print(f"Gemini error: {data}")
            return "Oprostite, došlo je do greške. Pokušajte ponovno!"
    except Exception as e:
        print(f"Error: {e}, Response: {data}")
        return "Oprostite, došlo je do greške. Pokušajte ponovno!"

@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_message = request.form.get("Body", "").strip()
    sender = request.form.get("From", "")
    print(f"Message from {sender}: {incoming_message}")
    
    # Get or create user profile
    user = get_or_create_user(sender)
    
    # Get active AND upcoming products
    active_products, upcoming_products = get_products(days_ahead=7)
    products_context = format_products_for_ai(active_products, upcoming_products)
    
    # Get AI response
    ai_response = ask_gemini(incoming_message, products_context, user)
    
    # Update user stats
    update_user(sender, {
        "total_searches": (user.get("total_searches") or 0) + 1,
        "last_active": date.today().strftime("%Y-%m-%d")
    })
    
    # Send response
    resp = MessagingResponse()
    resp.message(ai_response)
    return str(resp)

@app.route("/", methods=["GET"])
def home():
    return "katalog.ai bot is running! 🚀"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
