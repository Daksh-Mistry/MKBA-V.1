import unittest

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from Backend.app import create_app
from Backend.config import Settings
from Backend.controller import RobotController
class FakePi:
    async def start(self, callback):
        pass

    async def send(self, data):
        pass

    async def close(self):
        pass


class FakeML:
    async def start(self, callback):
        pass

    async def send(self, data):
        pass

    async def models(self):
        return {'models': []}

    async def chat(self, data):
        return {'text': 'ok'}

    async def close(self):
        pass


class APITests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(service_token='', ir_blocked_value=0, motion_calibrated=True)
        self.pi, self.ml = FakePi(), FakeML()
        self.robot = RobotController(self.settings, pi=self.pi, ml=self.ml)
        self.app = create_app(self.settings, controller=self.robot)

    def test_http_endpoints(self):
        with TestClient(self.app) as client:
            self.assertEqual(client.get('/api/v1/health').status_code, 200)
            response = client.get('/api/v1/robot')
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()['stopped'])
            video = client.get('/api/v1/video/sources').json()
            self.assertTrue(video['whep_url'].endswith('/cam/whep'))
            self.assertEqual(client.get('/api/v1/ml/models').status_code, 200)

    def test_websocket_handshake_and_malformed_json(self):
        with TestClient(self.app) as client:
            with client.websocket_connect('/api/v1/ws') as ws:
                hello = ws.receive_json()
                self.assertEqual(hello['type'], 'hello')
                ws.receive_json()  # State snapshot
                ws.send_text('{malformed json')
                err = ws.receive_json()
                self.assertEqual(err['type'], 'error')

    def test_binary_and_oversize_messages_close(self):
        with TestClient(self.app) as client:
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect('/api/v1/ws') as ws:
                    ws.receive_json()
                    ws.receive_json()
                    ws.send_bytes(b'binary message')
                    while True:
                        ws.receive_json()
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect('/api/v1/ws') as ws:
                    ws.receive_json()
                    ws.receive_json()
                    ws.send_text('x' * 16385)
                    while True:
                        ws.receive_json()


if __name__ == '__main__':
    unittest.main()
