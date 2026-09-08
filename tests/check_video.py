"""Optional WebRTC protocol check, without a browser or hardware controls.

Install aiortc separately for this diagnostic. Defaults to the synthetic local
publisher; --url can explicitly select a Pi WHEP endpoint for a read-only check.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from urllib.parse import urljoin, urlparse

import httpx


async def check(url):
    from aiortc import RTCConfiguration, RTCPeerConnection, RTCRtpSender, RTCSessionDescription
    peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    received = asyncio.get_running_loop().create_future()
    tasks = []
    resource = None

    async def consume(track):
        try:
            sizes = []
            for _ in range(10):
                frame = await track.recv()
                sizes.append([frame.width, frame.height])
            if not received.done():
                received.set_result(sizes)
        except Exception as exc:
            if not received.done():
                received.set_exception(exc)

    @peer.on('track')
    def on_track(track):
        if track.kind == 'video':
            tasks.append(asyncio.create_task(consume(track)))

    async with httpx.AsyncClient(timeout=12, trust_env=False) as http:
        try:
            transceiver = peer.addTransceiver('video', direction='recvonly')
            codecs = [codec for codec in RTCRtpSender.getCapabilities('video').codecs
                      if codec.mimeType.lower() == 'video/h264']
            transceiver.setCodecPreferences(codecs)
            await peer.setLocalDescription(await peer.createOffer())
            response = await http.post(url, content=peer.localDescription.sdp,
                                       headers={'Content-Type': 'application/sdp', 'Origin': 'http://localhost:3000'})
            response.raise_for_status()
            assert response.status_code == 201, response.status_code
            assert response.headers.get('access-control-allow-origin') in ('*', 'http://localhost:3000')
            assert 'location' in response.headers.get('access-control-expose-headers', '').lower()
            resource = urljoin(url, response.headers['location'])
            assert urlparse(resource).netloc == urlparse(url).netloc
            await peer.setRemoteDescription(RTCSessionDescription(sdp=response.text, type='answer'))
            try:
                sizes = await asyncio.wait_for(received, timeout=20)
            except TimeoutError:
                raise RuntimeError(f'No video frames: connection={peer.connectionState}, ICE={peer.iceConnectionState}') from None
            assert all(width > 0 and height > 0 for width, height in sizes)
            print(json.dumps({'whep': 'passed', 'codec': 'H264', 'decoded_frames': len(sizes),
                              'dimensions': sizes[0], 'cors': 'passed', 'browser_visual_check': False}))
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await peer.close()
            if resource:
                response = await http.delete(resource)
                if response.status_code != 404:  # A failed/closed ICE session may already be gone.
                    response.raise_for_status()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:18889/cam/whep')
    args = parser.parse_args()
    parsed = urlparse(args.url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        parser.error('Use an HTTP(S) WHEP URL without credentials')
    asyncio.run(check(args.url))
