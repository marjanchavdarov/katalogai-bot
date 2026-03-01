from flask import Flask, request
import google.generativeai as genai
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
import os

app = Flask(__name__)

# Configuration - these come from environment variables
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")

# Setup Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# System prompt - this is the bot's personality and knowledge
SYSTEM_PROMPT = """Ti si katalog.ai asistent - pametni shopping asistent za Hrvatsku.

Tvoj posao je pomagati korisnicima pronaći najbolje cijene i popuste u hrvatskim trgovinama.

Trenutno dostupne trgovine u bazi: Konzum, Lidl, Kaufland, DM, Bauhaus i druge.

Kada korisnik pita za cijene ili popuste:
- Odgovori prijateljski na hrvatskom jeziku
- Ako imaš info o popustu, daj ga jasno
- Ako nemaš info, reci "Trenutno nemam tu informaciju u bazi, ali provjerite katalog.ai web stranicu"

Za opća pitanja (vremenska prognoza, recepti, savjeti) - samo normalno odgovori.

Budi kratak, prijateljski i koristan. Odgovori na jeziku na kojem te korisnik pita (hrvatski ili engleski)."""

def ask_gemini(user_message):
    """Send message to Gemini and get response"""
    try:
        full_prompt = f"{SYSTEM_PROMPT}\n\nKorisnik pita: {user_message}"
        response = model.generate_content(full_prompt)
        return response.text
    except Exception as e:
        return "Oprostite, došlo je do greške. Pokušajte ponovno! 🙏"

@app.route("/webhook", methods=["POST"])
def webhook():
    """Handle incoming WhatsApp messages"""
    # Get the message from WhatsApp
    incoming_message = request.form.get("Body", "").strip()
    sender = request.form.get("From", "")
    
    print(f"Message from {sender}: {incoming_message}")
    
    # Get AI response
    ai_response = ask_gemini(incoming_message)
    
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
