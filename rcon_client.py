"""
CS2 Source RCON Protocol Client
Implements the Valve Source RCON protocol for communicating with CS2 servers.
"""

from __future__ import annotations

import socket
import struct
import threading
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# RCON Packet Types
SERVERDATA_AUTH = 3
SERVERDATA_AUTH_RESPONSE = 2
SERVERDATA_EXECCOMMAND = 2
SERVERDATA_RESPONSE_VALUE = 0


class RCONError(Exception):
    """Base exception for RCON errors."""
    pass


class RCONAuthError(RCONError):
    """Authentication failed."""
    pass


class RCONConnectionError(RCONError):
    """Connection error."""
    pass


class RCONPacket:
    """Represents an RCON protocol packet."""

    def __init__(self, request_id: int, packet_type: int, body: str):
        self.request_id = request_id
        self.packet_type = packet_type
        self.body = body

    def encode(self) -> bytes:
        """Encode packet to bytes for sending."""
        body_bytes = self.body.encode('utf-8') + b'\x00'
        # Size = 4 (id) + 4 (type) + len(body) + 1 (null terminator for body) + 1 (null terminator for packet)
        # But body_bytes already includes one null, so we add one more
        payload = struct.pack('<ii', self.request_id, self.packet_type) + body_bytes + b'\x00'
        size = len(payload)
        return struct.pack('<i', size) + payload

    @staticmethod
    def decode(data: bytes) -> 'RCONPacket':
        """Decode bytes into an RCONPacket."""
        if len(data) < 8:
            raise RCONError(f"Packet too small ({len(data)} bytes)")
        request_id, packet_type = struct.unpack('<ii', data[:8])
        # Body is everything after ID+Type, minus trailing null terminators
        if len(data) > 10:
            body = data[8:-2].decode('utf-8', errors='replace')
        elif len(data) > 8:
            body = data[8:].rstrip(b'\x00').decode('utf-8', errors='replace')
        else:
            body = ''
        return RCONPacket(request_id, packet_type, body)


class RCONClient:
    """
    CS2 RCON Client for server management.
    Thread-safe implementation with connection management.
    """

    def __init__(self) -> None:
        self.socket: Optional[socket.socket] = None
        self.host: Optional[str] = None
        self.port: Optional[int] = None
        self.password: Optional[str] = None
        self.connected: bool = False
        self.authenticated: bool = False
        self._lock = threading.Lock()
        self._request_id: int = 0
        self._timeout: int = 10

    def _next_request_id(self) -> int:
        """Get next unique request ID."""
        self._request_id += 1
        if self._request_id > 2147483647:
            self._request_id = 1
        return self._request_id

    def connect(self, host: str, port: int, password: str) -> bool:
        """
        Connect and authenticate to the CS2 server.
        Returns True if successful.
        """
        with self._lock:
            # Close existing connection
            self._disconnect_internal()

            self.host = host
            self.port = port
            self.password = password

            try:
                # Resolve hostname first
                resolved = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
                if not resolved:
                    raise RCONConnectionError(f"Cannot resolve hostname: {host}")
                addr_info = resolved[0]
                ip_address = addr_info[4][0]
                logger.info(f"Resolved {host} to {ip_address}")

                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.settimeout(self._timeout)
                self.socket.connect((ip_address, port))
                self.connected = True
                logger.info(f"TCP connected to {ip_address}:{port}")

                # Authenticate
                auth_id = self._next_request_id()
                auth_packet = RCONPacket(auth_id, SERVERDATA_AUTH, password)
                self.socket.sendall(auth_packet.encode())
                logger.info(f"Sent auth packet (id={auth_id})")

                # Read auth response - CS2 may send multiple packets
                # Expect: optional SERVERDATA_RESPONSE_VALUE, then SERVERDATA_AUTH_RESPONSE
                auth_success = False
                for _ in range(5):  # Read up to 5 packets to find auth response
                    try:
                        response = self._read_packet()
                        logger.info(f"Auth recv: id={response.request_id}, type={response.packet_type}, body_len={len(response.body)}")

                        if response.request_id == -1:
                            raise RCONAuthError("Authentication failed - wrong RCON password")

                        if response.packet_type == SERVERDATA_AUTH_RESPONSE and response.request_id == auth_id:
                            auth_success = True
                            break

                        # Also accept if type matches auth_id even with type==0 (some CS2 builds)
                        if response.request_id == auth_id:
                            auth_success = True
                            break

                    except (socket.timeout, RCONConnectionError):
                        break

                if not auth_success:
                    raise RCONAuthError("Authentication failed - no valid auth response received")

                self.authenticated = True
                logger.info("RCON authentication successful")
                return True

            except socket.timeout:
                self._disconnect_internal()
                raise RCONConnectionError(f"Connection to {host}:{port} timed out")
            except socket.gaierror as e:
                self._disconnect_internal()
                raise RCONConnectionError(f"DNS resolution failed for {host}: {str(e)}")
            except socket.error as e:
                self._disconnect_internal()
                raise RCONConnectionError(f"Connection failed: {str(e)}")
            except RCONAuthError:
                self._disconnect_internal()
                raise
            except RCONError as e:
                self._disconnect_internal()
                raise RCONConnectionError(f"RCON protocol error: {str(e)}")

    def _read_packet(self) -> RCONPacket:
        """Read a single RCON packet from the socket."""
        # Read packet size (4 bytes, little-endian int32)
        size_data = self._recv_exact(4)
        size = struct.unpack('<i', size_data)[0]

        # CS2 can send very small auth packets and very large status responses
        if size < 0 or size > 65536:
            raise RCONError(f"Invalid packet size: {size}")

        if size == 0:
            # Empty packet - return dummy
            return RCONPacket(0, 0, '')

        # Read packet body
        body_data = self._recv_exact(size)
        return RCONPacket.decode(body_data)

    def _recv_exact(self, num_bytes: int) -> bytes:
        """Receive exactly num_bytes from socket."""
        if self.socket is None:
            raise RCONConnectionError("Not connected")
        data = b''
        while len(data) < num_bytes:
            try:
                chunk = self.socket.recv(num_bytes - len(data))
                if not chunk:
                    raise RCONConnectionError("Connection closed by server")
                data += chunk
            except socket.timeout:
                raise RCONConnectionError("Read timeout")
        return data

    def execute(self, command: str) -> str:
        """
        Execute an RCON command and return the response.
        Thread-safe.
        """
        with self._lock:
            if not self.connected or not self.authenticated:
                raise RCONConnectionError("Not connected or not authenticated")

            if self.socket is None:
                raise RCONConnectionError("Socket not available")

            try:
                req_id = self._next_request_id()
                packet = RCONPacket(req_id, SERVERDATA_EXECCOMMAND, command)
                self.socket.sendall(packet.encode())

                # Send a follow-up EMPTY COMMAND to detect end of multi-packet response
                # Must be SERVERDATA_EXECCOMMAND (type 2) so CS2 actually responds to it
                end_id = self._next_request_id()
                end_packet = RCONPacket(end_id, SERVERDATA_EXECCOMMAND, "")
                self.socket.sendall(end_packet.encode())

                # Read response - may be multi-packet
                response_body = ""
                old_timeout = self.socket.gettimeout()
                # Use a shorter timeout for reading responses (3 seconds max wait)
                self.socket.settimeout(3)

                try:
                    for _ in range(50):  # Safety limit
                        try:
                            response = self._read_packet()

                            # If we get our end marker back, we're done
                            if response.request_id == end_id:
                                break

                            if response.request_id == req_id:
                                response_body += response.body

                        except (socket.timeout, RCONConnectionError):
                            # Timeout means no more data - that's OK
                            break
                        except RCONError as e:
                            logger.warning(f"Packet read error during execute: {e}")
                            break
                finally:
                    self.socket.settimeout(old_timeout)

                return response_body

            except (socket.error, RCONError) as e:
                self.connected = False
                self.authenticated = False
                raise RCONConnectionError(f"Command execution failed: {str(e)}")

    def disconnect(self):
        """Disconnect from the server."""
        with self._lock:
            self._disconnect_internal()

    def _disconnect_internal(self):
        """Internal disconnect (no lock)."""
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
        self.socket = None
        self.connected = False
        self.authenticated = False

    def is_connected(self) -> bool:
        """Check if client is connected and authenticated."""
        return self.connected and self.authenticated

    def get_server_info(self) -> dict[str, str]:
        """Get server status information."""
        info: dict[str, str] = {}
        try:
            status = self.execute("status")
            info['raw_status'] = status
            # Parse status output
            for line in status.split('\n'):
                line = line.strip()
                if line.startswith('hostname:'):
                    info['hostname'] = line.split(':', 1)[1].strip()
                elif line.startswith('map'):
                    parts = line.split()
                    if len(parts) >= 3:
                        info['map'] = parts[2] if ':' in parts[0] else parts[1]
                elif line.startswith('players'):
                    info['players_line'] = line
                elif 'udp/ip' in line.lower() or 'ip' in line.lower():
                    info['ip_line'] = line
        except Exception as e:
            info['error'] = str(e)
        return info

    def get_players(self) -> list[dict[str, str]]:
        """Get list of connected players."""
        players: list[dict[str, str]] = []
        try:
            status = self.execute("status")
            for line in status.split('\n'):
                line = line.strip()
                if line.startswith('#'):
                    # Parse player line
                    parts = line.split()
                    if len(parts) >= 3 and parts[0] != '#end':
                        player = {
                            'id': parts[0].replace('#', ''),
                            'name': ' '.join(parts[1:-1]) if len(parts) > 3 else parts[1],
                            'raw': line
                        }
                        # Try to extract steamid and other info
                        if 'STEAM_' in line or '[U:' in line:
                            for part in parts:
                                if 'STEAM_' in part or '[U:' in part:
                                    player['steamid'] = part
                                    break
                        players.append(player)
        except Exception as e:
            logger.error(f"Error getting players: {e}")
        return players

    def change_map(self, map_name: str) -> str:
        """Change the current map."""
        return self.execute(f"changelevel {map_name}")

    def kick_player(self, player_id: str, reason: str = "") -> str:
        """Kick a player by their ID."""
        if reason:
            return self.execute(f'kickid {player_id} "{reason}"')
        return self.execute(f'kickid {player_id}')

    def ban_player(self, player_id: str, duration: int = 0, reason: str = "") -> str:
        """Ban a player. Duration in minutes, 0 = permanent."""
        return self.execute(f'banid {duration} {player_id}')

    def set_cvar(self, cvar: str, value: str) -> str:
        """Set a console variable."""
        return self.execute(f'{cvar} {value}')

    def get_cvar(self, cvar: str) -> str:
        """Get a console variable value."""
        return self.execute(cvar)

    def say(self, message: str) -> str:
        """Send a message to all players."""
        return self.execute(f'say "{message}"')

    def restart_round(self) -> str:
        """Restart the current round."""
        return self.execute('mp_restartgame 1')

    def exec_config(self, config_name: str) -> str:
        """Execute a server config file."""
        return self.execute(f'exec {config_name}')
