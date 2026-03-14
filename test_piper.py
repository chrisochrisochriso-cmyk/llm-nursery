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
        }
    }
    w.write((json.dumps(event) + "\n").encode())
    await w.drain()
    print("sent, waiting...")
    for _ in range(20):
        line = await asyncio.wait_for(r.readline(), timeout=5.0)
        msg = json.loads(line.decode().strip())
        print("got:", msg.get("type"), "payload:", msg.get("payload_length", 0))
        if msg.get("payload_length", 0) > 0:
            await r.readexactly(msg["payload_length"])
        if msg["type"] == "audio-stop":
            break
    w.close()

asyncio.run(test())
