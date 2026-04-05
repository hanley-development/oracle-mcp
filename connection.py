"""
Connection Manager
Supports two tunnel modes (set TUNNEL_MODE in config.py):

  "manual" — you run the ossh command yourself before calling connect.
             The server just connects to localhost:LOCAL_TUNNEL_PORT.

  "auto"   — the server spawns the ossh command for you on connect,
             then connects to localhost:LOCAL_TUNNEL_PORT.
"""

import os
import asyncio
import logging
import zipfile
import tempfile
import subprocess
import socket
import shutil
import re
import oracledb
from pathlib import Path
from config import Config

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.config = Config()
        self.connection = None
        self.tunnel_process = None
        self.wallet_dir = None
        self._schema = None

    def is_connected(self) -> bool:
        if self.connection is None:
            return False
        try:
            self.connection.ping()
            return True
        except Exception:
            return False

    async def connect(self, schema: str = None) -> str:
        try:
            self._schema = schema

            # Step 1: Extract wallet to temp dir
            logger.info("Extracting wallet...")
            self.wallet_dir = tempfile.mkdtemp(prefix="oracle_wallet_")
            with zipfile.ZipFile(self.config.WALLET_ZIP_PATH, "r") as zf:
                zf.extractall(self.wallet_dir)
            self._patch_sqlnet_ora()

            # Step 2: Tunnel — auto-spawn or verify manual
            if self.config.TUNNEL_MODE == "auto":
                logger.info("Spawning ossh tunnel...")
                await self._spawn_ossh_tunnel()
                tunnel_note = "tunnel opened automatically via ossh"
            else:
                logger.info("Manual mode — verifying tunnel on localhost...")
                self._assert_tunnel_reachable()
                tunnel_note = "using pre-existing tunnel on localhost"

            # Step 3: Connect to ADB
            logger.info("Connecting to Oracle ADB...")
            self.connection = self._create_db_connection()

            schema_info = f" (schema: {self._schema})" if self._schema else ""
            return (
                f"✅ Connected to Oracle ADB{schema_info}. "
                f"Tunnel mode: {tunnel_note}. Ready to inspect schema."
            )

        except Exception as e:
            await self._cleanup()
            raise RuntimeError(f"Connection failed: {e}") from e

    # ── Wallet ─────────────────────────────────────────────────────────────────

    def _patch_sqlnet_ora(self):
        """Rewrite wallet path in sqlnet.ora to the extracted temp dir."""
        sqlnet_path = os.path.join(self.wallet_dir, "sqlnet.ora")
        if not os.path.exists(sqlnet_path):
            return
        with open(sqlnet_path, "r") as f:
            content = f.read()
        content = re.sub(
            r'DIRECTORY="[^"]*"',
            f'DIRECTORY="{self.wallet_dir}"',
            content
        )
        with open(sqlnet_path, "w") as f:
            f.write(content)

    # ── Tunnel: auto mode ──────────────────────────────────────────────────────

    async def _spawn_ossh_tunnel(self):
        """Launch the ossh tunnel as a background subprocess."""
        cfg = self.config
        cmd = [
            "ossh", "proxy",
            "-V",
            f"-U{cfg.DB_USERNAME}",
            "--overlay-bastion",
            "--region", cfg.OCI_REGION,
            "--compartment", cfg.COMPARTMENT_OCID,
            "--", "ssh",
            f"stb-internal.bastion{cfg.OCI_REGION}.oci.oracleiaas.com",
            "-p", "22",
            "-A",
            "-s", f"proxy:{cfg.BASTION_SESSION_OCID}",
            cfg.ADB_PRIVATE_IP,
            "-L", f"{cfg.LOCAL_TUNNEL_PORT}:{cfg.ADB_HOSTNAME}:{cfg.ADB_PORT}",
            "-t", "watch", "-n", "90", "date"
        ]

        self.tunnel_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        # Wait up to 30s for the local port to open
        for _ in range(30):
            await asyncio.sleep(1)
            if self.tunnel_process.poll() is not None:
                raise RuntimeError(
                    "ossh tunnel process exited unexpectedly. "
                    "Check BASTION_SESSION_OCID and COMPARTMENT_OCID in config.py."
                )
            if self._port_open():
                logger.info(f"Tunnel ready on localhost:{cfg.LOCAL_TUNNEL_PORT}")
                return

        raise RuntimeError(
            f"Tunnel did not open on localhost:{cfg.LOCAL_TUNNEL_PORT} within 30s."
        )

    # ── Tunnel: manual mode ────────────────────────────────────────────────────

    def _assert_tunnel_reachable(self):
        """Verify the manually-opened tunnel is listening before we try to connect."""
        if not self._port_open():
            raise RuntimeError(
                f"No listener found on localhost:{self.config.LOCAL_TUNNEL_PORT}. "
                f"Please run your ossh command first, then call connect again."
            )

    def _port_open(self) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", self.config.LOCAL_TUNNEL_PORT), timeout=1):
                return True
        except (ConnectionRefusedError, OSError):
            return False

    # ── DB connection ──────────────────────────────────────────────────────────

    def _create_db_connection(self):
        """Connect via oracledb thin mode through the local tunnel + wallet."""
        port = self.config.LOCAL_TUNNEL_PORT
        dsn = (
            f"(DESCRIPTION="
            f"(ADDRESS=(PROTOCOL=TCPS)(HOST=127.0.0.1)(PORT={port}))"
            f"(CONNECT_DATA=(SERVICE_NAME={self.config.ADB_SERVICE_NAME}))"
            f"(SECURITY=(SSL_SERVER_DN_MATCH=yes)))"
        )
        return oracledb.connect(
            user=self.config.DB_USERNAME,
            password=self.config.DB_PASSWORD,
            dsn=dsn,
            config_dir=self.wallet_dir,
            wallet_location=self.wallet_dir,
            wallet_password=self.config.WALLET_PASSWORD
        )

    # ── Accessors ──────────────────────────────────────────────────────────────

    def get_connection(self):
        return self.connection

    def get_schema(self):
        return self._schema

    # ── Disconnect ─────────────────────────────────────────────────────────────

    async def disconnect(self) -> str:
        await self._cleanup()
        return "✅ Disconnected from Oracle ADB and cleaned up tunnel/wallet."

    async def _cleanup(self):
        if self.connection:
            try:
                self.connection.close()
            except Exception:
                pass
            self.connection = None

        if self.tunnel_process:
            self.tunnel_process.terminate()
            try:
                self.tunnel_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.tunnel_process.kill()
            self.tunnel_process = None

        if self.wallet_dir and os.path.exists(self.wallet_dir):
            shutil.rmtree(self.wallet_dir, ignore_errors=True)
            self.wallet_dir = None
