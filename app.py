from flask import Flask, request, jsonify, send_file
from twilio.twiml.messaging_response import MessagingResponse
import requests
import os
import json
import base64
import threading
from datetime import datetime, date, timedelta
import re
import io
import tempfile
from PIL import Image
import pdf2image
from pdf2image import convert_from_path

app = Flask(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# Check if required env vars are set
if not GEMINI_API_KEY:
    print("WARNING: GEMINI_API_KEY not set!")
if not SUPABASE_URL:
    print("WARNING: SUPABASE_URL not set!")
if not SUPABASE_KEY:
    print("WARNING: SUPABASE_KEY not set!")

# ===========================
# UPLOAD TOOL HTML (embedded as fallback)
# ===========================
UPLOAD_HTML = '''<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>katalog.ai Upload</title>
<style>
body { font-family: monospace; background: #111; color: #eee; padding: 40px; max-width: 700px; margin: 0 auto; }
h1 { color: #00ff88; }
.info { background: #222; padding: 15px; margin: 20px 0; border-left: 3px solid #00ff88; font-size: 13px; }
input[type=file] { display: block; margin: 20px 0; color: #eee; font-size: 14px; }
input[type=text] { background: #222; border: 1px solid #444; color: #eee; padding: 8px; width: 100%; margin: 5px 0 15px 0; font-family: monospace; }
label { color: #aaa; font-size: 13px; }
button { background: #00ff88; color: #000; border: none; padding: 15px 30px; font-weight: bold; font-size: 16px; cursor: pointer; width: 100%; margin-top: 10px; }
button:disabled { background: #444; color: #888; cursor: not-allowed; }
#log { background: #000; padding: 20px; margin-top: 20px; min-height: 100px; font-size: 12px; line-height: 1.8; white-space: pre-wrap; overflow: auto; max-height: 400px; }
</style>
</head>
<body>
<h1>katalog.ai — Upload Tool</h1>

<div class="info">
Select your PDF catalogue, fill in the details, and click Process.<br>
No need to rename files — just fill in the form!
</div>

<label>PDF Catalogue:</label>
<input type="file" id="fileInput" accept=".pdf">

<label>Store Name:</label>
<input type="text" id="storeName" placeholder="e.g. Lidl, Konzum, DM">

<label>Valid From (YYYY-MM-DD):</label>
<input type="text" id="validFrom" placeholder="e.g. 2026-03-02">

<label>Valid Until (YYYY-MM-DD, leave empty for 14 days):</label>
<input type="text" id="validUntil" placeholder="e.g. 2026-03-16 (optional)">

<button id="btn" onclick="startUpload()">Process Catalogue</button>

<div id="log">Waiting for upload...</div>

<script>
document.getElementById("fileInput").addEventListener("change", function() {
    const f = this.files[0];
    if (f) {
        document.getElementById("log").textContent = "File selected: " + f.name + " (" + Math.round(f.size/1024) + " KB)";
    }
});

async function startUpload() {
    const fileInput = document.getElementById("fileInput");
    const store = document.getElementById("storeName").value.trim();
    const validFrom = document.getElementById("validFrom").value.trim();
    let validUntil = document.getElementById("validUntil").value.trim();
    
    if (!fileInput.files[0]) { alert("Please select a PDF file!"); return; }
    if (!store) { alert("Please enter store name!"); return; }
    if (!validFrom) { alert("Please enter valid from date!"); return; }
    
    // Default 14 days if no end date
    if (!validUntil) {
        const from = new Date(validFrom);
        from.setDate(from.getDate() + 14);
        validUntil = from.toISOString().split("T")[0];
    }
    
    const btn = document.getElementById("btn");
    btn.disabled = true;
    btn.textContent = "Processing...";
    
    const log = document.getElementById("log");
    log.textContent = "Starting upload...\\n";
    
    const formData = new FormData();
    formData.append("file", fileInput.files[0]);
    formData.append("store", store);
    formData.append("valid_from", validFrom);
    formData.append("valid_until", validUntil);
    
    try {
        const response = await fetch("/upload", { method: "POST", body: formData });
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\\n");
            buffer = lines.pop();
            for (const line of lines) {
                if (!line.trim()) continue;
                try {
                    const data = JSON.parse(line);
                    if (data.type === "start") {
                        log.textContent += "Total pages: " + data.pages + "\\n";
                    } else if (data.type === "page") {
                        log.textContent += "Page " + data.page + "/" + data.total_pages + ": " + data.products_found + " products\\n";
                        log.scrollTop = log.scrollHeight;
                    } else if (data.type === "done") {
                        log.textContent += "\\n✓ DONE! " + data.products + " products saved from " + data.pages + " pages!\\n";
                        btn.textContent = "Process Another Catalogue";
                        btn.disabled = false;
                    } else if (data.type === "error") {
                        log.textContent += "ERROR: " + data.message + "\\n";
                        btn.disabled = false;
                        btn.textContent = "Try Again";
                    } else if (data.type === "page_error") {
                        log.textContent += "Page " + data.page + " error: " + data.error + "\\n";
                    }
                } catch(e) {
                    log.textContent += "Parse error: " + e.message + "\\n";
                }
            }
        }
    } catch(err) {
        log.textContent += "ERROR: " + err.message + "\\n";
        btn.disabled = false;
        btn.textContent = "Try Again";
    }
}
</script>
</body>
</html>'''

# ===========================
# PDF PROCESSING FUNCTIONS
# ===========================

def extract_products(image_base64, store_name, page_num, attempt=1):
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY not set")
        return []
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    prompt = "Stranica " + str(page_num) + " kataloga od trgovine " + store_name + ". Pokusaj " + str(attempt) + ". Izvuci SVE proizvode s cijenama. Vrati SAMO JSON array: [{\"product\":\"naziv\",\"brand\":\"brend ili null\",\"quantity\":\"250g ili null\",\"original_price\":\"2.99 ili null\",\"sale_price\":\"1.99\",\"discount_percent\":\"33% ili null\",\"valid_until\":\"08.03.2026. ili null\",\"category\":\"kategorija\",\"subcategory\":\"potkategorija\",\"fine_print\":\"sitni tisak s ove stranice ili null\"}] Kategorije: Meso i riba, Mlijecni proizvodi, Kruh i pekarski, Voce i povrce, Pice, Grickalice i slatkisi, Konzervirana hrana, Kozmetika i higijena, Kucanstvo i ciscenje, Alati i gradnja, Dom i vrt, Elektronika, Odjeca i obuca, Kucni ljubimci, Zdravlje i ljekarna, Ostalo. Ako nema proizvoda vrati: []"
    payload = {
        "contents": [{"parts": [{"inline_data": {"mime_type": "image/jpeg", "data": image_base64}}, {"text": prompt}]}],
        "generationConfig": {"temperature": 0.1}
    }
    try:
        response = requests.post(url, json=payload, timeout=60)
        data = response.json()
        
        # Check if response has expected structure
        if "candidates" not in data or not data["candidates"]:
            print(f"Gemini response missing candidates: {data}")
            return []
            
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        text = text.replace("```json", "").replace("```", "").strip()
        
        # Find JSON array in text
        import re
        json_match = re.search(r'\[.*\]', text, re.DOTALL)
        if json_match:
            text = json_match.group()
        
        result = json.loads(text)
        return result if isinstance(result, list) else []
    except Exception as e:
        print(f"Extract error on page {page_num} attempt {attempt}: {e}")
        return []

def merge_results(first_tuple, second_tuple):
    first_products, fine_print1 = first_tuple if isinstance(first_tuple, tuple) else (first_tuple, None)
    second_products, fine_print2 = second_tuple if isinstance(second_tuple, tuple) else (second_tuple, None)
    seen = set()
    merged = []
    for p in (first_products or []) + (second_products or []):
        if not isinstance(p, dict):
            continue
        name = p.get("product", "").lower().strip()
        if name and name not in seen:
            seen.add(name)
            merged.append(p)
    fine_print = fine_print1 or fine_print2
    return merged, fine_print

def parse_date(date_str):
    if not date_str or date_str == 'null':
        return None
    for fmt in ["%d.%m.%Y.", "%d.%m.%Y", "%d. %m. %Y.", "%Y-%m-%d"]:
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except:
            continue
    return None

def upload_image_to_supabase(image_bytes, filename):
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Supabase credentials not set")
        return None
        
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "image/jpeg"
    }
    url = f"{SUPABASE_URL}/storage/v1/object/katalog-images/{filename}"
    response = requests.post(url, headers=headers, data=image_bytes)
    if response.status_code in [200, 201]:
        return f"{SUPABASE_URL}/storage/v1/object/public/katalog-images/{filename}"
    print(f"Supabase upload failed: {response.status_code} - {response.text}")
    return None

def save_products(products, store_name, page_num, page_image_url, catalogue_name, valid_from, valid_until):
    if not products or not SUPABASE_URL or not SUPABASE_KEY:
        return 0
        
    if not valid_until and valid_from:
        try:
            from_date = datetime.strptime(valid_from, "%Y-%m-%d")
            valid_until = (from_date + timedelta(days=14)).strftime("%Y-%m-%d")
        except:
            pass
    
    records = []
    for p in products:
        if not isinstance(p, dict):
            continue
            
        product_valid_until = parse_date(p.get("valid_until"))
        final_valid_until = product_valid_until or valid_until
        if not final_valid_until:
            continue
            
        record = {
            "store": store_name,
            "product": p.get("product", ""),
            "brand": p.get("brand") if p.get("brand") not in [None, "null"] else None,
            "quantity": p.get("quantity") if p.get("quantity") not in [None, "null"] else None,
            "original_price": p.get("original_price") if p.get("original_price") not in [None, "null"] else None,
            "sale_price": p.get("sale_price", ""),
            "discount_percent": p.get("discount_percent") if p.get("discount_percent") not in [None, "null"] else None,
            "category": p.get("category", "Ostalo"),
            "subcategory": p.get("subcategory"),
            "valid_from": valid_from,
            "valid_until": final_valid_until,
            "is_expired": False,
            "page_image_url": page_image_url,
            "page_number": page_num,
            "catalogue_name": catalogue_name,
            "catalogue_week": datetime.now().strftime("%Y-W%V"),
            "fine_print": p.get("fine_print") if p.get("fine_print") not in [None, "null"] else None
        }
        records.append(record)
        
    if not records:
        return 0
        
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }
    response = requests.post(f"{SUPABASE_URL}/rest/v1/products", headers=headers, json=records)
    if response.status_code in [200, 201]:
        return len(records)
    print(f"Failed to save products: {response.status_code} - {response.text}")
    return 0

def save_catalogue(store_name, catalogue_name, valid_from, valid_until, fine_print, pages, products_count):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return
        
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal"
    }
    record = {
        "store": store_name,
        "catalogue_name": catalogue_name,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "fine_print": fine_print,
        "pages": pages,
        "products_count": products_count
    }
    requests.post(f"{SUPABASE_URL}/rest/v1/catalogues", headers=headers, json=record)

# ===========================
# FLASK ROUTES
# ===========================

@app.route("/upload-tool")
def upload_tool():
    return UPLOAD_HTML

@app.route("/upload", methods=["POST"])
def upload():
    def generate():
        try:
            file = request.files.get("file")
            store_name = request.form.get("store")
            valid_from = request.form.get("valid_from")
            valid_until = request.form.get("valid_until")
            
            if not file or not store_name or not valid_from or not valid_until:
                yield json.dumps({"type": "error", "message": "Missing required fields"}) + "\n"
                return
            
            # Check if pdf2image is working
            try:
                from pdf2image import convert_from_path
            except ImportError as e:
                yield json.dumps({"type": "error", "message": f"PDF processing library not installed: {str(e)}"}) + "\n"
                return
            
            # Save file temporarily
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
                file.save(tmp_file.name)
                temp_path = tmp_file.name
            
            catalogue_name = os.path.splitext(file.filename)[0]
            
            # Convert PDF to images
            try:
                images = convert_from_path(temp_path, dpi=150)  # Lower DPI for faster processing
                total_pages = len(images)
            except Exception as e:
                yield json.dumps({"type": "error", "message": f"PDF conversion failed: {str(e)}. Make sure poppler is installed."}) + "\n"
                # Clean up
                try:
                    os.remove(temp_path)
                except:
                    pass
                return
            
            total_products = 0
            catalogue_fine_print = None
            
            yield json.dumps({"type": "start", "pages": total_pages}) + "\n"
            
            for page_num in range(total_pages):
                try:
                    # Get image from converted PDF
                    img = images[page_num]
                    
                    # Convert PIL Image to bytes
                    img_byte_arr = io.BytesIO()
                    img.save(img_byte_arr, format='JPEG', quality=85)
                    img_bytes = img_byte_arr.getvalue()
                    
                    img_base64 = base64.b64encode(img_bytes).decode("utf-8")
                    
                    page_filename = f"{store_name.lower()}_page_{str(page_num+1).zfill(3)}_{datetime.now().strftime('%Y%m%d')}.jpg"
                    page_image_url = upload_image_to_supabase(img_bytes, page_filename)
                    
                    first_pass = extract_products(img_base64, store_name, page_num + 1, attempt=1)
                    second_pass = extract_products(img_base64, store_name, page_num + 1, attempt=2)
                    merged, page_fine_print = merge_results(first_pass, second_pass)
                    
                    if page_fine_print:
                        catalogue_fine_print = (catalogue_fine_print + " " + page_fine_print) if catalogue_fine_print else page_fine_print
                    
                    saved = 0
                    if merged:
                        saved = save_products(merged, store_name, page_num + 1, page_image_url, catalogue_name, valid_from, valid_until)
                        total_products += saved
                    
                    yield json.dumps({
                        "type": "page",
                        "page": page_num + 1,
                        "total_pages": total_pages,
                        "products_found": len(merged) if merged else 0,
                        "products_saved": saved,
                        "total_products": total_products
                    }) + "\n"
                    
                except Exception as page_error:
                    print(f"Page {page_num+1} error: {page_error}")
                    yield json.dumps({"type": "page_error", "page": page_num+1, "error": str(page_error)}) + "\n"
                    continue
            
            # Clean up
            try:
                os.remove(temp_path)
            except:
                pass
            
            if total_products > 0:
                save_catalogue(store_name, catalogue_name, valid_from, valid_until, catalogue_fine_print, total_pages, total_products)
            
            yield json.dumps({
                "type": "done",
                "products": total_products,
                "pages": total_pages
            }) + "\n"
            
        except Exception as e:
            print(f"Upload error: {e}")
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"
    
    return app.response_class(generate(), mimetype="application/x-ndjson")

# ===========================
# WHATSAPP BOT
# ===========================

def get_products():
    if not SUPABASE_URL or not SUPABASE_KEY:
        return [], [], {}
        
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
    today = date.today().strftime("%Y-%m-%d")
    future = (date.today() + timedelta(days=7)).strftime("%Y-%m-%d")
    
    try:
        active = requests.get(f"{SUPABASE_URL}/rest/v1/products?valid_from=lte.{today}&valid_until=gte.{today}&is_expired=eq.false&limit=300&order=store", headers=headers)
        upcoming = requests.get(f"{SUPABASE_URL}/rest/v1/products?valid_from=gt.{today}&valid_from=lte.{future}&is_expired=eq.false&limit=100&order=valid_from", headers=headers)
        catalogues = requests.get(f"{SUPABASE_URL}/rest/v1/catalogues?valid_until=gte.{today}&select=store,fine_print", headers=headers)
    except Exception as e:
        print(f"Error fetching products: {e}")
        return [], [], {}
    
    catalogue_fine_prints = {}
    if catalogues.status_code == 200:
        for c in catalogues.json():
            if c.get("fine_print"):
                catalogue_fine_prints[c["store"]] = c["fine_print"]
    
    active_data = active.json() if active.status_code == 200 else []
    upcoming_data = upcoming.json() if upcoming.status_code == 200 else []
    
    return active_data, upcoming_data, catalogue_fine_prints

def get_or_create_user(phone):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return {"phone": phone, "total_searches": 0, "money_saved": 0}
        
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
    try:
        response = requests.get(f"{SUPABASE_URL}/rest/v1/users?phone=eq.{phone}&limit=1", headers=headers)
        if response.status_code == 200 and response.json():
            return response.json()[0]
    except Exception as e:
        print(f"Error getting user: {e}")
        
    new_user = {"phone": phone, "total_searches": 0, "money_saved": 0}
    try:
        create = requests.post(f"{SUPABASE_URL}/rest/v1/users", headers={**headers, "Prefer": "return=representation"}, json=new_user)
        return create.json()[0] if create.status_code in [200, 201] else new_user
    except:
        return new_user

def update_user(phone, updates):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return
        
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
    try:
        requests.patch(f"{SUPABASE_URL}/rest/v1/users?phone=eq.{phone}", headers=headers, json=updates)
    except Exception as e:
        print(f"Error updating user: {e}")

def format_products_for_ai(active, upcoming, fine_prints={}):
    result = ""
    if active:
        result += "=== AKTIVNE AKCIJE DANAS ===\n"
        for p in active:
            if not isinstance(p, dict):
                continue
            result += f"{p.get('store', 'N/A')} | {p.get('product', 'N/A')}"
            if p.get('brand'): result += f" ({p.get('brand')})"
            if p.get('quantity'): result += f" {p.get('quantity')}"
            result += f" | {p.get('sale_price', 'N/A')}"
            if p.get('original_price'): result += f" (bilo {p.get('original_price')})"
            if p.get('fine_print'): result += f" | Napomena: {p.get('fine_print')}"
            result += f" | do: {p.get('valid_until', 'N/A')}\n"
    if upcoming:
        result += "\n=== NADOLAZECE AKCIJE ===\n"
        for p in upcoming:
            if not isinstance(p, dict):
                continue
            result += f"{p.get('store', 'N/A')} | {p.get('product', 'N/A')}"
            if p.get('brand'): result += f" ({p.get('brand')})"
            result += f" | {p.get('sale_price', 'N/A')}"
            result += f" | POCINJE: {p.get('valid_from', 'N/A')} do {p.get('valid_until', 'N/A')}\n"
    if fine_prints:
        result += "\n=== NAPOMENE PO TRGOVINAMA ===\n"
        for store, fp in fine_prints.items():
            result += f"{store}: {fp}\n"
    return result or "Baza je prazna."

def ask_gemini(user_message, products_context, user_profile):
    if not GEMINI_API_KEY:
        return "Trenutno nisam spojen na AI. Provjerite GEMINI_API_KEY."
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    today = date.today().strftime("%d.%m.%Y.")
    user_context = ""
    if user_profile.get('name'): user_context += f"Ime: {user_profile.get('name')}\n"
    if user_profile.get('preferred_stores'): user_context += f"Preferira: {user_profile.get('preferred_stores')}\n"
    
    prompt = "Ti si katalog.ai - osobni shopping asistent za Hrvatsku. Danas je " + today + ". " + (("Korisnik: " + user_context) if user_context else "") + " KATALOZI: " + products_context + " PRAVILA: 1. Ako postoji aktivna akcija - reci gdje i po kojoj cijeni. 2. Ako nema aktivne ali ima nadolazece akcije - reci kada pocinje i gdje. 3. Maksimalno 4-5 proizvoda. 4. NIKAD ne koristi markdown zvjezdice ili bullet points - samo obican tekst. 5. Budi kao prijatelj koji zna sve cijene. 6. Za ostala pitanja odgovori normalno. Korisnik pita: " + user_message
    
    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.3}}
    try:
        response = requests.post(url, json=payload, timeout=30)
        data = response.json()
        if "candidates" in data and data["candidates"]:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        return "Oprostite, doslo je do greske. Pokusajte ponovno!"
    except Exception as e:
        print(f"Gemini API error: {e}")
        return "Oprostite, doslo je do greske. Pokusajte ponovno!"

@app.route("/webhook", methods=["POST"])
def webhook():
    incoming_message = request.form.get("Body", "").strip()
    sender = request.form.get("From", "")
    print(f"Message from {sender}: {incoming_message}")
    user = get_or_create_user(sender)
    active, upcoming, fine_prints = get_products()
    products_context = format_products_for_ai(active, upcoming, fine_prints)
    ai_response = ask_gemini(incoming_message, products_context, user)
    update_user(sender, {"total_searches": (user.get("total_searches") or 0) + 1, "last_active": date.today().strftime("%Y-%m-%d")})
    resp = MessagingResponse()
    resp.message(ai_response)
    return str(resp)

@app.route("/", methods=["GET"])
def home():
    status = {
        "status": "running",
        "gemini_api": "✅ Set" if GEMINI_API_KEY else "❌ Not Set",
        "supabase": "✅ Set" if SUPABASE_URL and SUPABASE_KEY else "❌ Not Set",
        "endpoints": ["/", "/upload-tool", "/upload", "/webhook", "/upload-tool-simple"]
    }
    return jsonify(status)

@app.route("/upload-tool-simple")
def upload_tool_simple():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Simple Upload</title>
        <meta charset="UTF-8">
        <style>
            body { font-family: Arial; padding: 20px; background: #f0f0f0; }
            .container { max-width: 500px; margin: 0 auto; background: white; padding: 20px; border-radius: 5px; }
            input, button { display: block; width: 100%; margin: 10px 0; padding: 8px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Simple Upload Test</h1>
            <form action="/upload" method="post" enctype="multipart/form-data">
                <input type="file" name="file" accept=".pdf" required><br>
                <input type="text" name="store" placeholder="Store Name" required><br>
                <input type="text" name="valid_from" placeholder="Valid From (YYYY-MM-DD)" required><br>
                <input type="text" name="valid_until" placeholder="Valid Until (YYYY-MM-DD)" required><br>
                <button type="submit">Upload PDF</button>
            </form>
        </div>
    </body>
    </html>
    '''

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
