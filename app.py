"""Forgenix web app: serves the prototype and takes Pro subscriptions through
Interswitch Web Checkout (Web Redirect). Run: python app.py"""
import os, time, uuid, requests
from flask import Flask, request, jsonify, session, redirect, send_from_directory

PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:5000").rstrip("/")

app = Flask(__name__, static_folder="static")
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = PUBLIC_URL.startswith("https://")

# Defaults are the sample sandbox values shown in Interswitch's docs. Replace with your own
# from the Interswitch developer console (or their "Default Test Credentials" page).
MERCHANT_CODE = os.environ.get("ISW_MERCHANT_CODE", "MX6072")
PAY_ITEM_ID = os.environ.get("ISW_PAY_ITEM_ID", "9405967")
MODE = os.environ.get("ISW_MODE", "TEST").upper()          # TEST or LIVE

LIVE = MODE == "LIVE"
PAY_URL = ("https://newwebpay.interswitchng.com" if LIVE else "https://newwebpay-sandbox.interswitchng.com") + "/collections/w/pay"
QUERY_URL = ("https://webpay.interswitchng.com" if LIVE else "https://sandbox.interswitchng.com") + "/collections/api/v1/gettransaction.json"

PLANS = {"pro_monthly": {"name": "Forgenix Pro (1 month)", "amount": 200000}}  # kobo = NGN 2,000 (placeholder price)
PENDING = {}  # txn_ref -> order. In-memory for the demo; use a database in production.


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/service-worker.js")
def service_worker():
    response = send_from_directory("static", "service-worker.js", mimetype="application/javascript")
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/api/status")
def status():
    return jsonify(pro=session.get("pro_until", 0) > time.time(), ref=session.get("ref", ""))


@app.post("/api/start-payment")
def start_payment():
    d = request.get_json(force=True, silent=True) or {}
    plan, email = PLANS.get(d.get("plan")), (d.get("email") or "").strip()
    if not plan or "@" not in email:
        return jsonify(error="Enter a valid email first."), 400
    ref = "FGX-" + uuid.uuid4().hex[:16]  # unique per attempt; amount is set here, never by the browser
    PENDING[ref] = {"amount": plan["amount"], "email": email, "paid": False}
    return jsonify(action=PAY_URL, fields={
        "merchant_code": MERCHANT_CODE, "pay_item_id": PAY_ITEM_ID, "txn_ref": ref,
        "amount": str(plan["amount"]), "currency": "566", "cust_email": email,
        "pay_item_name": plan["name"], "site_redirect_url": PUBLIC_URL + "/payment-response"})


@app.route("/payment-response", methods=["POST", "GET"])
def payment_response():
    # Interswitch sends the browser back here. Never trust these fields; requery server-side.
    ref = request.values.get("txnref") or request.values.get("txn_ref") or ""
    order = PENDING.get(ref)
    if not order:
        return redirect("/?failed=1", code=303)
    ok = order["paid"]
    if not ok:
        try:
            r = requests.get(QUERY_URL, params={"merchantcode": MERCHANT_CODE, "transactionreference": ref,
                             "amount": order["amount"]}, headers={"Content-Type": "application/json"}, timeout=20)
            j = r.json()
            ok = j.get("ResponseCode") == "00" and int(j.get("Amount", -1)) == order["amount"]
        except Exception:
            ok = False
    if ok:
        order["paid"] = True
        session["pro_until"] = int(time.time()) + 30 * 86400
        session["ref"] = ref
        return redirect("/?paid=1", code=303)
    return redirect("/?failed=1", code=303)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
