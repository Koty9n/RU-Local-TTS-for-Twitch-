// Запускатель Twitch TTS: та же проверка, что в start_tts.bat, но без чёрного окна.
// Всё установлено -> сразу venv\Scripts\pythonw.exe app\tts_app.py.
// Чего-то не хватает -> start_tts.bat (он ставит недостающее в окне с прогрессом).
// Сборка: app\launcher\build.ps1 (компилятор csc.exe из .NET Framework, есть в каждой Windows).
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("Twitch TTS")]
[assembly: System.Reflection.AssemblyProduct("Twitch TTS")]
[assembly: System.Reflection.AssemblyVersion("1.0.0.0")]

static class Launcher
{
    static string root;

    static string P(string rel) { return Path.Combine(root, rel); }

    static bool NeedInstall()
    {
        if (!File.Exists(P(@"data\installed.flag"))) return true;
        if (!File.Exists(P(@"venv\Scripts\pythonw.exe"))) return true;
        if (Directory.Exists(P(@"venv\Lib\site-packages\TeraTTS"))) return false;
        if (Directory.Exists(P(@"venv_tera\Lib\site-packages\TeraTTS"))) return false;
        // движка GLaDOS нет: ставить, только если GLaDOS выбрана при установке (как в start_tts.bat)
        string choice = P(@"data\voices.choice");
        if (!File.Exists(choice)) return true;
        foreach (string line in File.ReadAllLines(choice))
            if (line.Trim() == "GLaDOS") return true;
        return false;
    }

    [STAThread]
    static int Main()
    {
        root = AppDomain.CurrentDomain.BaseDirectory;
        try
        {
            Directory.CreateDirectory(P("data"));
            ProcessStartInfo psi;
            if (NeedInstall())
            {
                string bat = P("start_tts.bat");
                if (!File.Exists(bat))
                    throw new Exception("Рядом с программой нет start_tts.bat.\nTwitchTTS.exe должен лежать в папке Twitch TTS.");
                psi = new ProcessStartInfo(bat);
                psi.UseShellExecute = true;
            }
            else
            {
                psi = new ProcessStartInfo(P(@"venv\Scripts\pythonw.exe"), "\"" + P(@"app\tts_app.py") + "\"");
                psi.UseShellExecute = false;
            }
            psi.WorkingDirectory = root;
            Process.Start(psi);
            return 0;
        }
        catch (Exception e)
        {
            MessageBox.Show("Не получилось запустить Twitch TTS:\n\n" + e.Message +
                "\n\nМожно запустить start_tts.bat из той же папки.",
                "Twitch TTS", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
