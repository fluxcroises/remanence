"""Bavure : interface graphique (tkinter, fourni avec Python sous Windows)."""
import os
import queue
import random
import tempfile
import threading
import time
import tkinter as tk
from dataclasses import asdict
from tkinter import filedialog, messagebox, ttk

import cv2
from PIL import Image, ImageTk

from .effets import ReglagesEffets, appliquer
from .moteur_mosh import ReglagesMosh
from .outils import infos_video
from .rendu import Annule, rendre

# --- Palette sombre -------------------------------------------------------
FOND = "#141418"
PANNEAU = "#1d1d23"
CHAMP = "#26262e"
TEXTE = "#e8e6ef"
TEXTE_DOUX = "#9a97a8"
ACCENT = "#ff3d7f"      # rose « glitch »
ACCENT2 = "#3df2ff"     # cyan
POLICE = ("Segoe UI", 10)
POLICE_TITRE = ("Segoe UI Semibold", 11)

LARGEUR_APERCU = 800
HAUTEUR_APERCU = 450

PREREGLAGES = {
    "Bavure classique": dict(mosh=dict(actif=True, supprimer_cles=True, bloom=False, blocs=4, databending=0),
                             fx=dict()),
    "Fonte (bloom)": dict(mosh=dict(actif=True, supprimer_cles=True, bloom=True, bloom_repetitions=60, blocs=3),
                          fx=dict()),
    "Cassette abîmée": dict(mosh=dict(actif=False), fx=dict(vhs=70, scanlines=40, rvb=20)),
    "Pixels triés": dict(mosh=dict(actif=False), fx=dict(tri_pixels=45, rvb=15)),
    "Chaos total": dict(mosh=dict(actif=True, supprimer_cles=True, bloom=True, bloom_repetitions=25,
                                  blocs=14, databending=45),
                        fx=dict(rvb=40, blocs=35, scanlines=30)),
}


def format_temps(s):
    s = max(0, s)
    return f"{int(s // 60):02d}:{s % 60:05.2f}"


class Bavure(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Bavure · datamosh & glitch")
        self.configure(bg=FOND)
        self.minsize(1180, 700)
        self._style()

        self.sources = []            # fichiers chargés (mis bout à bout)
        self.fichier_affiche = None  # vidéo actuellement lue dans l'aperçu
        self.cap = None
        self.fps = 25.0
        self.nb_images = 1
        self.position = 0
        self.lecture = False
        self.maj_curseur = False
        self.cles = []               # instants des images clés détectées
        self.apercus = {}            # "original" / "mosh" -> chemin du fichier d'aperçu
        self.mode = tk.StringVar(value="original")
        self.file = queue.Queue()
        self.travail_en_cours = False
        self.annulation = False
        self.dossier_tmp = tempfile.mkdtemp(prefix="bavure_apercu_")
        self.image_tk = None

        self._variables()
        self._construire()
        self.after(80, self._relever_file)
        self.protocol("WM_DELETE_WINDOW", self._quitter)

    # ------------------------------------------------------------------ style
    def _style(self):
        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure(".", background=PANNEAU, foreground=TEXTE, font=POLICE,
                     fieldbackground=CHAMP, bordercolor=FOND, lightcolor=PANNEAU, darkcolor=PANNEAU)
        st.configure("TFrame", background=PANNEAU)
        st.configure("Fond.TFrame", background=FOND)
        st.configure("TLabel", background=PANNEAU, foreground=TEXTE)
        st.configure("Doux.TLabel", foreground=TEXTE_DOUX)
        st.configure("Titre.TLabel", font=POLICE_TITRE, foreground=ACCENT2)
        st.configure("Fond.TLabel", background=FOND, foreground=TEXTE_DOUX)
        st.configure("TCheckbutton", background=PANNEAU, foreground=TEXTE)
        st.map("TCheckbutton", background=[("active", PANNEAU)], indicatorcolor=[("selected", ACCENT)])
        st.configure("TRadiobutton", background=FOND, foreground=TEXTE)
        st.map("TRadiobutton", background=[("active", FOND)], indicatorcolor=[("selected", ACCENT)])
        st.configure("TButton", background=CHAMP, foreground=TEXTE, padding=(10, 5), borderwidth=0)
        st.map("TButton", background=[("active", "#33333d"), ("disabled", PANNEAU)],
               foreground=[("disabled", TEXTE_DOUX)])
        st.configure("Accent.TButton", background=ACCENT, foreground="#ffffff", font=POLICE_TITRE)
        st.map("Accent.TButton", background=[("active", "#ff5c93"), ("disabled", "#5a2a3b")])
        st.configure("TNotebook", background=FOND, borderwidth=0)
        st.configure("TNotebook.Tab", background=FOND, foreground=TEXTE_DOUX, padding=(14, 6))
        st.map("TNotebook.Tab", background=[("selected", PANNEAU)], foreground=[("selected", TEXTE)])
        st.configure("Horizontal.TScale", background=PANNEAU, troughcolor=CHAMP)
        st.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=CHAMP)
        st.configure("TSpinbox", arrowcolor=TEXTE, foreground=TEXTE)
        st.configure("TCombobox", arrowcolor=TEXTE, foreground=TEXTE, background=CHAMP)
        st.map("TCombobox", fieldbackground=[("readonly", CHAMP)], foreground=[("readonly", TEXTE)],
               selectbackground=[("readonly", CHAMP)], selectforeground=[("readonly", TEXTE)])
        self.option_add("*TCombobox*Listbox.background", CHAMP)
        self.option_add("*TCombobox*Listbox.foreground", TEXTE)

    # -------------------------------------------------------------- variables
    def _variables(self):
        m, f = ReglagesMosh(), ReglagesEffets()
        self.v_mosh = {
            "actif": tk.BooleanVar(value=m.actif),
            "supprimer_cles": tk.BooleanVar(value=m.supprimer_cles),
            "debut": tk.DoubleVar(value=0.0),
            "fin": tk.DoubleVar(value=0.0),
            "bloom": tk.BooleanVar(value=m.bloom),
            "bloom_instant": tk.DoubleVar(value=m.bloom_instant),
            "bloom_repetitions": tk.IntVar(value=m.bloom_repetitions),
            "blocs": tk.IntVar(value=m.blocs),
            "databending": tk.IntVar(value=m.databending),
            "graine": tk.IntVar(value=m.graine),
        }
        for k in ("bloom", "bloom_instant"):
            self.v_mosh[k].trace_add("write", lambda *_: self._dessiner_reperes())
        self.v_fx = {k: tk.IntVar(value=0) for k in ("rvb", "tri_pixels", "scanlines", "blocs", "vhs")}
        self.v_fx["tri_vertical"] = tk.BooleanVar(value=False)
        for v in self.v_fx.values():
            v.trace_add("write", lambda *_: self._rafraichir())
        self.v_resolution = tk.StringVar(value="Originale")
        self.v_qualite = tk.StringVar(value="Haute")
        self.v_prereglage = tk.StringVar(value="Choisir…")

    @staticmethod
    def _lire(var, defaut=0):
        try:
            return var.get()
        except tk.TclError:
            return defaut

    def reglages_mosh(self):
        d = {k: self._lire(v) for k, v in self.v_mosh.items()}
        return ReglagesMosh(**d)

    def reglages_fx(self):
        d = {k: self._lire(v) for k, v in self.v_fx.items()}
        return ReglagesEffets(graine=self._lire(self.v_mosh["graine"], 1234), **d)

    # ------------------------------------------------------------ interface
    def _construire(self):
        # Barre du haut
        haut = ttk.Frame(self, style="Fond.TFrame", padding=(12, 10, 12, 4))
        haut.pack(fill="x")
        tk.Label(haut, text="BAVURE", bg=FOND, fg=ACCENT, font=("Segoe UI Black", 16)).pack(side="left")
        tk.Label(haut, text=" datamosh & glitch", bg=FOND, fg=ACCENT2, font=("Segoe UI", 11)).pack(side="left")
        ttk.Button(haut, text="Ouvrir une vidéo…", command=self.ouvrir).pack(side="left", padx=(24, 6))
        self.b_ajouter = ttk.Button(haut, text="+ Ajouter un clip (transition)", command=self.ajouter_clip,
                                    state="disabled")
        self.b_ajouter.pack(side="left", padx=6)
        self.l_clips = ttk.Label(haut, text="Aucune vidéo chargée", style="Fond.TLabel")
        self.l_clips.pack(side="left", padx=12)

        corps = ttk.Frame(self, style="Fond.TFrame", padding=(12, 6, 12, 12))
        corps.pack(fill="both", expand=True)

        # Colonne aperçu
        gauche = ttk.Frame(corps, style="Fond.TFrame")
        gauche.pack(side="left", fill="both", expand=True)
        cadre = tk.Frame(gauche, bg="#000000", width=LARGEUR_APERCU, height=HAUTEUR_APERCU)
        cadre.pack(fill="both", expand=True)
        cadre.pack_propagate(False)
        self.ecran = tk.Label(cadre, bg="#000000", fg=TEXTE_DOUX, font=("Segoe UI", 12),
                              text="Ouvre une vidéo pour commencer\n(MP4, MOV, AVI, MKV…)")
        self.ecran.pack(fill="both", expand=True)

        # Repères des images clés au-dessus de la frise
        self.reperes = tk.Canvas(gauche, height=10, bg=FOND, highlightthickness=0)
        self.reperes.pack(fill="x", pady=(8, 0))
        self.reperes.bind("<Configure>", lambda e: self._dessiner_reperes())

        self.curseur = ttk.Scale(gauche, from_=0, to=1, orient="horizontal", command=self._chercher)
        self.curseur.pack(fill="x")

        ctrl = ttk.Frame(gauche, style="Fond.TFrame")
        ctrl.pack(fill="x", pady=(6, 0))
        self.b_lecture = ttk.Button(ctrl, text="▶ Lecture", command=self.basculer_lecture, width=11)
        self.b_lecture.pack(side="left")
        self.l_temps = ttk.Label(ctrl, text="00:00.00 / 00:00.00", style="Fond.TLabel")
        self.l_temps.pack(side="left", padx=12)
        ttk.Label(ctrl, text="Aperçu :", style="Fond.TLabel").pack(side="left", padx=(20, 4))
        self.r_original = ttk.Radiobutton(ctrl, text="Original", value="original", variable=self.mode,
                                          command=self._changer_mode)
        self.r_original.pack(side="left")
        self.r_mosh = ttk.Radiobutton(ctrl, text="Datamosh", value="mosh", variable=self.mode,
                                      command=self._changer_mode, state="disabled")
        self.r_mosh.pack(side="left", padx=6)
        self.l_info = ttk.Label(ctrl, text="", style="Fond.TLabel")
        self.l_info.pack(side="right")

        # Barre d'état
        etat = ttk.Frame(gauche, style="Fond.TFrame")
        etat.pack(fill="x", pady=(10, 0))
        self.barre = ttk.Progressbar(etat, mode="determinate", maximum=1.0)
        self.barre.pack(side="left", fill="x", expand=True)
        self.b_annuler = ttk.Button(etat, text="Annuler", command=self._annuler, state="disabled")
        self.b_annuler.pack(side="left", padx=(8, 0))
        self.l_etat = ttk.Label(gauche, text="Prêt.", style="Fond.TLabel")
        self.l_etat.pack(anchor="w", pady=(4, 0))

        # Colonne réglages
        droite = ttk.Frame(corps, style="Fond.TFrame", width=360)
        droite.pack(side="right", fill="y", padx=(14, 0))
        droite.pack_propagate(False)

        pre = ttk.Frame(droite, style="Fond.TFrame")
        pre.pack(fill="x", pady=(0, 8))
        ttk.Label(pre, text="Préréglage", style="Fond.TLabel").pack(side="left")
        cb = ttk.Combobox(pre, textvariable=self.v_prereglage, values=list(PREREGLAGES), state="readonly")
        cb.pack(side="left", fill="x", expand=True, padx=(8, 0))
        cb.bind("<<ComboboxSelected>>", lambda e: self.appliquer_prereglage())

        onglets = ttk.Notebook(droite)
        onglets.pack(fill="both", expand=True)
        onglets.add(self._onglet_mosh(onglets), text="Datamosh")
        onglets.add(self._onglet_glitch(onglets), text="Glitchs")
        onglets.add(self._onglet_export(onglets), text="Export")

        self.bind("<space>", lambda e: self.basculer_lecture())

    # -- petites briques d'interface
    def _curseur(self, parent, texte, var, de, a, aide=None):
        ligne = ttk.Frame(parent)
        ligne.pack(fill="x", pady=(6, 0))
        ttk.Label(ligne, text=texte).pack(side="left")
        val = ttk.Label(ligne, text=str(var.get()), style="Doux.TLabel", width=4, anchor="e")
        val.pack(side="right")
        sc = ttk.Scale(parent, from_=de, to=a, orient="horizontal",
                       command=lambda x: (var.set(int(float(x))), val.config(text=str(int(float(x))))))
        sc.set(var.get())
        sc.pack(fill="x")
        var.trace_add("write", lambda *_: (sc.set(self._lire(var)), val.config(text=str(self._lire(var)))))
        if aide:
            ttk.Label(parent, text=aide, style="Doux.TLabel", wraplength=310, font=("Segoe UI", 8)).pack(anchor="w")
        return sc

    def _champ_temps(self, parent, texte, var):
        ligne = ttk.Frame(parent)
        ligne.pack(fill="x", pady=(4, 0))
        ttk.Label(ligne, text=texte, width=18).pack(side="left")
        ttk.Spinbox(ligne, textvariable=var, from_=0, to=99999, increment=0.1, width=8).pack(side="left")
        ttk.Button(ligne, text="Position actuelle", command=lambda: var.set(round(self._temps(), 2))
                   ).pack(side="left", padx=6)

    def _onglet_mosh(self, parent):
        f = ttk.Frame(parent, padding=12)
        ttk.Checkbutton(f, text="Activer le datamosh", variable=self.v_mosh["actif"]).pack(anchor="w")

        ttk.Label(f, text="Supprimer les images clés", style="Titre.TLabel").pack(anchor="w", pady=(12, 0))
        ttk.Checkbutton(f, text="Faire baver l'image aux changements de plan",
                        variable=self.v_mosh["supprimer_cles"]).pack(anchor="w")
        self._champ_temps(f, "Début (s)", self.v_mosh["debut"])
        self._champ_temps(f, "Fin (s) (0 = la fin)", self.v_mosh["fin"])
        self.l_cles = ttk.Label(f, text="Images clés : calcule un aperçu pour les voir",
                                style="Doux.TLabel", wraplength=320, font=("Segoe UI", 8))
        self.l_cles.pack(anchor="w", pady=(4, 0))

        ttk.Label(f, text="Bloom (le mouvement se répète)", style="Titre.TLabel").pack(anchor="w", pady=(12, 0))
        ttk.Checkbutton(f, text="Activer le bloom", variable=self.v_mosh["bloom"]).pack(anchor="w")
        self._champ_temps(f, "Instant (s)", self.v_mosh["bloom_instant"])
        self._curseur(f, "Répétitions", self.v_mosh["bloom_repetitions"], 1, 200)

        ttk.Label(f, text="Texture", style="Titre.TLabel").pack(anchor="w", pady=(12, 0))
        self._curseur(f, "Taille des blocs", self.v_mosh["blocs"], 1, 31, "1 = net, 31 = très pixelisé")
        self._curseur(f, "Databending", self.v_mosh["databending"], 0, 100,
                      "Corrompt des octets au hasard. Au-delà de 60, résultat très imprévisible.")

        graine = ttk.Frame(f)
        graine.pack(fill="x", pady=(10, 0))
        ttk.Label(graine, text="Graine du hasard").pack(side="left")
        ttk.Spinbox(graine, textvariable=self.v_mosh["graine"], from_=0, to=999999, width=8).pack(side="left", padx=6)
        ttk.Button(graine, text="🎲", width=3,
                   command=lambda: self.v_mosh["graine"].set(random.randint(0, 999999))).pack(side="left")

        self.b_apercu = ttk.Button(f, text="Calculer l'aperçu datamosh", style="Accent.TButton",
                                   command=self.calculer_apercu, state="disabled")
        self.b_apercu.pack(fill="x", pady=(16, 0))
        return f

    def _onglet_glitch(self, parent):
        f = ttk.Frame(parent, padding=12)
        ttk.Label(f, text="Visibles en direct dans l'aperçu", style="Doux.TLabel").pack(anchor="w")
        self._curseur(f, "Décalage RVB", self.v_fx["rvb"], 0, 100)
        self._curseur(f, "Tri de pixels", self.v_fx["tri_pixels"], 0, 100,
                      "Trie les pixels par luminosité dans les zones claires.")
        ttk.Checkbutton(f, text="Trier verticalement", variable=self.v_fx["tri_vertical"]).pack(anchor="w")
        self._curseur(f, "Scanlines", self.v_fx["scanlines"], 0, 100)
        self._curseur(f, "Blocs déplacés", self.v_fx["blocs"], 0, 100)
        self._curseur(f, "Cassette VHS", self.v_fx["vhs"], 0, 100,
                      "Bavure de couleur, bruit, ondulation, bande de tracking.")
        ttk.Button(f, text="Tout remettre à zéro", command=self._raz_fx).pack(fill="x", pady=(16, 0))
        return f

    def _onglet_export(self, parent):
        f = ttk.Frame(parent, padding=12)
        ttk.Label(f, text="Résolution", style="Titre.TLabel").pack(anchor="w")
        ttk.Combobox(f, textvariable=self.v_resolution, state="readonly",
                     values=["Originale", "1920 (1080p)", "1280 (720p)", "854 (480p)"]).pack(fill="x", pady=4)
        ttk.Label(f, text="Qualité du fichier", style="Titre.TLabel").pack(anchor="w", pady=(12, 0))
        ttk.Combobox(f, textvariable=self.v_qualite, state="readonly",
                     values=["Haute", "Moyenne", "Légère"]).pack(fill="x", pady=4)
        ttk.Label(f, text="Le son de la vidéo d'origine est conservé quand un seul clip est chargé.",
                  style="Doux.TLabel", wraplength=320, font=("Segoe UI", 8)).pack(anchor="w", pady=(10, 0))
        self.b_export = ttk.Button(f, text="Exporter en MP4…", style="Accent.TButton",
                                   command=self.exporter, state="disabled")
        self.b_export.pack(fill="x", pady=(18, 0))
        return f

    # ------------------------------------------------------------- fichiers
    def ouvrir(self):
        chemin = filedialog.askopenfilename(title="Choisir une vidéo", filetypes=[
            ("Vidéos", "*.mp4 *.mov *.avi *.mkv *.m4v *.webm *.wmv *.mts *.mpg"), ("Tous les fichiers", "*.*")])
        if not chemin:
            return
        self.charger([chemin])

    def ajouter_clip(self):
        chemin = filedialog.askopenfilename(title="Clip à enchaîner (la transition bavera dessus)",
                                            filetypes=[("Vidéos", "*.mp4 *.mov *.avi *.mkv *.m4v *.webm *.wmv"),
                                                       ("Tous les fichiers", "*.*")])
        if chemin:
            self.charger(self.sources + [chemin])

    def charger(self, sources):
        try:
            infos = [infos_video(s) for s in sources]
        except Exception as e:
            messagebox.showerror("Bavure", str(e))
            return
        self.sources = sources
        self.apercus = {}
        self.cles = []
        self.mode.set("original")
        self.r_mosh.config(state="disabled")
        noms = " + ".join(os.path.basename(s) for s in sources)
        duree = sum(i["duree"] for i in infos)
        self.l_clips.config(text=f"{noms}   ·   {format_temps(duree)}")
        i0 = infos[0]
        self.l_info.config(text=f"{i0['largeur']}×{i0['hauteur']} · {i0['fps']:.2f} i/s"
                                + ("" if i0["audio"] else " · sans son"))
        for b in (self.b_ajouter, self.b_apercu, self.b_export):
            b.config(state="normal")
        self.l_cles.config(text="Images clés : calcule un aperçu pour les voir")
        self.v_mosh["bloom_instant"].set(round(min(1.0, duree / 3), 2))
        if len(sources) == 1:
            self.apercus["original"] = sources[0]
            self._ouvrir_lecteur(sources[0])
        else:
            # Plusieurs clips : on prépare un assemblage pour l'aperçu « Original »
            self._lancer_travail("assemblage")

    # --------------------------------------------------------------- lecteur
    def _ouvrir_lecteur(self, chemin, garder_position=False):
        ancienne = self._temps() if garder_position else 0
        if self.cap:
            self.cap.release()
        self.cap = cv2.VideoCapture(chemin)
        self.fichier_affiche = chemin
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 25.0
        self.nb_images = max(1, int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)))
        self.curseur.config(to=self.nb_images - 1)
        self.aller_a(min(self.nb_images - 1, int(ancienne * self.fps)))
        self._dessiner_reperes()

    def _temps(self):
        return self.position / self.fps if self.fps else 0

    def aller_a(self, n):
        if not self.cap:
            return
        self.position = int(n)
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.position)
        ok, img = self.cap.read()
        if ok:
            self.image_brute = img
            self._afficher(img)

    def _chercher(self, valeur):
        if self.maj_curseur:
            return
        self.aller_a(float(valeur))

    def _afficher(self, img):
        h, w = img.shape[:2]
        lw = max(100, self.ecran.winfo_width())
        lh = max(100, self.ecran.winfo_height())
        k = min(lw / w, lh / h)
        petite = cv2.resize(img, (max(2, int(w * k)), max(2, int(h * k))), interpolation=cv2.INTER_AREA)
        petite = appliquer(petite, self.reglages_fx(), self.position)
        self.image_tk = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(petite, cv2.COLOR_BGR2RGB)))
        self.ecran.config(image=self.image_tk, text="")
        self.maj_curseur = True
        self.curseur.set(self.position)
        self.maj_curseur = False
        self.l_temps.config(text=f"{format_temps(self._temps())} / {format_temps(self.nb_images / self.fps)}")

    def _rafraichir(self):
        if self.cap is not None and not self.lecture and hasattr(self, "image_brute"):
            self._afficher(self.image_brute)

    def basculer_lecture(self):
        if not self.cap:
            return
        self.lecture = not self.lecture
        self.b_lecture.config(text="❚❚ Pause" if self.lecture else "▶ Lecture")
        if self.lecture:
            if self.position >= self.nb_images - 1:
                self.aller_a(0)
            self._t0 = time.perf_counter()
            self._n0 = self.position
            self._jouer()

    def _jouer(self):
        if not self.lecture or not self.cap:
            return
        cible = self._n0 + int((time.perf_counter() - self._t0) * self.fps)
        # si l'ordinateur est en retard (effets lourds), on saute des images
        while self.position < cible - 1:
            if not self.cap.grab():
                break
            self.position += 1
        ok, img = self.cap.read()
        if not ok:
            self.basculer_lecture()
            return
        self.position += 1
        self.image_brute = img
        self._afficher(img)
        delai = int(max(1, (self._t0 + (self.position - self._n0) / self.fps - time.perf_counter()) * 1000))
        self.after(delai, self._jouer)

    def _changer_mode(self):
        chemin = self.apercus.get(self.mode.get())
        if chemin:
            self._ouvrir_lecteur(chemin, garder_position=True)

    def _dessiner_reperes(self):
        c = self.reperes
        c.delete("all")
        if not self.cles or not self.nb_images:
            return
        w = c.winfo_width()
        duree = self.nb_images / self.fps
        for t in self.cles[1:]:
            x = 8 + (w - 16) * min(1, t / duree)
            c.create_rectangle(x - 1, 1, x + 1, 10, fill=ACCENT, outline="")
        r = self.reglages_mosh()
        if r.bloom:
            x = 8 + (w - 16) * min(1, r.bloom_instant / duree)
            c.create_oval(x - 4, 1, x + 4, 9, fill=ACCENT2, outline="")

    # ------------------------------------------------------------ réglages
    def _raz_fx(self):
        for k, v in self.v_fx.items():
            v.set(False if k == "tri_vertical" else 0)

    def appliquer_prereglage(self):
        p = PREREGLAGES.get(self.v_prereglage.get())
        if not p:
            return
        defaut_m = asdict(ReglagesMosh())
        for k, v in self.v_mosh.items():
            if k in ("debut", "fin", "bloom_instant", "graine"):
                continue
            v.set(p["mosh"].get(k, defaut_m[k]))
        self._raz_fx()
        for k, val in p["fx"].items():
            self.v_fx[k].set(val)
        self.etat("Préréglage appliqué. Calcule l'aperçu datamosh pour voir le résultat.")

    # -------------------------------------------------------- travaux longs
    def calculer_apercu(self):
        self._lancer_travail("mosh")

    def exporter(self):
        base = os.path.splitext(os.path.basename(self.sources[0]))[0]
        chemin = filedialog.asksaveasfilename(title="Enregistrer la vidéo", defaultextension=".mp4",
                                              initialfile=f"{base}_bavure.mp4",
                                              filetypes=[("Vidéo MP4", "*.mp4")])
        if chemin:
            self._lancer_travail("export", chemin)

    def _lancer_travail(self, nature, chemin=None):
        if self.travail_en_cours:
            return
        if self.lecture:
            self.basculer_lecture()
        self.travail_en_cours = True
        self.annulation = False
        for b in (self.b_apercu, self.b_export, self.b_ajouter):
            b.config(state="disabled")
        self.b_annuler.config(state="normal")
        sources = list(self.sources)
        mosh = self.reglages_mosh()
        fx = self.reglages_fx()
        largeur = {"Originale": None, "1920 (1080p)": 1920, "1280 (720p)": 1280,
                   "854 (480p)": 854}[self.v_resolution.get()]
        crf = {"Haute": 17, "Moyenne": 21, "Légère": 26}[self.v_qualite.get()]

        def tache():
            retour = {}
            try:
                prog = lambda f, m: self.file.put(("progression", f, m))
                if nature == "assemblage":
                    sortie = os.path.join(self.dossier_tmp, f"original_{time.time_ns()}.mp4")
                    rendre(sources, sortie, ReglagesMosh(actif=False), ReglagesEffets(), largeur_max=854,
                           qualite=23, progression=prog, annuler=lambda: self.annulation)
                elif nature == "mosh":
                    sortie = os.path.join(self.dossier_tmp, f"mosh_{time.time_ns()}.mp4")
                    rendre(sources, sortie, mosh, ReglagesEffets(), largeur_max=854, qualite=23,
                           progression=prog, annuler=lambda: self.annulation, retour=retour)
                else:
                    sortie = rendre(sources, chemin, mosh, fx, largeur_max=largeur, qualite=crf,
                                    progression=prog, annuler=lambda: self.annulation)
                self.file.put(("fini", nature, sortie, retour))
            except Annule:
                self.file.put(("annule",))
            except Exception as e:
                self.file.put(("erreur", str(e)))

        threading.Thread(target=tache, daemon=True).start()

    def _relever_file(self):
        try:
            while True:
                msg = self.file.get_nowait()
                if msg[0] == "progression":
                    self.barre["value"] = msg[1]
                    self.etat(msg[2])
                elif msg[0] == "fini":
                    self._fin_travail()
                    _, nature, sortie, retour = msg
                    if nature == "assemblage":
                        self.apercus["original"] = sortie
                        self._ouvrir_lecteur(sortie)
                        self.etat("Clips assemblés. Prêt.")
                    elif nature == "mosh":
                        self.apercus["mosh"] = sortie
                        self.cles = retour.get("cles", [])
                        n = max(0, len(self.cles) - 1)
                        self.l_cles.config(text=(f"{n} image(s) clé(s) après le début : "
                                                 + ", ".join(f"{t:.2f} s" for t in self.cles[1:12])
                                                 + (" …" if n > 11 else "")) if n else
                                           "Aucune image clé après le début (pas de changement de plan "
                                           "détecté) : utilise plutôt le bloom ou ajoute un 2e clip.")
                        self.r_mosh.config(state="normal")
                        self.mode.set("mosh")
                        self._ouvrir_lecteur(sortie, garder_position=True)
                        self.etat("Aperçu datamosh prêt (basse résolution). Les glitchs s'appliquent en direct.")
                    else:
                        self.etat(f"Exporté : {sortie}")
                        if messagebox.askyesno("Bavure", "Export terminé. Ouvrir le dossier ?"):
                            self._ouvrir_dossier(os.path.dirname(sortie))
                elif msg[0] == "annule":
                    self._fin_travail()
                    self.etat("Annulé.")
                elif msg[0] == "erreur":
                    self._fin_travail()
                    self.etat("Erreur.")
                    messagebox.showerror("Bavure", msg[1])
        except queue.Empty:
            pass
        self.after(80, self._relever_file)

    def _fin_travail(self):
        self.travail_en_cours = False
        self.barre["value"] = 0
        self.b_annuler.config(state="disabled")
        for b in (self.b_apercu, self.b_export, self.b_ajouter):
            b.config(state="normal" if self.sources else "disabled")

    def _annuler(self):
        self.annulation = True
        self.etat("Annulation…")

    def etat(self, texte):
        self.l_etat.config(text=texte)

    @staticmethod
    def _ouvrir_dossier(dossier):
        try:
            os.startfile(dossier)  # Windows
        except AttributeError:
            pass

    def _quitter(self):
        self.lecture = False
        self.annulation = True
        if self.cap:
            self.cap.release()
        import shutil
        shutil.rmtree(self.dossier_tmp, ignore_errors=True)
        self.destroy()


def main():
    try:  # netteté de l'affichage sur les écrans haute densité (Windows)
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    Bavure().mainloop()


if __name__ == "__main__":
    main()
