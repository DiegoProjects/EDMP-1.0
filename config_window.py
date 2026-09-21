"""
config_window.py
-----------------
Janela (Toplevel) que permite ao usuário escolher, dentre as playlists reais
da própria conta do Spotify, qual toca em cada estado do jogo.
"""

import threading
import tkinter as tk
from tkinter import ttk

from playlist_config import ESTADOS, NOMES_ESTADOS, carregar_config, salvar_config


class JanelaConfigPlaylists(tk.Toplevel):
    """
    Uso:
        JanelaConfigPlaylists(root, spotify_manager, on_salvar=callback)

    'spotify_manager' precisa já estar conectado (spotify.disponivel == True)
    para conseguir buscar a lista de playlists do usuário.
    'on_salvar' é chamado com o novo dict {estado: uri} assim que o usuário salva.
    """

    def __init__(self, master, spotify_manager, on_salvar=None):
        super().__init__(master)
        self.title("Configurar Playlists por Estado")
        self.geometry("440x460")
        self.resizable(False, False)
        self.configure(bg="#121721")
        self.attributes("-topmost", True)

        self.spotify_manager = spotify_manager
        self.on_salvar = on_salvar
        self.config_atual = carregar_config()
        self.combos = {}  # estado -> (combobox, {nome: uri})

        tk.Label(
            self, text="Escolha a playlist para cada estado do jogo",
            bg="#121721", fg="#FF7700", font=("Consolas", 10, "bold")
        ).pack(pady=(12, 4))

        self.lbl_status = tk.Label(
            self, text="Carregando suas playlists do Spotify...",
            bg="#121721", fg="#FFB400", font=("Consolas", 9)
        )
        self.lbl_status.pack(pady=4)

        self.frame_estados = tk.Frame(self, bg="#121721")
        self.frame_estados.pack(fill="both", expand=True, padx=14, pady=6)

        frame_botoes = tk.Frame(self, bg="#121721")
        frame_botoes.pack(pady=10)

        self.btn_salvar = tk.Button(
            frame_botoes, text="Salvar", command=self._salvar, state="disabled", width=12
        )
        self.btn_salvar.pack(side="left", padx=6)

        tk.Button(
            frame_botoes, text="Cancelar", command=self.destroy, width=12
        ).pack(side="left", padx=6)

        if not self.spotify_manager or not self.spotify_manager.disponivel:
            self.lbl_status.config(
                text="Spotify ainda não conectado. Aguarde a conexão e tente de novo."
            )
            return

        threading.Thread(target=self._carregar_playlists_thread, daemon=True).start()

    # -------------------------------------------------------------
    def _carregar_playlists_thread(self):
        playlists = self.spotify_manager.listar_playlists_usuario()
        self.after(0, lambda: self._montar_formulario(playlists))

    def _montar_formulario(self, playlists):
        if not playlists:
            self.lbl_status.config(
                text="Nenhuma playlist encontrada (verifique login/permissões)."
            )
            return

        self.lbl_status.config(text=f"{len(playlists)} playlists encontradas — escolha abaixo:")

        nomes = [p["name"] for p in playlists]
        uri_por_nome = {p["name"]: p["uri"] for p in playlists}
        nome_por_uri = {p["uri"]: p["name"] for p in playlists}

        for estado in ESTADOS:
            linha = tk.Frame(self.frame_estados, bg="#121721")
            linha.pack(fill="x", pady=3)

            tk.Label(
                linha, text=NOMES_ESTADOS.get(estado, estado), width=20, anchor="w",
                bg="#121721", fg="#FFB400", font=("Consolas", 9)
            ).pack(side="left")

            combo = ttk.Combobox(linha, values=nomes, state="readonly", width=26)
            uri_atual = self.config_atual.get(estado, "")
            if uri_atual in nome_por_uri:
                combo.set(nome_por_uri[uri_atual])
            combo.pack(side="left", padx=4, fill="x", expand=True)

            self.combos[estado] = (combo, uri_por_nome)

        self.btn_salvar.config(state="normal")

    def _salvar(self):
        print(f"[ConfigWindow] Botão Salvar clicado. Estados mapeados: {list(self.combos.keys())}")
        novo_config = dict(self.config_atual)
        for estado, (combo, uri_por_nome) in self.combos.items():
            nome_selecionado = combo.get()
            print(f"[ConfigWindow]   {estado} -> seleção: '{nome_selecionado}'")
            if nome_selecionado in uri_por_nome:
                novo_config[estado] = uri_por_nome[nome_selecionado]
            elif not nome_selecionado:
                print(f"[ConfigWindow]   ATENÇÃO: nenhum item selecionado para {estado}")

        try:
            salvar_config(novo_config)
        except Exception as e:
            print(f"[ConfigWindow] ERRO ao salvar: {e}")
            self.lbl_status.config(text=f"Erro ao salvar: {e}")
            return

        self.config_atual = novo_config

        if self.on_salvar:
            self.on_salvar(novo_config)

        self.destroy()
