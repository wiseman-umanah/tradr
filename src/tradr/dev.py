import subprocess

def main():
    subprocess.run([
        "textual",
        "run",
        "--dev",
        "src/tradr/app.py"
    ])

