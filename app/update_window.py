"""Tiny native update progress window; remains usable before WebView starts."""
import logging
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk

import httpx

from .updates import download


def obtain_update(data, payload):
    messages = queue.Queue()
    root = tk.Tk()
    root.title('Расписание — обновление')
    root.geometry('420x155')
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text=f"Устанавливаем версию {payload['version']}").pack(anchor='w')
    progress = ttk.Progressbar(frame, maximum=100)
    progress.pack(fill='x', pady=14)
    label = ttk.Label(frame, text='Загружаем обновление…')
    label.pack(anchor='w')
    result = []
    cancelled = threading.Event()

    def cancel():
        cancelled.set()
        root.destroy()

    root.protocol('WM_DELETE_WINDOW', cancel)
    ttk.Button(frame, text='Открыть без обновления', command=cancel).pack(anchor='e', pady=(8, 0))

    def receive(done, size):
        if cancelled.is_set():
            raise InterruptedError('Update deferred')
        messages.put(('progress', done * 100 / size))

    def work():
        try:
            with httpx.Client(timeout=httpx.Timeout(30, connect=8), follow_redirects=False,
                              headers={'User-Agent': 'SchoolSchedule-Updates'}) as client:
                path = download(client, payload, Path(data) / 'updates', receive)
            messages.put(('done', path))
        except Exception:
            logging.info('Update download deferred', exc_info=True)
            messages.put(('error', None))

    def poll():
        try:
            while True:
                kind, value = messages.get_nowait()
                if kind == 'progress':
                    progress['value'] = value
                    label['text'] = f'Загружено {value:.0f}%'
                else:
                    if kind == 'done':
                        result.append(value)
                    root.destroy()
                    return
        except queue.Empty:
            root.after(100, poll)

    threading.Thread(target=work, daemon=True).start()
    root.after(100, poll)
    root.mainloop()
    return result[0] if result else None
