from flask import Flask, render_template, request, redirect
import stripe
import os

app = Flask(__name__)
stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

# Your 5% commission
COMMISSION_RATE = 0.05

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        # ... your existing OCR + refund-finding code here ...
        # (keep everything you already have that finds total_save)

        total_save = 4.01  # ← replace with your actual calculated amount

        if total_save > 0:
            commission = total_save * COMMISSION_RATE
            session = stripe.checkout.Session.create(
                payment_method_types=['card', 'venmo', 'paypal'],  # ← Venmo included!
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {'name': 'RefundQueen 5% Fee'},
                        'unit_amount': int(commission * 100),
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
    return "<h1>Thank you! Your refund is being processed — RefundQueen got her 5%</h1>"
