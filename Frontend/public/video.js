/** Direct Pi WHEP playback: complete SDP exchange, no backend frame forwarding. */
export class PiVideo {
  constructor(video, onStatus) {
    this.video = video;
    this.onStatus = onStatus;
    this.generation = 0;
    this.peer = null;
    this.resource = null;
    this.abort = null;
    this.retry = null;
  }
  async connect(source) {
    this.stop(false);
    this.source = source;
    const generation = this.generation;
    const endpoint = new URL(source.whep_url);
    if (!['http:', 'https:'].includes(endpoint.protocol) || endpoint.username || endpoint.password) throw new Error('Invalid camera URL.');
    if (!globalThis.RTCPeerConnection) { this.onStatus('error', 'WebRTC is unavailable. Open the console on localhost or HTTPS.'); return; }
    this.onStatus('connecting', 'Opening a direct connection to the Pi…');
    const peer = new RTCPeerConnection({ iceServers: source.ice_servers || [] });
    this.peer = peer;
    const abort = new AbortController();
    this.abort = abort;
    let deadline = setTimeout(() => abort.abort(), 12_000);
    const failed = message => {
      if (generation !== this.generation) return;
      this.onStatus('error', message);
      if (!this.retry) this.retry = setTimeout(() => { this.retry = null; this.connect(source).catch(() => {}); }, 5000);
    };
    peer.ontrack = event => {
      if (generation !== this.generation) return;
      this.video.srcObject = event.streams[0] || new MediaStream([event.track]);
      this.video.play().catch(() => this.onStatus('error', 'Press Connect video to allow playback.'));
    };
    peer.onconnectionstatechange = () => {
      if (generation !== this.generation) return;
      if (peer.connectionState === 'connected') this.onStatus('connected', 'Direct video connected');
      else if (['failed', 'disconnected'].includes(peer.connectionState)) failed('Camera connection lost. Retrying…');
    };
    try {
      peer.addTransceiver('video', { direction: 'recvonly' });
      await peer.setLocalDescription(await peer.createOffer());
      if (peer.iceGatheringState !== 'complete') await new Promise((resolve, reject) => {
        const timer = setTimeout(() => finish(new Error('Camera ICE gathering timed out.')), 5000);
        const changed = () => { if (peer.iceGatheringState === 'complete') finish(); };
        const cancelled = () => finish(new Error('Camera connection cancelled.'));
        const finish = error => { clearTimeout(timer); peer.removeEventListener('icegatheringstatechange', changed); abort.signal.removeEventListener('abort', cancelled); error ? reject(error) : resolve(); };
        peer.addEventListener('icegatheringstatechange', changed);
        abort.signal.addEventListener('abort', cancelled, { once: true });
        if (abort.signal.aborted) cancelled(); else changed();
      });
      if (generation !== this.generation) return;
      const response = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/sdp' }, body: peer.localDescription.sdp, signal: abort.signal, credentials: 'omit' });
      if (!response.ok) throw new Error(`Camera signaling returned ${response.status}. Check MediaMTX and the camera path.`);
      const location = response.headers.get('location');
      const resource = location ? new URL(location, endpoint) : null;
      if (resource && resource.origin === endpoint.origin) {
        if (generation !== this.generation) { fetch(resource, { method: 'DELETE', credentials: 'omit' }).catch(() => {}); return; }
        this.resource = resource;
      }
      const sdp = await response.text();
      if (generation !== this.generation) return;
      await peer.setRemoteDescription({ type: 'answer', sdp });
      clearTimeout(deadline);
      deadline = setTimeout(() => { if (peer.connectionState !== 'connected') failed('Video negotiation timed out. Check Pi UDP 8189 reachability.'); }, 12_000);
      peer.addEventListener('connectionstatechange', () => { if (peer.connectionState === 'connected') clearTimeout(deadline); });
    } catch (error) {
      if (generation === this.generation) failed(error.name === 'AbortError' ? 'Camera request timed out. Check the Pi address and CORS settings.' : error.message);
    } finally {
      if (peer.connectionState === 'connected' || peer.signalingState === 'closed') clearTimeout(deadline);
    }
  }
  stop(report = true) {
    this.generation++;
    clearTimeout(this.retry);
    this.retry = null;
    this.abort?.abort();
    this.abort = null;
    if (this.peer) { this.peer.ontrack = null; this.peer.onconnectionstatechange = null; this.peer.close(); }
    this.peer = null;
    if (this.resource) fetch(this.resource, { method: 'DELETE', credentials: 'omit', keepalive: true }).catch(() => {});
    this.resource = null;
    this.video.srcObject = null;
    if (report) this.onStatus('offline', 'Video disconnected');
  }
}
