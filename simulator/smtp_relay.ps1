# ============================================================================
# SI Bid Tool — PowerShell SMTP Relay
# Lightweight SMTP listener on localhost:2525
# Routes emails to vendor_inbox/ or bidtool_inbox/ based on To: header
# ============================================================================

param(
    [int]$Port = 2525,
    [string]$MailboxDir = (Join-Path $PSScriptRoot "mailbox")
)

$VendorInbox = Join-Path $MailboxDir "vendor_inbox"
$BidToolInbox = Join-Path $MailboxDir "bidtool_inbox"
$LogFile = Join-Path $PSScriptRoot "smtp_relay.log"

# Ensure directories exist
@($VendorInbox, $BidToolInbox, (Join-Path $VendorInbox "processed"), (Join-Path $BidToolInbox "processed")) | ForEach-Object {
    if (!(Test-Path $_)) { New-Item -ItemType Directory -Path $_ -Force | Out-Null }
}

function Write-Log {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $Message"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line
}

function Get-RouteFolder {
    param([string]$ToAddress)
    # If the To address contains "standard" or "si-bid", route to bidtool inbox
    if ($ToAddress -match "(?i)standard|si-bid|si_bid") {
        return $BidToolInbox
    }
    # Everything else goes to vendor inbox
    return $VendorInbox
}

function Handle-SmtpSession {
    param([System.Net.Sockets.TcpClient]$Client)

    $stream = $Client.GetStream()
    $reader = New-Object System.IO.StreamReader($stream)
    $writer = New-Object System.IO.StreamWriter($stream)
    $writer.AutoFlush = $true

    $mailFrom = ""
    $rcptTo = @()
    $data = ""
    $inData = $false

    try {
        # Send greeting
        $writer.WriteLine("220 localhost SI-SMTP-Relay Ready")

        while ($Client.Connected -and $stream.DataAvailable -or $true) {
            $line = $reader.ReadLine()
            if ($null -eq $line) { break }

            if ($inData) {
                if ($line -eq ".") {
                    $inData = $false
                    $writer.WriteLine("250 OK Message accepted")

                    # Route and save the email
                    $toAddr = if ($rcptTo.Count -gt 0) { $rcptTo[0] } else { "" }
                    $folder = Get-RouteFolder -ToAddress $toAddr
                    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
                    $safeName = ($toAddr -replace '[<>:"/\\|?*@]', '_').Trim('_')
                    if (-not $safeName) { $safeName = "unknown" }
                    $filename = "${timestamp}_${safeName}.eml"
                    $filepath = Join-Path $folder $filename

                    Set-Content -Path $filepath -Value $data -Encoding UTF8
                    Write-Log "Saved: $filename -> $(Split-Path $folder -Leaf) (To: $toAddr)"

                    # Reset for next message
                    $mailFrom = ""
                    $rcptTo = @()
                    $data = ""
                } else {
                    # Handle dot-stuffing (RFC 5321)
                    if ($line.StartsWith("..")) {
                        $data += $line.Substring(1) + "`r`n"
                    } else {
                        $data += $line + "`r`n"
                    }
                }
                continue
            }

            $cmd = $line.Trim()
            $cmdUpper = $cmd.ToUpper()

            if ($cmdUpper.StartsWith("EHLO") -or $cmdUpper.StartsWith("HELO")) {
                $writer.WriteLine("250-localhost")
                $writer.WriteLine("250-SIZE 10485760")
                $writer.WriteLine("250 OK")
            }
            elseif ($cmdUpper.StartsWith("MAIL FROM:")) {
                $mailFrom = ($cmd -replace "(?i)MAIL FROM:\s*", "").Trim('<', '>', ' ')
                $writer.WriteLine("250 OK")
            }
            elseif ($cmdUpper.StartsWith("RCPT TO:")) {
                $addr = ($cmd -replace "(?i)RCPT TO:\s*", "").Trim('<', '>', ' ')
                $rcptTo += $addr
                $writer.WriteLine("250 OK")
            }
            elseif ($cmdUpper -eq "DATA") {
                $writer.WriteLine("354 Start mail input; end with <CRLF>.<CRLF>")
                $inData = $true
                $data = ""
            }
            elseif ($cmdUpper -eq "QUIT") {
                $writer.WriteLine("221 Bye")
                break
            }
            elseif ($cmdUpper -eq "RSET") {
                $mailFrom = ""
                $rcptTo = @()
                $data = ""
                $writer.WriteLine("250 OK")
            }
            elseif ($cmdUpper -eq "NOOP") {
                $writer.WriteLine("250 OK")
            }
            else {
                $writer.WriteLine("500 Command not recognized")
            }
        }
    }
    catch {
        Write-Log "Session error: $_"
    }
    finally {
        $reader.Close()
        $writer.Close()
        $Client.Close()
    }
}

# ── Main listener loop ──────────────────────────────────────────────────────

Write-Log "========================================="
Write-Log "  SI Bid Tool SMTP Relay"
Write-Log "  Listening on localhost:$Port"
Write-Log "  Vendor inbox: $VendorInbox"
Write-Log "  BidTool inbox: $BidToolInbox"
Write-Log "========================================="

$listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $Port)
$listener.Start()

Write-Log "SMTP Relay started. Press Ctrl+C to stop."

try {
    while ($true) {
        if ($listener.Pending()) {
            $client = $listener.AcceptTcpClient()
            $remoteEp = $client.Client.RemoteEndPoint
            Write-Log "Connection from $remoteEp"
            Handle-SmtpSession -Client $client
        }
        Start-Sleep -Milliseconds 100
    }
}
catch {
    Write-Log "Relay stopped: $_"
}
finally {
    $listener.Stop()
    Write-Log "SMTP Relay shut down."
}
