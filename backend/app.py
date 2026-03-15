# admin_app.py

import os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO
from datetime import datetime
import threading
import time

servo_state = {"command": "none"}

servo_schedule = {
    "hour": None,
    "minute": None,
    "command": None
}

from db import get_users
from db import (
    find_user_by_name_and_employee,
    register_user,
    find_user_by_uid,
    count_users_by_access_level,
    trigger_buzzer_event,
    get_cottage_status,
    set_cottage_status,
    get_all_cottages
)

# -------------------------------------------------
# FLASK CONFIG
# -------------------------------------------------

app = Flask(__name__, static_folder="../frontend", static_url_path="")
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")


# -------------------------------------------------
# GET ALL SMART DEVICES
# -------------------------------------------------

@app.route("/ping")
def ping():
    return "alive"

@app.route("/api/devices")
def get_devices():
    from db import get_all_devices
    devs = get_all_devices()
    return jsonify(devs)


# -------------------------------------------------
# GET RFID TAP HISTORY
# -------------------------------------------------

@app.route("/api/taps")
def get_taps():

    from db import taps

    history = list(taps.find({}, {"_id":0}).sort("ts",-1).limit(50))

    return jsonify(history)

# -------------------------------------------------
# SERVO COMMAND
# -------------------------------------------------


@app.route("/api/set_servo", methods=["POST"])
def set_servo():

    global servo_state

    data = request.get_json()

    command = data.get("command")

    if command not in ["left", "right"]:
        return jsonify({"error":"invalid command"}), 400

    servo_state["command"] = command

    return jsonify({"success":True})


@app.route("/api/get_servo")
def get_servo():

    return jsonify(servo_state)

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

# serve logs page
@app.route("/logs")
def logs_page():
    return send_from_directory(app.static_folder, "logs.html")

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

    # -----------------------------------
    # CHECK COTTAGE STATUS
    # -----------------------------------

    status = get_cottage_status(reader_cottage)

    if status == "inactive":

        socketio.emit("card_tapped", {
            "uid": uid,
            "access": "denied",
            "reason": "Cottage inactive"
        })

        return jsonify({"access": "denied"})

    # -----------------------------------
    # CHECK USER
    # -----------------------------------

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
        "access_level": access_level.lower() if access_level else "guest",
        "valid_until": valid_until,
        "cottage": cottage
    }

    register_user(doc)

    return jsonify({"status": "saved"})

@app.route("/api/set_servo_schedule", methods=["POST"])
def set_servo_schedule():

    data = request.get_json()

    servo_schedule["hour"] = data.get("hour")
    servo_schedule["minute"] = data.get("minute")
    servo_schedule["command"] = data.get("command")

    return jsonify({"success": True})

def servo_scheduler():

    global servo_state

    while True:

        now = datetime.now()

        h = now.hour
        m = now.minute

        if (
                servo_schedule["hour"] is not None and
                servo_schedule["minute"] is not None and
                servo_schedule["hour"] == h and
                servo_schedule["minute"] == m
            ):

            servo_state["command"] = servo_schedule["command"]

            print("Servo triggered:", servo_schedule["command"])

            time.sleep(60)

        time.sleep(1)
    
# -------------------------------------------------
# DASHBOARD: Get Users
# -------------------------------------------------

@app.route("/api/users")
def get_all_users():

    cottage = request.args.get("cottage")
    sort_by = request.args.get("sort")

    users = get_users(cottage=cottage, sort_by=sort_by)

    return jsonify(users)


# -------------------------------------------------
# DASHBOARD: Get counts by access level
# -------------------------------------------------

@app.route("/api/user_counts")
def user_counts():

    counts = count_users_by_access_level()

    print("User counts:", counts)

    return jsonify(counts)


# -------------------------------------------------
# USER LOGIN (RFID)
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



@app.route("/api/cottages")
def cottages():
    cottages = get_all_cottages()
    return jsonify(cottages)
# -------------------------------------------------
# COTTAGE STATUS
# -------------------------------------------------

@app.route("/api/cottage_status/<cottage>")
def cottage_status(cottage):

    status = get_cottage_status(cottage)

    return jsonify({
        "cottage": cottage,
        "status": status
    })


@app.route("/api/set_cottage_status", methods=["POST"])
def update_cottage_status():

    data = request.get_json()

    cottage = data.get("cottage")
    status = data.get("status")

    if not cottage or not status:
        return jsonify({"error": "missing data"}), 400

    set_cottage_status(cottage, status)

    return jsonify({"success": True})


# -------------------------------------------------
# RUN SERVER
# -------------------------------------------------
# -------------------------------------------------
# RUN SERVER
# -------------------------------------------------

if __name__ == "__main__":

    scheduler_thread = threading.Thread(target=servo_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()

    port = int(os.environ.get("PORT", 10000))

    socketio.run(app, host="0.0.0.0", port=port)
