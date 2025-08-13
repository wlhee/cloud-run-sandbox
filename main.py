from http.server import BaseHTTPRequestHandler, HTTPServer
import subprocess
import os
import json
import uuid

PORT = 8080

class MyServer(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/list':
            self.list_containers()
        elif self.path == '/status':
            self.get_status()
        elif self.path.startswith('/suspend/'):
            self.suspend_container()
        elif self.path.startswith('/restore/'):
            self.restore_container()
        elif self.path.startswith('/delete/'):
            self.delete_container()
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

    def do_POST(self):
        if self.path == '/execute':
            self.execute_code()
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

    def list_containers(self):
        try:
            result = subprocess.run(["runsc", "list"], check=True, capture_output=True, text=True)
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(result.stdout.encode())
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def get_status(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Server is running")

    def suspend_container(self):
        try:
            container_id = self.path.split('/')[-1]
            subprocess.run(["runsc", "pause", container_id], check=True)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(f"App {container_id} suspended".encode())
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def restore_container(self):
        try:
            container_id = self.path.split('/')[-1]
            subprocess.run(["runsc", "resume", container_id], check=True)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(f"App {container_id} restored".encode())
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def delete_container(self):
        try:
            container_id = self.path.split('/')[-1]
            subprocess.run(["runsc", "delete", container_id], check=True)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(f"App {container_id} deleted".encode())
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def execute_code(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        
        temp_dir = "/tmp"
        os.makedirs(temp_dir, exist_ok=True)
        
        temp_filename = f"temp_code-{uuid.uuid4()}.py"
        temp_filepath = os.path.join(temp_dir, temp_filename)
        
        with open(temp_filepath, "wb") as f:
            f.write(post_data)
            
        container_id = f"exec-{uuid.uuid4()}"
        bundle_dir = f"/tmp/runsc_bundle_{container_id}"
        os.makedirs(bundle_dir, exist_ok=True)

        config = {
            "ociVersion": "1.0.0",
            "process": {
                "user": {"uid": 0, "gid": 0},
                "args": ["python3", temp_filepath],
                "env": [
                    "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                    "TERM=xterm",
                    f"CONTAINER_ID={container_id}"
                ],
                "cwd": "/",
                "capabilities": {
                    "bounding": ["CAP_AUDIT_WRITE", "CAP_KILL"],
                    "effective": ["CAP_AUDIT_WRITE", "CAP_KILL"],
                    "inheritable": ["CAP_AUDIT_WRITE", "CAP_KILL"],
                    "permitted": ["CAP_AUDIT_WRITE", "CAP_KILL"],
                },
                "rlimits": [{"type": "RLIMIT_NOFILE", "hard": 1024, "soft": 1024}],
            },
            "root": {"path": "/", "readonly": False},
            "hostname": "runsc",
            "mounts": [
                {"destination": "/proc", "type": "proc", "source": "proc"},
                {"destination": "/dev", "type": "tmpfs", "source": "tmpfs"},
                {"destination": "/sys", "type": "sysfs", "source": "sysfs"},
            ],
            "linux": {
                "namespaces": [
                    {"type": "pid"},
                    {"type": "network"},
                    {"type": "ipc"},
                    {"type": "uts"},
                    {"type": "mount"},
                ],
                "resources": {"memory": {"limit": 2147483648}},
            },
        }
        with open(os.path.join(bundle_dir, "config.json"), "w") as f:
            json.dump(config, f, indent=4)

        try:
            run_cmd = ["runsc", "--network=host", "run", "-bundle", bundle_dir, container_id]
            # Run the process in the background and let it inherit stdout/stderr
            subprocess.Popen(run_cmd)
            
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Exec process started")

        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())

if __name__ == "__main__":
    with HTTPServer(("", PORT), MyServer) as httpd:
        print("serving at port", PORT)
        httpd.serve_forever()
