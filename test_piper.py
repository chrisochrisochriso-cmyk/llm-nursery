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
    # Read raw bytes to understand actual protocol format
    raw = await asyncio.wait_for(r.read(4096), timeout=10.0)
    print("raw bytes (first 300):", raw[:300])
    print("repr:", repr(raw[:300]))
    w.close()

asyncio.run(test())
