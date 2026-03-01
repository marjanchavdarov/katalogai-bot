import os
import requests
import json
import base64
from pathlib import Path

# Configuration
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "YOUR_SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "YOUR_SUPABASE_ANON_KEY")

def extract_products_from_image(image_base64, store_name):
    """Send image to Gemini and extract products"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""Ovo je stranica kataloga od trgovine {store_name}.
Izvuci SVE proizvode s popustima koje vidiš.
Vrati SAMO JSON array, bez ikakvog drugog teksta, u ovom formatu:
[
  {{
    "product": "naziv proizvoda",
    "original_price": "originalna cijena ili null",
    "sale_price": "akcijska cijena",
    "valid_until": "vrijedi do datuma ili null",
    "category": "kategorija (hrana/piće/kozmetika/kućanstvo/tehnologija/ostalo)"
  }}
]
Ako ne vidiš proizvode s cijenama, vrati prazan array: []"""

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": image_base64
                        }
                    },
                    {"text": prompt}
                ]
            }
        ]
    }
    
    response = requests.post(url, json=payload, timeout=60)
    data = response.json()
    
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        # Clean up response - remove markdown if present
        text = text.replace("```json", "").replace("```", "").strip()
        products = json.loads(text)
        return products
    except Exception as e:
        print(f"Error parsing Gemini response: {e}")
        print(f"Raw response: {data}")
        return []

def save_to_supabase(products, store_name):
    """Save products to Supabase database"""
    if not products:
        return 0
    
    # Add store name to each product
    for p in products:
        p["store"] = store_name
    
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }
    
    response = requests.post(
        f"{SUPABASE_URL}/rest/v1/products",
        headers=headers,
        json=products
    )
    
    if response.status_code in [200, 201]:
        return len(products)
    else:
        print(f"Supabase error: {response.text}")
        return 0

def process_pdf(pdf_path, store_name):
    """Process a PDF catalogue and extract all products"""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("Installing PyMuPDF...")
        os.system("pip install PyMuPDF")
        import fitz
    
    print(f"\nProcessing: {pdf_path}")
    print(f"Store: {store_name}")
    
    doc = fitz.open(pdf_path)
    total_products = 0
    
    print(f"Total pages: {len(doc)}")
    
    for page_num in range(len(doc)):
        print(f"Processing page {page_num + 1}/{len(doc)}...", end=" ")
        
        page = doc[page_num]
        
        # Convert page to image
        mat = fitz.Matrix(2, 2)  # 2x zoom for better quality
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("jpeg")
        img_base64 = base64.b64encode(img_bytes).decode("utf-8")
        
        # Extract products with Gemini
        products = extract_products_from_image(img_base64, store_name)
        
        if products:
            saved = save_to_supabase(products, store_name)
            total_products += saved
            print(f"Found {len(products)} products, saved {saved}")
        else:
            print("No products found")
    
    doc.close()
    print(f"\nDone! Total products saved: {total_products}")
    return total_products

def clear_store_data(store_name):
    """Clear old data for a store before uploading new catalogue"""
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    
    response = requests.delete(
        f"{SUPABASE_URL}/rest/v1/products?store=eq.{store_name}",
        headers=headers
    )
    
    if response.status_code in [200, 204]:
        print(f"Cleared old data for {store_name}")
    else:
        print(f"Error clearing data: {response.text}")

if __name__ == "__main__":
    print("=== katalog.ai - PDF Upload Tool ===\n")
    
    # Example usage - change these values!
    pdf_file = input("Enter PDF file path: ").strip()
    store = input("Enter store name (e.g. Konzum, Lidl, DM): ").strip()
    
    if not os.path.exists(pdf_file):
        print(f"File not found: {pdf_file}")
        exit(1)
    
    # Clear old data for this store
    clear_old = input(f"Clear old {store} data first? (y/n): ").strip().lower()
    if clear_old == 'y':
        clear_store_data(store)
    
    # Process the PDF
    total = process_pdf(pdf_file, store)
    print(f"\n✅ Successfully processed {store} catalogue!")
    print(f"📦 {total} products now in database")
