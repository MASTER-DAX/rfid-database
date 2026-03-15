from pymongo import MongoClient
import os
from datetime import datetime

MONGO_URI = os.getenv("MONGO_URI")

if not MONGO_URI:
    raise RuntimeError("MONGO_URI environment variable not set")

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)

try:
    client.admin.command("ping")
    print("MongoDB connected")
except Exception as e:
    print("MongoDB connection failed:", e)
    raise

db = client["rfid_system"]

users = db["users"]
taps = db["taps"]
cottages = db["cottages"]
servo_schedule_col = db["servo_schedule"]


# ------------------------
# SMART DEVICES
# ------------------------

smart_db = client["smart_cottage"]
devices = smart_db["devices"]

def get_all_devices():
    return list(devices.find({}, {"_id": 0}))

# ------------------------
# USER OPERATIONS
# ------------------------

def get_users(cottage=None, sort_by=None):

    query = {}

    if cottage:
        query["cottage"] = cottage

    users_list = list(users.find(query, {"_id": 0}))

    if sort_by == "date_desc":

        users_list.sort(
            key=lambda x: x.get("created_at", datetime.min),
            reverse=True
        )

    elif sort_by == "access_level":

        order = {"premium": 1, "basic": 2, "guest": 3, "admin": 4}

        users_list.sort(
            key=lambda x: order.get(x.get("access_level", ""), 99)
        )

    return users_list


def find_user_by_name_and_employee(name, employee_id):

    try:
        return users.find_one(
            {
                "name": {"$regex": f"^{name}$", "$options": "i"},
                "employee_id": employee_id
            },
            {"_id": 0}
        )
    except Exception as e:
        print("DB ERROR:", e)
        return None


def register_user(doc):

    doc["created_at"] = datetime.utcnow()

    users.replace_one({"uid": doc["uid"]}, doc, upsert=True)

    return True


def find_user_by_uid(uid):

    return users.find_one({"uid": uid}, {"_id": 0})


def trigger_buzzer_event(uid):

    taps.insert_one({
        "uid": uid,
        "ts": datetime.utcnow().isoformat()
    })


# ------------------------
# DASHBOARD STATS
# ------------------------

def count_users_by_access_level():

    counts = {
        "guest": 0,
        "basic": 0,
        "premium": 0,
        "admin": 0
    }

    for user in users.find({}, {"access_level": 1}):

        level = user.get("access_level", "").lower()

        if level in counts:
            counts[level] += 1

    return counts

def set_servo_schedule(hour, minute, command):

    servo_schedule_col.update_one(
        {"type": "daily"},
        {
            "$set": {
                "hour": hour,
                "minute": minute,
                "command": command
            }
        },
        upsert=True
    )

# ------------------------
# COTTAGE STATUS
# ------------------------

def get_cottage_status(cottage):

    doc = cottages.find_one({"cottage": cottage})

    if not doc:
        return "active"

    return doc.get("status", "active")


def set_cottage_status(cottage, status):

    cottages.update_one(
        {"cottage": cottage},
        {"$set": {"status": status}},
        upsert=True
    )

def get_servo_schedule():

    return servo_schedule_col.find_one({"type": "daily"})
    
def get_all_cottages():

    return list(cottages.find({}, {"_id": 0}))
