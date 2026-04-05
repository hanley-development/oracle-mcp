# Oracle ADB MCP Server — Setup Guide

## How the tunnel works

This server connects to Oracle ADB through your existing `ossh` tunnel.
Two modes are supported — pick whichever suits your workflow:

| Mode | What you do | What the server does |
|---|---|---|
| **manual** (default) | Run your `ossh` command in a terminal before calling `connect` | Checks `localhost:1522` is reachable, then connects |
| **auto** | Nothing — just call `connect` | Spawns the `ossh` command itself, then connects, kills it on disconnect |

Your ossh command (for reference):
```
ssh -o 'ProxyCommand=ossh proxy -V -U%r --overlay-bastion --region us-ashburn-1
  --compartment <ocid.compartment> -- ssh stb-internal.bastion<region>.oci.oracleiaas.com
  -p 22 -A -s proxy:ocid.bastion.oc1.iad.<key> 192.168.111.2
  -L 1522:ocidwdata.adb.<region>.oraclecloud.com:1522
  -t watch -n 90 date'
```

---

## Prerequisites
- Python 3.11+ ✅ (you have 3.14)
- `ossh` in your system PATH ✅
- Wallet zip at `C:\scripts\oci_01.zip` ✅

---

## Step 1 — Install dependencies

Open PowerShell and run:

```powershell
cd C:\scripts
python -m venv mcp-oracle-env
mcp-oracle-env\Scripts\activate
pip install -r oracle-mcp\requirements.txt
```

---

## Step 2 — Edit config.py

Open `C:\scripts\oracle-mcp\config.py` and fill in:

```python
# "manual" or "auto" — see table above
TUNNEL_MODE = "manual"

# Only needed if TUNNEL_MODE = "auto"
OCI_REGION          = "us-ashburn-1"
COMPARTMENT_OCID    = "ocid1.compartment.oc1..<your-compartment-ocid>"
BASTION_SESSION_OCID = "ocid1.bastion.oc1.iad.<your-static-session-key>"
ADB_PRIVATE_IP      = "192.168.111.2"
ADB_HOSTNAME        = "<your-adb-hostname>.adb.us-ashburn-1.oraclecloud.com"

# Always required
ADB_SERVICE_NAME = "<your_db_name>_medium"   # see Step 3 below
DB_USERNAME      = "<your_db_username>"
DB_PASSWORD      = "<your_db_password>"

# Leave as "" if you didn't set a password when downloading the wallet
WALLET_PASSWORD  = ""
```

---

## Step 3 — Find your ADB service name

The service name is inside your wallet zip:

```powershell
Expand-Archive C:\scripts\oci_01.zip -DestinationPath C:\scripts\wallet_preview -Force
type C:\scripts\wallet_preview\tnsnames.ora
```

You'll see entries like `mydb_high`, `mydb_medium`, `mydb_low`, `mydb_tp`.
Use `mydb_medium` for general use — good balance of speed and concurrency.

---

## Step 4 — Register with Cline (VS Code)

1. Open VS Code with the Cline extension installed
2. Click the Cline icon in the sidebar → **MCP Servers** → **Edit Config**
3. Add the following:

```json
{
  "mcpServers": {
    "oracle-adb": {
      "command": "C:\\scripts\\mcp-oracle-env\\Scripts\\python.exe",
      "args": ["C:\\scripts\\oracle-mcp\\server.py"]
    }
  }
}
```

4. Save the file — Cline will pick up the server automatically.

> **Also works with Claude Desktop.** Config file is at:
> `C:\Users\mh026488\AppData\Roaming\Claude\claude_desktop_config.json`
> Use the same JSON block above.

---

## Step 5 — Connect and use

### Manual tunnel mode (default)

1. Open a PowerShell terminal and run your ossh command — leave it running
2. In Cline, say: `Connect to the Oracle database`
3. The server verifies the tunnel is up and connects

### Auto tunnel mode

1. Set `TUNNEL_MODE = "auto"` in config.py
2. In Cline, say: `Connect to the Oracle database`
3. The server launches ossh, waits for the tunnel, then connects
4. When you say `disconnect`, the tunnel is killed cleanly

---

## Example prompts once connected

```
Show me all tables starting with AP_
```
```
Generate an ERD for the AP invoicing tables
```
```
Explain the AP_INVOICES table — row count, columns, sample data
```
```
Search for all columns containing EMPLOYEE across the schema
```
```
Query the top 10 suppliers by invoice count
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `No listener on localhost:1522` | You're in manual mode but haven't run your ossh command yet |
| `ossh tunnel exited unexpectedly` | Check BASTION_SESSION_OCID and COMPARTMENT_OCID in config.py match your command |
| `ORA-01017 invalid credentials` | Check DB_USERNAME / DB_PASSWORD in config.py |
| `Wallet error / SSL error` | Verify WALLET_ZIP_PATH is `C:\scripts\oci_01.zip` and WALLET_PASSWORD is correct |
| `Service name not found` | Check ADB_SERVICE_NAME matches an entry in tnsnames.ora (Step 3) |
| Tunnel drops after a while | Normal — the `watch -n 90 date` keepalive in your ossh command handles this; in auto mode it's included automatically |

---

## File layout

```
C:\scripts\
├── oracle-mcp\
│   ├── server.py          # MCP entrypoint
│   ├── connection.py      # ossh tunnel + wallet + DB connection
│   ├── schema.py          # Table/column introspection
│   ├── relationships.py   # Heuristic FK inference
│   ├── diagram.py         # Mermaid ERD generation
│   ├── query.py           # Read-only SQL executor
│   ├── config.py          # ← EDIT THIS
│   └── requirements.txt
├── oci_01.zip             # Your wallet ✅
└── mcp-oracle-env\        # Python venv (created in Step 1)
```
