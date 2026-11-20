
from infrastructure.database.mongodb.mongo import MongoDB
from infrastructure.database.mongodb.repositories import MeasurementPointRepository
from application.camera_worker import CameraWorker

def main() -> None:
    mongodb = MongoDB()
    worker = None

    try:
        mongodb.connect()

        repository = MeasurementPointRepository(mongodb.database)
        camera = repository.get_by_code("AMP-006")

        if camera is None:
            raise RuntimeError("Camera AMP-006 was not found in MongoDB.")

        worker = CameraWorker(camera)

        captured = worker.capture_frame()

        print(f"Camera: {captured.camera_code}")
        print(f"Captured at: {captured.captured_at.isoformat()}")
        print(f"Image size: {captured.image.size}")
        print("Frame captured successfully.")

    finally:
        if worker is not None:
            worker.close()

        mongodb.close()

if __name__ == "__main__":
    main()
