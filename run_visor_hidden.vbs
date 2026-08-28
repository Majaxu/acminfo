' Lanza run_visor.bat sin ventana visible (para la tarea al iniciar sesion).
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")
carpeta = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = carpeta
sh.Run "cmd /c """ & carpeta & "\run_visor.bat""", 0, False
