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
    for _ in range(100):
        line = await asyncio.wait_for(r.readline(), timeout=10.0)
        if not line:
            break
        # Strip only the newline, not spaces - payload length is exact
        msg = json.loads(line.rstrip(b"\n"))
        payload_length = msg.get("payload_length", 0)
        print("got:", msg.get("type"), "payload:", payload_length)
        if payload_length > 0:
            await r.readexactly(payload_length)
            total_audio += payload_length
        if msg["type"] == "audio-stop":
            print("done! total audio bytes:", total_audio)
            break
    w.close()

asyncio.run(test())
