import RPi.GPIO as GPIO
from time import sleep

GPIO.setmode(GPIO.BOARD)
GPIO.setup(13, GPIO.IN)

try:
    while True:
        if GPIO.input(13) == GPIO.LOW:
            print("Vehicle detected!")
        else:
            print("No vehicle")
        sleep(1)
finally:
    GPIO.cleanup()
