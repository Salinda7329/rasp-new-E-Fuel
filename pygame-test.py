import pygame.camera

pygame.camera.init()
cams = pygame.camera.list_cameras()

for cam_path in cams:
    try:
        print(f"Testing camera: {cam_path}")
        cam = pygame.camera.Camera(cam_path, (640, 480))
        cam.start()
        img = cam.get_image()
        cam.stop()
        print(f"✅ Camera works: {cam_path}")
    except Exception as e:
        print(f"❌ Camera failed: {cam_path} - {e}")