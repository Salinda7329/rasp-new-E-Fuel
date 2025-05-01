import pygame
import pygame.camera
import os
import uuid
from dotenv import load_dotenv
load_dotenv()
#from azure.ai.vision import ImageAnalysisClient
from azure.ai.vision.imageanalysis import ImageAnalysisClient
#from azure.ai.vision.models import VisualFeatures
from azure.ai.vision.imageanalysis.models import VisualFeatures
from azure.core.credentials import AzureKeyCredential
import psycopg2
import RPi.GPIO as GPIO
from time import sleep

# GPIO setup
GPIO.setmode(GPIO.BOARD)
GPIO.setup(11, GPIO.OUT)
GPIO.setup(13, GPIO.IN)
gate_pin = GPIO.PWM(11, 50)

def capture_image(type="vehicle"):
    """Captures an image using the webcam and saves it."""
    pygame.camera.init()
    cam = None
    
    image_name = uuid.uuid4()
    image_path = None
    if type == "vehicle":
        cam_path = get_available_camera(0)  # First working camera
        image_path = f"images/vehicle_reg_numbers/{image_name}.jpg"
    elif type == "meter":
        cam_path = get_available_camera(0)  # Second working camera
        image_path = f"images/meter_readings/{image_name}.jpg"
        
    if cam_path is None:
        print(f"No camera available for type: {type}")
        return None

    cam = pygame.camera.Camera(cam_path, (640, 480))
    cam.start()
    image = cam.get_image()
    pygame.image.save(image, image_path)
    cam.stop()
    return image_name

def get_available_camera(index=0):
    """Returns the available camera device."""
    pygame.camera.init()
    camlist = pygame.camera.list_cameras()
    if len(camlist) > index:
        return camlist[index]
    else:
        return None

def get_vehicle_reg_number(image_path):
    """Extracts vehicle registration number from the image using OCR."""
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
    """Returns a connection to the PostgreSQL database."""
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
        return None

def open_gate():
    """Simulates opening the gate."""
    gate_pin.start(0)
    gate_pin.ChangeDutyCycle(3)
    sleep(1)
    gate_pin.ChangeDutyCycle(12)
    sleep(1)
    gate_pin.stop()

def get_vehicle_status(vehicle_reg_number):
    """Checks if the vehicle is registered in the database."""
    conn = get_db_connection()
    if conn:
        print("DB connected.")
    else:
        print("Unable to connect DB")
        return False

    curr = conn.cursor()
    curr.execute("SELECT * FROM vehicles WHERE vehicle_no = %s", (vehicle_reg_number,))
    data = curr.fetchall()
    
    conn.close()  # Always close the DB connection
    
    if len(data) > 0:
        return True
    return False

def get_meter_reading(image_path):
    """Extracts meter reading details from the image using OCR."""
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

    rupees = None
    litres = None
    if result.read is not None:
        print(result.read.blocks[0].lines)
        try:
            rupees = float(result.read.blocks[0].lines[1].text.replace(' ', '')) / 10
            litres = float(result.read.blocks[0].lines[3].text.replace(' ', ''))
        except Exception as e:
            print(f"Error extracting meter values: {e}")
        for line in result.read.blocks[0].lines:
            print(f"Line: '{line.text}'")
    else:
        print("OCR operation failed or timed out")
        
    return rupees, litres

def main():
    """Main loop for the system."""
    while True:
        if GPIO.input(13):  # When object detected (vehicle)
            print("Object detected")
            image_name = capture_image("vehicle")
            if image_name is None:
                print("No image captured")
                continue  # Skip if image is not captured
            image_path = f"images/vehicle_reg_numbers/{image_name}.jpg"
            vehicle_reg_number = get_vehicle_reg_number(image_path)
            print(f"Vehicle Registration Number: {vehicle_reg_number}")
            
            vehicle_status = get_vehicle_status(vehicle_reg_number)
            print(f"Vehicle Registered: {vehicle_status}")
            
            if vehicle_status:
                open_gate()  # Open the gate for registered vehicles
                meter_reading_0_image_name = capture_image("meter")
                meter_reading_0_image_path = f"images/meter_readings/{meter_reading_0_image_name}.jpg"
                amount, litres = get_meter_reading(meter_reading_0_image_path)
                print(f"Amount: {amount}")
                print(f"Litres: {litres}")
            else:
                print("Vehicle not registered.")
        else:
            print("No object detected")
            sleep(1)  # Wait for a while before checking again

# Run the main loop
if __name__ == "__main__":
    main()