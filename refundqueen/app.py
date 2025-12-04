from flask import Flask, render_template, request, flash
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
app.secret_key = "refundqueen2025"

def preprocess(file_stream):
    # Read the uploaded file
    file_bytes = np.frombuffer(file_stream.read(), np.uint8)
    img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
    if img is None:
        return None
    # Nuclear preprocessing
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
            flash("Could not read image")
            return render_template("index.html")
        
        # OCR
        text = pytesseract.image_to_string(img)
        print("OCR TEXT:", text)  # Debug log
        
        # Smart item extraction
        items = []
        lines = text.split('\n')
        prev_line = ""
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Look for price at the end
            match = re.search(r'(.+?)\s+\$?([\d.,]+)$', line)
            if match:
                name = match.group(1).strip()
                try:
                    price = float(match.group(2).replace(',', ''))
                    items.append({"name": name, "paid": price})
                except:
                    pass
                prev_line = ""
            else:
                prev_line = line  # might be name for next line's price
        
        # Find refunds
        refunds = []
        total = 0
        for item in items:
            try:
                query = quote(item["name"][:60])
                url = f"https://www.amazon.com/s?k={query}"
                headers = {"User-Agent": "Mozilla/5.0"}
                r = requests.get(url, headers=headers, timeout=10)
                soup = BeautifulSoup(r.text, "html.parser")
                
                prices = []
                for p in soup.select('.a-price-whole'):
                    whole = p.get_text(strip=True)
                    frac = p.find_next_sibling('.a-price-fraction')
                    frac = frac.get_text(strip=True) if frac else "00"
                    try:
                        prices.append(float(whole + "." + frac))
                    except:
                        continue
                
                if prices:
                    amazon_price = min(prices)
                    if item["paid"] > amazon_price + 0.01:
                        save = item["paid"] - amazon_price
                        total += save
                        refunds.append({
                            "name": item["name"],
                            "paid": item["paid"],
                            "amazon": amazon_price,
                            "save": save
                        })
            except Exception as e:
                print("Price check error:", e)
                continue
        
        return render_template("result.html", refunds=refunds, total=total, count=len(refunds))
    
    return render_template("index.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
