import pygame
import pygame.camera
import os
import uuid
from dotenv import load_dotenv

load_dotenv()

from azure.ai.vision.imageanalysis import ImageAnalysisClient
from azure.ai.vision.imageanalysis.models import VisualFeatures
from azure.core.credentials import AzureKeyCredential

import psycopg2
import RPi.GPIO as GPIO
from time import sleep
from datetime import datetime

import smtplib
from email.message import EmailMessage

# === GPIO SETUP ===
GPIO.setmode(GPIO.BOARD)
GPIO.setwarnings(False)

# motor pin
GPIO.setup(11, GPIO.OUT)

# IR sensor pins
GPIO.setup(13, GPIO.IN)  # IR1
GPIO.setup(16, GPIO.IN)  # IR2
GPIO.setup(15, GPIO.IN)  # IR3

gate_pin = GPIO.PWM(11, 50)


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


# === DATABASE CONNECTION ===
def get_db_connection():
    try:
        return psycopg2.connect(
            database=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            host=os.environ["DB_HOST"],
            port=os.environ["DB_PORT"],
        )
    except Exception as error:
        print("DB connection error:", error)
        return False


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


# === VEHICLE STATUS CHECK ===
def get_vehicle_status(vehicle_reg_number):
    conn = get_db_connection()
    if not conn:
        print("Unable to connect DB")
        return False
    curr = conn.cursor()

    # Normalize the OCR result
    normalized_reg = vehicle_reg_number.replace(" ", "").upper()

    # Fetch all vehicle numbers from DB and compare normalized
    curr.execute("SELECT vehicle_no FROM vehicles")
    rows = curr.fetchall()
    conn.close()

    # Check if any stored vehicle number (normalized) matches
    for (db_reg,) in rows:
        if db_reg.replace(" ", "").upper() == normalized_reg:
            return True
    return False


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


# === VEHICLE EXIT LOGGING ===
def log_vehicle_exit(vehicle_no, gate_open_time, exit_time, amount, litres):
    conn = get_db_connection()
    if not conn:
        print("Failed to log vehicle: DB connection failed.")
        return

    try:
        curr = conn.cursor()
        curr.execute(
            """
            INSERT INTO vehicle_logs (vehicle_no, gate_open_time, exit_time, amount, litres)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (vehicle_no, gate_open_time, exit_time, amount, litres),
        )
        conn.commit()
        print("Vehicle exit logged successfully.")
    except Exception as e:
        print("Error logging vehicle data:", e)
    finally:
        conn.close()


# === GET OWNER EMAIL ===
def get_owner_email_postgres(vehicle_reg_number):
    try:
        conn = psycopg2.connect(
            database=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            host=os.environ["DB_HOST"],
            port=os.environ["DB_PORT"],
        )
        curr = conn.cursor()
        curr.execute(
            """
            SELECT owner_email FROM public.vehicles 
            WHERE REPLACE(UPPER(vehicle_no), ' ', '') = REPLACE(UPPER(%s), ' ', '') 
            LIMIT 1
            """,
            (vehicle_reg_number,),
        )
        row = curr.fetchone()
        conn.close()
        if row:
            return row[0]
    except Exception as error:
        print("DB connection error (Postgres owner_email):", error)
    return None


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
            sleep(0.5)  # Debounce
            print("Vehicle arrived at gate.")

            # Add 5 second delay before capturing image
            print("Waiting 5 seconds before capturing vehicle image...")
            sleep(5)

            # Try to capture vehicle number up to 3 times
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

            if get_vehicle_status(vehicle_reg_number):
                gate_open_time = datetime.now()
                print("Valid vehicle. Opening gate...")
                open_gate()

                print("Waiting for vehicle to fully enter (IR2)...")
                GPIO.wait_for_edge(16, GPIO.FALLING)  # 15 to 16
                sleep(0.5)
                print("Vehicle fully entered. Closing gate...")
                close_gate()

                print("Waiting for vehicle to exit (IR3)...")
                GPIO.wait_for_edge(15, GPIO.FALLING)  # 16 to 15
                sleep(0.5)
                exit_time = datetime.now()
                print("Vehicle exit detected.")

                amount, litres = get_meter_reading_with_retry("/dev/video2")
                print("Amount:", amount)
                print("Litres:", litres)

                log_vehicle_exit(
                    vehicle_reg_number, gate_open_time, exit_time, amount, litres
                )

                # === Send owner email notification ===
                owner_email = get_owner_email_postgres(vehicle_reg_number)
                if owner_email:
                    subject = "Fuel Station: Vehicle Exit Notification"
                    content = (
                        f"Dear customer,\n\n"
                        f"Your vehicle ({vehicle_reg_number}) exited the fuel station at {exit_time.strftime('%Y-%m-%d %H:%M:%S')}.\n"
                        f"Amount: Rs. {amount}\n"
                        f"Litres: {litres}\n\n"
                        f"Thank you for using our service."
                    )
                    send_email(owner_email, subject, content)
                else:
                    print("Owner email not found for this vehicle.")

            else:
                print("Vehicle not registered.")
    finally:
        print("Cleaning up GPIO...")
        GPIO.cleanup()


if __name__ == "__main__":
    main()
