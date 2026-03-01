from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import requests
import os

app = Flask(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

SYSTEM_PROMPT = """Ti si katalog.ai asistent - pametni shopping asistent za Hrvatsku.
Pomažeš korisnicima pronaći najbolje cijene i popuste u hrvatskim trgovinama kao što su Konzum, Lidl, Kaufland, DM, Bauhaus i druge.
Za pitanja o cijenama i popustima - odgovori korisno i prijateljski.
Za opća pitanja - normalno odgovori.
Budi kratak i koristan. Odgovori na jeziku na kojem te korisnik pita."""

def ask_gemini(user_message):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": f"{SYSTEM_PROMPT}\n\nKorisnik: {user_message}"}
                    ]
                }
            ]
        }
        response = requests.post(url, json=payload, timeout=30)
        data = response.json()
        print(f"Gemini full response: {data}")
        if "candidates" in data:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            print(f"No candidates in response: {data}")
            return f"Greška: {data.get('error', {}).get('message', 'Unknown error')}"
    except Exception as e:
        print(f"Gemini error: {e}")
        return "Oprostite, došlo je do greške. Pokušajte ponovno! 🙏"

@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_message = request.form.get("Body", "").strip()
    sender = request.form.get("From", "")
    print(f"Message from {sender}: {incoming_message}")
    ai_response = ask_gemini(incoming_message)
    resp = MessagingResponse()
    resp.message(ai_response)
    return str(resp)

@app.route("/", methods=["GET"])
def home():
    return "katalog.ai bot is running! 🚀"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

