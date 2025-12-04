from flask import Flask, render_template, request, flash, redirect
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote
import os
import traceback
import io
import stripe

app = Flask(__name__)
app.secret_key = "refundqueen2025"

# ENV VARS
OCR_API_KEY = os.environ.get("OCR_API_KEY")
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
COMMISSION_RATE = 0.05  # 5%

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY


def ocr_image_with_api(file_storage):
    """
    Takes the uploaded file, sends it to OCR.space, and returns extracted text.
    Also logs the full OCR response so we can see errors.
    """
    if not OCR_API_KEY:
        raise RuntimeError("OCR_API_KEY is not set")

    # Ensure we're at the start of the file
    file_storage.seek(0)
    file_bytes = file_storage.read()

    files = {"file": ("receipt.jpg", file_bytes, file_storage.mimetype or "image/jpeg")}
    data = {
        "apikey": OCR_API_KEY,
        "language": "eng",
        "OCREngine": 2,
    }

    try:
        # Using http to avoid SSL issues in this environment
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

    # Log full OCR result for debugging
    print("FULL OCR RESULT:", result, flush=True)

    if result.get("IsErroredOnProcessing"):
        print("OCR ERROR MESSAGE:", result.get("ErrorMessage"), flush=True)
        print("OCR ERROR DETAILS:", result.get("ErrorDetails"), flush=True)
        return ""

    if not result.get("ParsedResults"):
        return ""

    return result["ParsedResults"][0].get("ParsedText", "")


def parse_amazon_receipt(text: str):
    """
    Specialized parser for Amazon order-summary screenshots.
    We:
      - Ignore everything before the 'Arriving' section
      - Collect description lines
      - When we hit a price-only line, we pair it with the buffered description
    """
    lines = text.split("\n")
    items = []

    in_items_section = False
    current_desc_lines = []

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        lower = line.lower()

        # Look for start of items section
        if "arriving" in lower:
            in_items_section = True
            current_desc_lines = []
            continue

        if not in_items_section:
            # Skip header/address/payment/summary section
            continue

        # Skip non-item metadata
        if any(
            key in lower
            for key in [
                "order summary",
                "subtotal",
                "total before tax",
                "grand total",
                "shipping & handling",
                "shipping and handling",
                "payment method",
                "sold by:",
                "supplied by:",
                "view related transactions",
                "order #",
            ]
        ):
            continue

        # Price-only line
        m_price = re.match(r"^\$?([\d.,]+)$", line)
        if m_price:
            if current_desc_lines:
                name = " ".join(current_desc_lines).strip()
                try:
                    price = float(m_price.group(1).replace(",", ""))
                    items.append({"name": name, "paid": price})
                except ValueError:
                    pass
                # Reset for next item
                current_desc_lines = []
            continue

        # Otherwise, treat as part of the current item description
        current_desc_lines.append(line)

    print("PARSED AMAZON ITEMS:", items, flush=True)
    return items


def parse_items(text: str):
    """
    Entry point for item parsing. For now we just support Amazon receipts well.
    Later we can add Walmart/Target/Costco branches here.
    """
    if "amazon.com/gp/css/summary/print.html" in text or "order summary" in text.lower():
        return parse_amazon_receipt(text)

    # Fallback: simple generic parser (can be expanded later)
    items = []
    prev_line = None
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        m_both = re.search(r"(.+?)\s+\$?([\d.,]+)$", line)
        if m_both:
            name = m_both.group(1).strip()
            try:
                price = float(m_both.group(2).replace(",", ""))
                items.append({"name": name, "paid": price})
            except ValueError:
                pass
            prev_line = None
            continue

        m_price_only = re.match(r"^\$?([\d.,]+)$", line)
        if m_price_only and prev_line:
            try:
                price = float(m_price_only.group(1).replace(",", ""))
                items.append({"name": prev_line, "paid": price})
            except ValueError:
                pass
            prev_line = None
            continue

        prev_line = line

    print("PARSED GENERIC ITEMS:", items, flush=True)
    return items


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
            text = ocr_image_with_api(file)

            print("OCR TEXT START >>>", flush=True)
            print(text, flush=True)
            print("<<< OCR TEXT END", flush=True)

            # --- Parse items from OCR text ---
            items = parse_items(text)

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

                    # 🔍 LOG THE AMAZON PRICES WE FOUND
                    print(
                        f"AMAZON PRICES for {item['name'][:40]}: paid={item['paid']}, prices={prices}",
                        flush=True,
                    )

                    if prices:
                        amazon = min(prices)
                        # Log the chosen best price and whether we consider it a refund
                        print(
                            f"BEST AMAZON PRICE for {item['name'][:40]}: {amazon} (paid {item['paid']})",
                            flush=True,
                        )
                        if item["paid"] > amazon + 0.01:
                            save = item["paid"] - amazon
                            total += save
                            refunds.append(
                                f"• {item['name'][:60]} → ${item['paid']:.2f} → ${amazon:.2f} (Save ${save:.2f})"
                            )
                        else:
                            print(
                                f"No refund: paid {item['paid']} vs best {amazon}",
                                flush=True,
                            )

                except Exception as inner_e:
                    print("Inner item error:", inner_e, flush=True)
                    traceback.print_exc()
                    continue

            # If no savings, just show the result page
            if total <= 0:
                return render_template("result.html", refunds=refunds, total=total)

            # If Stripe isn't configured, just show the refund summary
            if not STRIPE_SECRET_KEY:
                flash("Stripe not configured; showing refunds only")
                return render_template("result.html", refunds=refunds, total=total)

            # --- Calculate 5% commission and create Stripe Checkout session ---
            commission = total * COMMISSION_RATE
            try:
                session = stripe.checkout.Session.create(
                    payment_method_types=["card"],
                    line_items=[
                        {
                            "price_data": {
                                "currency": "usd",
                                "product_data": {"name": "RefundQueen 5% Fee"},
                                "unit_amount": int(commission * 100),
                            },
                            "quantity": 1,
                        }
                    ],
                    mode="payment",
                    success_url="https://refundqueen.me/success",
                    cancel_url="https://refundqueen.me",
                )
                return redirect(session.url, code=303)
            except Exception as e:
                print("Stripe error:", e, flush=True)
                traceback.print_exc()
                flash("Payment failed; showing refunds only")
                return render_template("result.html", refunds=refunds, total=total)

        except Exception as e:
            print("TOP-LEVEL ERROR:", e, flush=True)
            traceback.print_exc()
            flash("Error processing receipt")

    return render_template("index.html")


@app.route("/success")
def success():
    return "<h1>Thank you! Your refund is being processed — RefundQueen got her 5%</h1><br><a href='/'>Scan Another</a>"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
