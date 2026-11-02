import json
import socket

ENDPOINT = "/storage/emulated/0/Android/obb/dev.horizon.android.nx/horizon-control.json"


class Horizon:
    def __init__(self, endpoint=ENDPOINT):
        with open(endpoint) as file:
            details = json.load(file)
        self.connection = socket.create_connection(("127.0.0.1", details["port"]), timeout=60)
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.reader = self.connection.makefile("r", encoding="utf-8")
        self.connection.sendall(f"auth {details['token']}\n".encode())
        self.reader.readline()

    def send(self, line):
        self.connection.sendall((line.strip() + "\n").encode())
        reply = self.reader.readline()
        try:
            return json.loads(reply)
        except json.JSONDecodeError:
            return {"raw": reply}

    def __call__(self, *words):
        return self.send(" ".join(str(word) for word in words))
