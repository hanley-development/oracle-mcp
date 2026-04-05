"""
Configuration — edit this file with your environment details.
"""

import os
from pathlib import Path


class Config:
    # ── OCI ────────────────────────────────────────────────────────────────────
    OCI_PROFILE: str = "OCI01"

    # OCID of your OCI Bastion resource (not the session — the Bastion itself)
    # Found in OCI Console → Bastion → copy OCID
    BASTION_OCID: str = os.getenv("BASTION_OCID", "ocid1.bastion.oc1..<your-bastion-ocid>")

    # ── SSH Keys ────────────────────────────────────────────────────────────────
    # Path to SSH private key for bastion session auth.
    # If you leave these as-is, an ephemeral key pair will be auto-generated
    # in C:\scripts\ on first run.
    SSH_PRIVATE_KEY_PATH: str = os.getenv(
        "SSH_PRIVATE_KEY_PATH",
        str(Path(r"C:\scripts\mcp_bastion_key"))
    )
    SSH_PUBLIC_KEY_PATH: str = os.getenv(
        "SSH_PUBLIC_KEY_PATH",
        str(Path(r"C:\scripts\mcp_bastion_key.pub"))
    )

    # ── Wallet ──────────────────────────────────────────────────────────────────
    WALLET_ZIP_PATH: str = os.getenv("WALLET_ZIP_PATH", r"C:\scripts\oci_01.zip")

    # Leave empty string if your wallet is not password-protected
    WALLET_PASSWORD: str = os.getenv("WALLET_PASSWORD", "")

    # ── Oracle ADB ──────────────────────────────────────────────────────────────
    # Service name from tnsnames.ora — typically looks like:
    # <db_name>_high, <db_name>_medium, <db_name>_low, <db_name>_tp, <db_name>_tpurgent
    ADB_SERVICE_NAME: str = os.getenv("ADB_SERVICE_NAME", "<your_db_name>_medium")

    DB_USERNAME: str = os.getenv("DB_USERNAME", "<your_db_username>")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "<your_db_password>")

    # ── Tunnel ──────────────────────────────────────────────────────────────────
    # Local port to forward ADB traffic through. Change if 1522 is in use.
    LOCAL_TUNNEL_PORT: int = int(os.getenv("LOCAL_TUNNEL_PORT", "1522"))

    # Bastion session lifetime in seconds (max 10800 = 3 hours)
    SESSION_TTL_SECONDS: int = int(os.getenv("SESSION_TTL_SECONDS", "7200"))
