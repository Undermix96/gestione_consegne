@echo off
title Gestione Consegne - Configurazione Firewall
echo.
echo  ============================================
echo   Gestione Consegne - Configurazione Firewall
echo   Da eseguire UNA SOLA VOLTA sul PC server
echo  ============================================
echo.
echo  Questo script aggiunge una regola al firewall
echo  per consentire le connessioni degli altri PC
echo  sulla porta 8742.
echo.
echo  Verra' richiesta la conferma dell'amministratore.
echo.
pause

PowerShell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-NetFirewallRule -DisplayName 'Gestione Consegne' -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue; New-NetFirewallRule -DisplayName 'Gestione Consegne' -Direction Inbound -Protocol TCP -LocalPort 8742 -Action Allow -Profile Any | Out-Null; Write-Host ' Regola firewall configurata correttamente.' -ForegroundColor Green"

echo.
echo  Configurazione completata.
echo  Puoi eliminare questo file, non serve piu'.
echo.
pause
