#!/usr/bin/env python3
"""
Signaling server for "Cardboard Clinic Simulator" browser multiplayer.

It only introduces players to each other (room codes + forwarding of the
WebRTC connection offers). The game itself then runs directly between the
players' browsers; no game data passes through this server.

Pure Python 3 standard library - no packages to install.
Run locally:   python signaling_server.py          (port 9080)
On a host:     the port is taken from the PORT environment variable.

Protocol (JSON text messages over WebSocket):
  client -> server  {"type": "host"}                       create a room
                    {"type": "join", "code": "KQZT"}       join a room
                    {"type": "offer"|"answer", "to": id, "sdp": "..."}
                    {"type": "candidate", "to": id, "mid": "...", "index": 0, "sdp": "..."}
  server -> client  {"type": "hosted", "code": "KQZT", "id": 1}
                    {"type": "joined", "code": "KQZT", "id": 123456}
                    {"type": "peer_joined", "id": 123456}  (to the host)
                    {"type": "peer_left", "id": 123456}
                    forwarded offer/answer/candidate with "from": id
                    {"type": "error", "message": "..."}
"""

import asyncio
import base64
import hashlib
import json
import os
import random
import struct

MAX_PLAYERS = 4
CODE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # no I/O to avoid confusion
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

rooms = {}  # code -> {id: Client}


class Client:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.room = None
        self.id = 0

    async def send(self, message):
        data = json.dumps(message).encode("utf-8")
        header = bytearray([0x81])  # FIN + text frame
        if len(data) < 126:
            header.append(len(data))
        elif len(data) < 65536:
            header.append(126)
            header += struct.pack("!H", len(data))
        else:
            header.append(127)
            header += struct.pack("!Q", len(data))
        try:
            self.writer.write(bytes(header) + data)
            await self.writer.drain()
        except (ConnectionError, OSError):
            pass

    async def receive(self):
        """Returns the next text message, or None when the connection closed."""
        message = b""
        while True:
            head = await self.reader.readexactly(2)
            fin = head[0] & 0x80
            opcode = head[0] & 0x0F
            masked = head[1] & 0x80
            length = head[1] & 0x7F
            if length == 126:
                length = struct.unpack("!H", await self.reader.readexactly(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", await self.reader.readexactly(8))[0]
            mask = await self.reader.readexactly(4) if masked else b"\0\0\0\0"
            payload = bytearray(await self.reader.readexactly(length))
            for i in range(length):
                payload[i] ^= mask[i % 4]
            if opcode == 0x8:  # close
                return None
            if opcode == 0x9:  # ping -> pong
                self.writer.write(bytes([0x8A, len(payload)]) + bytes(payload))
                continue
            if opcode == 0xA:  # pong
                continue
            message += bytes(payload)
            if fin:
                return message.decode("utf-8", "replace")


async def handshake(reader, writer):
    request = await reader.readuntil(b"\r\n\r\n")
    headers = {}
    lines = request.decode("latin-1").split("\r\n")
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    key = headers.get("sec-websocket-key")
    if not key:
        # Plain HTTP request (e.g. a hosting health check): answer politely.
        body = b"Cardboard Clinic Simulator signaling server is running.\n"
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: "
                     + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
        await writer.drain()
        return False
    accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
    writer.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                  "Sec-WebSocket-Accept: " + accept + "\r\n\r\n").encode())
    await writer.drain()
    return True


def new_code():
    while True:
        code = "".join(random.choice(CODE_LETTERS) for _ in range(4))
        if code not in rooms:
            return code


async def handle(reader, writer):
    client = Client(reader, writer)
    try:
        if not await handshake(reader, writer):
            writer.close()
            return
        while True:
            text = await client.receive()
            if text is None:
                break
            try:
                msg = json.loads(text)
            except ValueError:
                continue
            await on_message(client, msg)
    except (asyncio.IncompleteReadError, ConnectionError, OSError, asyncio.LimitOverrunError):
        pass
    finally:
        await leave(client)
        try:
            writer.close()
        except OSError:
            pass


async def on_message(client, msg):
    kind = msg.get("type")
    if kind == "host" and client.room is None:
        code = new_code()
        client.room, client.id = code, 1
        rooms[code] = {1: client}
        await client.send({"type": "hosted", "code": code, "id": 1})
        print(f"room {code} created", flush=True)
    elif kind == "join" and client.room is None:
        code = str(msg.get("code", "")).upper()
        room = rooms.get(code)
        if room is None:
            await client.send({"type": "error", "message": f"There is no room with the code {code}."})
            return
        if len(room) >= MAX_PLAYERS:
            await client.send({"type": "error", "message": "This room is full (4 players)."})
            return
        new_id = random.randint(2, 2**31 - 1)
        while new_id in room:
            new_id = random.randint(2, 2**31 - 1)
        client.room, client.id = code, new_id
        room[new_id] = client
        await client.send({"type": "joined", "code": code, "id": new_id})
        await room[1].send({"type": "peer_joined", "id": new_id})
    elif kind in ("offer", "answer", "candidate") and client.room in rooms:
        target = rooms[client.room].get(int(msg.get("to", 0)))
        if target:
            msg["from"] = client.id
            await target.send(msg)


async def leave(client):
    room = rooms.get(client.room)
    if room is None:
        return
    room.pop(client.id, None)
    if client.id == 1 or not room:
        # The host left: the room is closed (the game ends for everybody anyway).
        rooms.pop(client.room, None)
        print(f"room {client.room} closed", flush=True)
    for other in list(room.values()):
        await other.send({"type": "peer_left", "id": client.id})


async def main():
    port = int(os.environ.get("PORT", "9080"))
    server = await asyncio.start_server(handle, "0.0.0.0", port)
    print(f"Signaling server listening on port {port}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
