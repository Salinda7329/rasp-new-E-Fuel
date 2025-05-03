import RPi.GPIO as GPIO
from time import sleep

GPIO.setmode(GPIO.BOARD)
GPIO.setup(16, GPIO.IN)
#IR1 = 13
#IR2 = 16
#IR3 = 15

try:
    while True:
        if GPIO.input(16) == GPIO.LOW:
            print("Vehicle detected!")
        else:
            print("No vehicle")
        sleep(1)
finally:
    GPIO.cleanup()
