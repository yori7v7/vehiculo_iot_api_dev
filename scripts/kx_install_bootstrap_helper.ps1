# K-X: Arranque tras boot con lanzador independiente SYSTEM.
# El lanzador solo inicia la tarea K-V existente. Sin contrasenas nuevas.
# No altera la tarea original, Caddy, app.main, RDS, ESP ni motores.
$ErrorActionPreference="Stop"
$root="C:\ProgramData\VehiculoIoT-KX-Installer"
$serviceDir="C:\ProgramData\VehiculoIoT-KX-State\service"
$manifestPath=Join-Path $serviceDir "install.json"
$caddy="C:\ProgramData\VehiculoIoT\Caddyfile"
$legacyTask="VehiculoIoT-Admission-Virtual"
$bootTask="VehiculoIoT-Admission-Virtual-Boot"
$bootScript=Join-Path $root "kx_boot_worker.ps1"
$bootReport=Join-Path $root "kx_boot_report.json"
$bootManifest=Join-Path $root "kx_boot_registration.json"
$bootCreated=$false
$scriptCreated=$false
$stopped=$false
$success=$false
$originalCaddyHash=$null

function Assert-KX([bool]$ok,[string]$reason){
 if(-not $ok){throw ("NO-GO: "+$reason)}
 Write-Host ("OK: "+$reason) -ForegroundColor Green
}
function Port-KX {
 return @(Get-NetTCPConnection -State Listen -LocalPort 9444 -ErrorAction SilentlyContinue)
}
function Wait-KX([bool]$up,[int]$seconds){
 for($i=0;$i -lt ($seconds*2);$i++){
   $p=@(Port-KX)
   if($up -and $p.Count -eq 1 -and $p[0].LocalAddress -eq "127.0.0.1"){return $true}
   if(-not $up -and $p.Count -eq 0){return $true}
   Start-Sleep -Milliseconds 500
 }
 return $false
}
function Check-Python-Sid([string]$expectedSid){
 $listener=@(Port-KX)
 if($listener.Count -ne 1 -or $listener[0].LocalAddress -ne "127.0.0.1"){return $false}
 $proc=Get-CimInstance Win32_Process -Filter ("ProcessId = "+$listener[0].OwningProcess) -ErrorAction Stop
 if($null -eq $proc){return $false}
 $result=Invoke-CimMethod -InputObject $proc -MethodName GetOwnerSid -ErrorAction Stop
 return ($result.Sid -eq $expectedSid)
}
Write-Host ""
Write-Host "=== K-X: BOOTSTRAP AUTOMATICO SIN ALTERAR CREDENCIALES ===" -ForegroundColor Cyan
try {
 $current=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
 Assert-KX ($current.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "Consola elevada"
 foreach($p in @($root,$serviceDir,$manifestPath,$caddy)){
   Assert-KX (Test-Path -LiteralPath $p) "Precondicion presente"
   Assert-KX (((Get-Item -LiteralPath $p -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) "Ruta no redirigida"
 }
 Assert-KX ((Get-Acl -LiteralPath $root).AreAccessRulesProtected) "Instalador privado"
 Assert-KX ((Get-Acl -LiteralPath $serviceDir).AreAccessRulesProtected) "Estado privado"
 foreach($path in @($bootScript,$bootReport,$bootManifest)){
   Assert-KX (-not (Test-Path -LiteralPath $path)) "Sin artefacto bootstrap anterior"
 }
 Assert-KX ($null -eq (Get-ScheduledTask -TaskPath "\" -TaskName $bootTask -ErrorAction SilentlyContinue)) "Tarea bootstrap nueva disponible"
 $manifest=Get-Content -LiteralPath $manifestPath -Raw -ErrorAction Stop|ConvertFrom-Json
 Assert-KX ($manifest.schema_version -eq 1 -and $manifest.mode -eq "loopback_only_not_public" -and
   $manifest.task_name -eq $legacyTask -and $manifest.dedicated_user -eq "VehIoT_KXSvc" -and
   $manifest.caddy_changed -eq $false -and $manifest.physical_control_enabled -eq $false -and
   $manifest.task_has_startup_trigger -eq $false) "Sidecar virtual sin boot trigger"
 $originalCaddyHash=(Get-FileHash -LiteralPath $caddy -Algorithm SHA256).Hash
 Assert-KX ($originalCaddyHash -eq $manifest.original_caddy_sha256) "Caddy original"
 Assert-KX ((Get-FileHash -LiteralPath (Join-Path $serviceDir "launcher.py") -Algorithm SHA256).Hash -eq $manifest.launcher_sha256) "Lanzador K-V no modificado"
 $dedicated=Get-LocalUser -Name "VehIoT_KXSvc" -ErrorAction Stop
 Assert-KX ($dedicated.Enabled -and $dedicated.SID.Value -eq $manifest.dedicated_sid) "Cuenta dedicada activa"
 $old=Get-ScheduledTask -TaskPath "\" -TaskName $legacyTask -ErrorAction Stop
 Assert-KX ($old.State -eq "Running" -and @($old.Triggers|Where-Object{$null -ne $_}).Count -eq 0) "Tarea K-V original sin autoarranque"
 Assert-KX ([string]$old.Principal.LogonType -eq "Password" -and [string]$old.Principal.RunLevel -eq "Limited") "Tarea K-V con inicio restringido"
 $principalName=[string]$old.Principal.UserId
 if($principalName -match '^S-1-[0-9]+(?:-[0-9]+)+$'){
    $principalSid=([Security.Principal.SecurityIdentifier]::new($principalName)).Value
 } else {
    $principalSid=([Security.Principal.NTAccount]::new($principalName)).Translate([Security.Principal.SecurityIdentifier]).Value
 }
 Assert-KX ($principalSid -eq $manifest.dedicated_sid) "Principal de K-V verificado por SID"
 Assert-KX (@($old.Actions).Count -eq 1 -and ([string]$old.Actions[0].Execute -match 'python\.exe$')) "Accion unica Python"
 Assert-KX (Wait-KX $true 2) "9444 en loopback"
 Assert-KX (Check-Python-Sid $manifest.dedicated_sid) "Python ya ejecutado por cuenta dedicada"
 foreach($n in @("VehiculoIoT-FastAPI","VehiculoIoT-Caddy")){
   Assert-KX ((Get-ScheduledTask -TaskPath "\" -TaskName $n -ErrorAction Stop).State -eq "Running") ("Tarea original activa: "+$n)
 }
 Assert-KX (@(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue).Count -gt 0) "Backend legacy 8000 activo"

 Write-Host ""
 Write-Host "=== PREPARANDO TRABAJADOR DE ARRANQUE SYSTEM ===" -ForegroundColor Cyan
 $worker=@'
# K-X bootstrap worker. SYSTEM solo invoca Start-ScheduledTask para K-V.
# Las credenciales guardadas y la identidad del proceso K-V no se modifican.
$ErrorActionPreference="Stop"
$serviceDir="C:\ProgramData\VehiculoIoT-KX-State\service"
$taskName="VehiculoIoT-Admission-Virtual"
$caddy="C:\ProgramData\VehiculoIoT\Caddyfile"
$reportPath="C:\ProgramData\VehiculoIoT-KX-Installer\kx_boot_report.json"
$result=[ordered]@{status="NO-GO";phase="preflight";time_utc=[DateTime]::UtcNow.ToString("o");exception_type="none"}
function AuditPort {
 return @(Get-NetTCPConnection -LocalPort 9444 -State Listen -ErrorAction SilentlyContinue)
}
try {
 $who=[Security.Principal.WindowsIdentity]::GetCurrent()
 if($who.User.Value -ne "S-1-5-18"){throw "Bootstrap debe correr como SYSTEM"}
 $manifestPath=Join-Path $serviceDir "install.json"
 $manifest=Get-Content -LiteralPath $manifestPath -Raw -ErrorAction Stop|ConvertFrom-Json
 if($manifest.schema_version -ne 1 -or $manifest.mode -ne "loopback_only_not_public" -or
    $manifest.task_name -ne $taskName -or $manifest.dedicated_user -ne "VehIoT_KXSvc" -or
    $manifest.physical_control_enabled -ne $false -or $manifest.caddy_changed -ne $false -or
    $manifest.task_has_startup_trigger -ne $false){throw "Manifest de sidecar inesperado"}
 if((Get-FileHash -LiteralPath $caddy -Algorithm SHA256).Hash -ne $manifest.original_caddy_sha256){
   throw "Caddy modificado"
 }
 if((Get-FileHash -LiteralPath (Join-Path $serviceDir "launcher.py") -Algorithm SHA256).Hash -ne $manifest.launcher_sha256){
   throw "Lanzador modificado"
 }
 $t=Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop
 if([string]$t.Principal.LogonType -ne "Password" -or [string]$t.Principal.RunLevel -ne "Limited" -or
    @($t.Triggers | Where-Object{$null -ne $_}).Count -ne 0){throw "Cambio de definicion de K-V"}
 $p=[string]$t.Principal.UserId
 if($p -match '^S-1-[0-9]+(?:-[0-9]+)+$'){
   $taskSid=([Security.Principal.SecurityIdentifier]::new($p)).Value
 } else {
   $taskSid=([Security.Principal.NTAccount]::new($p)).Translate([Security.Principal.SecurityIdentifier]).Value
 }
 if($taskSid -ne $manifest.dedicated_sid){throw "SID del principal K-V diferente"}
 $result.phase="start"
 if($t.State -ne "Running") {
   Start-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop
 }
 $result.phase="verify"
 $verified=$false
 for($i=0;$i -lt 90;$i++){
   $listeners=@(AuditPort)
   if($listeners.Count -eq 1 -and $listeners[0].LocalAddress -eq "127.0.0.1"){
     $proc=Get-CimInstance Win32_Process -Filter ("ProcessId = "+$listeners[0].OwningProcess) -ErrorAction Stop
     if($null -ne $proc){
       $sid=(Invoke-CimMethod -InputObject $proc -MethodName GetOwnerSid -ErrorAction Stop).Sid
       if($sid -eq $manifest.dedicated_sid){$verified=$true;break}
     }
   }
   Start-Sleep -Milliseconds 500
 }
 if(-not $verified){throw "No se certifico K-V en loopback bajo cuenta dedicada"}
 $result.status="PASS"
 $result.phase="complete"
} catch {
 $result.exception_type=$_.Exception.GetType().Name
} finally {
 try {
   $result|ConvertTo-Json -Compress|Set-Content -LiteralPath $reportPath -Encoding UTF8 -ErrorAction Stop
 } catch {
   $result.status="NO-GO"
   $result.exception_type="ReportWriteFailed"
 }
}
if($result.status -eq "PASS"){exit 0}
exit 2
'@
 Set-Content -LiteralPath $bootScript -Value $worker -Encoding UTF8 -ErrorAction Stop
 $scriptCreated=$true
 & icacls.exe $bootScript /inheritance:r | Out-Null
 Assert-KX ($LASTEXITCODE -eq 0) "Script bootstrap sin herencia"
 & icacls.exe $bootScript /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' | Out-Null
 Assert-KX ($LASTEXITCODE -eq 0) "Script bootstrap privado"
 $tokens=$null;$parseErrors=$null
 [System.Management.Automation.Language.Parser]::ParseFile($bootScript,[ref]$tokens,[ref]$parseErrors)|Out-Null
 Assert-KX (@($parseErrors).Count -eq 0) "Trabajador PowerShell 5.1 valido"
 $sha=(Get-FileHash -LiteralPath $bootScript -Algorithm SHA256).Hash

 Write-Host ""
 Write-Host "=== REGISTRO DE SEGUNDA TAREA SYSTEM ===" -ForegroundColor Cyan
 $action=New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument ('-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$bootScript+'"')
 $trigger=New-ScheduledTaskTrigger -AtStartup -RandomDelay (New-TimeSpan -Seconds 15)
 $settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew
 Register-ScheduledTask -TaskPath "\" -TaskName $bootTask -User "SYSTEM" -RunLevel Highest -Action $action -Trigger $trigger -Settings $settings -Description "Starts existing K-V task only; no physical control and no new credentials" -ErrorAction Stop|Out-Null
 $bootCreated=$true
 $registered=Get-ScheduledTask -TaskPath "\" -TaskName $bootTask -ErrorAction Stop
 Assert-KX (@($registered.Triggers|Where-Object{$null -ne $_}).Count -eq 1 -and
   [string]$registered.Triggers[0].CimClass.CimClassName -like '*BootTrigger') "Nuevo trigger solo en bootstrap"
 $bootIdentity=[string]$registered.Principal.UserId
 Assert-KX (-not [string]::IsNullOrWhiteSpace($bootIdentity)) "Identidad SYSTEM especificada"
 if($bootIdentity -match '^S-1-[0-9]+(?:-[0-9]+)+
 Assert-KX (@($registered.Actions).Count -eq 1 -and [string]$registered.Actions[0].Arguments -match 'kx_boot_worker\.ps1') "Bootstrap solo ejecuta trabajador protegido"
 Assert-KX (@((Get-ScheduledTask -TaskPath "\" -TaskName $legacyTask).Triggers | Where-Object{$null -ne $_}).Count -eq 0) "K-V original sin triggers"

 Write-Host ""
 Write-Host "=== PRUEBA MANUAL DEL BOOTSTRAP CON REINICIO DE K-V ===" -ForegroundColor Cyan
 $stopped=$true
 Stop-ScheduledTask -TaskPath "\" -TaskName $legacyTask -ErrorAction Stop
 Assert-KX (Wait-KX $false 35) "K-V temporalmente detenido, 9444 cerrado"
 Assert-KX (@(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue).Count -gt 0) "8000 no interrumpido"
 Start-ScheduledTask -TaskPath "\" -TaskName $bootTask -ErrorAction Stop
 $completed=$false
 for($i=0;$i -lt 180;$i++){
   Start-Sleep -Milliseconds 500
   $bootNow=Get-ScheduledTask -TaskPath "\" -TaskName $bootTask -ErrorAction Stop
   if((Test-Path -LiteralPath $bootReport) -and $bootNow.State -ne "Running"){$completed=$true;break}
 }
 Assert-KX ($completed) "Tarea bootstrap temporal finalizada"
 $report=Get-Content -LiteralPath $bootReport -Raw -ErrorAction Stop|ConvertFrom-Json
 Write-Host ("BOOTSTRAP STATUS: "+$report.status)
 Write-Host ("BOOTSTRAP PHASE: "+$report.phase)
 Write-Host ("BOOTSTRAP EXCEPTION: "+$report.exception_type)
 $info=Get-ScheduledTaskInfo -TaskPath "\" -TaskName $bootTask -ErrorAction Stop
 Write-Host ("WINDOWS TASK RESULT: "+$info.LastTaskResult)
 Assert-KX ($report.status -eq "PASS" -and $report.phase -eq "complete" -and $info.LastTaskResult -eq 0) "Bootstrap puede reiniciar K-V bajo identidad guardada"
 Assert-KX (Wait-KX $true 2) "9444 regresó a loopback"
 Assert-KX (Check-Python-Sid $manifest.dedicated_sid) "Python sigue siendo cuenta dedicada"
 Assert-KX (@((Get-ScheduledTask -TaskPath "\" -TaskName $legacyTask).Triggers | Where-Object{$null -ne $_}).Count -eq 0) "K-V original aun sin trigger"
 Assert-KX ((Get-FileHash -LiteralPath $caddy -Algorithm SHA256).Hash -eq $originalCaddyHash) "Caddy intacto"
 foreach($n in @("VehiculoIoT-FastAPI","VehiculoIoT-Caddy")){
   Assert-KX ((Get-ScheduledTask -TaskPath "\" -TaskName $n -ErrorAction Stop).State -eq "Running") ("Original intacta: "+$n)
 }
 $stateRecord=[ordered]@{
  schema_version=1;mode="bootstrap_system_starts_virtual_only"
  helper_task=$bootTask;legacy_task=$legacyTask;worker_sha256=$sha
  boot_tested=$false;manual_starter_test_passed=$true
  main_task_modified=$false;caddy_modified=$false;physical_control_enabled=$false
  registered_utc=[DateTime]::UtcNow.ToString("o")
 }
 $stateRecord|ConvertTo-Json -Depth 4|Set-Content -LiteralPath $bootManifest -Encoding UTF8 -ErrorAction Stop
 $success=$true
 Write-Host ""
 Write-Host "=== RESULTADO: BOOTSTRAP AUTOMATICO K-V VALIDADO ===" -ForegroundColor Green
 Write-Host "TAREA BOOT SYSTEM: ACTIVA CON TRIGGER ATSTARTUP"
 Write-Host "TAREA K-V ORIGINAL: SIN MODIFICACIONES, RUNNING"
 Write-Host "CREDENCIALES DEDICADAS: SIN CAMBIOS"
 Write-Host "BOOT REAL EC2: AUN NO PROBADO"
 Write-Host "9444: SOLO LOOPBACK; CADDY: INTACTO; MOTORES: OFF"
} catch {
 Write-Host ""
 Write-Host "=== RESULTADO: NO-GO DE BOOTSTRAP ===" -ForegroundColor Red
 Write-Host ("TIPO: "+$_.Exception.GetType().Name) -ForegroundColor Yellow
 Write-Host ("MENSAJE: "+$_.Exception.Message) -ForegroundColor Yellow
 if($_.FullyQualifiedErrorId){Write-Host ("ERROR ID: "+$_.FullyQualifiedErrorId) -ForegroundColor Yellow}
} finally {
 if(-not $success){
   Write-Host ""
   Write-Host "=== CONTENCION DE BOOTSTRAP FALLIDO ===" -ForegroundColor Cyan
   try {
      $bootExisting=Get-ScheduledTask -TaskPath "\" -TaskName $bootTask -ErrorAction SilentlyContinue
      if($null -ne $bootExisting){
         if($bootExisting.State -eq "Running"){
           Stop-ScheduledTask -TaskPath "\" -TaskName $bootTask -ErrorAction Stop
         }
         Unregister-ScheduledTask -TaskPath "\" -TaskName $bootTask -Confirm:$false -ErrorAction Stop
      }
      Assert-KX ($null -eq (Get-ScheduledTask -TaskPath "\" -TaskName $bootTask -ErrorAction SilentlyContinue)) "No quedo autoarranque SYSTEM"
   } catch {
      Write-Host "NO-GO: no se pudo retirar bootstrap; NO REINICIAR EC2" -ForegroundColor Red
   }
   if($stopped){
     try {
       $main=Get-ScheduledTask -TaskPath "\" -TaskName $legacyTask -ErrorAction Stop
       if($main.State -ne "Running"){Start-ScheduledTask -TaskPath "\" -TaskName $legacyTask -ErrorAction Stop}
       Assert-KX (Wait-KX $true 70) "Servicio K-V recuperado"
       if($null -ne $manifest){Assert-KX (Check-Python-Sid $manifest.dedicated_sid) "Identidad K-V recuperada"}
     } catch {
       Write-Host "NO-GO: recuperacion K-V no confirmada; preservar Caddy sin cambios" -ForegroundColor Red
     }
   }
   try {
      foreach($p in @($bootManifest,$bootReport,$bootScript)){
         if(Test-Path -LiteralPath $p){Remove-Item -LiteralPath $p -Force -ErrorAction Stop}
      }
      Write-Host "OK: Archivos de bootstrap fallido retirados" -ForegroundColor Green
   } catch {
      Write-Host "NO-GO: no se retiraron todos los archivos; no repetir" -ForegroundColor Red
   }
 }
 if($null -ne $originalCaddyHash -and (Test-Path -LiteralPath $caddy)){
   if((Get-FileHash -LiteralPath $caddy -Algorithm SHA256).Hash -eq $originalCaddyHash){
      Write-Host "OK: Caddy original intacto" -ForegroundColor Green
   }else{
      Write-Host "NO-GO: Hash de Caddy inesperado" -ForegroundColor Red
   }
 }
 Write-Host "NO REINICIAR EC2 AUN; SIN RDS, ESP, MOTORES NI EXPOSICION PUBLICA"
 Write-Host "=== FIN K-X BOOTSTRAP ===" -ForegroundColor Cyan
}
){
   $bootSid=([Security.Principal.SecurityIdentifier]::new($bootIdentity)).Value
 } else {
   $bootSid=([Security.Principal.NTAccount]::new($bootIdentity)).Translate([Security.Principal.SecurityIdentifier]).Value
 }
 Assert-KX ($bootSid -eq "S-1-5-18") "Bootstrap bajo SYSTEM comprobado por SID"
 Assert-KX (@($registered.Actions).Count -eq 1 -and [string]$registered.Actions[0].Arguments -match 'kx_boot_worker\.ps1') "Bootstrap solo ejecuta trabajador protegido"
 Assert-KX (@((Get-ScheduledTask -TaskPath "\" -TaskName $legacyTask).Triggers | Where-Object{$null -ne $_}).Count -eq 0) "K-V original sin triggers"

 Write-Host ""
 Write-Host "=== PRUEBA MANUAL DEL BOOTSTRAP CON REINICIO DE K-V ===" -ForegroundColor Cyan
 $stopped=$true
 Stop-ScheduledTask -TaskPath "\" -TaskName $legacyTask -ErrorAction Stop
 Assert-KX (Wait-KX $false 35) "K-V temporalmente detenido, 9444 cerrado"
 Assert-KX (@(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue).Count -gt 0) "8000 no interrumpido"
 Start-ScheduledTask -TaskPath "\" -TaskName $bootTask -ErrorAction Stop
 $completed=$false
 for($i=0;$i -lt 180;$i++){
   Start-Sleep -Milliseconds 500
   $bootNow=Get-ScheduledTask -TaskPath "\" -TaskName $bootTask -ErrorAction Stop
   if((Test-Path -LiteralPath $bootReport) -and $bootNow.State -ne "Running"){$completed=$true;break}
 }
 Assert-KX ($completed) "Tarea bootstrap temporal finalizada"
 $report=Get-Content -LiteralPath $bootReport -Raw -ErrorAction Stop|ConvertFrom-Json
 Write-Host ("BOOTSTRAP STATUS: "+$report.status)
 Write-Host ("BOOTSTRAP PHASE: "+$report.phase)
 Write-Host ("BOOTSTRAP EXCEPTION: "+$report.exception_type)
 $info=Get-ScheduledTaskInfo -TaskPath "\" -TaskName $bootTask -ErrorAction Stop
 Write-Host ("WINDOWS TASK RESULT: "+$info.LastTaskResult)
 Assert-KX ($report.status -eq "PASS" -and $report.phase -eq "complete" -and $info.LastTaskResult -eq 0) "Bootstrap puede reiniciar K-V bajo identidad guardada"
 Assert-KX (Wait-KX $true 2) "9444 regresó a loopback"
 Assert-KX (Check-Python-Sid $manifest.dedicated_sid) "Python sigue siendo cuenta dedicada"
 Assert-KX (@((Get-ScheduledTask -TaskPath "\" -TaskName $legacyTask).Triggers | Where-Object{$null -ne $_}).Count -eq 0) "K-V original aun sin trigger"
 Assert-KX ((Get-FileHash -LiteralPath $caddy -Algorithm SHA256).Hash -eq $originalCaddyHash) "Caddy intacto"
 foreach($n in @("VehiculoIoT-FastAPI","VehiculoIoT-Caddy")){
   Assert-KX ((Get-ScheduledTask -TaskPath "\" -TaskName $n -ErrorAction Stop).State -eq "Running") ("Original intacta: "+$n)
 }
 $stateRecord=[ordered]@{
  schema_version=1;mode="bootstrap_system_starts_virtual_only"
  helper_task=$bootTask;legacy_task=$legacyTask;worker_sha256=$sha
  boot_tested=$false;manual_starter_test_passed=$true
  main_task_modified=$false;caddy_modified=$false;physical_control_enabled=$false
  registered_utc=[DateTime]::UtcNow.ToString("o")
 }
 $stateRecord|ConvertTo-Json -Depth 4|Set-Content -LiteralPath $bootManifest -Encoding UTF8 -ErrorAction Stop
 $success=$true
 Write-Host ""
 Write-Host "=== RESULTADO: BOOTSTRAP AUTOMATICO K-V VALIDADO ===" -ForegroundColor Green
 Write-Host "TAREA BOOT SYSTEM: ACTIVA CON TRIGGER ATSTARTUP"
 Write-Host "TAREA K-V ORIGINAL: SIN MODIFICACIONES, RUNNING"
 Write-Host "CREDENCIALES DEDICADAS: SIN CAMBIOS"
 Write-Host "BOOT REAL EC2: AUN NO PROBADO"
 Write-Host "9444: SOLO LOOPBACK; CADDY: INTACTO; MOTORES: OFF"
} catch {
 Write-Host ""
 Write-Host "=== RESULTADO: NO-GO DE BOOTSTRAP ===" -ForegroundColor Red
 Write-Host ("TIPO: "+$_.Exception.GetType().Name) -ForegroundColor Yellow
 Write-Host ("MENSAJE: "+$_.Exception.Message) -ForegroundColor Yellow
 if($_.FullyQualifiedErrorId){Write-Host ("ERROR ID: "+$_.FullyQualifiedErrorId) -ForegroundColor Yellow}
} finally {
 if(-not $success){
   Write-Host ""
   Write-Host "=== CONTENCION DE BOOTSTRAP FALLIDO ===" -ForegroundColor Cyan
   try {
      $bootExisting=Get-ScheduledTask -TaskPath "\" -TaskName $bootTask -ErrorAction SilentlyContinue
      if($null -ne $bootExisting){
         if($bootExisting.State -eq "Running"){
           Stop-ScheduledTask -TaskPath "\" -TaskName $bootTask -ErrorAction Stop
         }
         Unregister-ScheduledTask -TaskPath "\" -TaskName $bootTask -Confirm:$false -ErrorAction Stop
      }
      Assert-KX ($null -eq (Get-ScheduledTask -TaskPath "\" -TaskName $bootTask -ErrorAction SilentlyContinue)) "No quedo autoarranque SYSTEM"
   } catch {
      Write-Host "NO-GO: no se pudo retirar bootstrap; NO REINICIAR EC2" -ForegroundColor Red
   }
   if($stopped){
     try {
       $main=Get-ScheduledTask -TaskPath "\" -TaskName $legacyTask -ErrorAction Stop
       if($main.State -ne "Running"){Start-ScheduledTask -TaskPath "\" -TaskName $legacyTask -ErrorAction Stop}
       Assert-KX (Wait-KX $true 70) "Servicio K-V recuperado"
       if($null -ne $manifest){Assert-KX (Check-Python-Sid $manifest.dedicated_sid) "Identidad K-V recuperada"}
     } catch {
       Write-Host "NO-GO: recuperacion K-V no confirmada; preservar Caddy sin cambios" -ForegroundColor Red
     }
   }
   try {
      foreach($p in @($bootManifest,$bootReport,$bootScript)){
         if(Test-Path -LiteralPath $p){Remove-Item -LiteralPath $p -Force -ErrorAction Stop}
      }
      Write-Host "OK: Archivos de bootstrap fallido retirados" -ForegroundColor Green
   } catch {
      Write-Host "NO-GO: no se retiraron todos los archivos; no repetir" -ForegroundColor Red
   }
 }
 if($null -ne $originalCaddyHash -and (Test-Path -LiteralPath $caddy)){
   if((Get-FileHash -LiteralPath $caddy -Algorithm SHA256).Hash -eq $originalCaddyHash){
      Write-Host "OK: Caddy original intacto" -ForegroundColor Green
   }else{
      Write-Host "NO-GO: Hash de Caddy inesperado" -ForegroundColor Red
   }
 }
 Write-Host "NO REINICIAR EC2 AUN; SIN RDS, ESP, MOTORES NI EXPOSICION PUBLICA"
 Write-Host "=== FIN K-X BOOTSTRAP ===" -ForegroundColor Cyan
}
