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

GPIO.setmode(GPIO.BOARD)
GPIO.setwarnings(False)

# motor pin
GPIO.setup(11, GPIO.OUT)

# ir pins
GPIO.setup(13, GPIO.IN)  # IR1
GPIO.setup(16, GPIO.IN)  # IR2
GPIO.setup(15, GPIO.IN)  # IR3 - vehicle passed gate (new)

gate_pin = GPIO.PWM(11, 50)

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

def get_vehicle_reg_number(image_path):
    try:
        endpoint = os.environ["VISION_ENDPOINT"]
        key = os.environ["VISION_KEY"]
    except KeyError:
        print("Missing environment variable 'VISION_ENDPOINT' or 'VISION_KEY'")
        exit()

    client = ImageAnalysisClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(key)
    )

    with open(image_path, "rb") as f:
        image_data = f.read()

    result = client.analyze(
        image_data=image_data,
        visual_features=[VisualFeatures.READ]
    )
    print(result)

    vehicle_reg_number = None
    if result.read is not None:
        if len(result.read.blocks) > 0:
            for line in result.read.blocks[0].lines:
                print(f"Line: '{line.text}'")
                vehicle_reg_number = line.text
        else:
            print("No vehicle detected!")
    else:
        print("OCR operation failed or timed out")

    return vehicle_reg_number

def get_db_connection():
    try:
        DB_HOST = os.environ["DB_HOST"]
        DB_NAME = os.environ["DB_NAME"]
        DB_PASSWORD = os.environ["DB_PASSWORD"]
        DB_PORT = os.environ["DB_PORT"]
        DB_USER = os.environ["DB_USER"]
        return psycopg2.connect(
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT,
        )
    except Exception as error:
        print("An exception occurred when connecting to the DB: ", error)
        return False

def open_gate():
    gate_pin.start(0)
    gate_pin.ChangeDutyCycle(3)  # Unlock or rotate to open
    sleep(1)
    gate_pin.ChangeDutyCycle(12)  # Keep it open
    sleep(1)
    gate_pin.stop()
    print("Gate opened.")

def close_gate():
    gate_pin.start(0)
    gate_pin.ChangeDutyCycle(12)  # Adjust as per servo
    sleep(1)
    gate_pin.ChangeDutyCycle(3)
    sleep(1)
    gate_pin.stop()
    print("Gate closed.")


def get_vehicle_status(vehicle_reg_number):
    conn = get_db_connection()
    if conn:
        print("DB connected.")
    else:
        print("Unable to connect DB")
        return False

    curr = conn.cursor()
    curr.execute("SELECT * FROM vehicles WHERE vehicle_no = %s", (vehicle_reg_number,))
    data = curr.fetchall()
    conn.close()

    if len(data) > 0:
        return True
    return False

def get_meter_reading_with_retry(camera_device, max_attempts=3):
    from azure.ai.vision import ImageAnalysisClient, AzureKeyCredential, VisualFeatures
    import os

    attempt = 0

    while attempt < max_attempts:
        print(f"Attempt {attempt + 1} to capture meter reading...")

        image_name = capture_image("meter", camera_device)
        image_path = f"images/meter_readings/{image_name}.jpg"

        try:
            endpoint = os.environ["VISION_ENDPOINT"]
            key = os.environ["VISION_KEY"]
        except KeyError:
            print("Missing environment variable 'VISION_ENDPOINT' or 'VISION_KEY'")
            return None, None

        client = ImageAnalysisClient(
            endpoint=endpoint,
            credential=AzureKeyCredential(key)
        )

        with open(image_path, "rb") as f:
            image_data = f.read()

        result = client.analyze(
            image_data=image_data,
            visual_features=[VisualFeatures.READ]
        )

        if result.read is not None and result.read.blocks:
            lines = result.read.blocks[0].lines
            print("OCR Lines:")
            for line in lines:
                print(f"Line: '{line.text}'")

            rupees, litres = None, None

            for i, line in enumerate(lines):
                text = line.text.lower().strip()
                if "rupees" in text and i + 1 < len(lines):
                    raw = lines[i + 1].text.strip()
                    try:
                        rupees = float("".join(c for c in raw if c.isdigit() or c == "."))
                    except ValueError:
                        print(f"[!] Couldn't parse Rupees from '{raw}'")
                elif "litres" in text and i + 1 < len(lines):
                    raw = lines[i + 1].text.strip()
                    try:
                        litres = float("".join(c for c in raw if c.isdigit() or c == "."))
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
            (vehicle_no, gate_open_time, exit_time, amount, litres)
        )
        conn.commit()
        print("Vehicle exit logged successfully.")
    except Exception as e:
        print("Error logging vehicle data:", e)
    finally:
        conn.close()



def main():
    try:
        while True:
            print("Waiting for vehicle arrival (IR1)...")
            GPIO.wait_for_edge(13, GPIO.FALLING)
            print("Vehicle arrived at gate.")

            image_name = capture_image("vehicle")
            if image_name is None:
                continue

            image_path = f"images/vehicle_reg_numbers/{image_name}.jpg"
            vehicle_reg_number = get_vehicle_reg_number(image_path)
            print("Vehicle number:", vehicle_reg_number)

            if get_vehicle_status(vehicle_reg_number):
                gate_open_time = datetime.now()
                print("Valid vehicle. Opening gate...")
                open_gate()

                print("Waiting for vehicle to fully enter (IR3)...")
                GPIO.wait_for_edge(15, GPIO.FALLING)
                print("Vehicle fully entered. Closing gate...")
                close_gate()

                print("Waiting for vehicle to exit (IR2)...")
                GPIO.wait_for_edge(16, GPIO.FALLING)
                exit_time = datetime.now()
                print("Vehicle exit detected.")

                amount, litres = get_meter_reading_with_retry("/dev/video2")
                print("Amount:", amount)
                print("Litres:", litres)

                log_vehicle_exit(vehicle_reg_number, gate_open_time, exit_time, amount, litres)
            else:
                print("Vehicle not registered.")
    finally:
        print("Cleaning up GPIO...")
        GPIO.cleanup()


if __name__ == "__main__":
    main()