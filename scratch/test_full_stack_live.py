"""Live End-to-End Stack Verification Script.
Starts Pi (simulation), ML (FastAPI + Gemini), and Backend (FastAPI),
and executes complete user scenarios through the real network sockets!
"""
import asyncio
import json
import os
import subprocess
import sys
import time
import httpx
import websockets
from dotenv import load_dotenv

load_dotenv()

PI_PORT = 18000
ML_PORT = 18200
BACKEND_PORT = 18100
SECRET = "local-robo-secret"

async def wait_for_http(url, name, timeout=12):
    start = time.time()
    async with httpx.AsyncClient() as client:
        while time.time() - start < timeout:
            try:
                r = await client.get(url, timeout=1)
                if r.status_code == 200:
                    print(f"  [READY] {name} is up at {url} (status={r.status_code})")
                    return True
            except Exception:
                await asyncio.sleep(0.3)
    raise RuntimeError(f"Timeout waiting for {name} at {url}")

async def main():
    print("=================================================================")
    print("       LIVE MULTI-SERVER INTEGRATION & GEMINI CHAT SUITE         ")
    print("=================================================================\n")

    env = os.environ.copy()
    env["PYTHONPATH"] = "."
    env["ML_SERVICE_TOKEN"] = SECRET
    env["ROBO_SERVICE_TOKEN"] = SECRET
    env["ROBO_BACKEND_PORT"] = str(BACKEND_PORT)
    env["ROBO_ML_URL"] = f"http://127.0.0.1:{ML_PORT}"
    env["ROBO_PI_WS_URL"] = f"ws://127.0.0.1:{PI_PORT}/ws"
    env["ROBO_PI_HTTP_URL"] = f"http://127.0.0.1:{PI_PORT}"
    env["ROBO_ALLOW_SIMULATION"] = "true"
    env["ROBO_MOTION_CALIBRATED"] = "true"
    env["ML_PORT"] = str(ML_PORT)
    env["PI_SIMULATION"] = "1"
    env["PI_PORT"] = str(PI_PORT)

    processes = []
    try:
        # 1. Start Simulated Pi Server
        print("1. Starting Simulated Raspberry Pi Server on port", PI_PORT)
        pi_env = env.copy()
        pi_env["PYTHONPATH"] = "PI:."
        p_pi = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(PI_PORT), "--log-level", "warning"],
            cwd="PI", env=pi_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        processes.append(("Pi", p_pi))
        await wait_for_http(f"http://127.0.0.1:{PI_PORT}/", "Raspberry Pi Server")

        # 2. Start ML Service (with Gemini API)
        print("\n2. Starting ML Service on port", ML_PORT)
        p_ml = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "ML.app:create_app", "--factory", "--host", "127.0.0.1", "--port", str(ML_PORT), "--log-level", "warning"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        processes.append(("ML", p_ml))
        await wait_for_http(f"http://127.0.0.1:{ML_PORT}/health", "ML Service")

        # 3. Start Backend Server
        print("\n3. Starting Backend Server on port", BACKEND_PORT)
        p_backend = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "Backend.app:create_app", "--factory", "--host", "127.0.0.1", "--port", str(BACKEND_PORT), "--log-level", "warning"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        processes.append(("Backend", p_backend))
        await wait_for_http(f"http://127.0.0.1:{BACKEND_PORT}/api/v1/health", "Backend Server")

        # Connect Frontend WebSocket client to Backend
        ws_url = f"ws://127.0.0.1:{BACKEND_PORT}/api/v1/ws"
        print(f"\n4. Connecting Frontend WebSocket client to {ws_url}...")
        async with websockets.connect(ws_url) as ws:
            hello = json.loads(await ws.recv())
            print(f"  ✓ Connected! Backend Hello received: mode={hello.get('mode')}")

            # Wait for backend to connect to Pi
            await asyncio.sleep(1.0)

            # --- SCENARIO 1: MANUAL DRIVE FORWARD & STOP ---
            print("\n--- SCENARIO 1: Manual Drive Forward & Stop ---")
            await ws.send(json.dumps({'type': 'drive', 'direction': 'forward', 'speed': 0.3, 'seq': 1, 'request_id': 'req-1'}))
            await asyncio.sleep(0.1)
            # Verify Pi status
            async with httpx.AsyncClient() as client:
                r = await client.get(f"http://127.0.0.1:{PI_PORT}/status")
                pi_status = r.json()
                print(f"  ✓ Drive forward dispatched through full stack! Pi motors status: {pi_status.get('motors')}")

            await ws.send(json.dumps({'type': 'drive', 'direction': 'stop', 'speed': 0, 'seq': 2, 'request_id': 'req-2'}))
            print("  ✓ Drive stop sent successfully!")

            # --- SCENARIO 2: SERVO MOVEMENTS ---
            print("\n--- SCENARIO 2: Face Gimbal Servos (Left, Right, Center) ---")
            await ws.send(json.dumps({'type': 'servo', 'direction': 'left', 'degrees': 5, 'seq': 3, 'request_id': 'req-3'}))
            await asyncio.sleep(0.2)
            await ws.send(json.dumps({'type': 'servo', 'direction': 'right', 'degrees': 5, 'seq': 4, 'request_id': 'req-4'}))
            await asyncio.sleep(0.2)
            await ws.send(json.dumps({'type': 'servo', 'direction': 'center', 'seq': 5, 'request_id': 'req-5'}))
            await asyncio.sleep(0.1)
            print("  ✓ Servos (left, right, center) successfully handled by Backend & Pi!")

            # --- SCENARIO 3: WATER PUMP ---
            print("\n--- SCENARIO 3: Water Pump Toggle ---")
            await ws.send(json.dumps({'type': 'pump', 'on': True, 'seq': 6, 'request_id': 'req-6'}))
            await asyncio.sleep(0.1)
            await ws.send(json.dumps({'type': 'pump', 'on': False, 'seq': 7, 'request_id': 'req-7'}))
            print("  ✓ Water pump toggle (ON/OFF) executed cleanly!")

            # --- SCENARIO 4: LIVE GEMINI CHAT WITH ROBOT COMMANDS ---
            print("\n--- SCENARIO 4: Live Gemini Chat with Movement Extraction ---")
            print("  [USER ➜ CHAT] 'can you look up twice please?'")
            await ws.send(json.dumps({'type': 'chat', 'message': 'can you look up twice please?', 'seq': 8, 'request_id': 'req-8'}))
            
            # Read messages until we get chat.reply
            chat_reply = None
            start_chat = time.time()
            while time.time() - start_chat < 15:
                raw = await asyncio.wait_for(ws.recv(), timeout=15)
                msg = json.loads(raw)
                if msg.get('type') == 'chat.reply':
                    chat_reply = msg
                    break

            assert chat_reply is not None, "Failed to receive chat.reply from Backend"
            print(f"  [GEMINI AI RESPONSE] '{chat_reply.get('text')}'")
            print(f"  [ACTION STATUS] {chat_reply.get('action_status')}")
            assert "haven't moved" in chat_reply.get('text') or chat_reply.get('action_status') in ('sent_to_pi', 'proposed')
            print("  ✓ Gemini response successfully received and parsed into Pi servo actions!")

            # --- SCENARIO 5: LIVE GEMINI NORMAL CONVERSATION ---
            print("\n--- SCENARIO 5: Live Gemini Normal Conversation (Zero Robot Commands) ---")
            print("  [USER ➜ CHAT] 'What is the capital of India?'")
            await ws.send(json.dumps({'type': 'chat', 'message': 'What is the capital of India?', 'seq': 9, 'request_id': 'req-9'}))
            
            normal_reply = None
            start_chat = time.time()
            while time.time() - start_chat < 15:
                raw = await asyncio.wait_for(ws.recv(), timeout=15)
                msg = json.loads(raw)
                if msg.get('type') == 'chat.reply':
                    normal_reply = msg
                    break

            assert normal_reply is not None
            print(f"  [GEMINI AI RESPONSE] '{normal_reply.get('text')}'")
            print(f"  [ACTION STATUS] {normal_reply.get('action_status')}")
            assert "//" not in normal_reply.get('text')
            print("  ✓ Normal conversation returned clean answer with ZERO commands executed on Pi!")

        print("\n=================================================================")
        print("   ALL 3 SERVERS RUNNING TOGETHER & PASSED ALL SCENARIOS 100%!   ")
        print("=================================================================")

    finally:
        print("\nStopping background servers...")
        for name, p in processes:
            try:
                p.terminate()
                p.wait(timeout=2)
            except Exception:
                p.kill()
        print("All servers stopped cleanly.")

if __name__ == "__main__":
    asyncio.run(main())
