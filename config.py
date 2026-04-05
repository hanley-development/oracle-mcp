"""
Configuration — edit this file with your environment details.
"""

import os


class Config:
    # ── Tunnel mode ─────────────────────────────────────────────────────────────
    # "manual" — run your ossh command yourself before calling connect.
    #            The MCP server will simply verify localhost:LOCAL_TUNNEL_PORT
    #            is reachable before connecting.
    #
    # "auto"   — the MCP server will spawn the ossh command for you on connect
    #            and kill it on disconnect.
    TUNNEL_MODE: str = os.getenv("TUNNEL_MODE", "manual")

    # ── ossh tunnel parameters (used in "auto" mode only) ───────────────────────
    OCI_REGION: str = os.getenv("OCI_REGION", "us-ashburn-1")

    # Compartment OCID — from your ossh command --compartment argument
    COMPARTMENT_OCID: str = os.getenv("COMPARTMENT_OCID", "ocid1.compartment.oc1..<your-compartment-ocid>")

    # Bastion session OCID — the static value after "proxy:" in your -s argument
    # e.g. ocid1.bastion.oc1.iad.<key>
    BASTION_SESSION_OCID: str = os.getenv("BASTION_SESSION_OCID", "ocid1.bastion.oc1.iad.<your-session-ocid>")

    # ADB private IP — the 192.168.x.x address in your ossh command
    ADB_PRIVATE_IP: str = os.getenv("ADB_PRIVATE_IP", "192.168.111.2")

    # ADB hostname for the -L tunnel target
    # e.g. ocidwdata.adb.us-ashburn-1.oraclecloud.com
    ADB_HOSTNAME: str = os.getenv("ADB_HOSTNAME", "<your-adb-hostname>.adb.us-ashburn-1.oraclecloud.com")

    # Port on the ADB side (almost always 1522 for ADB)
    ADB_PORT: int = int(os.getenv("ADB_PORT", "1522"))

    # ── Wallet ──────────────────────────────────────────────────────────────────
    WALLET_ZIP_PATH: str = os.getenv("WALLET_ZIP_PATH", r"C:\scripts\oci_01.zip")

    # Leave as empty string if your wallet was not downloaded with a password
    WALLET_PASSWORD: str = os.getenv("WALLET_PASSWORD", "")

    # ── Oracle ADB ──────────────────────────────────────────────────────────────
    # Service name — look inside oci_01.zip → tnsnames.ora for the entry names
    # e.g. mydb_medium, mydb_high, mydb_tp
    ADB_SERVICE_NAME: str = os.getenv("ADB_SERVICE_NAME", "<your_db_name>_medium")

    DB_USERNAME: str = os.getenv("DB_USERNAME", "<your_db_username>")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "<your_db_password>")

    # ── Local tunnel port ────────────────────────────────────────────────────────
    # Must match the port in your ossh -L argument (1522 by default)
    LOCAL_TUNNEL_PORT: int = int(os.getenv("LOCAL_TUNNEL_PORT", "1522"))
