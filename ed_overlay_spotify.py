import sys
import os
import time
import glob
import json
import random
import threading
import ctypes
import tkinter as tk
import keyboard
from PIL import Image, ImageTk
import io
from spotify_manager import SpotifyManager
from playlist_config import carregar_config
from config_window import JanelaConfigPlaylists

# ----------------------------------------------------------------------
# DETECÇÃO DE CAMINHO PARA EXECUTÁVEL EMBUTIDO (.EXE)
# ----------------------------------------------------------------------
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(__file__)

GAME_WINDOW_TITLE = "Elite - Dangerous"

USER_PROFILE = os.environ.get("USERPROFILE", "")
JOURNAL_DIR = os.path.join(
    USER_PROFILE, "Saved Games", "Frontier Developments", "Elite Dangerous"
)

HUD_STATE_PATH = os.path.join(BASE_DIR, "hud_estado.json")

# Cor de destaque (moldura + rótulo de estado) por estado do jogo.
# NORMAL mantém o laranja clássico do HUD do Elite; os demais usam cores
# com significado (combate = vermelho, supercruise = azul, etc.) para dar
# uma pista visual do estado sem precisar ler o texto.
ESTADO_CORES = {
    "NORMAL": "#FF7700",
    "SUPERCRUISE": "#3FA9F5",
    "COMBAT": "#E24B4A",
    "DOCKED": "#5DCAA5",
    "PLANETARY": "#C08A3E",
    "SRV": "#C08A3E",
    "ONFOOT": "#B39DDB",
    "ONFOOT_COMBAT": "#E24B4A",
}

# O mapeamento estado -> playlist do Spotify agora é escolhido pelo usuário
# pela janela de configuração (Alt+F7 ou botão ⚙) e persistido em
# playlists_config.json (ver playlist_config.py). Não há mais URIs fixas aqui.


def carregar_estado_hud():
    """Lê posição/escala salvas do HUD (hud_estado.json). Retorna {} se não
    existir ou estiver corrompido, e quem chamar aplica os padrões."""
    if os.path.exists(HUD_STATE_PATH):
        try:
            with open(HUD_STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[HUD] Erro ao ler hud_estado.json: {e}")
    return {}


def salvar_estado_hud(dados):
    try:
        with open(HUD_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[HUD] Erro ao salvar hud_estado.json: {e}")


def is_game_active():
    """Verifica se a janela do Elite Dangerous está ativa."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        return GAME_WINDOW_TITLE.lower() in buff.value.lower()
    except Exception:
        return False

class EliteAudioHUD:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("ED_HUD_AUDIO")

        # Dimensões base (escala 1.0). O HUD inteiro escala a partir daqui:
        # fontes, capa, espessura das barras — tudo junto, não só a janela.
        self.BASE_LARGURA = 320
        self.BASE_ALTURA = 124
        POS_Y_PADRAO = 15

        estado_salvo = carregar_estado_hud()
        self.escala = float(estado_salvo.get("escala", 1.0))

        largura_tela = self.root.winfo_screenwidth()
        largura_inicial = int(self.BASE_LARGURA * self.escala)
        altura_inicial = int(self.BASE_ALTURA * self.escala)
        pos_x_padrao = (largura_tela // 2) - (largura_inicial // 2)

        pos_x = int(estado_salvo.get("x", pos_x_padrao))
        pos_y = int(estado_salvo.get("y", POS_Y_PADRAO))

        self.root.geometry(f"{largura_inicial}x{altura_inicial}+{pos_x}+{pos_y}")
        self.root.overrideredirect(True)
        self.root.wm_attributes("-topmost", True)
        self.root.wm_attributes("-alpha", 0.88)

        # Cores HUD
        self.COLOR_BG = "#080B10"
        self.COLOR_BORDER = "#B35300"
        self.COLOR_ORANGE = "#FF7700"
        self.COLOR_YELLOW = "#FFB400"
        self.COLOR_DARK = "#121721"

        self.root.configure(bg=self.COLOR_BG)

        # Variáveis do Motor de Áudio
        self.estado_atual = "NORMAL"
        self.ultimo_journal = None
        self.file_position = 0
        self.hud_visivel = True
        self.pausado_manualmente = False
        self.volume_atual = 70

        # Integração com Spotify (conecta em thread separada, sem travar a UI)
        self.spotify = None
        self._volume_timer = None
        self.playlists_config = carregar_config()
        threading.Thread(target=self._conectar_spotify_thread, daemon=True).start()

        # Capa do álbum (miniatura) — TAM_CAPA é recalculado em aplicar_escala()
        self.TAM_CAPA = 40
        self._ultima_capa_url = None
        self._capa_photoimage = None  # mantém referência viva (senão o Tkinter descarta a imagem)

        # Variáveis de Movimentação (Arrastar)
        self._drag_start_x = 0
        self._drag_start_y = 0

        # Texto da faixa atual (título + artista, exibidos em duas linhas)
        self.texto_titulo = "Aguardando dados de voo..."
        self.texto_artista = ""
        self.marquee_offset = 0

        # Progresso da faixa atual, para a barrinha abaixo do texto.
        # progress_ms/duration_ms vêm do último poll ao Spotify; entre polls,
        # animar_progresso() interpola pelo tempo decorrido, então a barra
        # anda suavemente em vez de pular a cada 5s.
        self._progress_ms = 0
        self._duration_ms = 0
        self._progress_last_ts = None
        self._tocando = False

        # Equalizador com decaimento suave (ver animar_equalizador)
        self._eq_num_barras = 22
        self._eq_alturas = [1.0] * self._eq_num_barras

        # Camada de fundo onde a moldura chanfrada é desenhada, e o frame de
        # conteúdo por cima (com um pequeno recuo para a moldura aparecer).
        self.canvas_moldura = tk.Canvas(self.root, bg=self.COLOR_BG, highlightthickness=0)
        self.canvas_moldura.place(x=0, y=0, relwidth=1, relheight=1)

        self.main_frame = tk.Frame(self.root, bg=self.COLOR_BG)
        self.main_frame.place(x=3, y=3, relwidth=1, relheight=1, width=-6, height=-6)

        # 1. Rótulo de Estado
        self.lbl_estado = tk.Label(
            self.main_frame,
            text="[ COCKPIT AUDIO: ONLINE ]",
            font=("Consolas", 8, "bold"),
            fg=self.COLOR_ORANGE,
            bg=self.COLOR_BG,
            anchor="center"
        )
        self.lbl_estado.pack(fill="x", padx=4, pady=(4, 1))

        # 2. Capa do álbum + texto da faixa (título em cima, artista embaixo)
        self.frame_musica = tk.Frame(self.main_frame, bg=self.COLOR_BG)
        self.frame_musica.pack(fill="x", padx=6, pady=1)

        self.lbl_capa = tk.Label(self.frame_musica, bg=self.COLOR_DARK)
        self.lbl_capa.pack(side="left", padx=(0, 6))

        self.frame_textos = tk.Frame(self.frame_musica, bg=self.COLOR_BG)
        self.frame_textos.pack(side="left", fill="both", expand=True)

        self.lbl_titulo = tk.Label(
            self.frame_textos,
            text=self.texto_titulo,
            font=("Consolas", 9, "bold"),
            fg=self.COLOR_YELLOW,
            bg=self.COLOR_BG,
            anchor="w"
        )
        self.lbl_titulo.pack(fill="x")

        self.lbl_artista = tk.Label(
            self.frame_textos,
            text=self.texto_artista,
            font=("Consolas", 8),
            fg="#8A6A2A",
            bg=self.COLOR_BG,
            anchor="w"
        )
        self.lbl_artista.pack(fill="x")

        # 3. Barra de progresso da faixa (dado real, não decorativo)
        self.canvas_progresso = tk.Canvas(
            self.main_frame, height=3, bg=self.COLOR_DARK, highlightthickness=0
        )
        self.canvas_progresso.pack(fill="x", padx=10, pady=(4, 2))

        # 4. Canvas do Equalizador VFD
        self.canvas_eq = tk.Canvas(
            self.main_frame, height=14, bg=self.COLOR_DARK, highlightthickness=0
        )
        self.canvas_eq.pack(fill="x", padx=10, pady=3)

        # 5. Painel de Controles
        self.frame_ctrl = tk.Frame(self.main_frame, bg=self.COLOR_BG)
        self.frame_ctrl.pack(fill="x", padx=8, pady=(1, 4))

        self.btn_prev = self._criar_botao(self.frame_ctrl, "⏮", self.musica_anterior)
        self.btn_prev.pack(side="left", padx=1)

        self.btn_play_pause = self._criar_botao(self.frame_ctrl, "❚❚", self.toggle_play_pause, largura=4)
        self.btn_play_pause.pack(side="left", padx=2)

        self.btn_next = self._criar_botao(self.frame_ctrl, "⏭", self.proxima_musica)
        self.btn_next.pack(side="left", padx=1)

        self.btn_config = self._criar_botao(self.frame_ctrl, "⚙", self.abrir_config_playlists)
        self.btn_config.pack(side="left", padx=1)

        self.scale_vol = tk.Scale(
            self.frame_ctrl, from_=0, to=100, orient="horizontal",
            showvalue=0, bg=self.COLOR_BG, fg=self.COLOR_ORANGE,
            troughcolor=self.COLOR_DARK, activebackground=self.COLOR_ORANGE,
            bd=0, highlightthickness=0, command=self.ajustar_volume
        )
        self.scale_vol.set(70)
        self.scale_vol.pack(side="right", fill="x", expand=True, padx=(8, 0))

        # Placeholder da capa (reserva o espaço visual até a primeira faixa carregar)
        self._exibir_capa_no_label(Image.new("RGB", (self.TAM_CAPA, self.TAM_CAPA), self.COLOR_DARK))

        self.configurar_arrasto()
        self.registrar_atalhos()

        # Aplica a escala carregada a fontes/tamanhos e desenha a moldura.
        # salvar=False porque isso é só sincronizar a UI com o que já foi lido do disco.
        self.aplicar_escala(salvar=False)
        self.root.bind("<Configure>", lambda e: self.desenhar_moldura())

        # Threads
        self.thread_log = threading.Thread(target=self.loop_principal, daemon=True)
        self.thread_log.start()

        # Animações
        self.animar_marquee()
        self.animar_equalizador()
        self.animar_progresso()

    # -------------------------------------------------------------
    # MOLDURA CHANFRADA E ESCALA
    # -------------------------------------------------------------
    def _cor_estado(self):
        return ESTADO_CORES.get(self.estado_atual, self.COLOR_ORANGE)

    def desenhar_moldura(self):
        """Desenha a moldura com cantos chanfrados no canvas de fundo,
        na cor do estado atual. Chamado na criação, ao trocar de estado
        e a cada redimensionamento (via <Configure>)."""
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        if w < 20 or h < 20:
            return
        c = max(6, round(10 * self.escala))  # tamanho do chanfro
        cor = self._cor_estado()
        pontos = [
            c, 0, w - c, 0, w, c, w, h - c,
            w - c, h, c, h, 0, h - c, 0, c,
        ]
        self.canvas_moldura.delete("moldura")
        self.canvas_moldura.create_polygon(
            pontos, outline=cor, fill=self.COLOR_BG, width=1, tags="moldura"
        )

    def _criar_botao(self, parent, texto, comando, largura=3):
        """Botão 'falso' feito com Label — visualmente consistente com o
        resto do HUD (os tk.Button nativos do Windows destoam do estilo)."""
        lbl = tk.Label(
            parent, text=texto, font=("Consolas", 8, "bold"),
            fg=self.COLOR_ORANGE, bg=self.COLOR_DARK,
            width=largura, cursor="hand2", padx=2, pady=1,
        )
        lbl.bind("<Button-1>", lambda e: comando())
        lbl.bind("<Enter>", lambda e: lbl.config(bg=self.COLOR_BORDER))
        lbl.bind("<Leave>", lambda e: lbl.config(bg=self.COLOR_DARK))
        return lbl

    def aplicar_escala(self, salvar=True):
        """Recalcula geometria, fontes, capa e espessuras a partir de
        self.escala, tudo junto — diferente da versão antiga, que só
        esticava a janela e deixava o conteúdo do mesmo tamanho."""
        largura = int(self.BASE_LARGURA * self.escala)
        altura = int(self.BASE_ALTURA * self.escala)
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        self.root.geometry(f"{largura}x{altura}+{x}+{y}")

        f_estado = max(7, round(8 * self.escala))
        f_titulo = max(8, round(9 * self.escala))
        f_artista = max(7, round(8 * self.escala))
        f_botao = max(7, round(8 * self.escala))

        self.lbl_estado.config(font=("Consolas", f_estado, "bold"))
        self.lbl_titulo.config(font=("Consolas", f_titulo, "bold"))
        self.lbl_artista.config(font=("Consolas", f_artista))
        for btn in (self.btn_prev, self.btn_play_pause, self.btn_next, self.btn_config):
            btn.config(font=("Consolas", f_botao, "bold"))

        self.TAM_CAPA = max(28, round(40 * self.escala))
        self.canvas_eq.config(height=max(10, round(14 * self.escala)))
        self.canvas_progresso.config(height=max(2, round(3 * self.escala)))

        # Espera o geometry() acima ser processado antes de medir a janela
        self.root.after(20, self.desenhar_moldura)

        if salvar:
            self.salvar_estado_hud()

    def salvar_estado_hud(self):
        salvar_estado_hud({
            "x": self.root.winfo_x(),
            "y": self.root.winfo_y(),
            "escala": self.escala,
        })

    # -------------------------------------------------------------
    # EVENTOS PARA MOVER E REDIMENSIONAR O HUD
    # -------------------------------------------------------------
    def configurar_arrasto(self):
        """Permite que o usuário clique em qualquer lugar do HUD e o mova."""
        componentes = [
            self.root, self.main_frame, self.lbl_estado, self.frame_musica,
            self.lbl_capa, self.frame_textos, self.lbl_titulo, self.lbl_artista,
            self.canvas_eq, self.canvas_progresso, self.frame_ctrl,
        ]
        for comp in componentes:
            comp.bind("<Button-1>", self._start_drag)
            comp.bind("<B1-Motion>", self._on_drag)
            comp.bind("<ButtonRelease-1>", self._end_drag)

    def _start_drag(self, event):
        self._drag_start_x = event.x
        self._drag_start_y = event.y

    def _on_drag(self, event):
        x = self.root.winfo_x() + (event.x - self._drag_start_x)
        y = self.root.winfo_y() + (event.y - self._drag_start_y)
        self.root.geometry(f"+{x}+{y}")

    def _end_drag(self, event):
        self.salvar_estado_hud()

    def aumentar_tamanho_hud(self):
        """Aumenta a escala do HUD (fontes, capa e barras juntas)."""
        self.escala = min(2.0, round(self.escala + 0.1, 2))
        self.aplicar_escala()

    def diminuir_tamanho_hud(self):
        """Diminui a escala do HUD (fontes, capa e barras juntas)."""
        self.escala = max(0.6, round(self.escala - 0.1, 2))
        self.aplicar_escala()

    # -------------------------------------------------------------
    # ANIMAÇÕES VISUAIS
    # -------------------------------------------------------------
    def _max_chars_titulo(self):
        """Quantos caracteres cabem confortavelmente no título, dada a
        escala atual. Aproximado (fonte não é monoespaçada em todos os
        tamanhos), mas suficiente pra decidir entre estático/ellipsis/scroll."""
        return max(10, round(22 * self.escala))

    def animar_marquee(self):
        max_chars = self._max_chars_titulo()
        texto = self.texto_titulo

        if len(texto) <= max_chars:
            # Cabe inteiro: mostra parado, sem cortar nada.
            self.lbl_titulo.config(text=texto)
        elif len(texto) <= max_chars * 1.4:
            # Passa só um pouco: corta com "…" em vez de rolar — rolar um
            # texto quase do tamanho certo incomoda mais do que ajuda.
            self.lbl_titulo.config(text=texto[:max_chars - 1] + "…")
        else:
            # Bem maior que o espaço: aí sim vale a pena rolar.
            display_text = texto + "   •   "
            self.marquee_offset = (self.marquee_offset + 1) % len(display_text)
            girado = display_text[self.marquee_offset:] + display_text[:self.marquee_offset]
            self.lbl_titulo.config(text=girado[:max_chars])

        max_chars_artista = max_chars + 6
        artista = self.texto_artista
        if len(artista) > max_chars_artista:
            artista = artista[:max_chars_artista - 1] + "…"
        self.lbl_artista.config(text=artista)

        self.root.after(250, self.animar_marquee)

    def animar_equalizador(self):
        self.canvas_eq.delete("all")

        num_barras = self._eq_num_barras
        largura_canvas = self.canvas_eq.winfo_width()
        if largura_canvas <= 1:
            largura_canvas = int(300 * self.escala)

        altura_canvas = max(10, round(14 * self.escala))
        altura_max = max(2, altura_canvas - 2)
        largura_barra = (largura_canvas / num_barras) - 2
        tocando = self._tocando and self.spotify is not None

        cor_ativa = self._cor_estado()

        for i in range(num_barras):
            alvo = random.randint(2, altura_max) if tocando else 1
            # Decaimento suave: a barra persegue o alvo em vez de saltar
            # direto nele — evita o efeito "chuvisco de TV" do random puro.
            atual = self._eq_alturas[i] + (alvo - self._eq_alturas[i]) * 0.4
            self._eq_alturas[i] = atual
            altura = max(1, atual)

            x0 = i * (largura_barra + 2) + 2
            y0 = altura_canvas - altura
            x1 = x0 + largura_barra
            y1 = altura_canvas

            if not tocando:
                cor = "#2A1800"
            else:
                cor = cor_ativa if altura > altura_max * 0.65 else self.COLOR_BORDER

            self.canvas_eq.create_rectangle(x0, y0, x1, y1, fill=cor, width=0)

        self.root.after(80, self.animar_equalizador)

    def animar_progresso(self):
        self.canvas_progresso.delete("all")
        largura = self.canvas_progresso.winfo_width()
        if largura <= 1:
            largura = int(280 * self.escala)
        altura = max(2, round(3 * self.escala))

        self.canvas_progresso.create_rectangle(0, 0, largura, altura, fill=self.COLOR_DARK, width=0)

        if self._duration_ms:
            decorrido_extra = 0
            if self._tocando and self._progress_last_ts:
                decorrido_extra = (time.time() - self._progress_last_ts) * 1000
            atual_ms = min(self._duration_ms, self._progress_ms + decorrido_extra)
            fracao = max(0.0, min(1.0, atual_ms / self._duration_ms))
            if fracao > 0:
                self.canvas_progresso.create_rectangle(
                    0, 0, largura * fracao, altura, fill=self._cor_estado(), width=0
                )

        self.root.after(500, self.animar_progresso)

    # -------------------------------------------------------------
    # REGISTRO DE ATALHOS
    # -------------------------------------------------------------
    def registrar_atalhos(self):
        try:
            keyboard.add_hotkey("alt+f9", lambda: self.root.after(0, self.toggle_play_pause))
            keyboard.add_hotkey("alt+f10", lambda: self.root.after(0, self.proxima_musica))
            keyboard.add_hotkey("alt+f11", lambda: self.root.after(0, self.musica_anterior))
            keyboard.add_hotkey("alt+up", lambda: self.root.after(0, self.aumentar_volume))
            keyboard.add_hotkey("alt+down", lambda: self.root.after(0, self.diminuir_volume))
            keyboard.add_hotkey("alt+f7", lambda: self.root.after(0, self.abrir_config_playlists))
            
            # Novos Atalhos para Redimensionar o HUD
            keyboard.add_hotkey("alt++", lambda: self.root.after(0, self.aumentar_tamanho_hud))
            keyboard.add_hotkey("alt+=", lambda: self.root.after(0, self.aumentar_tamanho_hud))
            keyboard.add_hotkey("alt+-", lambda: self.root.after(0, self.diminuir_tamanho_hud))
        except Exception:
            pass

    def aumentar_volume(self):
        self.scale_vol.set(min(100, self.scale_vol.get() + 5))

    def diminuir_volume(self):
        self.scale_vol.set(max(0, self.scale_vol.get() - 5))

    # -------------------------------------------------------------
    # CONEXÃO COM O SPOTIFY
    # -------------------------------------------------------------
    def _conectar_spotify_thread(self):
        """Roda em background para não travar a criação da janela (o primeiro
        login pode abrir o navegador e esperar autorização)."""
        self.spotify = SpotifyManager(on_status_change=self._spotify_status_callback)
        playlist_uri = self.playlists_config.get(self.estado_atual)
        if playlist_uri:
            self.spotify.tocar_playlist(playlist_uri)

    def _spotify_status_callback(self, msg):
        """Chamado pela thread do SpotifyManager; repassa a mensagem pro título com segurança."""
        def _atualizar():
            self.texto_titulo = f"🎧 {msg}"
            self.texto_artista = ""
            self.marquee_offset = 0
        self.root.after(0, _atualizar)

    # -------------------------------------------------------------
    # CAPA DO ÁLBUM (MINIATURA)
    # -------------------------------------------------------------
    def _atualizar_capa_se_necessario(self, capa_url):
        """Só baixa uma imagem nova se a URL da capa mudou desde a última vez."""
        if not capa_url or capa_url == self._ultima_capa_url:
            return
        self._ultima_capa_url = capa_url
        threading.Thread(target=self._baixar_e_processar_capa, args=(capa_url,), daemon=True).start()

    def _baixar_e_processar_capa(self, url):
        """Roda em background: baixa bytes + redimensiona com PIL (CPU/rede,
        não pode travar a UI). A troca do widget em si acontece no main thread."""
        if not self.spotify:
            return
        dados = self.spotify.baixar_imagem(url)
        if not dados:
            return
        try:
            img = Image.open(io.BytesIO(dados)).convert("RGB")
            img = img.resize((self.TAM_CAPA, self.TAM_CAPA), Image.LANCZOS)
        except Exception:
            return
        self.root.after(0, lambda: self._exibir_capa_no_label(img))

    def _exibir_capa_no_label(self, img_pil):
        """Só pode ser chamado a partir do main thread (cria um ImageTk.PhotoImage)."""
        self._capa_photoimage = ImageTk.PhotoImage(img_pil)  # guarda referência: sem isso o GC recolhe a imagem
        self.lbl_capa.config(image=self._capa_photoimage)

    def abrir_config_playlists(self):
        """Abre a janela onde o usuário escolhe suas próprias playlists por estado."""
        if not self.spotify or not self.spotify.disponivel:
            self.texto_titulo = "Aguarde conectar ao Spotify p/ configurar playlists"
            self.texto_artista = ""
            self.marquee_offset = 0
            return
        JanelaConfigPlaylists(self.root, self.spotify, on_salvar=self._ao_salvar_config_playlists)

    def _ao_salvar_config_playlists(self, novo_config):
        """Callback disparado quando o usuário salva a nova configuração."""
        self.playlists_config = novo_config
        # Se o estado atual tiver playlist nova/alterada, troca imediatamente
        playlist_uri = self.playlists_config.get(self.estado_atual)
        if playlist_uri and self.spotify:
            self.spotify.tocar_playlist(playlist_uri)

    # -------------------------------------------------------------
    # CONTROLES DE ÁUDIO (via Spotify)
    # -------------------------------------------------------------
    def ajustar_volume(self, val):
        self.volume_atual = int(float(val))
        if not self.spotify:
            return
        # Debounce: evita disparar uma chamada de API a cada pixel do slider
        if self._volume_timer:
            self._volume_timer.cancel()
        self._volume_timer = threading.Timer(
            0.3, self.spotify.definir_volume, args=(self.volume_atual,)
        )
        self._volume_timer.daemon = True
        self._volume_timer.start()

    def toggle_play_pause(self):
        if not self.spotify:
            return
        if self.pausado_manualmente:
            self.spotify.retomar()
            self.pausado_manualmente = False
            self._tocando = True
            self._progress_last_ts = time.time()
            self.btn_play_pause.config(text="❚❚")
        else:
            self.spotify.pausar()
            self.pausado_manualmente = True
            self._tocando = False
            self.btn_play_pause.config(text="▶")

    def proxima_musica(self):
        if self.spotify:
            self.spotify.proxima_faixa()

    def musica_anterior(self):
        if self.spotify:
            self.spotify.faixa_anterior()

    # -------------------------------------------------------------
    # ROTINAS DO JOURNAL
    # -------------------------------------------------------------
    # -------------------------------------------------------------
    # COMBATE A PÉ (travado até voltar pra nave, sem timeout)
    # -------------------------------------------------------------
    # Antes havia um timer que voltava pra ONFOOT depois de X segundos sem
    # ataque. Trocado por uma trava simples: uma vez em ONFOOT_COMBAT, o
    # HUD ignora qualquer coisa que não seja "voltou pra nave" (Embark).
    # Isso elimina de vez a alternância ONFOOT <-> ONFOOT_COMBAT durante o
    # tiroteio — o único jeito de sair é embarcar de volta.
    def _entrar_combate_pe(self):
        self.atualizar_estado("ONFOOT_COMBAT")

    def atualizar_estado(self, novo_estado):
        if self.estado_atual != novo_estado:
            self.estado_atual = novo_estado
            cor = self._cor_estado()
            # atualizar_estado roda na thread do journal (loop_principal), não
            # na main thread da UI: tudo que mexe em widget precisa passar
            # por root.after(0, ...).
            self.root.after(0, lambda: self.lbl_estado.config(
                text=f"[ STATE: {novo_estado} ]", fg=cor
            ))
            self.root.after(0, self.desenhar_moldura)

            if not self.spotify:
                print("[HUD] Estado mudou mas self.spotify ainda é None (não conectado)")
                self.texto_titulo = "Conectando ao Spotify..."
                self.texto_artista = ""
                self.marquee_offset = 0
                return

            playlist_uri = self.playlists_config.get(novo_estado)
            print(f"[HUD] Novo estado: {novo_estado} | playlist mapeada: {playlist_uri}")
            if playlist_uri:
                self.spotify.tocar_playlist(playlist_uri)
            else:
                self.texto_titulo = f"[Sem playlist configurada p/ {novo_estado}]"
                self.texto_artista = ""
                self.marquee_offset = 0

    def get_latest_journal(self):
        files = glob.glob(os.path.join(JOURNAL_DIR, "Journal.*.log"))
        if not files:
            return None
        return max(files, key=os.path.getmtime)

    def processar_linha_log(self, linha):
        try:
            data = json.loads(linha)
            event = data.get("event")

            if event == "Disembark":
                self.atualizar_estado("ONFOOT")
            elif event == "Embark":
                self.atualizar_estado("SRV" if data.get("SRV") else "PLANETARY")
            elif event == "ApproachBody":
                self.atualizar_estado("PLANETARY")
            elif event == "LeaveBody":
                self.atualizar_estado("SUPERCRUISE" if data.get("InSupercruise") else "NORMAL")
            elif event == "LaunchSRV":
                self.atualizar_estado("SRV")
            elif event == "DockSRV":
                self.atualizar_estado("PLANETARY")
            elif event == "Docked":
                self.atualizar_estado("DOCKED")
            elif event == "Undocked":
                self.atualizar_estado("NORMAL")
            elif event == "SupercruiseEntry":
                self.atualizar_estado("SUPERCRUISE")
            elif event == "SupercruiseExit":
                self.atualizar_estado("PLANETARY" if data.get("BodyType") == "Planet" else "NORMAL")
            elif event in ["UnderAttack", "Interdicted"]:
                if self.estado_atual in ("ONFOOT", "ONFOOT_COMBAT"):
                    # O jogo raramente troca o MusicTrack para algo de combate
                    # enquanto você está a pé — na prática ele costuma ficar
                    # em "OnFoot" mesmo levando tiro. Então UnderAttack é o
                    # sinal confiável aqui, não o evento Music.
                    self._entrar_combate_pe()
                else:
                    self.atualizar_estado("COMBAT")
            elif event == "Music":
                track = data.get("MusicTrack", "")
                if track in ["Combat_OnFoot", "ConflictZone_OnFoot"]:
                    self._entrar_combate_pe()
                elif "Combat" in track and self.estado_atual not in ["ONFOOT", "ONFOOT_COMBAT"]:
                    self.atualizar_estado("COMBAT")
                elif track in ["OnFoot", "Explore_OnFoot"] and self.estado_atual != "ONFOOT_COMBAT":
                    # Importante: NÃO reage aqui se já estamos em
                    # ONFOOT_COMBAT. O jogo manda Music:"OnFoot" com
                    # frequência mesmo no meio do tiroteio (ver comentário
                    # acima), e sem essa checagem isso derrubava o estado
                    # de volta pra ONFOOT a cada mensagem, brigando com o
                    # timer de saída e fazendo o HUD oscilar entre os dois.
                    # Só o timeout (_sair_combate_pe_por_timeout) ou uma
                    # mudança real de estado (embarcar, docar etc.) tiram
                    # o HUD de ONFOOT_COMBAT.
                    self.atualizar_estado("ONFOOT")

        except json.JSONDecodeError:
            pass

    def gerenciar_visibilidade_hud(self):
        game_focado = is_game_active()

        if game_focado:
            if not self.hud_visivel:
                self.root.deiconify()
                self.root.wm_attributes("-topmost", True)
                self.hud_visivel = True
                if not self.pausado_manualmente and self.spotify:
                    self.spotify.retomar()
        else:
            if self.hud_visivel:
                self.root.withdraw()
                self.hud_visivel = False
                if self.spotify:
                    self.spotify.pausar()

    def loop_principal(self):
        contador_poll = 0
        while True:
            self.root.after(0, self.gerenciar_visibilidade_hud)

            journal_atual = self.get_latest_journal()
            if journal_atual != self.ultimo_journal:
                self.ultimo_journal = journal_atual
                if journal_atual:
                    self.file_position = os.path.getsize(journal_atual)

            if self.ultimo_journal and os.path.exists(self.ultimo_journal):
                with open(self.ultimo_journal, "r", encoding="utf-8") as f:
                    f.seek(self.file_position)
                    linhas = f.readlines()
                    self.file_position = f.tell()

                    for linha in linhas:
                        if linha.strip():
                            self.processar_linha_log(linha)

            # A cada ~5s, consulta a faixa atual no Spotify (nome, artista,
            # capa do álbum e progresso da faixa)
            contador_poll += 1
            if contador_poll >= 5 and self.spotify and not self.pausado_manualmente:
                contador_poll = 0
                info = self.spotify.obter_info_faixa_atual()
                if info:
                    def _atualizar_info(dados=info):
                        faixa = dados.get("faixa") or dados.get("titulo") or ""
                        if faixa:
                            self.texto_titulo = faixa
                            self.texto_artista = dados.get("artista", "")
                        self._progress_ms = dados.get("progress_ms", 0)
                        self._duration_ms = dados.get("duration_ms", 0)
                        self._progress_last_ts = time.time()
                        self._tocando = dados.get("is_playing", True)
                    self.root.after(0, _atualizar_info)
                    self._atualizar_capa_se_necessario(info.get("capa_url"))

            time.sleep(1)

    def iniciar(self):
        self.root.mainloop()

if __name__ == "__main__":
    app = EliteAudioHUD()
    app.iniciar()
