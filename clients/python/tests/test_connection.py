
import asyncio
import unittest
import websockets
from websockets.frames import Close
from unittest.mock import AsyncMock, MagicMock, patch

from sandbox.connection import Connection

class TestConnection(unittest.TestCase):
    @patch('websockets.connect', new_callable=AsyncMock)
    def test_successful_connection_and_messaging(self, mock_connect):
        """
        Verify that the Connection class can connect, send, and receive messages.
        """
        async def run_test():
            mock_ws = AsyncMock()
            mock_ws.state = websockets.protocol.State.OPEN
            mock_ws.recv.side_effect = ["message1", "message2", websockets.exceptions.ConnectionClosed(rcvd=Close(1000, "Normal"), sent=None)]
            mock_connect.return_value = mock_ws

            on_message_mock = MagicMock()
            on_error_mock = MagicMock()
            on_close_mock = MagicMock()

            conn = Connection(
                url="ws://fake-url",
                on_message=on_message_mock,
                on_error=on_error_mock,
                on_close=on_close_mock,
            )
            
            connect_task = asyncio.create_task(conn.connect())
            await asyncio.sleep(0.01)

            self.assertEqual(on_message_mock.call_count, 2)
            on_message_mock.assert_any_call("message1")
            on_message_mock.assert_any_call("message2")

            await connect_task
            on_close_mock.assert_called_once_with(1000, "Normal")
            on_error_mock.assert_not_called()

        asyncio.run(run_test())

    @patch('websockets.connect', new_callable=AsyncMock)
    def test_connection_failure(self, mock_connect):
        """
        Verify that the on_error callback is triggered on connection failure.
        """
        async def run_test():
            connection_error = ConnectionRefusedError("Connection refused")
            mock_connect.side_effect = connection_error

            on_message_mock = MagicMock()
            on_error_mock = MagicMock()
            on_close_mock = MagicMock()

            conn = Connection(
                url="ws://fake-url",
                on_message=on_message_mock,
                on_error=on_error_mock,
                on_close=on_close_mock,
            )

            with self.assertRaises(ConnectionRefusedError):
                await conn.connect()

            on_error_mock.assert_called_once_with(connection_error)
            on_message_mock.assert_not_called()
            on_close_mock.assert_not_called()

        asyncio.run(run_test())

if __name__ == '__main__':
    unittest.main()
