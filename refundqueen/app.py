from flask import Flask, render_template, request
import cv2
import numpy as np
from PIL import Image
import pytesseract
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote
import os

app = Flask(__name__)

def preprocess(file_stream):
    file_bytes = np.frombuffer(file_stream.read(), np.uint8)
    img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
    if img is None:
        return None
    img = cv2.resize(img, None, fx=1.5, fy=1.5)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
    gray = clahe.apply(gray)
    thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
    kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
    sharpened = cv2.filter2D(thresh, -1, kernel)
    return Image.fromarray(sharpened)

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        file = request.files["file"]
        file.seek(0)
        img = preprocess(file)
        if img is None:
            return "<h1>Could not read image</h1>", 400
        
        text = pytesseract.image_to_string(img)
        
        # Parse items
        items = []
        for line in text.split('\n'):
            m = re.search(r'(.+?)\s+\$?([\d.,]+)$', line)
            if m:
                name = m.group(1).strip()
                price = float(m.group(2).replace(',', ''))
                items.append({"name": name, "paid": price})
        
        # Find refunds
        refunds = []
        total = 0
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
                        total += save
                        refunds.append(f"• {item['name'][:60]} — ${item['paid']:.2f} → ${amazon:.2f} (Save ${save:.2f})")
            except:
                continue
        
        return render_template("result.html", refunds=refunds, total=total)
    
    return render_template("index.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
