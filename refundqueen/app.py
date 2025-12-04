from flask import Flask, render_template, request, flash
import cv2
import numpy as np
from PIL import Image
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote
import os
import traceback
import io

app = Flask(__name__)
app.secret_key = "refundqueen2025"

# Read OCR API key from environment (set in Railway)
OCR_API_KEY = os.environ.get("OCR_API_KEY")


def ocr_image_with_api(pil_image):
    """
    Takes a PIL image, sends it to OCR.space, and returns extracted text.
    """
    if not OCR_API_KEY:
        raise RuntimeError("OCR_API_KEY is not set")

    # Convert image (PIL) to bytes
    buf = io.BytesIO()
    pil_image.save(buf, format="JPEG")
    buf.seek(0)

    files = {"file": ("receipt.jpg", buf, "image/jpeg")}
    data = {
        "apikey": OCR_API_KEY,
        "language": "eng",
        "OCREngine": 2,
    }

    try:
        # NOTE: using http (not https) to avoid SSL issues in this environment
        r = requests.post(
            "http://api.ocr.space/parse/image",
            files=files,
            data=data,
            timeout=60,
        )
        r.raise_for_status()
        result = r.json()
    except Exception as e:
        print("OCR API error:", e, flush=True)
        traceback.print_exc()
        return ""

    if not result.get("ParsedResults"):
        return ""

    return result["ParsedResults"][0].get("ParsedText", "")


def preprocess(file):
    """
    Basic denoising/sharpening so the OCR API gets a clearer image.
    """
    nparr = np.frombuffer(file.read(), np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    img = cv2.resize(img, None, fx=1.5, fy=1.5)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    thresh = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        11,
        2,
    )
    kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
    sharpened = cv2.filter2D(thresh, -1, kernel)
    return Image.fromarray(sharpened)


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        if "file" not in request.files:
            flash("No file uploaded")
            return render_template("index.html")

        file = request.files["file"]
        if file.filename == "":
            flash("No file selected")
            return render_template("index.html")

        try:
            # --- OCR via API ---
            file.seek(0)
            img = preprocess(file)
            text = ocr_image_with_api(img)

            # --- Parse items + prices from receipt text ---
            items = []
            for line in text.split("\n"):
                match = re.search(r"(.+?)\s+[\$]?([\d.,]+)$", line)
                if match:
                    name = match.group(1).strip()
                    try:
                        price = float(match.group(2).replace(",", ""))
                    except ValueError:
                        continue
                    items.append({"name": name, "paid": price})

            # --- Check Amazon for cheaper prices ---
            refunds = []
            total = 0.0
            for item in items:
                try:
                    url = f"https://www.amazon.com/s?k={quote(item['name'][:60])}"
                    r = requests.get(
                        url,
                        headers={"User-Agent": "Mozilla/5.0"},
                        timeout=10,
                    )
                    soup = BeautifulSoup(r.text, "html.parser")
                    prices = []
                    for p in soup.select(".a-price-whole"):
                        whole = p.get_text(strip=True)
                        frac_el = p.find_next_sibling(".a-price-fraction")
                        frac = frac_el.get_text(strip=True) if frac_el else "00"
                        try:
                            prices.append(float(whole + "." + frac))
                        except ValueError:
                            continue

                    if prices:
                        amazon = min(prices)
                        if item["paid"] > amazon + 0.01:
                            save = item["paid"] - amazon
                            total += save
                            refunds.append(
                                f"• {item['name'][:60]} → ${item['paid']:.2f} → ${amazon:.2f} (Save ${save:.2f})"
                            )

                except Exception as inner_e:
                    print("Inner item error:", inner_e, flush=True)
                    traceback.print_exc()
                    continue

            return render_template("result.html", refunds=refunds, total=total)

        except Exception as e:
            print("TOP-LEVEL ERROR:", e, flush=True)
            traceback.print_exc()
            flash("Error processing receipt")

    return render_template("index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
