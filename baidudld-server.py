#! /usr/bin/python
# coding=utf-8

from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
import threading
import subprocess
import signal

PORT = 8068
HTTP_SERVER = HTTPServer

class ResquestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()

        html_head = ("<head><style>"
                     "body { width: 65em; margin: 0 auto; font-size: 22px;}"
                     "</style></head>")
        self.wfile.write(html_head.encode("utf8"))

        command = [cmd.split("=") for cmd in urllib.parse.unquote(self.path[1:]).split("?") if cmd]
        for cmd in command:
            cmd.insert(0, "baidudld")
            ps_ret = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            output = (ps_ret.stdout.replace("\n", "<br>")
                      .replace(" ", "&ensp;").encode("utf-8"))
            self.wfile.write(("<br>==>&ensp;&ensp;" + " ".join(cmd) + "<br>").encode("utf8"))
            self.wfile.write(output)


def http_server_start():
    global HTTP_SERVER
    host = ("0.0.0.0", PORT)
    HTTP_SERVER = HTTPServer(host, ResquestHandler)
    HTTP_SERVER.serve_forever()


def http_server_stop():
    def handler(signum, frame):
        HTTP_SERVER.shutdown()

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)


if __name__ == "__main__":
    start_t = threading.Thread(target=http_server_start)
    start_t.start()
    http_server_stop()
    start_t.join()
