from http.server import ThreadingHTTPServer
from .handlers import Handlers

PORT = 8080

class MyServer(Handlers):
    pass

def run():
    with ThreadingHTTPServer(("", PORT), MyServer) as httpd:
        print("serving at port", PORT)
        httpd.serve_forever()
