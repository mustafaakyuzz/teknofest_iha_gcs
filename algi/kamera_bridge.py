import os
os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"

from gz.transport13 import Node
from gz.msgs10.image_pb2 import Image
import numpy as np
import cv2
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
import mimetypes

TOPIC = "/world/default/model/rc_cessna_0/camera/image"
HOST  = "0.0.0.0"
PORT  = 8554
GCS_DIR = os.path.expanduser("~/teknofest_iha/yki")

latest_jpeg = None
frame_lock  = threading.Lock()
frame_count = 0

def image_callback(msg):
    global latest_jpeg, frame_count
    try:
        data = bytes(msg.data)
        arr  = np.frombuffer(data, dtype=np.uint8)
        if len(arr) == msg.width * msg.height * 3:
            frame     = arr.reshape((msg.height, msg.width, 3))
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            _, buf    = cv2.imencode('.jpg', frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
            with frame_lock:
                latest_jpeg  = buf.tobytes()
                frame_count += 1
    except Exception as e:
        print(f"[KAMERA] Frame hatasi: {e}")

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        # CORS header her zaman
        if self.path == "/video":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                while True:
                    with frame_lock:
                        jpeg = latest_jpeg
                    if jpeg:
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n\r\n")
                        self.wfile.write(jpeg)
                        self.wfile.write(b"\r\n")
                    time.sleep(0.033)
            except (BrokenPipeError, ConnectionResetError):
                pass

        elif self.path == "/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(
                f'{{"frames":{frame_count},"active":{str(latest_jpeg is not None).lower()}}}'.encode()
            )

        elif self.path == "/" or self.path == "/gcs":
            # GCS ana sayfasını sun
            self._serve_file("/gcs_sim.html")

        else:
            # Statik dosyalar (gcs_sim.html vb.)
            self._serve_file(self.path)

    def _serve_file(self, path):
        filepath = os.path.join(GCS_DIR, path.lstrip("/"))
        if os.path.exists(filepath) and os.path.isfile(filepath):
            mime, _ = mimetypes.guess_type(filepath)
            self.send_response(200)
            self.send_header("Content-Type", mime or "text/plain")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            with open(filepath, 'rb') as f:
                self.wfile.write(f.read())
        else:
            self.send_response(404)
            self.end_headers()

def start_server():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[SERVER] GCS:   http://localhost:{PORT}/gcs_sim.html")
    print(f"[SERVER] Video: http://localhost:{PORT}/video")
    print(f"[SERVER] Status: http://localhost:{PORT}/status")
    server.serve_forever()

# Gazebo subscribe
node   = Node()
result = node.subscribe(Image, TOPIC, image_callback)
print(f"[KAMERA] Subscribe: {result} | Topic: {TOPIC}")

# Server thread
threading.Thread(target=start_server, daemon=True).start()

print("[KAMERA] Calisıyor. Ctrl+C ile durdur.")
try:
    while True:
        time.sleep(5)
        with frame_lock:
            fc = frame_count
        print(f"[KAMERA] {fc} frame alindi.")
except KeyboardInterrupt:
    print("\n[KAMERA] Durduruldu.")