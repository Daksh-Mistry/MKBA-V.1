# 🚀 Robo 2.0 - Complete Startup Instructions

## 📋 Prerequisites Check

**On Pi:**
- ✅ Raspberry Pi OS Bookworm 64-bit
- ✅ Camera module connected
- ✅ All hardware wired per your specifications
- ✅ Python 3.11+ installed

**On Laptop:**
- ✅ Modern web browser (Chrome/Edge/Firefox)
- ✅ Python 3.9+ (for auto mode later)

---

## 🔧 STEP 1: Setup Pi Server

**1.1 Navigate to Pi directory:**
```bash
cd ~/Desktop/PI
```

**1.2 Activate virtual environment:**
```bash
source .venv/bin/activate
```

**1.3 Install/verify dependencies:**
```bash
pip install -r requirements.txt
```

**1.4 Find your Pi's IP address:**
```bash
hostname -I
```
**Write down this IP address** (e.g., `192.168.29.59`)

**1.5 Start the server:**
```bash
python server.py
```

**Expected output:**
```
🤖 Initializing Robo 2.0 Server...
  ⚙️  Initializing motors...
     ✓ Motors ready (default speed: 0.5)
  🎯 Initializing servos (PCA9685)...
     ✓ Servos initialized - Pan: 1790µs, Tilt: 1850µs
       Pan range: 580-3000µs
       Tilt range: 1200-2500µs
  🔥 Initializing sensors...
     ✓ Sensors ready - 5 flame array, 3 single flame, 4 IR
  💧 Initializing relay & LED...
     ✓ Relay on GPIO17, LED on GPIO7
  📹 Initializing camera...
     ✓ Camera ready (rpicam-vid)

✅ All hardware initialized!

🌐 Starting servers...
   WebSocket: ws://0.0.0.0:8765
   Video: http://0.0.0.0:8080/video.mjpg
   Waiting for client connections...
```

**✅ Keep this terminal open!** Server must stay running.

---

## 💻 STEP 2: Setup Laptop Client

**2.1 Open the web interface:**

**Option A - Direct file:**
- Navigate to: `Laptop/PC/Server/web/`
- Double-click `index.html`
- It will open in your default browser

**Option B - Local server (recommended):**
```bash
cd "Laptop/PC/Server/web"
python -m http.server 8000
```
Then open: `http://localhost:8000`

**2.2 Connect to Pi:**
- In the browser, you'll see "Pi IP:" input field at the top
- Enter your Pi's IP address (from Step 1.4)
- Click the blue "Connect" button
- Status should change from "Disconnected" (red) to "Connected (IP)" (green)

**2.3 Verify connection:**
- Open browser console: Press `F12` → Click "Console" tab
- You should see:
  ```
  Connecting to ws://192.168.29.59:8765...
  WebSocket connected!
  Server hello: {type: "hello", mode: "manual"}
  Loading video: http://192.168.29.59:8080/video.mjpg...
  Video loaded successfully
  ```

**2.4 Check Pi terminal:**
- You should see: `📱 Client connected from ('192.168.29.194', ...)`
- No error spam (errors are suppressed)

---

## ✅ STEP 3: Test Controls

**3.1 Enable keyboard controls:**
- Click anywhere on the page (not in input fields) to focus it
- The page needs focus to capture keyboard input

**3.2 Test movement:**
- Press `W` - Robot should move forward
- Press `S` - Robot should move backward
- Press `A` - Robot should turn left
- Press `D` - Robot should turn right
- Release keys - Robot should stop

**3.3 Test servos:**
- Press `←` (Left Arrow) - Pan servo should move left
- Press `→` (Right Arrow) - Pan servo should move right
- Press `↑` (Up Arrow) - Tilt servo should move up
- Press `↓` (Down Arrow) - Tilt servo should move down
- Check bottom status bar - Servo values should update

**3.4 Test pump:**
- Hold `Space` - Pump should turn ON
- Release `Space` - Pump should turn OFF
- Check bottom status bar - Pump status should show "ON"/"OFF"

**3.5 Test speed modifiers:**
- Hold `Shift` + `W` - Robot should move faster
- Hold `Ctrl` + `W` - Robot should move slower

**3.6 Test emergency stop:**
- Press `Esc` - All motors stop, pump turns off

**3.7 Test mode toggle:**
- Press `M` or click "Toggle Mode" button
- Mode should switch between "Manual" and "Auto"

---

## 🔍 Troubleshooting

**Problem: Video shows but controls don't work**
- ✅ Check browser console (F12) for WebSocket errors
- ✅ Verify status shows "Connected" (green), not "Disconnected" (red)
- ✅ Make sure you clicked on the page to focus it
- ✅ Check Pi terminal shows client connected

**Problem: Can't connect WebSocket**
- ✅ Verify Pi IP address is correct
- ✅ Make sure Pi server is running (`python server.py`)
- ✅ Check firewall isn't blocking port 8765
- ✅ Try pinging Pi: `ping 192.168.29.59` (replace with your IP)

**Problem: Video doesn't load**
- ✅ Check camera is connected
- ✅ Verify `rpicam-vid` command works: `rpicam-vid --help`
- ✅ Check Pi terminal for camera errors

**Problem: Servos don't move**
- ✅ Check PCA9685 is connected (I²C)
- ✅ Verify servos are powered (5V from LM2596)
- ✅ Check Pi terminal shows servo initialization messages

**Problem: Motors don't move**
- ✅ Check L298N is powered (11.1V battery)
- ✅ Verify GPIO pins are correct in `config.py`
- ✅ Check motor connections

**Problem: Sensors show all zeros**
- ✅ Check sensors are wired correctly
- ✅ Verify GPIO pins in `config.py` match your wiring
- ✅ Check logic level shifters are working

---

## 📊 Expected Behavior

**When everything works:**
- ✅ Video feed shows live camera view
- ✅ Status bar shows "Connected" in green
- ✅ Sensor values update at bottom (Flame, IR, Pump, Servos)
- ✅ WASD keys control robot movement
- ✅ Arrow keys control servo pan/tilt
- ✅ Space bar controls pump
- ✅ Shift/Ctrl modify speed
- ✅ Pi terminal shows connection messages (no errors)

---

## 🎯 Next Steps (After Manual Mode Works)

Once manual mode is working, you can:
1. Test auto mode (requires YOLO model or Gemini API)
2. Add AI chat integration
3. Fine-tune servo ranges and motor speeds
4. Add more features

---

## 📝 Quick Reference

**Controls:**
- `W/A/S/D` - Move robot
- `←/→` - Pan servo
- `↑/↓` - Tilt servo
- `Space` - Pump ON/OFF
- `Shift` - Speed boost (+30%)
- `Ctrl` - Speed reduction (-30%)
- `M` - Toggle Manual/Auto mode
- `Esc` - Emergency stop

**Ports:**
- WebSocket: `8765`
- Video: `8080`

**Files:**
- Pi server: `PI/server.py`
- Pi config: `PI/config.py`
- Client UI: `Laptop/PC/Server/web/index.html`
- Client JS: `Laptop/PC/Server/web/app.js`

---

**Ready to start? Follow steps 1 → 2 → 3 in order!** 🚀

