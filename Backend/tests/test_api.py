import unittest

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from Backend.app import create_app
from Backend.config import Settings
from Backend.controller import RobotController
from Backend.tests.test_controller import FakeML, FakePi


class APITests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(service_token='unit-test-service-token', ir_blocked_value=0,
                                 motion_calibrated=True)
        self.pi, self.ml = FakePi(), FakeML()
        self.robot = RobotController(self.settings, pi=self.pi, ml=self.ml)
        self.app = create_app(self.settings, controller=self.robot)
        self.headers = {'Authorization': 'Bearer unit-test-service-token'}

    def test_http_auth_origin_and_public_health(self):
        with TestClient(self.app) as client:
            self.assertEqual(client.get('/api/v1/health').status_code, 200)
            self.assertEqual(client.get('/api/v1/robot').status_code, 401)
            self.assertEqual(client.get('/api/v1/robot', headers={**self.headers, 'Origin': 'http://evil.test'}).status_code, 401)
            response = client.get('/api/v1/robot', headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()['stopped'])
            self.assertNotIn('unit-test-service-token', response.text)
            video = client.get('/api/v1/video/sources', headers=self.headers).json()
            self.assertTrue(video['whep_url'].endswith('/cam/whep'))
            self.assertEqual(client.get('/api/v1/ml/models', headers=self.headers).status_code, 200)

    def test_websocket_auth(self):
        with TestClient(self.app) as client:
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect('/api/v1/ws'):
                    pass
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect('/api/v1/ws', headers={**self.headers, 'Origin': 'http://evil.test'}):
                    pass

    def test_websocket_contract_disconnect_and_malformed_json(self):
        with TestClient(self.app) as client:
            with client.websocket_connect('/api/v1/ws', headers=self.headers) as ws:
                hello = ws.receive_json()
                self.assertEqual(hello['type'], 'hello')
                ws.receive_json()
                ws.send_text('{broken')
                while ws.receive_json()['type'] != 'error':
                    pass
                ws.send_json({'type': 'control', 'command': 'claim', 'request_id': 'claim', 'seq': 1})
                while True:
                    message = ws.receive_json()
                    if message.get('request_id') == 'claim':
                        self.assertEqual(message['status'], 'completed')
                        break
                ws.send_json({'type': 'heartbeat', 'request_id': 'beat', 'seq': 2})
                while True:
                    message = ws.receive_json()
                    if message.get('request_id') == 'beat':
                        self.assertEqual(message['type'], 'heartbeat_ack')
                        break
            self.assertTrue(self.robot.stopped)
            self.assertIsNone(self.robot.owner)

    def test_binary_and_oversize_messages_close(self):
        with TestClient(self.app) as client:
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect('/api/v1/ws', headers=self.headers) as ws:
                    ws.receive_json()
                    ws.receive_json()
                    ws.send_bytes(b'hello')
                    while True:
                        ws.receive_json()
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect('/api/v1/ws', headers=self.headers) as ws:
                    ws.receive_json()
                    ws.receive_json()
                    ws.send_text('x' * 16385)
                    while True:
                        ws.receive_json()


if __name__ == '__main__':
    unittest.main()
