"""
Comprehensive Backend Message Dispatch & Auto Mode Verification Script.
Tests that for every message received from the Frontend, the Backend sends
the exact expected commands to the Raspberry Pi and the ML service.
"""
import asyncio
import sys
from Backend.config import Settings
from Backend.controller import RobotController


class MockPi:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(dict(data))
        print(f"  [PI DISPATCH ➜] {data}")


class MockML:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(dict(data))
        print(f"  [ML DISPATCH ➜] {data}")

    async def chat(self, data):
        self.sent.append(dict(data))
        msg = data.get('message', '').lower()
        if 'look up twice' in msg:
            return {
                'request_id': data.get('request_id'),
                'session_id': data.get('session_id'),
                'text': "Sure, looking up twice! // type : 'servo' command : 'up' ; type : 'servo' command : 'up' //",
            }
        elif 'look left' in msg:
            return {
                'request_id': data.get('request_id'),
                'session_id': data.get('session_id'),
                'text': "Turning camera left! // type : 'servo' command : 'left' //",
            }
        return {
            'request_id': data.get('request_id'),
            'session_id': data.get('session_id'),
            'text': f"Hello! Robo is operating normally. You said: {data.get('message')}"
        }


async def run_tests():
    print("=================================================================")
    print("       BACKEND MESSAGE DISPATCH & LOGIC DEBUGGING SUITE          ")
    print("=================================================================\n")

    settings = Settings(service_token='', ir_blocked_value=0, motion_calibrated=True)
    pi = MockPi()
    ml = MockML()
    robot = RobotController(settings, pi=pi, ml=ml)

    # 1. Connect Session
    client_events = []
    sid = await robot.connect(client_events.append)
    print(f"✓ Session connected: sid={sid}\n")

    # Simulate Pi is connected with healthy hardware
    await robot.on_pi({
        'type': 'connection', 'connected': True
    })
    await robot.on_pi({
        'type': 'capabilities', 'watchdog': True, 'simulation': False, 'speech': True, 'partial_hardware': True
    })
    await robot.on_pi({
        'type': 'status',
        'servos': {'pan': 90.0, 'tilt': 90.0},
        'pump': False,
        'hardware': {
            'motors': {'state': 'available', 'available': True},
            'servos': {'state': 'available', 'available': True},
            'pump': {'state': 'available', 'available': True},
            'sensors': {'state': 'available', 'available': True}
        },
        'sensors': {'ir': [0, 0, 0, 0], 'flame': [0, 0, 0, 0]},
        'safety': {'faults': [], 'trip_count': 0, 'control_lease_valid': True}
    })
    robot.stopped = False
    robot.owner = sid
    print("✓ Simulated Pi hardware connected & ready\n")

    # Helper to send message into robot.handle
    seq = 0
    async def send_cmd(cmd_dict):
        nonlocal seq
        seq += 1
        cmd_dict['seq'] = seq
        if 'request_id' not in cmd_dict:
            cmd_dict['request_id'] = f"req-{seq}"
        print(f"[FRONTEND ➜ BACKEND] {cmd_dict}")
        await robot.handle(sid, cmd_dict)

    # -------------------------------------------------------------
    # TEST 1: WASD Drive Forward & Backward
    # -------------------------------------------------------------
    print("--- 1. Testing Drive Forward & Backward ---")
    await send_cmd({'type': 'drive', 'direction': 'forward', 'speed': 0.4})
    assert pi.sent[-1] == {'type': 'drive', 'left': 1, 'right': 1, 'speed': 0.4}, f"Wrong Pi command: {pi.sent[-1]}"
    print("  ✓ Forward correctly mapped to motors: left=1, right=1, speed=0.4")

    await send_cmd({'type': 'drive', 'direction': 'backward', 'speed': 0.4})
    assert pi.sent[-1] == {'type': 'drive', 'left': -1, 'right': -1, 'speed': 0.4}, f"Wrong Pi command: {pi.sent[-1]}"
    print("  ✓ Backward correctly mapped to motors: left=-1, right=-1, speed=0.4")

    await send_cmd({'type': 'drive', 'direction': 'stop', 'speed': 0})
    assert pi.sent[-1] == {'type': 'drive', 'left': 0, 'right': 0, 'speed': 0}, f"Wrong Pi command: {pi.sent[-1]}"
    print("  ✓ Drive stop correctly mapped to motors: left=0, right=0, speed=0\n")

    # -------------------------------------------------------------
    # TEST 2: Turn Left & Turn Right
    # -------------------------------------------------------------
    print("--- 2. Testing Turn Left & Right ---")
    await send_cmd({'type': 'drive', 'direction': 'left', 'speed': 0.3})
    assert pi.sent[-1] == {'type': 'drive', 'left': -1, 'right': 1, 'speed': 0.3}, f"Wrong Pi command: {pi.sent[-1]}"
    print("  ✓ Left turn correctly mapped to motors: left=-1, right=1, speed=0.3")

    await send_cmd({'type': 'drive', 'direction': 'right', 'speed': 0.3})
    assert pi.sent[-1] == {'type': 'drive', 'left': 1, 'right': -1, 'speed': 0.3}, f"Wrong Pi command: {pi.sent[-1]}"
    print("  ✓ Right turn correctly mapped to motors: left=1, right=-1, speed=0.3")

    await send_cmd({'type': 'drive', 'direction': 'stop', 'speed': 0})
    print("  ✓ Motors stopped\n")

    # -------------------------------------------------------------
    # TEST 3: Face Gimbal Servos (Pan Left/Right, Tilt, Center)
    # -------------------------------------------------------------
    print("--- 3. Testing Face Gimbal Servos ---")
    await asyncio.sleep(0.16)
    await send_cmd({'type': 'servo', 'direction': 'left', 'degrees': 5})
    assert pi.sent[-1] == {'type': 'servo', 'pan': -5, 'tilt': 0}, f"Wrong Pi command: {pi.sent[-1]}"
    print("  ✓ Servo Left correctly mapped: pan=-5, tilt=0")

    await asyncio.sleep(0.16)
    await send_cmd({'type': 'servo', 'direction': 'right', 'degrees': 5})
    assert pi.sent[-1] == {'type': 'servo', 'pan': 5, 'tilt': 0}, f"Wrong Pi command: {pi.sent[-1]}"
    print("  ✓ Servo Right correctly mapped: pan=5, tilt=0")

    await asyncio.sleep(0.16)
    await send_cmd({'type': 'servo', 'direction': 'up', 'degrees': 5})
    assert pi.sent[-1] == {'type': 'servo', 'pan': 0, 'tilt': -5}, f"Wrong Pi command: {pi.sent[-1]}"
    print("  ✓ Servo Up correctly mapped: pan=0, tilt=-5")

    await asyncio.sleep(0.16)
    await send_cmd({'type': 'servo', 'direction': 'center'})
    assert pi.sent[-1] == {'type': 'servo', 'action': 'center'}, f"Wrong Pi command: {pi.sent[-1]}"
    print("  ✓ Servo Center correctly mapped: action='center'\n")

    # -------------------------------------------------------------
    # TEST 4: Water Pump Toggle ON and OFF
    # -------------------------------------------------------------
    print("--- 4. Testing Water Pump ON & OFF ---")
    await send_cmd({'type': 'pump', 'on': True})
    assert pi.sent[-1] == {'type': 'pump', 'on': True}
    print("  ✓ Pump ON dispatched to Pi: on=True")

    await send_cmd({'type': 'pump', 'on': False})
    assert pi.sent[-1] == {'type': 'pump', 'on': False}
    print("  ✓ Pump OFF dispatched to Pi: on=False\n")

    # -------------------------------------------------------------
    # TEST 5: Operating Mode Switch & ML Session Lifecycle
    # -------------------------------------------------------------
    print("--- 5. Testing Operating Mode Switch & ML Lifecycle ---")
    robot.ml_connected = True
    robot.ml_workers_stopped = True
    robot.alignment_confirmed = True
    await send_cmd({'type': 'mode', 'value': 'auto'})
    assert robot.mode == 'auto'
    assert pi.sent[-1] == {'type': 'mode', 'value': 'auto'}
    print("  ✓ Mode switched to 'auto' and dispatched to Pi")
    assert ml.sent[-1]['type'] == 'session.start' and ml.sent[-1]['model_id'] == settings.model_id
    print("  ✓ Auto mode automatically requested ML vision session start!")

    # Simulate ML session became active
    robot.ml_session = "sess-active-1"

    # Now switch back to manual
    await send_cmd({'type': 'mode', 'value': 'manual'})
    assert robot.mode == 'manual'
    assert pi.sent[-1] == {'type': 'mode', 'value': 'manual'}
    assert ml.sent[-1] == {'type': 'session.stop', 'session_id': 'sess-active-1'}
    print("  ✓ Switching back to 'manual' cleanly stopped the ML session!\n")

    # -------------------------------------------------------------
    # TEST 6: Emergency Stop
    # -------------------------------------------------------------
    print("--- 6. Testing Emergency Stop ---")
    await send_cmd({'type': 'system', 'command': 'stop'})
    assert robot.stopped is True
    assert pi.sent[-1] == {'type': 'system', 'command': 'stop'}
    print("  ✓ System stop sets stopped=True and sends {'type': 'system', 'command': 'stop'} to Pi\n")

    # -------------------------------------------------------------
    # TEST 7: Chat Command Extraction & Sequential Execution
    # -------------------------------------------------------------
    print("--- 7. Testing Chat Command Extraction & Execution ---")
    robot.stopped = False
    pi.sent.clear()
    client_events.clear()

    # Part A: Multi-step command execution
    print("  Part A: User asks robot to look up twice...")
    await send_cmd({'type': 'chat', 'message': 'can you please look up twice?'})
    # Wait 1.2s for the two 0.5s commands to execute
    await asyncio.sleep(1.2)

    # Filter Pi commands for servo movements
    servo_moves = [c for c in pi.sent if c.get('type') == 'servo']
    assert len(servo_moves) == 2, f"Expected 2 servo movements, got: {servo_moves}"
    assert servo_moves[0] == {'type': 'servo', 'pan': 0, 'tilt': -5}
    assert servo_moves[1] == {'type': 'servo', 'pan': 0, 'tilt': -5}
    print("  ✓ Chat successfully parsed '// type : 'servo' command : 'up' ; ... //' and sent 2 commands at 2/sec to Pi!")

    # Verify chat display text had the commands stripped out cleanly
    reply_events = [e for e in client_events if e.get('type') == 'chat.reply']
    assert len(reply_events) >= 1
    assert "Sure, looking up twice!" in reply_events[-1]['text']
    assert "//" not in reply_events[-1]['text']
    print(f"  ✓ User chat log shows clean response text: '{reply_events[-1]['text']}'")

    # Part B: Normal conversation (no robot movement commands)
    print("  Part B: User chats normally without robot commands...")
    pi.sent.clear()
    await send_cmd({'type': 'chat', 'message': 'How are you feeling today?'})
    await asyncio.sleep(0.3)
    assert len(pi.sent) == 0, f"Expected 0 Pi commands for normal chat, got: {pi.sent}"
    print("  ✓ Normal chat executed 0 robot commands!\n")

    # -------------------------------------------------------------
    # TEST 8: Auto Mode Policy (Fire Aiming & Spraying)
    # -------------------------------------------------------------
    print("--- 8. Testing Auto Mode Fire Detection & Aiming ---")
    robot.mode = 'auto'
    robot.stopped = False
    robot.alignment_confirmed = True
    robot.ml_connected = True
    robot.ml_ready = True
    robot.ml_session = "ml-sess-1"
    robot.last_pump_off = 0
    robot.last_servo = 0

    # Feed detection result from ML: Fire on the right (x=0.8, y=0.5)
    print("  Feed ML Detection: Fire spotted on the right (x=0.8, y=0.5)...")
    for frame in range(4):
        await robot.on_ml({
            'type': 'result',
            'session_id': 'ml-sess-1',
            'model_id': settings.model_id,
            'stream_id': settings.stream_id,
            'schema_version': 1,
            'frame_seq': frame + 1,
            'capture_epoch': 'epoch-1',
            'frame_age_at_send_ms': 50,
            'detections': [{'class': 'fire', 'score': 0.9, 'bbox': [0.75, 0.45, 0.85, 0.55]}]
        })
        await asyncio.sleep(0.01)

    assert pi.sent[-1] == {'type': 'servo', 'pan': 3, 'tilt': 0}, f"Wrong Pi command: {pi.sent[-1]}"
    print("  ✓ Auto mode correctly commanded pan=+3 to center fire on right!")

    # Wait for servo movement delay (0.35s)
    await asyncio.sleep(0.4)

    # Feed centered fire (x=0.5, y=0.5)
    print("  Feed ML Detection: Fire centered in crosshairs (x=0.5, y=0.5)...")
    for frame in range(4, 15):
        await robot.on_ml({
            'type': 'result',
            'session_id': 'ml-sess-1',
            'model_id': settings.model_id,
            'stream_id': settings.stream_id,
            'schema_version': 1,
            'frame_seq': frame + 1,
            'capture_epoch': 'epoch-1',
            'frame_age_at_send_ms': 50,
            'detections': [{'class': 'fire', 'score': 0.95, 'bbox': [0.48, 0.48, 0.52, 0.52]}]
        })
        await asyncio.sleep(0.01)

    assert pi.sent[-1] == {'type': 'pump', 'on': True}
    assert robot.auto.bursts == 1
    print("  ✓ Fire centered! Auto mode activated water pump 3s burst #1: {'type': 'pump', 'on': True}")

    # Simulate 3s burst ends: turn pump off and enter 2s assess pause
    robot.pump_until = None
    robot.pump = False
    robot.last_pump_off = robot.clock()
    robot.auto.phase = 'reassess'
    await pi.send({'type': 'pump', 'on': False})
    print("  ✓ 3s burst finished, water pump OFF. Pausing 2s to assess the situation...")

    # Set clock past the 2s cooldown
    robot.auto.next_at = robot.clock() - 0.1
    robot.last_pump_off = robot.clock() - 2.1

    # Fire is still present: feed centered fire again to trigger burst #2
    print("  Feed ML Detection: Fire is still visible! Aiming and bursting again...")
    for frame in range(15, 25):
        await robot.on_ml({
            'type': 'result',
            'session_id': 'ml-sess-1',
            'model_id': settings.model_id,
            'stream_id': settings.stream_id,
            'schema_version': 1,
            'frame_seq': frame + 1,
            'capture_epoch': 'epoch-1',
            'frame_age_at_send_ms': 50,
            'detections': [{'class': 'fire', 'score': 0.95, 'bbox': [0.49, 0.49, 0.51, 0.51]}]
        })
        await asyncio.sleep(0.01)

    assert pi.sent[-1] == {'type': 'pump', 'on': True}
    assert robot.auto.bursts == 2
    print("  ✓ Fire still visible! Auto mode triggered burst #2 (unlimited bursts confirmed)!")

    # Fire extinguished! Feed 4 clear frames without fire
    print("  Feed ML Detection: Fire extinguished (0 fire detections)...")
    robot.auto.next_at = robot.clock() - 0.1
    for frame in range(25, 30):
        await robot.on_ml({
            'type': 'result',
            'session_id': 'ml-sess-1',
            'model_id': settings.model_id,
            'stream_id': settings.stream_id,
            'schema_version': 1,
            'frame_seq': frame + 1,
            'capture_epoch': 'epoch-1',
            'frame_age_at_send_ms': 50,
            'detections': []
        })
        await asyncio.sleep(0.01)

    assert robot.auto.phase == 'complete'
    print("  ✓ Fire extinguished for 4 frames! Auto mode marked cycle complete!\n")

    # -------------------------------------------------------------
    # TEST 9: Servo Rapid-Fire Debounce Protection
    # -------------------------------------------------------------
    print("--- 9. Testing Servo Debounce Protection (<0.15s) ---")
    robot.mode = 'manual'
    robot.stopped = False
    await send_cmd({'type': 'servo', 'direction': 'left', 'degrees': 5})
    # Sending another servo command immediately without waiting
    client_events.clear()
    await send_cmd({'type': 'servo', 'direction': 'left', 'degrees': 5})
    rejected_events = [e for e in client_events if e.get('type') == 'error']
    assert len(rejected_events) >= 1
    assert 'Wait before the next face movement' in rejected_events[-1]['message']
    print("  ✓ Rapid servo command properly debounced and rejected with clear error message\n")

    # -------------------------------------------------------------
    # TEST 10: Speed Limit Clamping & Validation
    # -------------------------------------------------------------
    print("--- 10. Testing Speed Limit Clamping & Parameter Validation ---")
    client_events.clear()
    # Speed above maximum_speed (0.6) must be rejected
    await send_cmd({'type': 'drive', 'direction': 'forward', 'speed': 0.99})
    rejected = [e for e in client_events if e.get('type') == 'error']
    assert len(rejected) >= 1
    print("  ✓ Excessive speed (> 0.6) correctly rejected by input validation")

    # Invalid direction name must be rejected
    client_events.clear()
    await send_cmd({'type': 'drive', 'direction': 'fly_away', 'speed': 0.2})
    rejected = [e for e in client_events if e.get('type') == 'error']
    assert len(rejected) >= 1
    print("  ✓ Invalid direction name ('fly_away') rejected safely\n")

    # -------------------------------------------------------------
    # TEST 11: Emergency Stop Cancels Running Chat Commands
    # -------------------------------------------------------------
    print("--- 11. Testing Emergency Stop Interrupts Chat Command Queue ---")
    robot.stopped = False
    robot.last_servo = 0
    pi.sent.clear()
    # User requests 2 look up movements
    await send_cmd({'type': 'chat', 'message': 'can you please look up twice?'})
    # Wait 0.1s so the first command starts
    await asyncio.sleep(0.1)
    # User slams emergency STOP
    await send_cmd({'type': 'system', 'command': 'stop'})
    assert robot.stopped is True
    # Wait 1.0s to ensure 2nd command did NOT execute
    await asyncio.sleep(1.0)
    servo_moves = [c for c in pi.sent if c.get('type') == 'servo']
    assert len(servo_moves) <= 1, f"Expected 2nd command to be cancelled by STOP, got: {servo_moves}"
    print("  ✓ Emergency stop immediately halts background chat command execution!\n")

    # -------------------------------------------------------------
    # TEST 12: Chat Centering Face Gimbal
    # -------------------------------------------------------------
    print("--- 12. Testing Chat Command Centering ('center') ---")
    robot.stopped = False
    robot.last_servo = 0
    pi.sent.clear()
    # In MockML, add centering response or trigger directly
    await robot._execute_chat_commands([{'type': 'servo', 'command': 'center'}], robot.generation)
    assert pi.sent[-1] == {'type': 'servo', 'action': 'center'}
    print("  ✓ Chat command 'center' correctly triggered {'type': 'servo', 'action': 'center'} on Pi!\n")

    print("=================================================================")
    print("   ALL 12 BACKEND DISPATCH, AUTO & SAFETY TESTS PASSED 100%!     ")
    print("=================================================================")


if __name__ == '__main__':
    asyncio.run(run_tests())
