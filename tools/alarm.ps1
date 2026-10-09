# Loud tornado alarm: unmutes the PC, turns volume to max, plays a siren,
# speaks the message out loud, and shows a pop-up on top of everything.
# Click OK on the pop-up to stop it (it stops on its own after -Minutes).
#
#   powershell -ExecutionPolicy Bypass -File tools\alarm.ps1 -Message "Tornado warning. Take shelter now."
#   ... -Test   (5 seconds, leaves your volume alone)
param(
  [string]$Message = "Tornado warning. Take shelter now.",
  [int]$Minutes = 10,
  [switch]$Test
)

# --- Volume: unmute + max (Windows Core Audio) ---
$audio = @'
using System; using System.Runtime.InteropServices;
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {
  int f(); int g(); int h(); int i();
  int SetMasterVolumeLevelScalar(float level, Guid ctx);
  int j(); int GetMasterVolumeLevelScalar(out float level);
  int k(); int l(); int m(); int n();
  int SetMute([MarshalAs(UnmanagedType.Bool)] bool mute, Guid ctx);
  int GetMute(out bool mute);
}
[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice { int Activate(ref Guid id, int ctx, IntPtr p, [MarshalAs(UnmanagedType.IUnknown)] out object o); }
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator { int f(); int GetDefaultAudioEndpoint(int flow, int role, out IMMDevice dev); }
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumeratorCom { }
public static class PcVolume {
  static IAudioEndpointVolume Vol() {
    var e = new MMDeviceEnumeratorCom() as IMMDeviceEnumerator; IMMDevice dev;
    Marshal.ThrowExceptionForHR(e.GetDefaultAudioEndpoint(0, 1, out dev));
    var iid = typeof(IAudioEndpointVolume).GUID; object o;
    Marshal.ThrowExceptionForHR(dev.Activate(ref iid, 23, IntPtr.Zero, out o));
    return (IAudioEndpointVolume)o;
  }
  public static float Level { get { float v; Marshal.ThrowExceptionForHR(Vol().GetMasterVolumeLevelScalar(out v)); return v; } }
  public static void Max() { var v = Vol(); v.SetMute(false, Guid.Empty); v.SetMasterVolumeLevelScalar(1.0f, Guid.Empty); }
}
'@
try { Add-Type -TypeDefinition $audio -ErrorAction Stop } catch {}
if (-not $Test) {
  try { [PcVolume]::Max() } catch {
    # fallback: tap the volume-up key a bunch of times
    $wsh = New-Object -ComObject WScript.Shell
    1..50 | ForEach-Object { $wsh.SendKeys([char]175) }
  }
}

# --- Siren: build a rising/falling tone WAV in memory and loop it ---
$rate = 22050; $secs = 2.0; $n = [int]($rate * $secs)
$ms = New-Object System.IO.MemoryStream
$w = New-Object System.IO.BinaryWriter($ms)
$w.Write([Text.Encoding]::ASCII.GetBytes("RIFF")); $w.Write([int](36 + $n * 2))
$w.Write([Text.Encoding]::ASCII.GetBytes("WAVEfmt ")); $w.Write([int]16); $w.Write([int16]1); $w.Write([int16]1)
$w.Write([int]$rate); $w.Write([int]($rate * 2)); $w.Write([int16]2); $w.Write([int16]16)
$w.Write([Text.Encoding]::ASCII.GetBytes("data")); $w.Write([int]($n * 2))
$phase = 0.0
for ($s = 0; $s -lt $n; $s++) {
  $t = $s / $rate
  $f = 600 + 700 * [Math]::Abs(($t % 2.0) - 1.0)    # sweeps 600-1300 Hz like a siren
  $phase += 2 * [Math]::PI * $f / $rate
  $w.Write([int16](30000 * [Math]::Sign([Math]::Sin($phase)) * 0.9))   # square wave = loud
}
$ms.Position = 0
$player = New-Object System.Media.SoundPlayer($ms)
$player.PlayLooping()

# --- Say it out loud, then pop-up on top of everything ---
try {
  $voice = New-Object -ComObject SAPI.SpVoice
  $voice.Volume = 100
  # speaks without waiting, so the siren and pop-up still come up
  $null = $voice.Speak("$Message $Message", 1)
} catch {}

$wait = if ($Test) { 5 } else { $Minutes * 60 }
$wsh = New-Object -ComObject WScript.Shell
$null = $wsh.Popup("$Message`n`nClick OK to stop the alarm.", $wait, "TORNADO ALARM", 0x30 + 0x1000)
$player.Stop()
