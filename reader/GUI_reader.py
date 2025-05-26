# gui_reader.py
import asyncio, json, threading, tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from . import make_reader
import webbrowser

KANJI_FILE = Path(__file__).parent.with_name("kanji_by_grade.json")

# ── core async helper ───────────────────────────────────────────
def run_async(coro):
    """Run an asyncio coroutine in a background thread (keeps UI alive)."""
    threading.Thread(target=lambda: asyncio.run(coro), daemon=True).start()

# ── GUI ─────────────────────────────────────────────────────────
class ReaderGUI(tk.Tk):
    def __init__(self):
        super().__init__()
       
        # optional: set a comfortable default window size
        self.geometry("600x600")
        
        self.title("Kanji Reader Generator")

        # ── 1. SCROLLABLE ROOT ────────────────────────────
        canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        vsb    = ttk.Scrollbar(self, orient="vertical",
                               command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)

        vsb.pack(side="right", fill="y")
        canvas.pack(side="left",  fill="both", expand=True)

        form = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=form, anchor="nw")

        # update scrollregion whenever widgets resize
        form.bind("<Configure>",
                  lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        # enable mouse-wheel scrolling
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(int(-e.delta/120), "units"))

        # --- keep a reference for later widget creation ---
        self.form = form

        # --- load canonical kanji list once --------------
        self.kanji_dict = json.load(KANJI_FILE.open(encoding="utf-8"))

        # ── 2.  REST OF ORIGINAL WIDGET CREATION ──────────
        self.build_form_widgets()      # moved to its own method


        
    def build_form_widgets(self):
        """
        Create every control inside the scrollable “form” frame.
        This replaces the original flat layout and uses self.form
        (created in __init__) as the parent container.
        """
        parent = self.form  # alias for brevity
        pady   = 4          # uniform vertical spacing

        # ── Grade level ───────────────────────────────────────
        self.grade_var = tk.StringVar(value="1")
        ttk.Label(parent, text="Grade level (1–6):").grid(row=0, column=0, sticky="w", pady=pady)
        ttk.Spinbox(parent, from_=1, to=6, width=5,
                    textvariable=self.grade_var,
                    command=self.populate_kanji
                   ).grid(row=0, column=1, sticky="w", pady=pady)

        # ── Kanji grid header ─────────────────────────────────
        ttk.Label(parent, text="Select kanji (click to toggle):")\
            .grid(row=1, column=0, columnspan=2, sticky="w")
        self.kanji_frame = ttk.Frame(parent)
        self.kanji_frame.grid(row=2, column=0, columnspan=4, sticky="w")
        self.selected_kanji = set()
        self.populate_kanji()  # initial fill

        # ── Min repetition ────────────────────────────────────
        self.rep_var = tk.IntVar(value=3)
        ttk.Label(parent, text="Min repetition:")\
            .grid(row=3, column=0, sticky="w", pady=pady)
        ttk.Spinbox(parent, from_=1, to=10, width=5,
                    textvariable=self.rep_var)\
            .grid(row=3, column=1, sticky="w", pady=pady)

        # ── Word-count range ──────────────────────────────────
        self.wmin = tk.IntVar(value=2000)
        self.wmax = tk.IntVar(value=3000)
        ttk.Label(parent, text="Word count (min–max):")\
            .grid(row=4, column=0, sticky="w", pady=pady)
        ttk.Entry(parent, textvariable=self.wmin, width=6)\
            .grid(row=4, column=1, sticky="w", pady=pady)
        ttk.Entry(parent, textvariable=self.wmax, width=6)\
            .grid(row=4, column=2, sticky="w", pady=pady)

        # ── Image count ───────────────────────────────────────
        self.img_var = tk.IntVar(value=0)
        ttk.Label(parent, text="Illustrations (max 3):")\
            .grid(row=5, column=0, sticky="w", pady=pady)
        ttk.Spinbox(parent, from_=0, to=10, width=5,
                    textvariable=self.img_var,
                    command=self.toggle_style)\
            .grid(row=5, column=1, sticky="w", pady=pady)

        # style widgets (hidden unless img_var > 0)
        self.style_label = ttk.Label(parent, text="Illustration style:")
        self.style_entry = ttk.Entry(parent, width=30)
        self.toggle_style()  # show/hide based on initial value

        # ── Optional theme ────────────────────────────────────
        self.theme_var = tk.StringVar()
        ttk.Label(parent, text="Optional story theme (if none, AI will determine):")\
            .grid(row=7, column=0, sticky="w", pady=pady)
        ttk.Entry(parent, textvariable=self.theme_var, width=40)\
            .grid(row=7, column=1, columnspan=3, sticky="w", pady=pady)

        # ── Generate button & status ──────────────────────────
        ttk.Button(parent, text="Generate", command=self.on_generate)\
            .grid(row=8, column=0, pady=10, sticky="w")
        self.status = ttk.Label(parent, text="")
        self.status.grid(row=8, column=1, columnspan=3, sticky="w")
      


    # ----- dynamic UI helpers ----------------------------

    def populate_kanji(self):
        for w in self.kanji_frame.winfo_children():
            w.destroy()
        self.selected_kanji.clear()
        
        self.update_idletasks()                 # be sure geometry is settled
        win_w      = self.winfo_width()         # current window width in px
        cell_w     = 28                         # ≈ label width + gap
        cols_wrap  = max(10, -1 + win_w // cell_w)   # never less than 10
    
        grade = self.grade_var.get()
        row = col = 0
        for ch in self.kanji_dict.get(grade, []):
            lbl = tk.Label(self.kanji_frame, text=ch, font=("Noto Serif JP", 14))
            lbl.grid(row=row, column=col, padx=0, pady=0) 
            lbl.bind("<Button-1>", lambda e, c=ch, l=lbl: self.toggle_kanji(c, l))
            col += 1
            if col % cols_wrap == 0:  # wrap
                row += 1; col = 0

    def toggle_kanji(self, ch, lbl):
        if ch in self.selected_kanji:
            self.selected_kanji.remove(ch)
            lbl.config(fg="black")
        else:
            self.selected_kanji.add(ch)
            lbl.config(fg="red")

    def toggle_style(self):
        if self.img_var.get() > 0:
            self.style_label.grid(row=6, column=0, sticky="w")
            self.style_entry.grid(row=6, column=1, columnspan=3, sticky="w")
        else:
            self.style_label.grid_remove()
            self.style_entry.grid_remove()

    # ----- generate button callback ----------------------

    def on_generate(self):
        if not self.selected_kanji:
            messagebox.showwarning("No kanji selected", "Please select at least one kanji.")
            return
        self.status.config(text="Running… please wait")
        run_async(self.build_reader())

    async def build_reader(self):
        try:
            epub_path, pdf_path, html_path = await make_reader(
                grade=int(self.grade_var.get()),
                kanji=list(self.selected_kanji),
                min_freq=self.rep_var.get(),
                wc_range=(self.wmin.get(), self.wmax.get()),
                n_pics=self.img_var.get(),
                style=self.style_entry.get() or "Colored Pencil sketch",
                idea=self.theme_var.get() or None
            )
            self.status.config(text=f"Done → {epub_path}")
            
            webbrowser.open_new_tab(html_path.as_uri())
        except Exception as e:
            self.status.config(text="Error")
            messagebox.showerror("Generation failed", str(e))

# ── run GUI ──────────────────────────────────────────────
if __name__ == "__main__":
    ReaderGUI().mainloop()
