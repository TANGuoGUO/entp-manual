from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LOGS = ROOT / "logs"


def emergency_log(message: str) -> None:
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        with (LOGS / "crash.log").open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message.rstrip()}\n")
    except OSError:
        pass


try:
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    import app

    app.main()
except BaseException:
    emergency_log("Windowless launcher failure\n" + traceback.format_exc())
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "ENTP Manual failed to start",
            f"Error details were saved to:\n{LOGS / 'crash.log'}",
        )
        root.destroy()
    except Exception:
        pass
    raise

