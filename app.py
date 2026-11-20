"""Forgenix mobile web app and account-backed learning progress."""
import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager

import requests
from flask import Flask, jsonify, redirect, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "instance", "forgenix.sqlite3"))
PUBLIC_URL = os.environ.get(
    "PUBLIC_URL", os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:5000")
).rstrip("/")
PATHS_PATH = os.path.join(BASE_DIR, "static", "paths.json")

with open(PATHS_PATH, encoding="utf-8") as paths_file:
    LEARNING_PATHS = json.load(paths_file)

app = Flask(__name__, static_folder="static")
app.secret_key = os.environ.get("SECRET_KEY") or os.urandom(32)
if not os.environ.get("SECRET_KEY"):
    app.logger.warning("SECRET_KEY is unset; sessions will reset on restart. Configure a persistent secret.")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = PUBLIC_URL.startswith("https://")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

MERCHANT_CODE = os.environ.get("ISW_MERCHANT_CODE", "MX6072")
PAY_ITEM_ID = os.environ.get("ISW_PAY_ITEM_ID", "9405967")
MODE = os.environ.get("ISW_MODE", "TEST").upper()
LIVE = MODE == "LIVE"
PAY_URL = (
    "https://newwebpay.interswitchng.com"
    if LIVE
    else "https://newwebpay-sandbox.interswitchng.com"
) + "/collections/w/pay"
QUERY_URL = (
    "https://webpay.interswitchng.com"
    if LIVE
    else "https://sandbox.interswitchng.com"
) + "/collections/api/v1/gettransaction.json"
PLANS = {"pro_monthly": {"name": "Forgenix Pro (1 month)", "amount": 200000}}
MODULE_IDS = {
    goal: {module["id"] for module in path["modules"]}
    for goal, path in LEARNING_PATHS.items()
}
EMPTY_STATE = {"goal": "", "hours": 4, "completed": {}}


@contextmanager
def connect_db():
    directory = os.path.dirname(os.path.abspath(DATABASE_PATH))
    os.makedirs(directory, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db():
    with connect_db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                pro_until INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS learner_state (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                goal TEXT NOT NULL DEFAULT '',
                weekly_hours INTEGER NOT NULL DEFAULT 4,
                completed_json TEXT NOT NULL DEFAULT '{}',
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS payments (
                txn_ref TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                amount INTEGER NOT NULL,
                email TEXT NOT NULL,
                paid INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL
            );
            """
        )


def normalize_state(value):
    if not isinstance(value, dict):
        return None
    goal = value.get("goal", "")
    hours = value.get("hours", 4)
    completed = value.get("completed", {})
    if goal not in LEARNING_PATHS and goal != "":
        return None
    if isinstance(hours, bool) or hours not in (2, 4, 7):
        return None
    if not isinstance(completed, dict):
        return None

    clean_completed = {}
    for path_goal, module_ids in completed.items():
        if path_goal not in LEARNING_PATHS or not isinstance(module_ids, list):
            return None
        valid_ids = MODULE_IDS[path_goal]
        if any(not isinstance(module_id, str) or module_id not in valid_ids for module_id in module_ids):
            return None
        clean_completed[path_goal] = sorted(set(module_ids))
    return {"goal": goal, "hours": hours, "completed": clean_completed}


def save_state(connection, user_id, learner_state):
    connection.execute(
        """
        INSERT INTO learner_state (user_id, goal, weekly_hours, completed_json, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            goal = excluded.goal,
            weekly_hours = excluded.weekly_hours,
            completed_json = excluded.completed_json,
            updated_at = excluded.updated_at
        """,
        (
            user_id,
            learner_state["goal"],
            learner_state["hours"],
            json.dumps(learner_state["completed"]),
            int(time.time()),
        ),
    )


def read_state(connection, user_id):
    row = connection.execute(
        "SELECT goal, weekly_hours, completed_json FROM learner_state WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        return dict(EMPTY_STATE)
    return {
        "goal": row["goal"],
        "hours": row["weekly_hours"],
        "completed": json.loads(row["completed_json"]),
    }


def current_user(connection):
    user_id = session.get("user_id")
    if not user_id:
        return None
    return connection.execute(
        "SELECT id, email, pro_until FROM users WHERE id = ?", (user_id,)
    ).fetchone()


def valid_email(email):
    return (
        isinstance(email, str)
        and len(email) <= 254
        and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) is not None
    )


def payload():
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else {}


init_db()


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/service-worker.js")
def service_worker():
    response = send_from_directory("static", "service-worker.js", mimetype="application/javascript")
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/api/auth/me")
def auth_me():
    with connect_db() as connection:
        user = current_user(connection)
        if user is None:
            return jsonify(authenticated=False)
        return jsonify(
            authenticated=True,
            email=user["email"],
            pro_until=user["pro_until"],
            state=read_state(connection, user["id"]),
        )


@app.post("/api/auth/register")
def register():
    data = payload()
    email = data.get("email", "").strip().lower() if isinstance(data.get("email"), str) else ""
    password = data.get("password")
    learner_state = normalize_state(data.get("state", EMPTY_STATE))
    if not valid_email(email):
        return jsonify(error="Enter a valid email address."), 400
    if not isinstance(password, str) or len(password) < 10:
        return jsonify(error="Use a password with at least 10 characters."), 400
    if len(password) > 1024:
        return jsonify(error="Password is too long."), 400
    if learner_state is None:
        return jsonify(error="The saved learning progress is invalid. Refresh and try again."), 400

    try:
        with connect_db() as connection:
            cursor = connection.execute(
                "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
                (email, generate_password_hash(password), int(time.time())),
            )
            user_id = cursor.lastrowid
            save_state(connection, user_id, learner_state)
    except sqlite3.IntegrityError:
        return jsonify(error="An account with that email already exists. Sign in instead."), 409

    session.clear()
    session["user_id"] = user_id
    return jsonify(authenticated=True, email=email, pro_until=0, state=learner_state), 201


@app.post("/api/auth/login")
def login():
    data = payload()
    email = data.get("email", "").strip().lower() if isinstance(data.get("email"), str) else ""
    password = data.get("password")
    if not valid_email(email) or not isinstance(password, str):
        return jsonify(error="Check your email and password and try again."), 401

    with connect_db() as connection:
        user = connection.execute(
            "SELECT id, email, password_hash, pro_until FROM users WHERE email = ?",
            (email,),
        ).fetchone()
        if user is None or not check_password_hash(user["password_hash"], password):
            return jsonify(error="Check your email and password and try again."), 401
        learner_state = read_state(connection, user["id"])

    session.clear()
    session["user_id"] = user["id"]
    return jsonify(
        authenticated=True,
        email=user["email"],
        pro_until=user["pro_until"],
        state=learner_state,
    )


@app.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify(authenticated=False)


@app.get("/api/config")
def public_config():
    payments_available = not LIVE or (
        bool(os.environ.get("ISW_MERCHANT_CODE"))
        and bool(os.environ.get("ISW_PAY_ITEM_ID"))
        and MERCHANT_CODE != "MX6072"
        and PAY_ITEM_ID != "9405967"
    )
    return jsonify(
        payment_mode="LIVE" if LIVE else "TEST",
        payments_available=payments_available,
    )


@app.get("/api/status")
def status():
    with connect_db() as connection:
        user = current_user(connection)
        if user is not None:
            return jsonify(
                pro=user["pro_until"] > time.time(),
                ref=session.get("ref", ""),
                authenticated=True,
            )
    return jsonify(
        pro=session.get("pro_until", 0) > time.time(),
        ref=session.get("ref", ""),
        authenticated=False,
    )


@app.post("/api/state")
def update_state():
    learner_state = normalize_state(payload().get("state"))
    if learner_state is None:
        return jsonify(error="The learning progress is invalid. Refresh and try again."), 400
    with connect_db() as connection:
        user = current_user(connection)
        if user is None:
            return jsonify(error="Sign in to sync progress across devices."), 401
        save_state(connection, user["id"], learner_state)
    return jsonify(saved=True)


@app.post("/api/start-payment")
def start_payment():
    data = payload()
    plan = PLANS.get(data.get("plan"))
    if plan is None:
        return jsonify(error="Choose an available plan."), 400
    if LIVE and (
        MERCHANT_CODE == "MX6072"
        or PAY_ITEM_ID == "9405967"
        or not os.environ.get("ISW_MERCHANT_CODE")
        or not os.environ.get("ISW_PAY_ITEM_ID")
    ):
        return jsonify(error="Live payments are not configured. Contact the site administrator."), 503

    with connect_db() as connection:
        user = current_user(connection)
        if user is None:
            return jsonify(error="Create a free account or sign in before subscribing."), 401
        ref = "FGX-" + uuid.uuid4().hex[:16]
        connection.execute(
            "INSERT INTO payments (txn_ref, user_id, amount, email, created_at) VALUES (?, ?, ?, ?, ?)",
            (ref, user["id"], plan["amount"], user["email"], int(time.time())),
        )

    return jsonify(
        action=PAY_URL,
        fields={
            "merchant_code": MERCHANT_CODE,
            "pay_item_id": PAY_ITEM_ID,
            "txn_ref": ref,
            "amount": str(plan["amount"]),
            "currency": "566",
            "cust_email": user["email"],
            "pay_item_name": plan["name"],
            "site_redirect_url": PUBLIC_URL + "/payment-response",
        },
    )


@app.route("/payment-response", methods=["POST", "GET"])
def payment_response():
    ref = request.values.get("txnref") or request.values.get("txn_ref") or ""
    with connect_db() as connection:
        order = connection.execute(
            "SELECT txn_ref, user_id, amount, paid FROM payments WHERE txn_ref = ?",
            (ref,),
        ).fetchone()
    if order is None:
        return redirect("/?failed=1", code=303)

    ok = bool(order["paid"])
    if not ok:
        try:
            response = requests.get(
                QUERY_URL,
                params={
                    "merchantcode": MERCHANT_CODE,
                    "transactionreference": ref,
                    "amount": order["amount"],
                },
                headers={"Content-Type": "application/json"},
                timeout=20,
            )
            response.raise_for_status()
            result = response.json()
            ok = (
                result.get("ResponseCode") == "00"
                and int(result.get("Amount", -1)) == order["amount"]
            )
        except (
            requests.RequestException,
            ValueError,
            TypeError,
            AttributeError,
        ):
            app.logger.exception("Could not verify Interswitch payment %s", ref)

    if not ok:
        return redirect("/?failed=1", code=303)

    with connect_db() as connection:
        claimed_order = connection.execute(
            "UPDATE payments SET paid = 1 WHERE txn_ref = ? AND paid = 0", (ref,)
        )
        user = connection.execute(
            "SELECT pro_until FROM users WHERE id = ?", (order["user_id"],)
        ).fetchone()
        if user is not None:
            pro_until = user["pro_until"]
            if claimed_order.rowcount:
                pro_until = max(pro_until, int(time.time())) + 30 * 86400
                connection.execute(
                    "UPDATE users SET pro_until = ? WHERE id = ?",
                    (pro_until, order["user_id"]),
                )
            if session.get("user_id") == order["user_id"]:
                session["pro_until"] = pro_until
                session["ref"] = ref
    return redirect("/?paid=1", code=303)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
