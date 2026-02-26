' Launch InterYubi silently (no console window).
' Resolves paths dynamically — no hardcoded user directories.

Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
mainScript = fso.BuildPath(scriptDir, "interyubi.py")

If Not fso.FileExists(mainScript) Then
    MsgBox "interyubi.py not found in:" & vbCrLf & scriptDir, vbExclamation, "InterYubi"
    WScript.Quit 1
End If

Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = scriptDir
WshShell.Run "pythonw.exe """ & mainScript & """", 0, False
