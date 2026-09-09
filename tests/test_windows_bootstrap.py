"""Exercise runtime recovery with local ZIPs, without downloading or executing tools."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile


@unittest.skipUnless(os.name == "nt", "Windows PowerShell installer")
class RuntimeExtractionTests(unittest.TestCase):
    def test_repairs_partial_runtime_and_preserves_verified_copy(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            payload = b"fixture executable contents - never executed"
            archive = work / "fixture.zip"
            with zipfile.ZipFile(archive, "w") as out:
                out.writestr("nested/fixture.exe", payload)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            destination = work / "fixture.exe"
            destination.write_bytes(b"interrupted old extraction")
            (work / "fixture.exe.installing").write_bytes(b"interrupted new extraction")
            # Load just the actual function, without running the installer entry point.
            script = work / "check.ps1"
            script.write_text(r'''
param($Source, $Work, $Digest)
$ErrorActionPreference = 'Stop'
$roboRuntime = $Work
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($Source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw $errors[0] }
$function = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-VerifiedExecutable' }, $true)
. ([ScriptBlock]::Create($function.Extent.Text))
$destination = Join-Path $Work 'fixture.exe'
Get-VerifiedExecutable 'https://invalid.invalid/never-download' $Digest 'fixture.zip' 'fixture.exe' $destination
$before = (Get-Item -LiteralPath $destination).LastWriteTimeUtc
Get-VerifiedExecutable 'https://invalid.invalid/never-download' $Digest 'fixture.zip' 'fixture.exe' $destination
if ((Get-Item -LiteralPath $destination).LastWriteTimeUtc -ne $before) { throw 'Valid executable was replaced' }
# A bad archive must not replace the last valid executable.
try {
    Get-VerifiedExecutable 'bad-protocol://never-download' ('0' * 64) 'fixture.zip' 'fixture.exe' $destination
    throw 'Bad archive was accepted'
} catch {
    if ($_.Exception.Message -eq 'Bad archive was accepted') { throw }
}
''', encoding="utf-8")
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                 str(root / "scripts/bootstrap_windows.ps1"), str(work), digest],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(destination.read_bytes(), payload)
            self.assertFalse((work / "fixture.exe.installing").exists())
