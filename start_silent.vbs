Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
ScriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

WshShell.CurrentDirectory = ScriptDir

Dim PythonwPath
PythonwPath = ""

Dim localApp
localApp = WshShell.ExpandEnvironmentStrings("%LOCALAPPDATA%")

If fso.FileExists(localApp & "\Programs\Python\Python312\pythonw.exe") Then
    PythonwPath = localApp & "\Programs\Python\Python312\pythonw.exe"
ElseIf fso.FileExists(localApp & "\Programs\Python\Python311\pythonw.exe") Then
    PythonwPath = localApp & "\Programs\Python\Python311\pythonw.exe"
ElseIf fso.FileExists(localApp & "\Programs\Python\Python313\pythonw.exe") Then
    PythonwPath = localApp & "\Programs\Python\Python313\pythonw.exe"
Else
    PythonwPath = "pythonw.exe"
End If

Cmd = """" & PythonwPath & """ """ & ScriptDir & "\agy_tray.py"""
On Error Resume Next
WshShell.Run Cmd, 0, False
If Err.Number <> 0 Then
    Err.Clear
    Cmd = "pyw.exe """ & ScriptDir & "\agy_tray.py"""
    WshShell.Run Cmd, 0, False
End If
