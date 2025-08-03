import os
from dotenv import load_dotenv
from pymongo import MongoClient
from bson.objectid import ObjectId
import smtplib
from email.message import EmailMessage
from datetime import datetime

# Your other imports for GPIO, vision, pygame, etc. remain as before...
# import pygame
# import pygame.camera
# import RPi.GPIO as GPIO
# ... etc.

load_dotenv()

# === MONGODB CONNECTION ===
def get_mongo_client():
    uri = os.environ.get('MONGODB_URI')
    return MongoClient(uri)

# === EMAIL SENDER ===
def send_email(to_email, subject, content):
    GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
    GMAIL_PASSWORD = os.environ.get("GMAIL_PASSWORD")

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = GMAIL_ADDRESS
    msg['To'] = to_email
    msg.set_content(content)

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(GMAIL_ADDRESS, GMAIL_PASSWORD)
            smtp.send_message(msg)
        print(f"Email sent to {to_email}")
    except Exception as e:
        print("Email failed:", e)

# === VEHICLE STATUS CHECK ===
def get_vehicle_status(vehicle_reg_number):
    client = get_mongo_client()
    db = client["fill_and_go"]
    vehicles = db.vehicles
    vehicle = vehicles.find_one({"vehicle_number": vehicle_reg_number, "status": 1})
    client.close()
    return vehicle

# === DEDUCT ACCOUNT BALANCE ===
def deduct_account_balance(user_id, amount):
    client = get_mongo_client()
    db = client["fill_and_go"]
    accounts = db.accounts

    account = accounts.find_one({"user_id": user_id})
    if not account:
        client.close()
        return False, None

    current_balance = float(account.get('balance', 0))
    if current_balance < amount:
        client.close()
        return False, current_balance

    new_balance = current_balance - amount
    accounts.update_one({"user_id": user_id}, {"$set": {"balance": new_balance, "updated_at": datetime.utcnow()}})
    client.close()
    return True, new_balance

# === GET CUSTOMER EMAIL ===
def get_customer_email(user_id):
    client = get_mongo_client()
    db = client["fill_and_go"]
    users = db.users
    user = users.find_one({"_id": ObjectId(user_id)})
    client.close()
    return user.get("email") if user else None

# === LOG VEHICLE EXIT ===
def log_vehicle_exit(vehicle_no, gate_open_time, exit_time, amount, litres, user_id):
    client = get_mongo_client()
    db = client["fill_and_go"]
    vehicle_logs = db.vehicle_logs
    log_entry = {
        "vehicle_number": vehicle_no,
        "gate_open_time": gate_open_time.isoformat(),
        "exit_time": exit_time.isoformat(),
        "amount": amount,
        "litres": litres,
        "user_id": user_id,
        "created_at": datetime.utcnow().isoformat()
    }
    vehicle_logs.insert_one(log_entry)
    client.close()

# === MAIN LOGIC (CORE LOOP) ===
def main():
    while True:
        # This is a stub for GPIO/Camera logic
        # For demonstration, you may replace this with your detection logic
        vehicle_reg_number = input("Enter vehicle number (or 'exit'): ").strip()
        if vehicle_reg_number.lower() == 'exit':
            break

        vehicle = get_vehicle_status(vehicle_reg_number)
        if not vehicle:
            print("Vehicle not registered.")
            continue

        user_id = vehicle['user_id']
        customer_email = get_customer_email(user_id)

        # Dummy values for demo; replace with your actual OCR and sensor data:
        amount_to_deduct = float(input("Enter amount to deduct: "))
        litres = float(input("Enter litres filled: "))
        gate_open_time = datetime.now()
        exit_time = datetime.now()

        # Deduct balance
        success, new_balance = deduct_account_balance(user_id, amount_to_deduct)
        if not success:
            print(f"Insufficient balance. Current balance: {new_balance}")
            continue

        # Log exit
        log_vehicle_exit(vehicle_reg_number, gate_open_time, exit_time, amount_to_deduct, litres, user_id)
        print(f"Vehicle exit logged. Deducted {amount_to_deduct}. New balance: {new_balance}")

        # Send email
        if customer_email:
            subject = "Fuel Refill: Balance Deducted"
            content = (
                f"Dear customer,\n\n"
                f"Your vehicle ({vehicle_reg_number}) was refueled with {litres} litres.\n"
                f"Rs. {amount_to_deduct:.2f} has been deducted from your account.\n"
                f"Current balance: Rs. {new_balance:.2f}\n\n"
                f"Thank you for using our service.\n"
            )
            send_email(customer_email, subject, content)
        else:
            print("Customer email not found.")

if __name__ == "__main__":
    main()
