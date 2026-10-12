// Scrybinder launcher: starts the app from the project environment (.venv) without a console window.
// Build: assets\build_launcher.ps1  (uses the csc.exe that ships with Windows).
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

static class Launcher
{
    [STAThread]
    static int Main()
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        // the .exe may sit in the project root or in a subfolder (e.g. assets\): walk up until the .venv is found
        for (int i = 0; i < 3 && !File.Exists(Path.Combine(root, ".venv", "Scripts", "pythonw.exe")); i++)
            root = Path.GetFullPath(Path.Combine(root, ".."));
        string py = Path.Combine(root, ".venv", "Scripts", "pythonw.exe");
        if (!File.Exists(py))
        {
            MessageBox.Show("Could not find the Scrybinder environment (.venv).\nIn the project folder run:  uv sync --extra vision",
                            "Scrybinder", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return 1;
        }
        var psi = new ProcessStartInfo(py, "-m scrybinder.app") { WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true };
        Process.Start(psi);
        return 0;
    }
}
