"""Threaded WebSocket server for StickS3 status and control messages."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import Server, ServerConnection, serve

from .device_protocol import (
    DeviceProtocolError,
    DeviceState,
    parse_device_event,
    serialize_state_message,
)


EventCallback = Callable[[str], None]
ConnectionCallback = Callable[[str], None]


class DeviceWebSocketServer:
    """Broadcast Python state and receive StickS3 events in a worker thread."""

    def __init__(
        self,
        host: str,
        port: int,
        on_alarm_cancelled: EventCallback,
        on_connected: ConnectionCallback | None = None,
        on_disconnected: ConnectionCallback | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self._on_alarm_cancelled = on_alarm_cancelled
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._clients: set[ServerConnection] = set()
        self._clients_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._last_message: str | None = None
        self._server: Server | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._start_error: Exception | None = None

    def start(self, timeout: float = 5.0) -> None:
        """Start listening and wait until the socket is ready."""

        if self._thread is not None and self._thread.is_alive():
            return
        self._ready.clear()
        self._start_error = None
        self._thread = threading.Thread(
            target=self._serve,
            name="sticks3-websocket",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError("WebSocket server did not start in time")
        if self._start_error is not None:
            raise RuntimeError(f"Failed to start WebSocket server: {self._start_error}")

    def broadcast_state(self, state: DeviceState, timestamp: datetime) -> None:
        """Send a state update to all currently connected devices."""

        message = serialize_state_message(state, timestamp)
        with self._send_lock:
            self._last_message = message
            with self._clients_lock:
                clients = tuple(self._clients)
            for client in clients:
                try:
                    client.send(message)
                except (ConnectionClosed, OSError):
                    self._discard_client(client)

    def stop(self, timeout: float = 5.0) -> None:
        """Stop accepting connections and wait for the worker thread."""

        with self._send_lock:
            with self._clients_lock:
                clients = tuple(self._clients)
            for client in clients:
                try:
                    client.close(code=1001, reason="Python service stopping")
                except (ConnectionClosed, OSError):
                    pass
        server = self._server
        if server is not None:
            server.shutdown()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        self._server = None
        self._thread = None

    def _serve(self) -> None:
        try:
            with serve(self._handle_client, self.host, self.port) as server:
                self._server = server
                self._ready.set()
                server.serve_forever()
        except Exception as exc:
            self._start_error = exc
            self._ready.set()

    def _handle_client(self, client: ServerConnection) -> None:
        source = self._client_source(client)
        with self._clients_lock:
            self._clients.add(client)
        if self._on_connected is not None:
            self._on_connected(source)

        try:
            with self._send_lock:
                if self._last_message is not None:
                    client.send(self._last_message)
            for message in client:
                try:
                    event = parse_device_event(message)
                except DeviceProtocolError as exc:
                    print(f"忽略来自 {source} 的无效设备消息：{exc}")
                    continue
                if event == "ALARM_CANCELLED":
                    self._on_alarm_cancelled(source)
        except ConnectionClosed:
            pass
        finally:
            self._discard_client(client)
            if self._on_disconnected is not None:
                self._on_disconnected(source)

    def _discard_client(self, client: ServerConnection) -> None:
        with self._clients_lock:
            self._clients.discard(client)

    @staticmethod
    def _client_source(client: ServerConnection) -> str:
        address = client.remote_address
        if isinstance(address, tuple) and address:
            return f"sticks3:{address[0]}"
        return "sticks3:unknown"
