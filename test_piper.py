import asyncio
import json

async def test():
    r, w = await asyncio.open_connection("piper", 10200)
    event = {
        "type": "synthesize",
        "data": {
            "text": "hello bill",
            "voice": {
                "name": "en_GB-alan-medium",
                "language": "en_GB",
                "speaker": None
            }
        },
        "payload_length": 0
    }
    w.write((json.dumps(event) + "\n").encode())
    await w.drain()
    print("sent, waiting...")
    total_audio = 0

    async def read_event():
        header_line = await asyncio.wait_for(r.readline(), timeout=10.0)
        header = json.loads(header_line.rstrip(b"\n"))
        data_length = header.get("data_length", 0)
        payload_length = header.get("payload_length", 0)
        data = await r.readexactly(data_length) if data_length > 0 else b"{}"
        payload = await r.readexactly(payload_length) if payload_length > 0 else b""
        return header, json.loads(data) if data else {}, payload

    for _ in range(200):
        header, data, payload = await read_event()
        print("got:", header.get("type"), "data_length:", header.get("data_length", 0), "payload_length:", header.get("payload_length", 0))
        if header["type"] == "audio-chunk":
            total_audio += len(payload)
        elif header["type"] == "audio-stop":
            print("done! total audio bytes:", total_audio)
            break

    w.close()

asyncio.run(test())
