' Lanza run_vistas.bat SIN ventana visible (para la tarea programada horaria).
' Chrome igual se ve cuando esta dentro de la ventana; esto solo evita el
' parpadeo de consola cuando la corrida arranca y sale enseguida.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")
carpeta = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = carpeta
sh.Run "cmd /c """ & carpeta & "\run_vistas.bat""", 0, False
