# admin_app.py
import os
from flask import Flask, request, jsonify, send_from_directory
import requests
from flask_cors import CORS
from flask_socketio import SocketIO
from db import get_users
from db import (
    find_user_by_name_and_employee,
    register_user,
    find_user_by_uid,
    count_users_by_access_level,
    trigger_buzzer_event
)

# -------------------------------------------------
# FLASK CONFIG
# -------------------------------------------------
app = Flask(__name__, static_folder="../frontend", static_url_path="")
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

# -------------------------------------------------
# HEALTH CHECK
# -------------------------------------------------
@app.route("/health")
def health():
    return "OK", 200

# -------------------------------------------------
# SERVE FRONTEND
# -------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

# -------------------------------------------------
# ESP32 → Server: Tap Card
# -------------------------------------------------
@app.route("/api/tap", methods=["POST"])
def tap_card():
    data = request.get_json() or {}
    
    uid = data.get("uid")
    reader_cottage = data.get("reader_cottage")
    
    if not uid:
        return jsonify({"error": "missing uid"}), 400
    if not reader_cottage:
        return jsonify({"error": "missing reader_cottage"}), 400

    trigger_buzzer_event(uid)
    socketio.emit("card_tapped", {"uid": uid})
    user = find_user_by_uid(uid)

    return jsonify({
        "status": "ok",
        "registered": bool(user),
        "user": user
    })



@app.route("/api/users")
def get_all_users():
    cottage = request.args.get("cottage")
    sort_by = request.args.get("sort")

    users = get_users(cottage=cottage, sort_by=sort_by)
    return jsonify(users)
# -------------------------------------------------
# ESP32 CHECK ACCESS
# -------------------------------------------------
@app.route("/api/check_access", methods=["POST"])
def check_access():
    data = request.get_json() or {}

    uid = data.get("uid")
    reader_cottage = data.get("reader_cottage")

    if not uid or not reader_cottage:
        return jsonify({"error": "missing data"}), 400

    user = find_user_by_uid(uid)

    if not user:
        socketio.emit("card_tapped", {
            "uid": uid,
            "access": "denied",
            "reason": "Card not registered"
        })
        return jsonify({"access": "denied"})

    if user.get("cottage") != reader_cottage:
        socketio.emit("card_tapped", {
            "uid": uid,
            "access": "denied",
            "reason": "Wrong cottage"
        })
        return jsonify({"access": "denied"})

    socketio.emit("card_tapped", {
        "uid": uid,
        "access": "granted",
        "reason": "Access granted"
    })

    return jsonify({"access": "granted"})


# -------------------------------------------------
# Admin → Login User (for Mobile App)
# -------------------------------------------------
@app.route("/api/login_user", methods=["POST"])
def login_user():
    data = request.get_json() or {}
    name = data.get("name")
    employee_id = data.get("employee_id")

    if not name or not employee_id:
        return jsonify({"success": False, "message": "name and employee_id required"}), 400

    # Use helper function
    user = find_user_by_name_and_employee(name, employee_id)

    if not user:
        return jsonify({"success": False, "message": "User not found"}), 401

    return jsonify({
        "success": True,
        "user": {
            "name": user.get("name"),
            "employee_id": user.get("employee_id"),
            "access_level": user.get("access_level"),
            "cottage": user.get("cottage")
        }
    })

# -------------------------------------------------
# Admin → Register Card
# -------------------------------------------------
@app.route("/api/register_card", methods=["POST"])
def register_card():
    data = request.get_json() or {}

    uid = data.get("uid")
    name = data.get("name")
    employee_id = data.get("employee_id")
    access_level = data.get("access_level")
    valid_until = data.get("valid_until")
    cottage = data.get("cottage")

    if not uid or not name:
        return jsonify({"error": "uid and name required"}), 400

    doc = {
        "uid": uid,
        "name": name,
        "employee_id": employee_id,
        # ✅ SAFETY: force lowercase + default guest
        "access_level": access_level.lower() if access_level else "guest",
        "valid_until": valid_until,
        "cottage": cottage
    }

    register_user(doc)

    return jsonify({"status": "saved"})


# -------------------------------------------------
# DASHBOARD: Get counts by access level
# -------------------------------------------------
# -------------------------------------------------
# DASHBOARD: Get counts by access level (mapped for graph)
# -------------------------------------------------
@app.route("/api/user_counts")
def user_counts():
    counts = count_users_by_access_level()
    print("User counts:", counts)
    return jsonify(counts)


# -------------------------------------------------
# USER LOGIN (UID + NAME) → RFID login
# -------------------------------------------------
@app.route("/api/rfid/login", methods=["POST"])
def login_rfid():
    data = request.get_json() or {}

    uid = data.get("uid")
    name = data.get("name")

    if not uid or not name:
        return jsonify({"error": "uid and name required"}), 400

    user = find_user_by_uid(uid)

    if not user:
        return jsonify({
            "success": False,
            "message": "User not found"
        }), 401

    # Case-insensitive name check
    if user.get("name", "").lower() != name.lower():
        return jsonify({
            "success": False,
            "message": "Invalid credentials"
        }), 401

    return jsonify({
        "success": True,
        "user": {
            "uid": user.get("uid"),
            "name": user.get("name"),
            "access_level": user.get("access_level"),
            "cottage": user.get("cottage")
        }
    })

PI_IP = "http://192.168.100.180:5000"  # your Pi's HTTP server

@app.route("/api/pi/6am")
def pi_6am():
    try:
        resp = requests.get(f"{PI_IP}/6am", timeout=5)
        return {"status": "ok", "pi_response": resp.text}
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

@app.route("/api/pi/6pm")
def pi_6pm():
    try:
        resp = requests.get(f"{PI_IP}/6pm", timeout=5)
        return {"status": "ok", "pi_response": resp.text}
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

# -------------------------------------------------
# RUN SERVER
# -------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    socketio.run(app, host="0.0.0.0", port=port)
