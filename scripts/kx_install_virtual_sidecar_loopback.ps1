# K-X 5.5 - sidecar virtual independiente (127.0.0.1:9444).
# Compatible Windows PowerShell 5.1. NO cambia Caddy, backend legacy ni hardware.
# Tarea con identidad dedicada, sin trigger, arrancada manualmente para validacion.
$ErrorActionPreference = "Stop"
$staging = "C:\ProgramData\VehiculoIoT-KX-Staging"
$state = "C:\ProgramData\VehiculoIoT-KX-State"
$work = Join-Path $state "service"
$code = Join-Path $staging "code"
$runtime = Join-Path $staging "runtime"
$python = Join-Path $runtime "venv\Scripts\python.exe"
$caddy = "C:\ProgramData\VehiculoIoT\Caddyfile"
$userName = "VehIoT_KXSvc"
$taskName = "VehiculoIoT-Admission-Virtual"
$configFile = Join-Path $work "config.json"
$launcher = Join-Path $work "launcher.py"
$manifestFile = Join-Path $work "install.json"
$createdUser=$false; $createdWork=$false; $sid=$null
$granted=@(); $rights=@(); $pass=$null; $secure=$null
$success=$false; $before=$null
function Assert([bool]$ok,[string]$why) {
  if(-not $ok){throw ("NO-GO: "+$why)}
  Write-Host ("OK: "+$why) -ForegroundColor Green
}
function New-RandomProof {
  $bytes=New-Object byte[] 48
  $rng=[Security.Cryptography.RandomNumberGenerator]::Create()
  try { $rng.GetBytes($bytes); return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_') }
  finally { $rng.Dispose(); [Array]::Clear($bytes,0,$bytes.Length) }
}
function Assert-ACL([string]$path,[string]$ownerSid) {
  $a=Get-Acl -LiteralPath $path
  $allowed=@("S-1-5-18","S-1-5-32-544",$ownerSid)
  foreach($r in $a.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])){
    if($r.AccessControlType -eq "Allow" -and $r.IdentityReference.Value -notin $allowed){
      throw ("NO-GO: ACL con tercero: "+$path)
    }
  }
  Write-Host ("OK: ACL privada: "+[IO.Path]::GetFileName($path)) -ForegroundColor Green
}
Write-Host ""
Write-Host "=== K-X: INSTALACION SIDECAR VIRTUAL LOOPBACK ===" -ForegroundColor Cyan
try {
  $elevated=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
  Assert ($elevated.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "Consola elevada"
  foreach($p in @($staging,$state,$code,$runtime,$python,$caddy)) {
    Assert (Test-Path -LiteralPath $p) "Componente requerido presente"
    Assert (((Get-Item -LiteralPath $p -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) "Ruta no redirigida"
  }
  $st=Get-Content (Join-Path $staging "stage.json") -Raw | ConvertFrom-Json
  $rt=Get-Content (Join-Path $runtime "runtime.json") -Raw | ConvertFrom-Json
  Assert ($st.mode -eq "offline_staging_only" -and $st.persistent_task_created -eq $false -and
          $st.physical_control_enabled -eq $false -and $rt.mode -eq "runtime_ready_but_disabled" -and
          $rt.task_installed -eq $false) "Manifiestos de seguridad originales"
  $before=(Get-FileHash $caddy -Algorithm SHA256).Hash
  Assert ($before -eq $st.live_caddy_sha256_before -and $before -eq $st.live_caddy_sha256_after) "Caddy original verificado"
  Assert (-not (Test-Path -LiteralPath $work)) "Carpeta definitiva disponible"
  Assert ($null -eq (Get-LocalUser -Name $userName -ErrorAction SilentlyContinue)) "Cuenta definitiva no existe"
  Assert ($null -eq (Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction SilentlyContinue)) "Tarea definitiva no existe"
  Assert (@(Get-NetTCPConnection -LocalPort 9444 -State Listen -ErrorAction SilentlyContinue).Count -eq 0) "Puerto 9444 libre"
  Assert (Test-Path (Join-Path $code "app\public_control\kv_virtual_staging.py") -PathType Leaf) "Modulo K-V presente"
  Assert ((Get-Acl -LiteralPath $state).AreAccessRulesProtected) "Estado original ACL protegida"
  foreach($n in @("VehiculoIoT-FastAPI","VehiculoIoT-Caddy")){
    $t=Get-ScheduledTask -TaskPath "\" -TaskName $n -ErrorAction Stop
    Assert ($t.State -eq "Running") ("Tarea legacy intacta: "+$n)
  }
  $on8000=@(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
  Assert ($on8000.Count -gt 0 -and @($on8000|Where-Object{$_.LocalAddress -notin @("127.0.0.1","::1")}).Count -eq 0) "8000 solo loopback"

  if(-not ("KXDedicatedRightsV1" -as [type])){
    Add-Type -Language CSharp -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Principal;
public static class KXDedicatedRightsV1 {
 [StructLayout(LayoutKind.Sequential)] private struct Obj {
   public uint Length; public IntPtr Root,Name; public uint Flags; public IntPtr Security,Quality;
 }
 [StructLayout(LayoutKind.Sequential)] private struct Ustr { public ushort Length,Maximum; public IntPtr Text; }
 [DllImport("advapi32.dll")] private static extern uint LsaOpenPolicy(IntPtr system, ref Obj attributes,uint access,out IntPtr handle);
 [DllImport("advapi32.dll")] private static extern uint LsaAddAccountRights(IntPtr handle,IntPtr sid,ref Ustr right,uint count);
 [DllImport("advapi32.dll")] private static extern uint LsaRemoveAccountRights(IntPtr handle,IntPtr sid,[MarshalAs(UnmanagedType.U1)] bool all,ref Ustr right,uint count);
 [DllImport("advapi32.dll")] private static extern uint LsaNtStatusToWinError(uint code);
 [DllImport("advapi32.dll")] private static extern uint LsaClose(IntPtr handle);
 public static void Change(string sidValue,string right,bool add){
   var identity=new SecurityIdentifier(sidValue);var bytes=new byte[identity.BinaryLength];
   identity.GetBinaryForm(bytes,0);
   IntPtr sid=IntPtr.Zero,text=IntPtr.Zero,policy=IntPtr.Zero;
   try {
     sid=Marshal.AllocHGlobal(bytes.Length);Marshal.Copy(bytes,0,sid,bytes.Length);
     text=Marshal.StringToHGlobalUni(right);
     Ustr r=new Ustr();r.Length=(ushort)(right.Length*2);r.Maximum=(ushort)((right.Length+1)*2);r.Text=text;
     Obj a=new Obj();a.Length=(uint)Marshal.SizeOf(typeof(Obj));
     uint status=LsaOpenPolicy(IntPtr.Zero,ref a,0x00000810,out policy);
     if(status!=0) throw new Win32Exception((int)LsaNtStatusToWinError(status),"LsaOpenPolicy");
     status=add?LsaAddAccountRights(policy,sid,ref r,1):LsaRemoveAccountRights(policy,sid,false,ref r,1);
     if(status!=0) throw new Win32Exception((int)LsaNtStatusToWinError(status),right);
   } finally {
     if(policy!=IntPtr.Zero)LsaClose(policy);
     if(text!=IntPtr.Zero)Marshal.FreeHGlobal(text);
     if(sid!=IntPtr.Zero)Marshal.FreeHGlobal(sid);
   }
 }
}
'@ -ErrorAction Stop
  }
  Write-Host "OK: Windows LSA disponible" -ForegroundColor Green

  Write-Host ""
  Write-Host "=== IDENTIDAD DEDICADA Y ESTADO PRIVADO ===" -ForegroundColor Cyan
  $pass="Aa1!"+(New-RandomProof)
  $secure=ConvertTo-SecureString $pass -AsPlainText -Force
  $newUser=New-LocalUser -Name $userName -Password $secure -PasswordNeverExpires -UserMayNotChangePassword -Description "VehiculoIoT K-V virtual 127.0.0.1" -ErrorAction Stop
  $createdUser=$true
  $sid=$newUser.SID.Value
  $adminGroup=Get-LocalGroup -SID (New-Object Security.Principal.SecurityIdentifier("S-1-5-32-544"))
  Assert (@(Get-LocalGroupMember -Group $adminGroup.Name|Where-Object{$null -ne $_.SID -and $_.SID.Value -eq $sid}).Count -eq 0) "Cuenta sin Administradores"
  foreach($right in @("SeBatchLogonRight","SeDenyInteractiveLogonRight","SeDenyRemoteInteractiveLogonRight")){
    [KXDedicatedRightsV1]::Change($sid,$right,$true)
    $rights+= $right
    Write-Host ("OK: Permiso especifico "+$right) -ForegroundColor Green
  }
  foreach($root in @($code,$runtime)){
    & icacls.exe $root /grant ("*"+$sid+":(OI)(CI)RX") | Out-Null
    Assert ($LASTEXITCODE -eq 0) "Lectura de runtime y codigo"
    $granted+= $root
  }
  New-Item -ItemType Directory -Path $work -ErrorAction Stop|Out-Null
  $createdWork=$true
  & icacls.exe $work /inheritance:r | Out-Null
  Assert ($LASTEXITCODE -eq 0) "Herencia deshabilitada"
  & icacls.exe $work /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' ("*"+$sid+":(OI)(CI)M") | Out-Null
  Assert ($LASTEXITCODE -eq 0) "ACL exclusiva de estado"
  & icacls.exe $work /setowner '*S-1-5-32-544' | Out-Null
  Assert ($LASTEXITCODE -eq 0) "Propietario seguro de carpeta"
  Assert-ACL $work $sid
  $adminKey=New-RandomProof
  $proxyKey=New-RandomProof
  Assert ($adminKey -ne $proxyKey) "Secretos distintos"
  $config=[ordered]@{
    schema_version=1;mode="virtual_loopback_only";bind_host="127.0.0.1";bind_port=9444
    database_path=(Join-Path $work "admission.sqlite")
    admin_proof=$adminKey;proxy_proof=$proxyKey
  }
  ($config|ConvertTo-Json -Depth 3)|Set-Content -LiteralPath $configFile -Encoding UTF8 -ErrorAction Stop
  $adminKey=$null;$proxyKey=$null;$config=$null
  & icacls.exe $configFile /setowner '*S-1-5-32-544'|Out-Null
  Assert ($LASTEXITCODE -eq 0) "Propietario de secretos seguro"
  Assert-ACL $configFile $sid

  $py=@'
"""K-X: sidecar VIRTUAL sin importaciones de app.main ni control del dispositivo."""
import json, os, re, sys
from pathlib import Path
if os.name != "nt":
    raise SystemExit(2)
HOME=Path(r"C:\ProgramData\VehiculoIoT-KX-State\service")
CONFIG=HOME/"config.json"
CODE=Path(r"C:\ProgramData\VehiculoIoT-KX-Staging\code")
sys.path.insert(0,str(CODE))
from app.public_control.local_files import check_private
try:
    check_private(HOME,directory=True)
    check_private(CONFIG)
    if CONFIG.stat().st_size > 4096: raise ValueError("size")
    data=json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    if not isinstance(data,dict) or set(data)!={"schema_version","mode","bind_host","bind_port","database_path","admin_proof","proxy_proof"}: raise ValueError("shape")
    if (type(data["schema_version"]) is not int or data["schema_version"]!=1 or
        data["mode"]!="virtual_loopback_only" or data["bind_host"]!="127.0.0.1" or
        type(data["bind_port"]) is not int or data["bind_port"]!=9444 or
        Path(data["database_path"])!=HOME/"admission.sqlite"): raise ValueError("target")
    for secret in (data["admin_proof"],data["proxy_proof"]):
        if not isinstance(secret,str) or re.fullmatch(r"[A-Za-z0-9_-]{64}",secret) is None: raise ValueError("secret")
    if data["admin_proof"]==data["proxy_proof"]: raise ValueError("same secret")
    os.environ["APP_ENV"]="staging"
    os.environ["ADMISSION_VIRTUAL_ONLY"]="enabled"
    from app.public_control.kv_virtual_staging import create_kv_virtual_app
    app=create_kv_virtual_app(data["database_path"],data["admin_proof"],data["proxy_proof"])
    import uvicorn
    uvicorn.run(app,host="127.0.0.1",port=9444,workers=1,reload=False,
                proxy_headers=False,access_log=False,server_header=False,log_level="error")
except BaseException:
    print("[K-X] NO-GO: sidecar virtual cerrado.",file=sys.stderr)
    raise SystemExit(2)
'@
  Set-Content -LiteralPath $launcher -Value $py -Encoding UTF8 -ErrorAction Stop
  Assert-ACL $launcher $sid
  $launcherHash=(Get-FileHash $launcher -Algorithm SHA256).Hash

  Write-Host ""
  Write-Host "=== TAREA SIN DISPARADOR DE INICIO AUTOMATICO ===" -ForegroundColor Cyan
  $action=New-ScheduledTaskAction -Execute $python -Argument ('-B -I "'+$launcher+'"')
  $settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 1)
  $parameters=@{
    TaskPath='\';TaskName=$taskName;User=($env:COMPUTERNAME+"\"+$userName)
    Password=$pass;RunLevel='Limited';Action=$action;Settings=$settings
    Description='K-X virtual loopback only; NO trigger; NO physical control';ErrorAction='Stop'
  }
  Register-ScheduledTask @parameters|Out-Null
  $pass=$null;$secure=$null
  $task=Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop
  Assert (@($task.Triggers | Where-Object { $null -ne $_ }).Count -eq 0) "Tarea sin trigger"
  Assert ([string]$task.Principal.RunLevel -eq "Limited") "Tarea no elevada"

  Write-Host ""
  Write-Host "=== ARRANQUE AISLADO 9444 ===" -ForegroundColor Cyan
  Start-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop
  $listening=@()
  for($i=0;$i -lt 60;$i++){
    Start-Sleep -Milliseconds 500
    $listening=@(Get-NetTCPConnection -LocalPort 9444 -State Listen -ErrorAction SilentlyContinue)
    if($listening.Count -gt 0){break}
    $nowTask=Get-ScheduledTask -TaskPath "\" -TaskName $taskName
    if($nowTask.State -ne "Running" -and $i -gt 8){break}
  }
  Assert ($listening.Count -eq 1 -and $listening[0].LocalAddress -eq "127.0.0.1") "9444 solamente loopback"
  $proc=Get-CimInstance Win32_Process -Filter ("ProcessId = "+$listening[0].OwningProcess) -ErrorAction Stop
  Assert ($null -ne $proc) "Proceso virtual existente"
  $owner=Invoke-CimMethod -InputObject $proc -MethodName GetOwnerSid -ErrorAction Stop
  Assert ($owner.Sid -eq $sid) "Python ejecutado por cuenta dedicada"
  foreach($pair in @(@("/docs","404"),@("/publico/vehiculos/1/solicitudes/estado","403"),@("/admin/vehiculos/1/control-publico/solicitudes","403"))){
    $status=& curl.exe --silent --show-error --max-time 4 --output NUL --write-out '%{http_code}' ("http://127.0.0.1:9444"+$pair[0])
    Assert ($LASTEXITCODE -eq 0 -and $status -eq $pair[1]) ("Rechazo HTTP esperado "+$pair[1])
  }
  Assert (@(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue).Count -gt 0) "8000 original disponible"
  Assert ((Get-FileHash $caddy -Algorithm SHA256).Hash -eq $before) "Caddy original intacto"
  $manifest=[ordered]@{
    schema_version=1;mode="loopback_only_not_public";dedicated_user=$userName;dedicated_sid=$sid
    task_name=$taskName;task_has_startup_trigger=$false;caddy_changed=$false
    physical_control_enabled=$false;launcher_sha256=$launcherHash
    original_caddy_sha256=$before;created_utc=(Get-Date).ToUniversalTime().ToString('o')
  }
  ($manifest|ConvertTo-Json -Depth 3)|Set-Content -LiteralPath $manifestFile -Encoding UTF8 -ErrorAction Stop
  Assert-ACL $manifestFile $sid
  $success=$true
  Write-Host ""
  Write-Host "=== RESULTADO: SERVICIO K-X LOOPBACK INSTALADO ===" -ForegroundColor Green
  Write-Host "TAREA: RUNNING, SIN ARRANQUE AUTOMATICO"
  Write-Host "9444: SOLO LOCAL; CADDY: INTACTO; CONTROL FISICO: OFF"
} catch {
  Write-Host ""
  Write-Host "=== RESULTADO: NO-GO ===" -ForegroundColor Red
  Write-Host ("TIPO: "+$_.Exception.GetType().Name) -ForegroundColor Yellow
  Write-Host ("ERROR: "+$_.Exception.Message) -ForegroundColor Yellow
} finally {
  if(-not $success){
    Write-Host ""
    Write-Host "=== ROLLBACK DE INSTALACION FALLIDA ===" -ForegroundColor Cyan
    $clean=$true
    try {
      $t=Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction SilentlyContinue
      if($null -ne $t){
        if($t.State -eq "Running"){ Stop-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop }
        Unregister-ScheduledTask -TaskPath "\" -TaskName $taskName -Confirm:$false -ErrorAction Stop
      }
      Assert ($null -eq (Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction SilentlyContinue)) "Tarea retirada"
    } catch {
      $clean=$false;Write-Host "NO-GO: tarea no pudo retirarse" -ForegroundColor Red
    }
    if(@(Get-NetTCPConnection -LocalPort 9444 -State Listen -ErrorAction SilentlyContinue).Count -gt 0){
      $clean=$false;Write-Host "NO-GO: puerto 9444 ocupado; preservar cuenta para investigacion" -ForegroundColor Red
    }
    if($clean){
      try {
        if($createdWork -and (Test-Path $work)){Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction Stop}
        foreach($p in $granted) {
          & icacls.exe $p /remove:g ("*"+$sid)|Out-Null
          if($LASTEXITCODE -ne 0){throw "ACL no retirada"}
        }
        foreach($right in $rights){[KXDedicatedRightsV1]::Change($sid,$right,$false)}
        if($createdUser){Remove-LocalUser -Name $userName -ErrorAction Stop}
        Write-Host "OK: Estado, permisos y cuenta retirados" -ForegroundColor Green
      } catch {
        $clean=$false;Write-Host "NO-GO: rollback de identidad incompleto" -ForegroundColor Red
        Write-Host $_.Exception.GetType().Name -ForegroundColor Yellow
      }
    }
    if($null -ne $before -and (Test-Path $caddy)){
      if((Get-FileHash $caddy -Algorithm SHA256).Hash -eq $before){
        Write-Host "OK: Caddy intacto" -ForegroundColor Green
      } else {$clean=$false;Write-Host "NO-GO: Caddy cambio" -ForegroundColor Red}
    }
    if($clean){Write-Host "=== ROLLBACK K-X COMPLETO ===" -ForegroundColor Green}
    else{Write-Host "=== ROLLBACK INCOMPLETO; NO REPETIR ===" -ForegroundColor Red}
  }
  $pass=$null;$secure=$null
  Write-Host "SIN CAMBIOS A TAREAS ORIGINALES / RDS / ESP / MOTORES"
  Write-Host "=== FIN K-X ===" -ForegroundColor Cyan
}
