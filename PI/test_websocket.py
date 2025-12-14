#!/usr/bin/env python3
"""Quick test to verify WebSocket server is working."""

import asyncio
import websockets

async def test_connection():
    uri = "ws://localhost:8765"
    print(f"Testing WebSocket connection to {uri}...")
    
    try:
        async with websockets.connect(uri) as websocket:
            print("✅ Connected successfully!")
            
            # Wait for hello message
            message = await asyncio.wait_for(websocket.recv(), timeout=2.0)
            print(f"📨 Received: {message}")
            
            # Send a test message
            await websocket.send('{"type": "drive", "left": 0, "right": 0}')
            print("✅ Test message sent")
            
    except ConnectionRefusedError:
        print("❌ Connection refused - server not running or port not listening")
    except Exception as e:
        print(f"❌ Error: {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(test_connection())

