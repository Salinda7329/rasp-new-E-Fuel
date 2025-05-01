import RPi.GPIO as GPIO
from time import sleep
GPIO.setmode(GPIO.BOARD)

GPIO.setup(13, GPIO.IN)

while True:
    ir_pin = GPIO.input(13)
    print(ir_pin)
    if ir_pin:
        print("No vehicle")
    else:
        print("Detected detected")
        sleep(3)
    