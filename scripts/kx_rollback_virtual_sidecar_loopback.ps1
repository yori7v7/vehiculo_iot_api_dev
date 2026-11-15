# K-X: rollback de sidecar virtual instalado por kx_install_virtual_sidecar_loopback.ps1
# Windows PowerShell 5.1, solo archivos privados y tarea/cuenta dedicadas.
$ErrorActionPreference="Stop"
$stage="C:\ProgramData\VehiculoIoT-KX-Staging"
$work="C:\ProgramData\VehiculoIoT-KX-State\service"
$taskName="VehiculoIoT-Admission-Virtual"
$userName="VehIoT_KXSvc"
$caddy="C:\ProgramData\VehiculoIoT\Caddyfile"
$manifestFile=Join-Path $work "install.json"
function Assert([bool]$yes,[string]$message) {
  if(-not $yes){throw ("NO-GO: "+$message)}
  Write-Host ("OK: "+$message) -ForegroundColor Green
}
Write-Host "=== K-X: ROLLBACK MANUAL DEL SIDECAR VIRTUAL ===" -ForegroundColor Cyan
try {
  $who=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
  Assert ($who.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) "Consola elevada"
  Assert (Test-Path -LiteralPath $manifestFile -PathType Leaf) "Manifiesto instalado presente"
  $m=Get-Content $manifestFile -Raw|ConvertFrom-Json
  Assert ($m.schema_version -eq 1 -and $m.mode -eq "loopback_only_not_public" -and
          $m.dedicated_user -eq $userName -and $m.task_name -eq $taskName -and
          $m.caddy_changed -eq $false -and $m.physical_control_enabled -eq $false) "Manifest seguro"
  $account=Get-LocalUser -Name $userName -ErrorAction Stop
  $sid=$account.SID.Value
  Assert ($sid -eq $m.dedicated_sid) "SID de cuenta coincide"
  Assert ((Get-FileHash $caddy -Algorithm SHA256).Hash -eq $m.original_caddy_sha256) "Caddy original intacto"
  Assert (((Get-Item -LiteralPath $work -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) "Carpeta servicio no redirigida"
  foreach($n in @("VehiculoIoT-FastAPI","VehiculoIoT-Caddy")){
    $t=Get-ScheduledTask -TaskPath "\" -TaskName $n -ErrorAction Stop
    Assert ($t.State -eq "Running") ("Tarea original activa: "+$n)
  }
  $task=Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop
  Assert ($null -ne $task) "Tarea sidecar existe"
  $allowed=@("config.json","launcher.py","install.json","data")
  foreach($f in @(Get-ChildItem -LiteralPath $work -Force -ErrorAction Stop)){
    Assert ($f.Name -in $allowed -and (($f.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0)) "Elemento privado esperado"
  }
  $dataDir=Join-Path $work "data"
  Assert (Test-Path -LiteralPath $dataDir -PathType Container) "Datos SQLite presentes"
  $allowedData=@("admission.sqlite","admission.sqlite.lock","admission.sqlite-journal",
                 "admission.sqlite-wal","admission.sqlite-shm")
  foreach($f in @(Get-ChildItem -LiteralPath $dataDir -Force -ErrorAction Stop)){
    Assert ($f.Name -in $allowedData -and (($f.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0)) "Archivo SQLite esperado"
  }
  if(-not ("KXRollbackRightsV1" -as [type])){
    Add-Type -Language CSharp -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Principal;
public static class KXRollbackRightsV1 {
 [StructLayout(LayoutKind.Sequential)] private struct Obj {
   public uint Length; public IntPtr Root,Name; public uint Flags; public IntPtr Security,Quality;
 }
 [StructLayout(LayoutKind.Sequential)] private struct Ustr { public ushort Length,Maximum; public IntPtr Text; }
 [DllImport("advapi32.dll")] private static extern uint LsaOpenPolicy(IntPtr system,ref Obj a,uint access,out IntPtr policy);
 [DllImport("advapi32.dll")] private static extern uint LsaRemoveAccountRights(IntPtr handle,IntPtr sid,[MarshalAs(UnmanagedType.U1)] bool all,ref Ustr right,uint count);
 [DllImport("advapi32.dll")] private static extern uint LsaNtStatusToWinError(uint code);
 [DllImport("advapi32.dll")] private static extern uint LsaClose(IntPtr handle);
 public static void Remove(string sidText,string privilege) {
   var id=new SecurityIdentifier(sidText);
   byte[] bytes=new byte[id.BinaryLength];id.GetBinaryForm(bytes,0);
   IntPtr sid=IntPtr.Zero,text=IntPtr.Zero,policy=IntPtr.Zero;
   try {
     sid=Marshal.AllocHGlobal(bytes.Length);Marshal.Copy(bytes,0,sid,bytes.Length);
     text=Marshal.StringToHGlobalUni(privilege);
     Ustr r=new Ustr();r.Length=(ushort)(privilege.Length*2);
     r.Maximum=(ushort)((privilege.Length+1)*2);r.Text=text;
     Obj a=new Obj();a.Length=(uint)Marshal.SizeOf(typeof(Obj));
     uint s=LsaOpenPolicy(IntPtr.Zero,ref a,0x00000810,out policy);
     if(s!=0) throw new Win32Exception((int)LsaNtStatusToWinError(s));
     s=LsaRemoveAccountRights(policy,sid,false,ref r,1);
     if(s!=0) throw new Win32Exception((int)LsaNtStatusToWinError(s));
   } finally {
     if(policy!=IntPtr.Zero)LsaClose(policy);
     if(text!=IntPtr.Zero)Marshal.FreeHGlobal(text);
     if(sid!=IntPtr.Zero)Marshal.FreeHGlobal(sid);
   }
 }
}
'@ -ErrorAction Stop
  }
  Write-Host "OK: Prevuelo rollback aprobado" -ForegroundColor Green
  if($task.State -eq "Running"){
    Stop-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction Stop
    Write-Host "OK: Stop de sidecar solicitado" -ForegroundColor Green
  }
  for($i=0;$i -lt 30;$i++){
    $p=@(Get-NetTCPConnection -LocalPort 9444 -State Listen -ErrorAction SilentlyContinue)
    if($p.Count -eq 0){break}
    Start-Sleep -Milliseconds 500
  }
  Assert (@(Get-NetTCPConnection -LocalPort 9444 -State Listen -ErrorAction SilentlyContinue).Count -eq 0) "9444 apagado"
  Unregister-ScheduledTask -TaskPath "\" -TaskName $taskName -Confirm:$false -ErrorAction Stop
  Assert ($null -eq (Get-ScheduledTask -TaskPath "\" -TaskName $taskName -ErrorAction SilentlyContinue)) "Tarea sidecar eliminada"
  Remove-Item -LiteralPath $work -Force -Recurse -ErrorAction Stop
  Assert (-not (Test-Path -LiteralPath $work)) "Estado virtual y credenciales retirados"
  foreach($p in @((Join-Path $stage "code"),(Join-Path $stage "runtime"))){
    & icacls.exe $p /remove:g ("*"+$sid)|Out-Null
    Assert ($LASTEXITCODE -eq 0) "Acceso del servicio retirado"
  }
  foreach($r in @("SeBatchLogonRight","SeDenyInteractiveLogonRight","SeDenyRemoteInteractiveLogonRight")){
    [KXRollbackRightsV1]::Remove($sid,$r)
    Write-Host ("OK: Derecho retirado: "+$r) -ForegroundColor Green
  }
  Remove-LocalUser -Name $userName -ErrorAction Stop
  Assert ($null -eq (Get-LocalUser -Name $userName -ErrorAction SilentlyContinue)) "Cuenta dedicada retirada"
  Assert ((Get-FileHash $caddy -Algorithm SHA256).Hash -eq $m.original_caddy_sha256) "Caddy intacto tras rollback"
  Write-Host "=== K-X: ROLLBACK COMPLETO ===" -ForegroundColor Green
} catch {
  Write-Host "=== NO-GO: ROLLBACK INCOMPLETO, NO REPETIR ===" -ForegroundColor Red
  Write-Host ("ERROR: "+$_.Exception.GetType().Name) -ForegroundColor Yellow
  Write-Host $_.Exception.Message -ForegroundColor Yellow
}
Write-Host "SIN OPERACIONES SOBRE RDS, ESP, MOTORES O CADDY LEGACY"
