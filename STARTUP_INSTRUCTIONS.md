# 🚀 Robo 2.0 - Beginner's Guide

This guide will help you set up Robo 2.0 from scratch. **Follow each step exactly.**

---

## 🛠️ Step 1: Hardware Check (Do this first)

1.  **Cable Check**: Ensure the Camera Ribbon is plugged in tight (silver pins facing the HDMI port).
2.  **Power Check**:
    -   Pi: Use a good USB-C power supply (or 5V/3A UBEC).
    -   Motors: Need a separate 12V battery (>7V is mandatory).
    -   Grounds: **IMPORTANT!** The Battery Pro/Negative wire must connect to the Pi's Ground pin. If Grounds are not connected, nothing will work.

---

## 🤖 Step 2: Preparing the Pi (The Robot)

1.  **Open Terminal**: Log in to your Pi and open a terminal window.
2.  **Navigate to Folder**:
    ```bash
    cd ~/Desktop/PI
    ```
    *(If your folder is named differently, use `ls` to find it)*
    
3.  **Activate Virtual Environment** (Prevents system breakage):
    ```bash
    source .venv/bin/activate
    ```
    *(If this fails, run `python3 -m venv .venv` first)*

4.  **Install Requirements** (Only need to do this once):
    ```bash
    pip install -r requirements.txt
    ```

5.  **Start the Server**:
    ```bash
    python server.py
    ```
    
    You should see: `✅ All hardware initialized!`
    
    > **Technical Note**: The server will listen on Port 8765 (Controls) and 8080 (Video).

---

## 💻 Step 3: Preparing the Laptop (The Brain)

1.  **Open Command Prompt/Terminal** on your Laptop.
2.  **Go to Project Folder**:
    ```bash
    cd Documents\Programming\MKBA\Laptop\PC
    ```
    *(Adjust path if needed)*

3.  **Find the Pi's IP**:
    -   Look at the Pi terminal. It doesn't show IP?
    -   Run `hostname -I` on the Pi. Let's say it is `192.168.29.59`.

4.  **Launch Auto Mode / Web UI**:
    Run this command (replace the IP with YOUR Pi's IP):
    ```bash
    python auto_mode.py --host 192.168.29.59
    ```

5.  **Browser Opens**:
    -   Chrome should open automatically.
    -   Double check that the "Pi IP" box at the top matches the IP you typed.
    -   Click **Connect**.
    -   Status should turn **GREEN**.

---

## ❓ Troubleshooting (If things go wrong)

<details>
<summary>❌ I can't connect (Status stays Red)</summary>

1.  **Ping Test**: Open Laptop terminal and type `ping 192.168.29.X` (your Pi IP).
    -   If "Request timed out": Pi is not on the same Wi-Fi.
    -   If "Reply from...": Network is good, check next step.
2.  **Firewall**: Disable Windows Firewall temporarily to test. Port 8765 might be blocked.
3.  **Check Pi Server**: Is `server.py` still running? Did it crash?
</details>

<details>
<summary>❌ Pump says "ON" but water doesn't flow</summary>

1.  **Active Low/High Mismatch**:
    -   Open `PI/config.py` on the Pi.
    -   Find `RELAY_ACTIVE_LOW = True`.
    -   Change it to `False`, save, and restart `server.py`.
2.  **Wiring**:
    -   Is the relay LED turning on?
        -   **No**: wiring issue.
        -   **Yes**: Pump voltage issue (battery dead?).
</details>

<details>
<summary>❌ Video freezes</summary>

1.  **Power**: The Pi camera freezes if voltage drops. Ensure Pi power is stable.
2.  **Resolution**: Click the **640x480** button to reduce bandwidth usage.
</details>

---

## 🎓 Advanced Users

-   **Auto Mode**: Press 'M' to toggle between Manual and AI mode.
-   **Config**: Edit `PI/config.py` to change motor pins or speeds.
-   **Docs**: See code comments in `hardware/*.py` for driver details.
