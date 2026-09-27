import os
import platform
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def is_valid_venv(env_path: Path, os_name: str) -> bool:
    """Verifica si la carpeta existe y contiene la estructura minima funcional de un venv."""
    if not env_path.is_dir():
        return False

    cfg_file = env_path / "pyvenv.cfg"
    if not cfg_file.is_file():
        return False

    if os_name == "windows":
        python_bin = env_path / "Scripts" / "python.exe"
    else:
        python_bin = env_path / "bin" / "python"

    return python_bin.exists()


def main():
    os_name = platform.system().lower()

    # Directorio raiz (un nivel arriba de 'tools')
    root_dir = Path(__file__).resolve().parent.parent
    env_dir = root_dir / "env"

    os.chdir(root_dir)

    print(f"Sistema detectado: {platform.system()}")
    print(f"Directorio raiz: {root_dir}")

    # 1. Comprobar si ya existe el entorno o crearlo
    if is_valid_venv(env_dir, os_name):
        print(f"-> Entorno virtual detectado y valido en: {env_dir}")
    else:
        print(f"-> No se encontro un entorno valido. Creando en: {env_dir}...")
        venv.create(env_dir, with_pip=True)
        print("-> Entorno virtual creado exitosamente.")

    # 2. Iniciar subshell interactiva con activacion oficial
    if os_name == "windows":
        activate_ps1 = env_dir / "Scripts" / "Activate.ps1"
        activate_bat = env_dir / "Scripts" / "activate.bat"

        if activate_ps1.exists():
            print("\nAbriendo PowerShell dentro del entorno virtual...")
            print("Escribe 'exit' para salir.\n")
            subprocess.run(
                [
                    "powershell.exe",
                    "-NoExit",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(activate_ps1),
                ],
                cwd=str(root_dir),
            )
        elif activate_bat.exists():
            print("\nAbriendo CMD dentro del entorno virtual...")
            print("Escribe 'exit' para salir.\n")
            subprocess.run(["cmd.exe", "/K", str(activate_bat)], cwd=str(root_dir))
        else:
            sys.exit("Error: No se encontraron los scripts de activacion en Windows.")

    elif os_name in ("linux", "darwin"):
        activate_sh = env_dir / "bin" / "activate"
        if not activate_sh.exists():
            sys.exit(f"Error: No se encontro el script de activacion en {activate_sh}")

        user_shell = os.environ.get("SHELL", "/bin/bash")
        print(f"\nAbriendo subshell ({user_shell}) dentro del entorno virtual...")
        print("Escribe 'exit' para salir del entorno.\n")

        # Script de arranque temporal: lee ~/.bashrc y luego aplica el activate oficial
        with tempfile.NamedTemporaryFile("w", delete=False, prefix="venv_init_") as f:
            f.write(
                f"[ -f ~/.bashrc ] && . ~/.bashrc\n"
                f'. "{activate_sh.resolve()}"\n'
            )
            rcfile_path = f.name

        try:
            if "bash" in user_shell:
                subprocess.run(
                    [user_shell, "--rcfile", rcfile_path, "-i"],
                    cwd=str(root_dir),
                )
            elif "zsh" in user_shell:
                cmd = f'. ~/.zshrc 2>/dev/null; . "{activate_sh.resolve()}"; exec zsh'
                subprocess.run([user_shell, "-c", cmd], cwd=str(root_dir))
            else:
                subprocess.run(
                    ["bash", "--rcfile", rcfile_path, "-i"],
                    cwd=str(root_dir),
                )
        finally:
            if os.path.exists(rcfile_path):
                os.remove(rcfile_path)

    else:
        sys.exit(f"Sistema operativo no soportado: {platform.system()}")


if __name__ == "__main__":
    main()