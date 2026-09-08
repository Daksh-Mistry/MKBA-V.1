// FILE: logic.js
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
const toolbarButtons = document.querySelectorAll("#video-toolbar button[data-res]");
const chatLog = document.getElementById("chat-log");
const chatText = document.getElementById("chat-text");
const chatSend = document.getElementById("chat-send");
const modeToggleBtn = document.getElementById("mode-toggle");

let ws = null;
let isConnecting = false;
let reconnectTimer = null;
let currentMode = "manual";

function connect() {
  if (isConnecting) return;
  if (ws) { ws.close(); ws = null; }

  if (ws) { ws.close(); ws = null; }

  // CRITICAL FIX: Connect WS to the Laptop (Commander), not the Pi directly!
  // The Laptop serves this file, so use window.location.hostname.
  const wsHost = window.location.hostname || "localhost";
  const wsUrl = `ws://${wsHost}:${wsPort}`;

  console.log(`🔌 Connecting to Brain at ${wsUrl}... (Video from ${host})`);
  connEl.textContent = "Connecting to Brain...";
  isConnecting = true;

  try {
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log("✅ Connected");
      isConnecting = false;
      connEl.textContent = `Connected (${host})`;
      connEl.style.color = "#4caf50";
      localStorage.setItem("robo_host", host);
      setVideo("640x480");

      const overlay = document.getElementById("loading-overlay");
      if (overlay) { overlay.style.opacity = "0"; setTimeout(() => overlay.remove(), 500); }
    };

    ws.onclose = (e) => {
      isConnecting = false;
      ws = null;
      connEl.textContent = "Disconnected";
      connEl.style.color = "#f44336";
      if (e.code !== 1000) reconnectTimer = setTimeout(() => { if (!ws) connect(); }, 2000);
    };

    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data.type === "status") {
          updateDashboard(data);
        } else if (data.type === "chat_response") {
          addChatMessage(data.message, false);
        }
      } catch (e) { }
    };
  } catch (error) { isConnecting = false; }
}

function updateDashboard(data) {
  currentMode = data.mode || "manual";
  modeEl.textContent = currentMode.toUpperCase();
  speedEl.textContent = ((data.speed ?? 0.5) * 100).toFixed(0) + "%";
  if (data.pump !== undefined) pumpEl.textContent = data.pump ? "ON" : "OFF";
  if (data.sensors?.flame_array) flameEl.textContent = data.sensors.flame_array.join(",");
  if (data.sensors?.ir_array) irEl.textContent = data.sensors.ir_array.join(",");
  if (data.servos) servosEl.textContent = `P:${data.servos.pan} T:${data.servos.tilt}`;

  if (modeToggleBtn) {
    modeToggleBtn.textContent = currentMode === "auto" ? "STOP AUTO" : "START AUTO";
    modeToggleBtn.style.background = currentMode === "auto" ? "#e91e63" : "#2b7cff";
  }
}

// VIDEO FIX: Hardcoded IP + Reduced FPS to 20
function setVideo(res = "640x480", fps = 20) {
  if (!videoEl) return;

  toolbarButtons.forEach(btn => {
    btn.style.background = "#232a36";
    btn.style.fontWeight = "normal";
    btn.style.border = "1px solid #384455";
  });

  // DYNAMIC PI IP: Uses the host variable (from URL or localStorage)
  const videoUrl = `http://${host}:${videoPort}/video.mjpg?res=${res}&fps=${fps}&_=${Date.now()}`;

  videoEl.src = "";
  setTimeout(() => videoEl.src = videoUrl, 100);

  videoEl.onload = () => {
    toolbarButtons.forEach(btn => {
      if (btn.dataset.res === res) {
        btn.style.background = "#2b7cff";
        btn.style.fontWeight = "bold";
        btn.style.border = "2px solid white";
      }
    });
  };
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

const keys = new Set();
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") return;
  keys.add(e.code);
  handleKeys();
  if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Space"].includes(e.code)) e.preventDefault();
});
document.addEventListener("keyup", (e) => {
  if (e.target.tagName === "INPUT") return;
  keys.delete(e.code);
  handleKeys();
});

// PUMP TOGGLE LOGIC
let isPumpOn = false;
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") return;
  if (e.code === "Space" && !e.repeat) {
    isPumpOn = !isPumpOn; // Toggle state
    send({ type: "pump", on: isPumpOn });
  }
});

function handleKeys() {
  if (!ws || ws.readyState !== WebSocket.OPEN || currentMode === "auto") return;

  const w = keys.has("KeyW");
  const s = keys.has("KeyS");
  const a = keys.has("KeyA");
  const d = keys.has("KeyD");

  let left = 0.0;
  let right = 0.0;

  // --- SWAPPED LOGIC (MATCHING YOUR REQUEST) ---
  if (w && !s) {
    left = 1.0; right = -1.0;
    if (a) { left = -1.0; }
    if (d) { right = 1.0; }
  }
  else if (s && !w) {
    left = -1.0; right = 1.0;
    if (a) { left = 1.0; }
    if (d) { right = -1.0; }
  }
  else if (a && !d) {
    left = -1.0; right = -1.0;
  }
  else if (d && !a) {
    left = 1.0; right = 1.0;
  }

  let scalar = 1.0;
  if (keys.has("ShiftLeft")) scalar = 1.3;
  if (keys.has("ControlLeft")) scalar = 0.6;

  send({ type: "drive", left, right, speed: 0.5 * scalar });

  let panDelta = 0;
  let tiltDelta = 0;
  if (keys.has("ArrowLeft")) panDelta += 5;
  if (keys.has("ArrowRight")) panDelta -= 5;
  if (keys.has("ArrowUp")) tiltDelta -= 5;
  if (keys.has("ArrowDown")) tiltDelta += 5;

  if (panDelta || tiltDelta) {
    send({ type: "servo", pan: panDelta, tilt: tiltDelta });
  }

  // Pump logic moved to separate event listener for TOGGLE behavior
  // send({ type: "pump", on: keys.has("Space") });
  if (keys.has("Escape")) send({ type: "system", command: "stop" });
  if (keys.has("KeyM")) send({ type: "mode", value: currentMode === "manual" ? "auto" : "manual" });
}

toolbarButtons.forEach(btn => btn.addEventListener("click", () => setVideo(btn.dataset.res)));
if (modeToggleBtn) modeToggleBtn.addEventListener("click", () => send({ type: "mode", value: currentMode === "manual" ? "auto" : "manual" }));

document.getElementById("connect-btn").addEventListener("click", () => {
  host = document.getElementById("host-input").value;
  connect();
});
document.getElementById("host-input").value = host;

function addChatMessage(msg, isUser) {
  const div = document.createElement("div");
  div.className = "chat-msg" + (isUser ? " user" : "");
  div.textContent = (isUser ? "You: " : "AI: ") + msg;
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
}

if (chatSend) {
  chatSend.addEventListener("click", () => {
    const msg = chatText.value;
    if (msg) {
      addChatMessage(msg, true);
      send({ type: "chat", message: msg });
      chatText.value = "";
    }
  });
  chatText.addEventListener("keypress", (e) => { if (e.key === "Enter") chatSend.click(); });
}

// NEW CONTROLS
document.getElementById("estop-btn").addEventListener("click", () => send({ type: "system", command: "stop" }));
document.getElementById("shutdown-btn").addEventListener("click", () => {
  if (confirm("Stop robot server and camera stream?")) send({ type: "system", command: "shutdown" });
});

// FLIP BUTTON LOGIC
let isFlipped = false;
const flipBtn = document.getElementById("flip-btn");
if (flipBtn) {
  flipBtn.addEventListener("click", () => {
    isFlipped = !isFlipped;
    if (videoEl) videoEl.style.transform = isFlipped ? "scaleX(-1)" : "none";
  });
}

connect();
