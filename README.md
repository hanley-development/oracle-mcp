# Oracle ADB MCP Server — Setup Guide

## Prerequisites
- Python 3.11+ (you have 3.14 ✅)
- OCI CLI config at `C:\Users\mh026488\.oci\config` with `OCI01` profile ✅
- Wallet zip at `C:\scripts\oci_01.zip` ✅
- OpenSSH available (built into Windows 10/11) ✅

---

## Step 1 — Install dependencies

Open a terminal (PowerShell or CMD) and run:

```powershell
cd C:\scripts
python -m venv mcp-oracle-env
mcp-oracle-env\Scripts\activate
pip install -r requirements.txt
```

---

## Step 2 — Edit config.py

Open `config.py` and fill in the blanks:

```python
# Your OCI Bastion OCID — found in OCI Console → Identity & Security → Bastion
# Click your Bastion → copy the OCID at the top
BASTION_OCID = "ocid1.bastion.oc1..<the-rest>"

# Your ADB service name — open C:\scripts\oci_01.zip and look at tnsnames.ora
# Pick one of the entries e.g. mydb_medium, mydb_high, mydb_tp
ADB_SERVICE_NAME = "mydb_medium"

# DB credentials
DB_USERNAME = "ADMIN"           # or your app schema user
DB_PASSWORD = "YourPassword123"

# Wallet password — check if your wallet zip was downloaded with a password
# In OCI Console → Autonomous Database → DB Connection → Download Wallet
# If you set a password when downloading, put it here. Otherwise leave ""
WALLET_PASSWORD = ""
```

> **SSH Keys:** Leave `SSH_PRIVATE_KEY_PATH` and `SSH_PUBLIC_KEY_PATH` as-is.
> The server will auto-generate an ephemeral key pair at `C:\scripts\mcp_bastion_key`
> on first run. You don't need to create these manually.

---

## Step 3 — Find your Bastion OCID

1. Go to [cloud.oracle.com](https://cloud.oracle.com) and sign in with your tenancy
2. Navigate to: **Identity & Security → Bastion**
3. Click your Bastion resource
4. Copy the **OCID** from the top of the page — it starts with `ocid1.bastion.oc1...`

---

## Step 4 — Find your ADB service name

The service names are inside your wallet zip. To check:

```powershell
# List contents of wallet
Expand-Archive C:\scripts\oci_01.zip -DestinationPath C:\scripts\wallet_preview -Force
type C:\scripts\wallet_preview\tnsnames.ora
```

You'll see entries like:
```
mydb_high = (DESCRIPTION=...
mydb_medium = (DESCRIPTION=...
mydb_low = (DESCRIPTION=...
```

Use `mydb_medium` for general queries (good balance of speed and concurrency).

---

## Step 5 — Register with Claude Desktop

Find your Claude Desktop config file:
```
C:\Users\mh026488\AppData\Roaming\Claude\claude_desktop_config.json
```

Add this to the `mcpServers` section:

```json
{
  "mcpServers": {
    "oracle-adb": {
      "command": "C:\\scripts\\mcp-oracle-env\\Scripts\\python.exe",
      "args": ["C:\\scripts\\oracle-mcp\\server.py"],
      "env": {}
    }
  }
}
```

If the file doesn't exist yet, create it with:
```json
{
  "mcpServers": {
    "oracle-adb": {
      "command": "C:\\scripts\\mcp-oracle-env\\Scripts\\python.exe",
      "args": ["C:\\scripts\\oracle-mcp\\server.py"],
      "env": {}
    }
  }
}
```

---

## Step 6 — Restart Claude Desktop

Close and reopen Claude Desktop. You should see the oracle-adb tools available.

---

## Step 7 — Test it

In Claude Desktop, try:

```
Connect to the Oracle database using the OCI01 profile
```

Then:
```
Show me the schema for tables starting with HR_
```

Then:
```
Generate an ERD for these tables: EMPLOYEES, DEPARTMENTS, LOCATIONS, JOBS, JOB_HISTORY
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `Bastion session FAILED` | Check BASTION_OCID is correct and your OCI user has `manage bastion-session` permission |
| `SSH tunnel not ready` | Ensure OpenSSH is installed: run `ssh -V` in PowerShell |
| `ORA-01017 invalid credentials` | Check DB_USERNAME / DB_PASSWORD in config.py |
| `Wallet error` | Ensure WALLET_ZIP_PATH points to the correct zip and WALLET_PASSWORD matches what you set when downloading |
| `Connection timed out` | Check the ADB private endpoint is reachable from the Bastion subnet |

---

## File Layout

```
C:\scripts\
├── oracle-mcp\
│   ├── server.py          # MCP entrypoint
│   ├── connection.py      # OCI + SSH + wallet
│   ├── schema.py          # Table/column introspection
│   ├── relationships.py   # Heuristic FK inference
│   ├── diagram.py         # Mermaid ERD generation
│   ├── query.py           # Read-only SQL executor
│   ├── config.py          # ← EDIT THIS
│   └── requirements.txt
├── oci_01.zip             # Your wallet ✅
└── mcp-oracle-env\        # Python venv (created in Step 1)
```
