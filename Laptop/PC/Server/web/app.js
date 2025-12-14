const qs = new URLSearchParams(window.location.search);
let host = qs.get("host") || localStorage.getItem("robo_host") || "robo.local";
const wsPort = qs.get("wsPort") || "8765";
const videoPort = qs.get("videoPort") || "8080";

const videoEl = document.getElementById("video");
const connEl = document.getElementById("conn");
const modeEl = document.getElementById("mode");
const speedEl = document.getElementById("speed");
const flameEl = document.getElementById("flame");
const irEl = document.getElementById("ir");
const pumpEl = document.getElementById("pump");
const servosEl = document.getElementById("servos");

const modeToggleBtn = document.getElementById("mode-toggle");
const toolbarButtons = document.querySelectorAll("#video-toolbar button[data-res]");

let ws = null;
let isConnecting = false;
let reconnectTimer = null;
let speedScalar = 1.0;
let pan = 0;
let tilt = 0;
let currentMode = "manual";

function connect() {
  // Prevent multiple simultaneous connection attempts
  if (isConnecting) {
    console.log("⏳ Already connecting, skipping...");
    return;
  }
  
  // Clear any pending reconnect timer
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  
  // Close existing connection if any
  if (ws) {
    console.log("🔌 Closing existing connection...");
    ws.onclose = null; // Prevent reconnect loop
    ws.close();
    ws = null;
  }
  
  const wsUrl = `ws://${host}:${wsPort}`;
  console.log(`🔌 Connecting to ${wsUrl}...`);
  connEl.textContent = "Connecting...";
  connEl.style.color = "#ffa500";
  isConnecting = true;
  
  try {
    ws = new WebSocket(wsUrl);
    
    ws.onopen = (event) => {
      console.log("✅ WebSocket connected successfully!");
      console.log("   Ready state:", ws.readyState);
      isConnecting = false;
      connEl.textContent = `Connected (${host})`;
      connEl.style.color = "#4caf50";
      localStorage.setItem("robo_host", host);
    };
    
    ws.onerror = (event) => {
      console.error("❌ WebSocket error:", event);
      console.error("   Ready state:", ws?.readyState);
      console.error("   URL attempted:", wsUrl);
      isConnecting = false;
      connEl.textContent = `Error: Check Pi IP & Port ${wsPort}`;
      connEl.style.color = "#f44336";
    };
    
    ws.onclose = (event) => {
      console.log("🔌 WebSocket closed");
      console.log("   Code:", event.code);
      console.log("   Reason:", event.reason || "No reason provided");
      console.log("   Was clean:", event.wasClean);
      
      isConnecting = false;
      ws = null;
      
      if (event.code === 1006) {
        console.error("   ⚠ Abnormal closure (1006) - connection closed without close frame");
        console.error("   This usually means the connection was interrupted");
      }
      
      connEl.textContent = "Disconnected";
      connEl.style.color = "#f44336";
      
      // Only auto-reconnect if not manually closed (code 1000)
      // Don't reconnect if user clicked disconnect or page is unloading
      if (event.code !== 1000 && event.code !== 1001) {
        console.log("   Will retry in 3 seconds...");
        reconnectTimer = setTimeout(() => {
          if (!ws) { // Only reconnect if not already connected
            connect();
          }
        }, 3000);
      }
    };
    
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        
        if (data.type === "status") {
          // Update UI with status data
          currentMode = data.mode || "manual";
          modeEl.textContent = currentMode;
          speedScalar = data.speed_scalar || 1.0;
          speedEl.textContent = `${speedScalar.toFixed(2)}x`;
          pan = data.servos?.pan ?? pan;
          tilt = data.servos?.tilt ?? tilt;
          servosEl.textContent = `Pan ${pan}µs Tilt ${tilt}µs`;
          pumpEl.textContent = data.pump ? "ON" : "OFF";
          flameEl.textContent = data.sensors?.flame_array?.join(",") ?? "";
          irEl.textContent = data.sensors?.ir_array?.join(",") ?? "";
          
          // Log first few status messages, then reduce noise
          if (!ws._statusCount) ws._statusCount = 0;
          ws._statusCount++;
          if (ws._statusCount <= 3) {
            console.log("📊 Status update received:", data);
          } else if (ws._statusCount === 4) {
            console.log("📊 Status updates continuing (logging reduced)...");
          }
        } else if (data.type === "hello") {
          console.log("👋 Server hello received:", data);
          console.log("✅ Connection established! Waiting for status updates...");
        } else if (data.type === "chat_response") {
          addChatMessage(data.message, false);
        } else {
          console.log("📨 Received:", data.type, data);
        }
      } catch (e) {
        console.error("❌ Parse error:", e, ev.data);
      }
    };
  } catch (error) {
    console.error("❌ Failed to create WebSocket:", error);
    isConnecting = false;
    connEl.textContent = "Error: Cannot create connection";
    connEl.style.color = "#f44336";
  }
}

function setVideo(res = "640x480", fps = 30) {
  const videoUrl = `http://${host}:${videoPort}/video.mjpg?res=${res}&fps=${fps}`;
  console.log("Loading video:", videoUrl);
  videoEl.src = videoUrl;
  videoEl.onerror = () => {
    console.error("Video load error - check Pi server and camera");
    videoEl.alt = "Video error - check connection";
  };
  videoEl.onload = () => {
    console.log("Video loaded successfully");
  };
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(obj));
    // Reduced logging noise - only log important commands
    if (obj.type === "mode" || obj.type === "emergency_stop") {
      console.log("📤 Sent:", obj.type, obj);
    }
  } else {
    console.warn("⚠ Cannot send - WebSocket not open. State:", ws?.readyState);
  }
}

const keys = new Set();
// Only capture keys when not typing in input fields
document.addEventListener("keydown", (e) => {
  // Ignore if typing in input field
  if (e.target.tagName === "INPUT" && e.target.id !== "chat-text") return;
  keys.add(e.code);
  handleKeys();
  // Prevent default for game controls
  if (["KeyW", "KeyA", "KeyS", "KeyD", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Space", "Escape", "KeyM"].includes(e.code)) {
    e.preventDefault();
  }
});
document.addEventListener("keyup", (e) => {
  if (e.target.tagName === "INPUT" && e.target.id !== "chat-text") return;
  keys.delete(e.code);
  handleKeys();
});

// Throttle servo commands to reduce noise
let lastServoSend = 0;
const SERVO_THROTTLE_MS = 50; // Send servo commands max every 50ms

function handleKeys() {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    // Show visual feedback that controls won't work
    if (keys.size > 0 && (keys.has("KeyW") || keys.has("KeyA") || keys.has("KeyS") || keys.has("KeyD") || 
        keys.has("ArrowUp") || keys.has("ArrowDown") || keys.has("ArrowLeft") || keys.has("ArrowRight"))) {
      console.warn("⚠ Controls disabled - WebSocket state:", ws?.readyState, "(need OPEN=1)");
    }
    return;
  }
  
  // Log first key press to confirm it's working
  if (keys.size > 0 && !handleKeys._logged) {
    console.log("⌨️ Keyboard input detected - controls active!");
    handleKeys._logged = true;
  }

  let left = 0;
  let right = 0;
  // movement - Fixed: W=forward, S=backward, A=left, D=right
  if (keys.has("KeyW")) { left += 1; right += 1; }
  if (keys.has("KeyS")) { left -= 1; right -= 1; }
  if (keys.has("KeyA")) { left -= 0.5; right += 0.5; }  // Left turn
  if (keys.has("KeyD")) { left += 0.5; right -= 0.5; }  // Right turn
  
  // speed modifiers
  let scalar = 1.0;
  if (keys.has("ShiftLeft") || keys.has("ShiftRight")) scalar = 1.3;
  if (keys.has("ControlLeft") || keys.has("ControlRight")) scalar = 0.7;
  send({ type: "speed_scalar", value: scalar });
  
  if (left !== 0 || right !== 0) {
    send({ type: "drive", left, right });
  } else {
    send({ type: "drive", left: 0, right: 0 });
  }

  // servos - continuous movement with deltas (throttled to reduce noise)
  const now = Date.now();
  let panDelta = 0;
  let tiltDelta = 0;
  if (keys.has("ArrowLeft")) panDelta -= 50;  // Increased step size for faster movement
  if (keys.has("ArrowRight")) panDelta += 50;
  if (keys.has("ArrowUp")) tiltDelta -= 50;
  if (keys.has("ArrowDown")) tiltDelta += 50;
  if (panDelta || tiltDelta) {
    // Throttle servo commands to reduce noise but keep them continuous
    if (now - lastServoSend >= SERVO_THROTTLE_MS) {
      // Update local values for display
      pan += panDelta;
      tilt += tiltDelta;
      // Send delta for smooth continuous movement
      send({ type: "servo_delta", pan_delta: panDelta, tilt_delta: tiltDelta });
      lastServoSend = now;
    }
  }

  if (keys.has("Space")) {
    send({ type: "pump", on: true });
  } else {
    send({ type: "pump", on: false });
  }
  
  if (keys.has("Escape")) {
    send({ type: "emergency_stop" });
  }
  
  if (keys.has("KeyM")) {
    const nextMode = currentMode === "manual" ? "auto" : "manual";
    send({ type: "mode", value: nextMode });
  }
}

// Host input handler
const hostInput = document.getElementById("host-input");
const connectBtn = document.getElementById("connect-btn");

// Initialize host input with saved or default value
const savedHost = localStorage.getItem("robo_host");
if (savedHost) {
  host = savedHost;
  hostInput.value = savedHost;
} else {
  hostInput.value = host;
}

hostInput.addEventListener("keypress", (e) => {
  if (e.key === "Enter") {
    reconnect();
  }
});
connectBtn.addEventListener("click", reconnect);

// Make page focusable for keyboard controls
document.body.setAttribute("tabindex", "0");
document.body.focus();

// Add visual indicator when page has focus
document.body.addEventListener("focus", () => {
  console.log("✅ Page focused - keyboard controls active");
  document.body.style.outline = "2px solid #4caf50";
});

document.body.addEventListener("blur", () => {
  console.log("⚠️ Page lost focus - click on page to enable controls");
  document.body.style.outline = "2px solid #ffa500";
});

// Click anywhere to focus
document.addEventListener("click", (e) => {
  if (e.target.tagName !== "INPUT" && e.target.tagName !== "BUTTON") {
    document.body.focus();
  }
});

function reconnect() {
  const newHost = hostInput.value.trim();
  if (newHost && newHost !== host) {
    // Clear reconnect timer
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    
    host = newHost;
    localStorage.setItem("robo_host", host);
    
    // Close existing connection
    if (ws) {
      ws.onclose = null; // Prevent auto-reconnect
      ws.close(1000, "Manual reconnect");
      ws = null;
    }
    
    isConnecting = false;
    connect();
    setVideo("640x480", 30);
    console.log(`🔄 Manually reconnecting to ${host}...`);
  } else if (!newHost) {
    alert("Please enter a valid IP address or hostname");
  } else {
    console.log(`Already connected to ${host}`);
  }
}

// Prevent connection from closing on page unload
window.addEventListener("beforeunload", () => {
  if (ws) {
    ws.onclose = null; // Prevent reconnect attempt
    ws.close(1000, "Page unloading");
  }
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
  }
});

// init
connect();
setVideo("640x480", 30);

modeToggleBtn.addEventListener("click", () => {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    alert("Not connected! Enter Pi IP and click Connect.");
    return;
  }
  const next = currentMode === "manual" ? "auto" : "manual";
  send({ type: "mode", value: next });
});

toolbarButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    const res = btn.dataset.res;
    setVideo(res, res === "1280x720" ? 30 : 30);
    // Highlight active button
    toolbarButtons.forEach(b => b.style.background = "#232a36");
    btn.style.background = "#2b7cff";
  });
});

// Chat functionality
const chatText = document.getElementById("chat-text");
const chatSend = document.getElementById("chat-send");
const chatLog = document.getElementById("chat-log");

function addChatMessage(msg, isUser = true) {
  const div = document.createElement("div");
  div.style.padding = "4px 8px";
  div.style.marginBottom = "4px";
  div.style.borderRadius = "4px";
  div.style.background = isUser ? "#2b7cff" : "#232a36";
  div.style.color = "#e8ecf0";
  div.textContent = (isUser ? "You: " : "AI: ") + msg;
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
}

if (chatSend && chatText) {
  chatSend.addEventListener("click", () => {
    const msg = chatText.value.trim();
    if (msg && ws && ws.readyState === WebSocket.OPEN) {
      addChatMessage(msg, true);
      send({ type: "chat", message: msg });
      chatText.value = "";
    }
  });

  chatText.addEventListener("keypress", (e) => {
    if (e.key === "Enter") {
      chatSend.click();
    }
  });
}

