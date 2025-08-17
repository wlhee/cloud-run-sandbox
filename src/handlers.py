from http.server import BaseHTTPRequestHandler
from . import sandbox

class Handlers(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/list':
            output, err = sandbox.list_containers()
            if err:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(err.encode())
            else:
                self.send_response(200)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(output.encode())

        elif self.path == '/status':
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Server is running")

        elif self.path.startswith('/suspend/'):
            container_id = self.path.split('/')[-1]
            output, err = sandbox.suspend_container(container_id)
            if err:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(err.encode())
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(output.encode())

        elif self.path.startswith('/restore/'):
            container_id = self.path.split('/')[-1]
            output, err = sandbox.resume_container(container_id)
            if err:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(err.encode())
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(output.encode())

        elif self.path.startswith('/delete/'):
            container_id = self.path.split('/')[-1]
            output, err = sandbox.delete_container(container_id)
            if err:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(err.encode())
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(output.encode())
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

    def do_POST(self):
        if self.path == '/execute':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            self.send_response(200)
            self.send_header("Content-type", "text/plain; charset=utf-8")
            self.end_headers()

            err = sandbox.execute_code(post_data, self.wfile)
            if err and not self.headers_sent:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(err.encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
