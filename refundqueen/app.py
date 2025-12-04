from flask import Flask, render_template, request, redirect
import cv2
import numpy as np
from PIL import Image
import pytesseract
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote
import stripe
import os

app = Flask(__name__)
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")

COMMISSION_RATE = 0.05  # 5%

def preprocess(file_stream):
    file_bytes = np.frombuffer(file_stream.read(), np.uint8)
    img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
    if img is None: return None
    img = cv2.resize(img, None, fx=1.5, fy=1.5)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
    gray = clahe.apply(gray)
    thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
    kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
    sharpened = cv2.filter2D(thresh, -1, kernel)
    return Image.fromarray(sharpened)

def find_refunds(file):
    file.seek(0)
    img = preprocess(file)
    if not img: return "Could not read image", [], 0
    
    text = pytesseract.image_to_string(img)
    
    items = []
    for line in text.split('\n'):
        m = re.search(r'(.+?)\s+\$?([\d.,]+)$', line.strip())
        if m:
            name = m.group(1).strip()
            price = float(m.group(2).replace(',', ''))
            items.append({"name": name, "paid": price})
    
    refunds = []
    total_save = 0
    for item in items:
        try:
            url = f"https://www.amazon.com/s?k={quote(item['name'][:60])}"
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            soup = BeautifulSoup(r.text, "html.parser")
            prices = []
            for p in soup.select('.a-price-whole'):
                whole = p.get_text(strip=True)
                frac = p.find_next_sibling('.a-price-fraction')
                frac = frac.get_text(strip=True) if frac else "00"
                prices.append(float(whole + "." + frac))
            if prices:
                amazon = min(prices)
                if item["paid"] > amazon + 0.01:
                    save = item["paid"] - amazon
                    total_save += save
                    refunds.append(f"• {item['name'][:60]} — ${item['paid']:.2f} → ${amazon:.2f} (Save ${save:.2f})")
        except:
            continue
    
    return f"REFUND FOUND: ${total_save:.2f}", refunds, total_save

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        file = request.files["file"]
        message, refunds, total_save = find_refunds(file)
        
        if total_save == 0:
            return render_template("result.html", message="No refunds found this time", refunds=[])
        
        # 5% commission via Stripe + Venmo
        session = stripe.checkout.Session.create(
            payment_method_types=['card', 'venmo'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {'name': 'RefundQueen 5% Fee'},
                    'unit_amount': int(total_save * COMMISSION_RATE * 100),
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url='https://refundqueen.me/success',
            cancel_url='https://refundqueen.me',
        )
        return redirect(session.url)
    
    return render_template("index.html")

@app.route("/success")
def success():
    return "<h1>Thank you! Your refund is being processed — RefundQueen got her 5%</h1><br><a href='/'>Scan Another</a>"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
