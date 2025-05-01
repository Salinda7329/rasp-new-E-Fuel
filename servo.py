import RPi.GPIO as GPIO
from time import sleep
GPIO.setmode(GPIO.BOARD)

GPIO.setup(11, GPIO.OUT)
gate_pin = GPIO.PWM(11, 50)

gate_pin.start(0)
gate_pin.ChangeDutyCycle(3)
sleep(1)
gate_pin.ChangeDutyCycle(12)
sleep(1)
gate_pin.stop()
