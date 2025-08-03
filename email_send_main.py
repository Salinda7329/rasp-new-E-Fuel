import pygame
import pygame.camera
import os
import uuid
from dotenv import load_dotenv

load_dotenv()

from azure.ai.vision.imageanalysis import ImageAnalysisClient
from azure.ai.vision.imageanalysis.models import VisualFeatures
from azure.core.credentials import AzureKeyCredential

from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from bson.objectid import ObjectId
import RPi.GPIO as GPIO
from time import sleep
from datetime import datetime

import smtplib
from email.message import EmailMessage

# === GPIO SETUP ===
GPIO.setmode(GPIO.BOARD)
GPIO.setwarnings(False)
GPIO.setup(11, GPIO.OUT)
GPIO.setup(13, GPIO.IN)  # IR1
GPIO.setup(16, GPIO.IN)  # IR2
GPIO.setup(15, GPIO.IN)  # IR3
gate_pin = GPIO.PWM(11, 50)


# === MONGODB CONNECTION WITH ERROR HANDLING ===
def get_mongo_client():
    uri = os.environ.get("MONGODB_URI")
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=3000)
        client.admin.command("ping")
        return client
    except ConnectionFailure as e:
        print("MongoDB connection failed:", e)
        return None


# === IMAGE CAPTURE ===
def capture_image(type="vehicle", camera_device="/dev/video0"):
    pygame.camera.init()
    cam = pygame.camera.Camera(camera_device, (640, 480))
    image_name = str(uuid.uuid4())
    if type == "vehicle":
        image_path = f"images/vehicle_reg_numbers/{image_name}.jpg"
    elif type == "meter":
        image_path = f"images/meter_readings/{image_name}.jpg"
    else:
        print("Invalid capture type")
        return None
    cam.start()
    image = cam.get_image()
    pygame.image.save(image, image_path)
    cam.stop()
    return image_name


# === VISION CLIENT ===
def get_vision_client():
    try:
        endpoint = os.environ["VISION_ENDPOINT"]
        key = os.environ["VISION_KEY"]
    except KeyError:
        print("Missing environment variable 'VISION_ENDPOINT' or 'VISION_KEY'")
        exit()
    return ImageAnalysisClient(endpoint=endpoint, credential=AzureKeyCredential(key))


# === VEHICLE NUMBER OCR ===
def get_vehicle_reg_number(image_path):
    client = get_vision_client()
    with open(image_path, "rb") as f:
        image_data = f.read()
    result = client.analyze(
        image_data=image_data, visual_features=[VisualFeatures.READ]
    )
    vehicle_reg_number = None
    if result.read and result.read.blocks:
        for line in result.read.blocks[0].lines:
            print(f"Line: '{line.text}'")
            vehicle_reg_number = line.text
    else:
        print("OCR operation failed or no text detected.")
    return vehicle_reg_number


# === GATE CONTROL ===
def open_gate():
    gate_pin.start(0)
    gate_pin.ChangeDutyCycle(3)
    sleep(1)
    gate_pin.ChangeDutyCycle(12)
    sleep(1)
    gate_pin.stop()
    print("Gate opened.")


def close_gate():
    gate_pin.start(0)
    gate_pin.ChangeDutyCycle(12)
    sleep(1)
    gate_pin.ChangeDutyCycle(3)
    sleep(1)
    gate_pin.stop()
    print("Gate closed.")


# === VEHICLE STATUS CHECK (MONGO) ===
def get_vehicle_status(vehicle_reg_number):
    client = get_mongo_client()
    if client is None:
        return None
    try:
        db = client["fill_and_go"]
        vehicles = db.vehicles
        normalized = vehicle_reg_number.replace(" ", "").upper()
        vehicle = vehicles.find_one(
            {
                "$expr": {
                    "$eq": [
                        {
                            "$replaceAll": {
                                "input": {"$toUpper": "$vehicle_number"},
                                "find": " ",
                                "replacement": "",
                            }
                        },
                        normalized,
                    ]
                },
                "status": 1,
            }
        )
        return vehicle
    except Exception as e:
        print("MongoDB error in get_vehicle_status:", e)
        return None
    finally:
        client.close()


# === GET ACCOUNT BALANCE (MIN BALANCE CHECK) ===
def get_account_balance(user_id):
    client = get_mongo_client()
    if client is None:
        return None
    try:
        db = client["fill_and_go"]
        accounts = db.accounts
        account = accounts.find_one({"user_id": user_id})
        if not account:
            return None
        return float(account.get("balance", 0))
    except Exception as e:
        print("MongoDB error in get_account_balance:", e)
        return None
    finally:
        client.close()


# === GET CUSTOMER EMAIL FROM MONGO ===
def get_customer_email(user_id):
    client = get_mongo_client()
    if client is None:
        return None
    try:
        db = client["fill_and_go"]
        users = db.users
        user = users.find_one({"_id": ObjectId(user_id)})
        return user.get("email") if user else None
    except Exception as e:
        print("MongoDB error in get_customer_email:", e)
        return None
    finally:
        client.close()


# === DEDUCT ACCOUNT BALANCE ===
def deduct_account_balance(user_id, amount):
    client = get_mongo_client()
    if client is None:
        return False, None
    try:
        db = client["fill_and_go"]
        accounts = db.accounts
        account = accounts.find_one({"user_id": user_id})
        if not account:
            return False, None
        current_balance = float(account.get("balance", 0))
        if current_balance < amount:
            return False, current_balance
        new_balance = current_balance - amount
        accounts.update_one(
            {"user_id": user_id},
            {"$set": {"balance": new_balance, "updated_at": datetime.utcnow()}},
        )
        return True, new_balance
    except Exception as e:
        print("MongoDB error in deduct_account_balance:", e)
        return False, None
    finally:
        client.close()


# === METER READING OCR ===
def get_meter_reading_with_retry(camera_device, max_attempts=3):
    client = get_vision_client()
    attempt = 0
    while attempt < max_attempts:
        print(f"Attempt {attempt + 1} to capture meter reading...")
        image_name = capture_image("meter", camera_device)
        image_path = f"images/meter_readings/{image_name}.jpg"
        with open(image_path, "rb") as f:
            image_data = f.read()
        result = client.analyze(
            image_data=image_data, visual_features=[VisualFeatures.READ]
        )
        if result.read and result.read.blocks:
            lines = result.read.blocks[0].lines
            if not lines:
                print("No lines found in OCR result.")
                attempt += 1
                continue
            print("OCR Lines:")
            for line in lines:
                print(f"Line: '{line.text}'")
            rupees = None
            litres = None
            for i, line in enumerate(lines):
                text = line.text.lower().strip()
                if "rupees" in text and i + 1 < len(lines):
                    raw = lines[i + 1].text.strip().replace(",", "")
                    try:
                        rupees = float(
                            "".join(c for c in raw if c.isdigit() or c == ".")
                        )
                    except ValueError:
                        print(f"[!] Couldn't parse Rupees from '{raw}'")
                elif "litres" in text and i + 1 < len(lines):
                    raw = lines[i + 1].text.strip().replace(",", "")
                    try:
                        litres = float(
                            "".join(c for c in raw if c.isdigit() or c == ".")
                        )
                    except ValueError:
                        print(f"[!] Couldn't parse Litres from '{raw}'")
            if rupees is not None and litres is not None:
                print("OCR success.")
                return rupees, litres
            else:
                print("Rupees or litres not detected correctly.")
        else:
            print("OCR returned no results.")
        attempt += 1
        print("Retrying...\n")
    print("All attempts failed.")
    return None, None


# === LOG VEHICLE EXIT ===
def log_vehicle_exit(vehicle_no, gate_open_time, exit_time, amount, litres, user_id):
    client = get_mongo_client()
    if client is None:
        print("Vehicle log failed: MongoDB connection error.")
        return
    try:
        db = client["fill_and_go"]
        vehicle_logs = db.vehicle_logs
        log_entry = {
            "vehicle_number": vehicle_no,
            "gate_open_time": gate_open_time.isoformat(),
            "exit_time": exit_time.isoformat(),
            "amount": amount,
            "litres": litres,
            "user_id": user_id,
            "created_at": datetime.utcnow().isoformat(),
        }
        vehicle_logs.insert_one(log_entry)
        print("Vehicle exit logged successfully.")
    except Exception as e:
        print("MongoDB error in log_vehicle_exit:", e)
    finally:
        client.close()


# === SEND EMAIL NOTIFICATION ===
def send_email(to_email, subject, content):
    GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
    GMAIL_PASSWORD = os.environ.get("GMAIL_PASSWORD")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = to_email
    msg.set_content(content)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(GMAIL_ADDRESS, GMAIL_PASSWORD)
            smtp.send_message(msg)
        print(f"Email sent to {to_email}")
    except Exception as e:
        print("Email failed:", e)


# === MAIN LOGIC ===
def main():
    try:
        while True:
            print("Waiting for vehicle arrival (IR1)...")
            GPIO.wait_for_edge(13, GPIO.FALLING)
            sleep(0.5)
            print("Vehicle arrived at gate.")

            print("Waiting 5 seconds before capturing vehicle image...")
            sleep(5)

            vehicle_reg_number = None
            for attempt in range(3):
                print(f"Vehicle number plate capture attempt {attempt + 1}...")
                image_name = capture_image("vehicle")
                if image_name is None:
                    print("Image capture failed, retrying...")
                    continue
                image_path = f"images/vehicle_reg_numbers/{image_name}.jpg"
                vehicle_reg_number = get_vehicle_reg_number(image_path)
                if vehicle_reg_number:
                    print(f"Vehicle number detected: {vehicle_reg_number}")
                    break
                else:
                    print("Failed to detect vehicle number, retrying...")
            if not vehicle_reg_number:
                print("Failed to capture vehicle number after 3 attempts. Skipping...")
                continue

            vehicle = get_vehicle_status(vehicle_reg_number)
            if vehicle is None:
                print("Could not query vehicle status: MongoDB error.")
                continue
            if not vehicle:
                print("Vehicle not registered.")
                continue

            user_id = vehicle["user_id"]
            balance = get_account_balance(user_id)
            if balance is None:
                print("Could not fetch account balance or account not found.")
                continue
            if balance < 500:
                print(f"Insufficient minimum balance. Current balance: Rs. {balance}")
                continue

            gate_open_time = datetime.now()
            print("Valid vehicle. Opening gate...")
            open_gate()

            print("Waiting for vehicle to fully enter (IR2)...")
            GPIO.wait_for_edge(16, GPIO.FALLING)
            sleep(0.5)
            print("Vehicle fully entered. Closing gate...")
            close_gate()

            print("Waiting for vehicle to exit (IR3)...")
            GPIO.wait_for_edge(15, GPIO.FALLING)
            sleep(0.5)
            exit_time = datetime.now()
            print("Vehicle exit detected.")

            amount, litres = get_meter_reading_with_retry("/dev/video2")
            print("Amount:", amount)
            print("Litres:", litres)

            if amount is None or litres is None:
                print("Meter reading failed. Skipping log and email.")
                continue

            # Deduct account balance
            success, new_balance = deduct_account_balance(user_id, amount)
            if not success:
                print(
                    f"Insufficient balance or MongoDB error. Current balance: {new_balance}"
                )
                continue

            log_vehicle_exit(
                vehicle_reg_number, gate_open_time, exit_time, amount, litres, user_id
            )
            print(f"Vehicle exit logged. Deducted {amount}. New balance: {new_balance}")

            customer_email = get_customer_email(user_id)
            if customer_email:
                subject = "Fuel Station: Vehicle Exit Notification"
                content = (
                    f"Dear customer,\n\n"
                    f"Your vehicle ({vehicle_reg_number}) exited the fuel station at {exit_time.strftime('%Y-%m-%d %H:%M:%S')}.\n"
                    f"Amount: Rs. {amount}\n"
                    f"Litres: {litres}\n"
                    f"Current balance: Rs. {new_balance}\n\n"
                    f"Thank you for using our service."
                )
                send_email(customer_email, subject, content)
            else:
                print("Customer email not found or MongoDB error.")

    finally:
        print("Cleaning up GPIO...")
        GPIO.cleanup()


if __name__ == "__main__":
    main()
