import pygame
import pygame.camera

pygame.camera.init()

cam = pygame.camera.Camera("/dev/video0", (640,480))

cam.start()

image = cam.get_image()

pygame.image.save(image, "photo.jpg")

cam.stop()