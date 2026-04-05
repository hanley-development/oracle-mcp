"""
Connection Manager
Handles: OCI API auth → Bastion session creation → SSH tunnel → ADB wallet connection
"""

import os
import time
import asyncio
import logging
import zipfile
import tempfile
import subprocess
import oci
import oracledb
from pathlib import Path
from config import Config

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.config = Config()
        self.connection = None
        self.tunnel_process = None
        self.bastion_client = None
        self.session_id = None
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

            # Step 1: OCI SDK auth
            logger.info("Authenticating with OCI...")
            oci_config = oci.config.from_file(
                file_location=str(Path.home() / ".oci" / "config"),
                profile_name=self.config.OCI_PROFILE
            )
            oci.config.validate_config(oci_config)
            self.bastion_client = oci.bastion.BastionClient(oci_config)

            # Step 2: Extract wallet
            logger.info("Extracting wallet...")
            self.wallet_dir = tempfile.mkdtemp(prefix="oracle_wallet_")
            with zipfile.ZipFile(self.config.WALLET_ZIP_PATH, 'r') as zf:
                zf.extractall(self.wallet_dir)
            self._patch_sqlnet_ora()

            # Step 3: Create bastion session
            logger.info("Creating OCI Bastion session...")
            session_id, tunnel_host, tunnel_port = await self._create_bastion_session(oci_config)
            self.session_id = session_id

            # Step 4: Open SSH tunnel
            logger.info("Opening SSH tunnel...")
            local_port = self.config.LOCAL_TUNNEL_PORT
            await self._open_ssh_tunnel(tunnel_host, tunnel_port, local_port, oci_config)

            # Step 5: Connect to ADB
            logger.info("Connecting to Oracle ADB...")
            self.connection = self._create_db_connection(local_port)

            schema_info = f" (schema: {self._schema})" if self._schema else ""
            return f"✅ Connected to Oracle ADB{schema_info} via OCI Bastion tunnel. Ready to inspect schema."

        except Exception as e:
            await self._cleanup()
            raise RuntimeError(f"Connection failed: {e}") from e

    def _patch_sqlnet_ora(self):
        """Update sqlnet.ora wallet path to the extracted temp directory."""
        sqlnet_path = os.path.join(self.wallet_dir, "sqlnet.ora")
        if os.path.exists(sqlnet_path):
            with open(sqlnet_path, "r") as f:
                content = f.read()
            # Replace placeholder wallet location with actual temp path
            import re
            content = re.sub(
                r'DIRECTORY="[^"]*"',
                f'DIRECTORY="{self.wallet_dir}"',
                content
            )
            with open(sqlnet_path, "w") as f:
                f.write(content)

    async def _create_bastion_session(self, oci_config: dict):
        """Create a managed SSH port forwarding session via OCI Bastion API."""
        import oci.bastion.models as bm

        # Read the SSH public key to use for the ephemeral session
        pub_key_path = Path(self.config.SSH_PUBLIC_KEY_PATH)
        if not pub_key_path.exists():
            # Generate an ephemeral key pair if none provided
            await self._generate_ephemeral_keypair()
            pub_key_path = Path(self.config.SSH_PUBLIC_KEY_PATH)

        with open(pub_key_path) as f:
            public_key = f.read().strip()

        # Parse the ADB private endpoint host/port from tnsnames.ora
        adb_host, adb_port = self._parse_adb_endpoint()

        session_details = bm.CreateSessionDetails(
            bastion_id=self.config.BASTION_OCID,
            display_name="mcp-oracle-session",
            key_details=bm.PublicKeyDetails(public_key_content=public_key),
            target_resource_details=bm.CreatePortForwardingSessionTargetResourceDetails(
                session_type="PORT_FORWARDING",
                target_resource_private_ip_address=adb_host,
                target_resource_port=adb_port
            ),
            session_ttl_in_seconds=self.config.SESSION_TTL_SECONDS
        )

        response = self.bastion_client.create_session(
            create_session_details=session_details
        )
        session_id = response.data.id

        # Poll until session is ACTIVE
        logger.info(f"Waiting for bastion session {session_id} to become active...")
        for _ in range(30):
            session = self.bastion_client.get_session(session_id).data
            if session.lifecycle_state == "ACTIVE":
                logger.info("Bastion session is ACTIVE")
                ssh_metadata = session.ssh_metadata
                return session_id, ssh_metadata.proxy_jump, ssh_metadata.target_resource_port
            elif session.lifecycle_state in ("FAILED", "DELETED"):
                raise RuntimeError(f"Bastion session entered state: {session.lifecycle_state}")
            await asyncio.sleep(5)

        raise RuntimeError("Timed out waiting for bastion session to become ACTIVE")

    async def _generate_ephemeral_keypair(self):
        """Generate a temporary RSA key pair for the bastion session."""
        key_path = self.config.SSH_PRIVATE_KEY_PATH
        pub_path = self.config.SSH_PUBLIC_KEY_PATH
        proc = await asyncio.create_subprocess_exec(
            "ssh-keygen", "-t", "rsa", "-b", "2048",
            "-f", key_path, "-N", "", "-q",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await proc.wait()
        logger.info(f"Generated ephemeral SSH key pair at {key_path}")

    def _parse_adb_endpoint(self):
        """Extract private endpoint host and port from tnsnames.ora."""
        tns_path = os.path.join(self.wallet_dir, "tnsnames.ora")
        with open(tns_path) as f:
            content = f.read()

        import re
        # Match HOST and PORT in tnsnames.ora
        host_match = re.search(r'HOST\s*=\s*([\w\.\-]+)', content, re.IGNORECASE)
        port_match = re.search(r'PORT\s*=\s*(\d+)', content, re.IGNORECASE)

        if not host_match or not port_match:
            raise ValueError("Could not parse HOST/PORT from tnsnames.ora")

        return host_match.group(1), int(port_match.group(1))

    async def _open_ssh_tunnel(self, tunnel_host: str, tunnel_port: int, local_port: int, oci_config: dict):
        """Open SSH port-forwarding tunnel through OCI Bastion."""
        adb_host, adb_port = self._parse_adb_endpoint()
        private_key = self.config.SSH_PRIVATE_KEY_PATH

        cmd = [
            "ssh",
            "-i", private_key,
            "-N",                           # No command, just tunnel
            "-o", "StrictHostKeyChecking=no",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            "-o", "ExitOnForwardFailure=yes",
            "-L", f"{local_port}:{adb_host}:{adb_port}",
            f"{self.session_id}@{tunnel_host}",
            "-p", str(tunnel_port)
        ]

        self.tunnel_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        # Wait for tunnel to be ready
        for _ in range(20):
            await asyncio.sleep(1)
            if self.tunnel_process.poll() is not None:
                raise RuntimeError("SSH tunnel process exited unexpectedly")
            try:
                import socket
                with socket.create_connection(("127.0.0.1", local_port), timeout=1):
                    logger.info(f"SSH tunnel ready on localhost:{local_port}")
                    return
            except (ConnectionRefusedError, OSError):
                continue

        raise RuntimeError("SSH tunnel did not become ready in time")

    def _create_db_connection(self, local_port: int):
        """Connect to ADB using python-oracledb thin mode via tunnel + wallet."""
        # Build DSN pointing to localhost tunnel
        dsn = f"(DESCRIPTION=(ADDRESS=(PROTOCOL=TCPS)(HOST=127.0.0.1)(PORT={local_port}))(CONNECT_DATA=(SERVICE_NAME={self.config.ADB_SERVICE_NAME}))(SECURITY=(SSL_SERVER_DN_MATCH=yes)))"

        conn = oracledb.connect(
            user=self.config.DB_USERNAME,
            password=self.config.DB_PASSWORD,
            dsn=dsn,
            config_dir=self.wallet_dir,
            wallet_location=self.wallet_dir,
            wallet_password=self.config.WALLET_PASSWORD  # if wallet is password-protected
        )
        return conn

    def get_connection(self):
        return self.connection

    def get_schema(self):
        return self._schema

    async def disconnect(self) -> str:
        await self._cleanup()
        return "✅ Disconnected from Oracle ADB and closed SSH tunnel."

    async def _cleanup(self):
        if self.connection:
            try:
                self.connection.close()
            except Exception:
                pass
            self.connection = None

        if self.tunnel_process:
            self.tunnel_process.terminate()
            self.tunnel_process = None

        if self.session_id and self.bastion_client:
            try:
                self.bastion_client.delete_session(self.session_id)
                logger.info(f"Deleted bastion session {self.session_id}")
            except Exception:
                pass
            self.session_id = None

        if self.wallet_dir and os.path.exists(self.wallet_dir):
            import shutil
            shutil.rmtree(self.wallet_dir, ignore_errors=True)
            self.wallet_dir = None
