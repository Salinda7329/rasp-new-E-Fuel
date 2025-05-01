import os
from dotenv import load_dotenv
load_dotenv()
from azure.ai.vision.imageanalysis import ImageAnalysisClient
from azure.ai.vision.imageanalysis.models import VisualFeatures
from azure.core.credentials import AzureKeyCredential

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

    vehicle_reg_number=None
    if result.read is not None:
        for line in result.read.blocks[0].lines:
            print(f"Line: '{line.text}'")
            vehicle_reg_number=line.text
    else:
        print("OCR operation failed or timed out")
        
    return vehicle_reg_number

if __name__ == "__main__":
    vehicle_reg_number=get_vehicle_reg_number("images/noplate5.jpg")
    print(vehicle_reg_number)