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

GPIO.setmode(GPIO.BOARD)
GPIO.setwarnings(False)
# motor pin
GPIO.setup(11, GPIO.OUT)
# ir pins
# ir 1 
GPIO.setup(13, GPIO.IN)
# ir 2 
GPIO.setup(16, GPIO.IN)


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

    # Create an Image Analysis client
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

    vehicle_reg_number=None
    if result.read is not None:
        if len(result.read.blocks) > 0:
            for line in result.read.blocks[0].lines:
                print(f"Line: '{line.text}'")
                vehicle_reg_number=line.text
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
        print("An exception occured when connectong to the DB: ", error)
        return False
def open_gate():
    gate_pin.start(0)
    gate_pin.ChangeDutyCycle(3)
    sleep(1)
    gate_pin.ChangeDutyCycle(12)
    sleep(1)
    # p.stop()
    gate_pin.stop()
    
def get_vehicle_status(vehicle_reg_number):
    conn = get_db_connection()
    if conn:
        print("DB connected.")
    else:
        print("Unable to connect DB")
    curr = conn.cursor()
    
    curr.execute("SELECT * FROM vehicles WHERE vehicle_no = %s", (vehicle_reg_number,))
    
    data = curr.fetchall()
    if len(data) > 0:
        return True
    return False

def get_meter_reading_with_retry(camera_device, max_attempts=3):
    attempt = 0
    rupees, litres = None, None
    
    while attempt < max_attempts:
        print(f"📸 Attempt {attempt+1} to capture meter reading...")

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

            if len(lines) >= 4:
                try:
                    rupees = float(lines[1].text.replace(' ', '')) / 10
                    litres = float(lines[3].text.replace(' ', ''))
                    print("OCR success.")
                    return rupees, litres
                except ValueError:
                    print("OCR text couldn't be converted to numbers.")
            else:
                print("Not enough lines detected in OCR.")
        else:
            print("OCR returned no results.")

        attempt += 1
        print("Retrying...\n")

    print("All attempts failed.")
    return None, None


def main():
    try:
        while True:
            print("Waiting for object...")
            GPIO.wait_for_edge(13, GPIO.FALLING)
            print("Object detected")
            print("GPIO input:", GPIO.input(13))

            image_name = capture_image("vehicle")
            if image_name is None:
                print("No image name")
                continue

            image_path = f"images/vehicle_reg_numbers/{image_name}.jpg"
            vehicle_reg_number = get_vehicle_reg_number(image_path)
            print("Vehicle number:", vehicle_reg_number)

            if get_vehicle_status(vehicle_reg_number):
                print("Valid vehicle, opening gate...")
                open_gate()
                sleep(5)  # wait for gate to close

                print("Waiting for vehicle exit (IR2)...")
                GPIO.wait_for_edge(16, GPIO.FALLING)  # or RISING depending on sensor behavior
                print("Vehicle Exit detected.")


                meter_image_name = capture_image("meter")
                meter_image_path = f"images/meter_readings/{meter_image_name}.jpg"
                amount, litres = get_meter_reading_with_retry("/dev/video2")
                print("Amount:", amount)
                print("Litres:", litres)
            else:
                print("Not a registered vehicle")
    finally:
        print("Cleaning up GPIO...")
        GPIO.cleanup()


                
                
if __name__ == "__main__":
    main()







  


