# 🤖 Robo 2.0 - Architecture Clarification Document

## 📋 Project Overview
- **Raspberry Pi 4 (Server)**: Runs local server, broadcasts sensor data & video, receives commands
- **Laptop/PC (Client)**: Connects to Pi, displays UI with manual controls, AI chat, video feed

---

## ❓ Questions & Clarifications Needed

### 1. **Communication Protocol**
**Question**: Which protocol should we use for Pi ↔ PC communication?
- **Option A**: WebSocket (real-time, bidirectional, good for streaming)
- **Option B**: HTTP REST API (simpler, but polling needed)
- **Option C**: TCP Socket (low-level, custom protocol)
- **Option D**: MQTT (IoT standard, but might be overkill)

**Recommendation**: WebSocket for real-time bidirectional communication

---

### 2. **Network Discovery & Connection**
**Question**: How should PC discover/connect to Pi?
- **Option A**: Manual IP entry in UI
- **Option B**: Auto-discovery via mDNS/Bonjour (Pi broadcasts as "robo.local")
- **Option C**: Fixed IP address (you configure Pi to static IP)
- **Option D**: QR code scan with IP/port info

**Recommendation**: Auto-discovery with manual IP fallback

---

### 3. **Video Streaming**
**Question**: How should video be streamed?
- **Option A**: MJPEG stream (HTTP, simple, low latency)
- **Option B**: WebRTC (best quality, complex)
- **Option C**: H.264 RTSP (good quality, needs player)
- **Option D**: WebSocket binary frames (custom)

**Recommendation**: MJPEG stream (simple, works in browser, low latency)

**Camera Details Needed**:
- What camera? (Pi Camera v2, USB webcam, etc.)
- Resolution preference? (640x480, 1280x720, etc.)
- FPS target? (15, 30, etc.)

---

### 4. **Sensor Data Structure**

**Hardware Sensors** (from your description):
- ✅ 5-in-1 flame sensor (5 channels: D1-D5)
- ✅ 3 single flame sensors
- ✅ 4 IR edge sensors
- ✅ 1 LED indicator (status)
- ✅ Pump relay state
- ❌ Ultrasonic (not working - skip)
- ❌ Lidar (removed)
- ❌ Speaker (removed)

**Questions**:
- How often should sensor data be sent? (e.g., every 100ms, 500ms, 1s)
- Should we send only changed values or full state every time?
- Do you want sensor history/logging?

---

### 5. **Command Structure**

**Manual Mode Controls**:
- **WASD**: Movement (W=forward, S=backward, A=left, D=right)
- **Arrow Keys**: Servo control (↑↓=tilt, ←→=pan)
- **Spacebar**: Toggle pump ON/OFF

**Questions**:
- Should movement be continuous (hold key = keep moving) or discrete (press = move for X seconds)?
- Servo control: Step size? (e.g., 5° per arrow press, or smooth continuous?)
- Should we support diagonal movement? (W+A, W+D, etc.)
- Speed control? (Shift for faster, Ctrl for slower?)

---

### 6. **UI Framework & Technology**

**Question**: What should we use for the PC client?
- **Option A**: Web-based (HTML/CSS/JS) - runs in browser, cross-platform
- **Option B**: Python Tkinter - simple, native
- **Option C**: Python PyQt/PySide - modern, professional
- **Option D**: Electron app - web tech, desktop app

**Recommendation**: Web-based (HTML/CSS/JS) - easiest to develop, cross-platform, can run locally

**UI Layout Questions**:
- Video feed: Center, full screen, or resizable?
- Sensor panel: Left sidebar, right sidebar, or bottom?
- AI chat: Right sidebar, bottom panel, or overlay?
- Control buttons: On-screen buttons or keyboard-only?

---

### 7. **AI Chat Integration**

**Questions**:
- What AI service? (OpenAI API, local LLM, custom?)
- What should it comment on? (sensor readings, movement, decisions?)
- Should it be always active or toggle on/off?
- Do you have API keys ready, or should we use a local model?

**Recommendation**: Start with OpenAI API (easy), can switch to local later

---

### 8. **Motor Control Details**

**Hardware**: L298N with 4 DC motors (2 left parallel, 2 right parallel)

**Questions**:
- PWM speed range? (0-100%, or specific range?)
- Default speed for manual mode?
- Should we support gradual acceleration/deceleration?
- Turn radius: Pivot turn (one side reverse) or smooth arc?

---

### 9. **Servo Control Details**

**Hardware**: PCA9685 with 2 servos (Pan CH0, Tilt CH1)

**Questions**:
- Servo range? (e.g., Pan: -90° to +90°, Tilt: -45° to +45°)
- Default position on startup?
- Step size per arrow key press?
- Should we show current angle in UI?

---

### 10. **Error Handling & Safety**

**Questions**:
- What happens if connection drops? (auto-reconnect?)
- Emergency stop mechanism? (ESC key, big red button?)
- Should we log errors to file?
- Safety limits? (max speed, servo limits, etc.)

---

### 11. **Auto Mode (Future)**

You mentioned auto mode is the core - should we:
- Create placeholder/stub for auto mode now?
- Design the interface so auto mode can be added later?
- Or wait for your detailed explanation before implementing anything auto-related?

---

### 12. **File Structure**

**Proposed Structure**:
```
Robo 2.0/
├── PI/
│   ├── server.py              # Main Pi server
│   ├── hardware/
│   │   ├── motors.py          # Motor control
│   │   ├── servos.py          # Servo control
│   │   ├── sensors.py        # Sensor reading
│   │   └── camera.py         # Video streaming
│   ├── config.py              # GPIO pins, settings
│   └── requirements.txt      # Python dependencies
│
├── Laptop/
│   └── PC/
│       ├── client.py          # Main client (if Python)
│       ├── ui/
│       │   ├── index.html     # Web UI
│       │   ├── style.css
│       │   └── app.js         # Client logic
│       └── requirements.txt
│
└── ARCHITECTURE_CLARIFICATION.md (this file)
```

**Question**: Does this structure work for you?

---

## ✅ My Assumptions (Please Confirm)

1. **Python 3.9+** on both Pi and PC
2. **Raspberry Pi OS Bookworm 64-bit** (latest)
3. **Camera**: Pi Camera v2 or compatible USB webcam
4. **Network**: Pi and PC on same WiFi/LAN
5. **No authentication** needed (local network only)
6. **Development first**, optimization later
7. **Manual mode first**, auto mode later

---

## 🎯 Next Steps

**Please answer the questions above, and I'll:**
1. Create detailed technical specification
2. Set up the project structure
3. Implement Pi server with all hardware interfaces
4. Implement PC client with UI
5. Test each component step by step

**Priority Order**:
1. ✅ Clarify all questions above
2. ✅ Design communication protocol
3. ✅ Build Pi server (hardware interfaces)
4. ✅ Build PC client (UI + connection)
5. ✅ Integrate and test
6. ✅ Add AI chat
7. ✅ Polish UI/UX

---

## 📝 Quick Answers Template

Copy this and fill in:

```
1. Communication: [A/B/C/D]
2. Network Discovery: [A/B/C/D]
3. Video: [A/B/C/D], Camera: [model], Resolution: [e.g., 640x480], FPS: [e.g., 30]
4. Sensor Update Rate: [e.g., 100ms]
5. Movement: [continuous/discrete], Servo Step: [e.g., 5°], Speed Control: [yes/no]
6. UI Framework: [A/B/C/D], Layout: [describe]
7. AI: [service], Comment on: [what], Always on: [yes/no]
8. Motor Speed: [0-100%], Default: [e.g., 50%]
9. Servo Range: Pan [e.g., -90° to +90°], Tilt [e.g., -45° to +45°]
10. Auto-reconnect: [yes/no], Emergency Stop: [key/button]
11. Auto Mode: [placeholder now / wait for details]
12. File Structure: [approve/modify]
```

---

**Once you confirm, I'll start coding! 🚀**

