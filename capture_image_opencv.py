def capture_image_opencv(type="vehicle"):
    """Captures an image using the webcam and saves it."""
    cap = cv2.VideoCapture(0)
    image_name=uuid.uuid4()
    image_path = None
    if type == "vehicle":
        image_path = f"images/vehicle_reg_numbers/{image_name}.jpg"
    elif type == "meter":
        image_path = f"images/meter_readings/{image_name}.jpg"
    if not cap.isOpened():
        print("Error: Could not access the webcam.")
        return None
    
    ret, frame = cap.read()
    if ret:
        cv2.imwrite(image_path, frame)
        print(f"Image saved as {image_path}")
    else:
        print("Error: Could not capture an image.")
        image_path = None
    
    cap.release()
    return image_name