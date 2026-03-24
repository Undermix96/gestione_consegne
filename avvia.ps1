# ============================================================
#  Gestione Consegne — Avvio
#  - Cerca server attivo sulla rete tramite server.lock
#  - Se trovato: apre il browser sul server esistente
#  - Se non trovato: avvia il server locale (Python embedded)
#  - Gestisce regola firewall automaticamente (UAC solo prima volta)
#  - Nessuna finestra nera visibile
# ============================================================

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

$PORT        = 8742
$LOCK_FILE   = Join-Path $ScriptDir "server.lock"
$PYTHON_DIR  = Join-Path $ScriptDir "python_embed"
$SERVER_PY   = Join-Path $ScriptDir "server.py"
$PING_TIMEOUT= 2000  # millisecondi

# ─── Funzione: testa se un server risponde ───────────────────
function Test-Server($ip, $port) {
    try {
        $url = "http://${ip}:${port}/api/ping"
        $req = [System.Net.WebRequest]::Create($url)
        $req.Timeout = $PING_TIMEOUT
        $req.Method = "GET"
        $resp = $req.GetResponse()
        $resp.Close()
        return $true
    } catch {
        return $false
    }
}

# ─── Funzione: trova Python ──────────────────────────────────
function Find-Python {
    # 1. Python embedded nella cartella del programma (priorita' massima)
    $embedded = Join-Path $PYTHON_DIR "python.exe"
    if (Test-Path $embedded) { return $embedded }

    # 2. python3 nel PATH
    $p = Get-Command python3 -ErrorAction SilentlyContinue
    if ($p) { return $p.Source }

    # 3. python nel PATH
    $p = Get-Command python -ErrorAction SilentlyContinue
    if ($p) { return $p.Source }

    # 4. Percorso Microsoft Store esplicito
    $ms = "$env:LOCALAPPDATA\Microsoft\WindowsApps\python3.exe"
    if (Test-Path $ms) { return $ms }

    # 5. Installazioni standard
    foreach ($v in @("313","312","311","310","39","38")) {
        $p1 = "$env:LOCALAPPDATA\Programs\Python\Python$v\python.exe"
        if (Test-Path $p1) { return $p1 }
        $p2 = "C:\Python$v\python.exe"
        if (Test-Path $p2) { return $p2 }
    }

    return $null
}

# ─── STEP 1: controlla se esiste un server attivo in rete ────
if (Test-Path $LOCK_FILE) {
    try {
        $lockData   = Get-Content $LOCK_FILE -Raw | ConvertFrom-Json
        $serverIp   = $lockData.ip
        $serverPort = $lockData.port

        if (Test-Server $serverIp $serverPort) {
            $url = "http://${serverIp}:${serverPort}/index.html"
            Start-Process $url
            exit 0
        } else {
            Remove-Item $LOCK_FILE -Force -ErrorAction SilentlyContinue
        }
    } catch {
        Remove-Item $LOCK_FILE -Force -ErrorAction SilentlyContinue
    }
}

# ─── STEP 2: nessun server attivo → avvia server locale ──────

$PYTHON_EXE = Find-Python
if (-not $PYTHON_EXE) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        "Python non trovato sul PC.`n`nInstallazione:`n1. Apri il Microsoft Store`n2. Cerca 'Python 3'`n3. Installa la versione piu' recente (gratuito)`n4. Riavvia il programma",
        "Gestione Consegne - Errore",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
    exit 1
}

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName         = $PYTHON_EXE
$psi.Arguments        = "`"$SERVER_PY`""
$psi.WorkingDirectory = $ScriptDir
$psi.WindowStyle      = [System.Diagnostics.ProcessWindowStyle]::Hidden
$psi.CreateNoWindow   = $true
$psi.UseShellExecute  = $false

try {
    $proc = [System.Diagnostics.Process]::Start($psi)
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        "Impossibile avviare il server:`n$_",
        "Gestione Consegne - Errore",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
    exit 1
}

# Aspetta che il server sia pronto (max 10 secondi)
$ready = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    if (Test-Server "localhost" $PORT) {
        $ready = $true
        break
    }
}

if (-not $ready) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        "Il server non risponde dopo l'avvio.`nControlla che Python funzioni correttamente.",
        "Gestione Consegne - Errore",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
    exit 1
}

Start-Process "http://localhost:$PORT/index.html"
