# Historical web client

This folder preserves an older direct-Pi browser client. It is **not loaded by the normal launcher** and its old ports, video path, keyboard bindings and command formats are not the current API.

Use the active [Frontend service](../../Frontend/README.md), which routes controls and metadata through the [Backend](../README.md) and reads Pi video directly using WebRTC. Start with [Getting started](../../Documents/GETTING_STARTED.md); the exact replacement contract is [API_BACKEND_FRONTEND.md](../../Documents/API_BACKEND_FRONTEND.md).

Do not open this historical UI to operate the current robot or run its direct control connection alongside the backend. It bypasses the current ownership, readiness, chat and auto-control architecture.
