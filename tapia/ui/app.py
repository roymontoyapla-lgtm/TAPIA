"""Ventana principal de TAPIA."""

import logging
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Tuple

from ..ai.gpt_client import get_ai_urgency
from ..core.config import cfg
from ..core.models import PatientInfo, Questionnaire
from ..core.report import build_report
from ..core.triage import URGENCY_ORDER, merge_buckets, triage_ap_vs_specialist, urgency_score_and_bucket
from ..core.wearable import filter_by_days, load_json, summarize
from ..export.pdf import REPORTLAB_OK, save_pdf

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageTk
    PILLOW_OK = True
except ImportError:
    PILLOW_OK = False

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()

        self.title(cfg.app.name)
        self.geometry(cfg.app.geometry)
        self.resizable(True, True)

        # Icono
        ico = os.path.join(BASE_DIR, "Tapia.ico")
        if os.path.exists(ico):
            try:
                self.iconbitmap(ico)
            except Exception as e:
                logger.warning("Icono no cargado: %s", e)

        self.current_report: str = ""
        self._build_ui()

    # ------------------------------------------------------------------
    # Construcción de la interfaz
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        logo_path = os.path.join(BASE_DIR, "Tapia_logo.png")
        if PILLOW_OK and os.path.exists(logo_path):
            try:
                img = Image.open(logo_path).resize((140, 70), Image.LANCZOS)
                self._logo = ImageTk.PhotoImage(img)
                ttk.Label(self, image=self._logo).pack(pady=(10, 4))
            except Exception as e:
                logger.warning("Logo no cargado: %s", e)

        main = ttk.Frame(self)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        left  = ttk.Frame(main, padding=10)
        left.pack(side=tk.LEFT, fill=tk.Y)

        right = ttk.Frame(main, padding=10)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self._build_left(left)
        self._build_right(right)

    def _build_left(self, parent: ttk.Frame) -> None:
        W = 28

        # Paciente
        ttk.Label(parent, text="Datos del paciente", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 6))
        self.name_var = tk.StringVar()
        self.age_var  = tk.StringVar()
        self.sex_var  = tk.StringVar(value="M")
        self._lbl_entry(parent, "Nombre", self.name_var, W)
        self._lbl_entry(parent, "Edad",   self.age_var,  10)
        ttk.Label(parent, text="Sexo").pack(anchor="w")
        ttk.Combobox(parent, textvariable=self.sex_var, values=["M", "F", "Otro"],
                     state="readonly", width=8).pack(anchor="w", pady=(0, 10))

        # Cuestionario
        ttk.Label(parent, text="Cuestionario", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(8, 6))
        self.headache_var = tk.BooleanVar(value=False)
        self.fever_var    = tk.BooleanVar(value=False)
        ttk.Checkbutton(parent, text="Dolor de cabeza último mes", variable=self.headache_var).pack(anchor="w")
        ttk.Checkbutton(parent, text="Fiebre",                     variable=self.fever_var).pack(anchor="w", pady=(0, 8))

        self.general_var = tk.IntVar(value=3)
        self.rest_var    = tk.IntVar(value=3)
        self.exdays_var  = tk.IntVar(value=2)
        self._lbl_spinbox(parent, "Estado general (1-5)",                self.general_var, 1, 5,  5)
        self._lbl_spinbox(parent, "Descanso suficiente (1-5)",           self.rest_var,    1, 5,  5)
        self._lbl_spinbox(parent, "Días de ejercicio (últimas semanas)", self.exdays_var,  0, 60, 6)

        self.diet_var    = tk.StringVar(value="")
        self.chronic_var = tk.StringVar(value="")
        self._lbl_entry(parent, "Estilo de alimentación (opcional)",           self.diet_var,    W)
        self._lbl_entry(parent, "Enfermedad crónica / preexistente (opcional)", self.chronic_var, W)

        # JSON
        ttk.Label(parent, text="Archivo JSON del wearable", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(10, 6))
        self.json_path = tk.StringVar(value="")
        ttk.Entry(parent, textvariable=self.json_path, width=W).pack(anchor="w", pady=(0, 4))
        ttk.Button(parent, text="Cargar JSON…", command=self._pick_json).pack(anchor="w")

        # Acciones
        ttk.Separator(parent).pack(fill=tk.X, pady=12)
        self.run_btn = ttk.Button(parent, text="▶  Ejecutar triaje", command=self._start_triage)
        self.run_btn.pack(anchor="w", fill=tk.X)
        ttk.Button(parent, text="💾  Guardar PDF", command=self._save_pdf).pack(anchor="w", fill=tk.X, pady=(6, 0))

    def _build_right(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Informe", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.text   = tk.Text(frame, wrap="word", font=("Courier New", 10))
        scroll      = ttk.Scrollbar(frame, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _lbl_entry(parent, label, var, width) -> None:
        ttk.Label(parent, text=label).pack(anchor="w")
        ttk.Entry(parent, textvariable=var, width=width).pack(anchor="w", pady=(0, 6))

    @staticmethod
    def _lbl_spinbox(parent, label, var, from_, to, width) -> None:
        ttk.Label(parent, text=label).pack(anchor="w")
        ttk.Spinbox(parent, from_=from_, to=to, textvariable=var, width=width).pack(anchor="w", pady=(0, 6))

    def _set_running(self, running: bool) -> None:
        self.run_btn.config(
            state="disabled" if running else "normal",
            text="⏳  Procesando…" if running else "▶  Ejecutar triaje",
        )

    # ------------------------------------------------------------------
    # Acciones
    # ------------------------------------------------------------------

    def _pick_json(self) -> None:
        path = filedialog.askopenfilename(
            title="Selecciona un archivo JSON",
            filetypes=[("JSON", "*.json"), ("Todos los archivos", "*.*")],
        )
        if path:
            self.json_path.set(path)

    def _validate_inputs(self) -> Tuple[PatientInfo, Questionnaire, str]:
        name = self.name_var.get().strip()
        if not name:
            raise ValueError("El nombre no puede estar vacío.")
        try:
            age = int(self.age_var.get().strip())
        except ValueError:
            raise ValueError("La edad debe ser un número entero.")
        if not (1 <= age <= 129):
            raise ValueError("La edad debe estar entre 1 y 129 años.")

        path = self.json_path.get().strip()
        if not path:
            raise ValueError("Selecciona un archivo JSON del wearable.")
        if not os.path.exists(path):
            raise ValueError(f"El archivo no existe:\n{path}")

        patient = PatientInfo(name=name, age=int(age), sex=self.sex_var.get() or "Otro")
        q = Questionnaire(
            headache_last_month=bool(self.headache_var.get()),
            fever=bool(self.fever_var.get()),
            general_feeling=int(self.general_var.get()),
            diet_style=self.diet_var.get().strip(),
            rested_enough=int(self.rest_var.get()),
            exercise_days_last_weeks=int(self.exdays_var.get()),
            other_notes=self.chronic_var.get().strip(),
        )
        return patient, q, path

    def _start_triage(self) -> None:
        try:
            patient, q, path = self._validate_inputs()
        except ValueError as e:
            messagebox.showerror("Error de validación", str(e))
            return
        self._set_running(True)
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, "Ejecutando triaje, por favor espera…\n")
        threading.Thread(target=self._worker, args=(patient, q, path), daemon=True).start()

    def _worker(self, patient: PatientInfo, q: Questionnaire, path: str) -> None:
        try:
            records = load_json(path)
            w30 = summarize(filter_by_days(records, cfg.wearable.window_short))
            w56 = summarize(filter_by_days(records, cfg.wearable.window_long))

            rec, spec, reasons                       = triage_ap_vs_specialist(q, w30, w56)
            local_bucket, local_score, local_motivos = urgency_score_and_bucket(patient, q, w30, w56)

            # Informe previo para alimentar la IA
            pre = build_report(
                patient, q, w30, w56, rec, spec, reasons,
                local_bucket, local_score, local_motivos,
                {"urgency": "2_semanas", "justification": "", "red_flags": []},
                local_bucket,
            )

            ai           = get_ai_urgency(pre, patient_name=patient.name)
            final_bucket = merge_buckets(local_bucket, ai.get("urgency", "2_semanas"))

            report = build_report(
                patient, q, w30, w56, rec, spec, reasons,
                local_bucket, local_score, local_motivos,
                ai, final_bucket,
            )
            self.after(0, self._update_report, report)

        except Exception as e:
            logger.exception("Error en el triaje.")
            self.after(0, lambda: messagebox.showerror("Error", str(e)))
            self.after(0, self._set_running, False)

    def _update_report(self, report: str) -> None:
        self.current_report = report
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, report)
        self._set_running(False)

    def _save_pdf(self) -> None:
        if not self.current_report:
            messagebox.showwarning("Aviso", "Primero ejecuta el triaje.")
            return
        if not REPORTLAB_OK:
            messagebox.showerror("PDF", "ReportLab no instalado.\npip install reportlab")
            return
        out = filedialog.asksaveasfilename(
            title="Guardar PDF",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
        )
        if out:
            try:
                save_pdf(out, self.current_report)
                messagebox.showinfo("OK", f"PDF guardado en:\n{out}")
            except Exception as e:
                messagebox.showerror("Error PDF", str(e))
