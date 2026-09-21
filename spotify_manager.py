"""
spotify_manager.py
-------------------
Camada de integração com a API do Spotify (via spotipy) para a HUD do
Elite Dangerous. Permite trocar a playlist tocando no Spotify de acordo
com o estado do jogo (docado, combate, etc.), espelhando a mesma lógica
já usada para as pastas de MP3 locais.

REQUISITOS IMPORTANTES:
- Conta Spotify PREMIUM (a Web API só permite controlar playback com Premium).
- Um dispositivo Spotify já ATIVO (app desktop/mobile aberto e logado),
  pois a API apenas comanda um player existente via Spotify Connect —
  ela não transmite áudio diretamente.
- Um App criado no Spotify Developer Dashboard (https://developer.spotify.com/dashboard)
  com Client ID, Client Secret e Redirect URI configurados.

Instalação:
    pip install spotipy
"""

import os
import random
import threading

try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
    SPOTIPY_DISPONIVEL = True
except ImportError:
    SPOTIPY_DISPONIVEL = False

# ----------------------------------------------------------------------
# CONFIGURAÇÃO — pode vir de variáveis de ambiente ou ser preenchido direto aqui
# ----------------------------------------------------------------------
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIPY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIPY_CLIENT_SECRET", "")
SPOTIFY_REDIRECT_URI = os.environ.get("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8888/callback")

SPOTIFY_SCOPE = (
    "user-modify-playback-state user-read-playback-state "
    "playlist-read-private playlist-read-collaborative"
)

CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".spotify_cache")


class SpotifyManager:
    """
    Gerencia autenticação e troca de playlists no Spotify.
    Todas as chamadas de rede rodam em threads separadas para não travar a UI.
    """

    def __init__(self, on_status_change=None):
        """
        on_status_change: callback opcional recebendo uma string de status
                           (ex: para exibir no marquee do HUD).
        """
        self.sp = None
        self.disponivel = False
        self.device_id = None
        self.playlist_atual_uri = None
        self.on_status_change = on_status_change
        self._lock = threading.Lock()

        # Quando True, ao trocar de playlist o player começa numa faixa
        # sorteada em vez da primeira, e o modo shuffle é ligado para que
        # as faixas seguintes também saiam fora de ordem.
        self.aleatorio = True
        # Cache {playlist_uri: total_de_faixas} — evita uma chamada de rede
        # a cada troca de estado do jogo.
        self._totais_playlists = {}

        self._conectar()

    # -------------------------------------------------------------
    # CONEXÃO / AUTENTICAÇÃO
    # -------------------------------------------------------------
    def _conectar(self):
        if not SPOTIPY_DISPONIVEL:
            self._status("Spotify: biblioteca 'spotipy' não instalada")
            return

        if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
            self._status("Spotify: defina SPOTIPY_CLIENT_ID / SPOTIPY_CLIENT_SECRET")
            return

        try:
            auth_manager = SpotifyOAuth(
                client_id=SPOTIFY_CLIENT_ID,
                client_secret=SPOTIFY_CLIENT_SECRET,
                redirect_uri=SPOTIFY_REDIRECT_URI,
                scope=SPOTIFY_SCOPE,
                cache_path=CACHE_PATH,
                open_browser=True,
            )
            self.sp = spotipy.Spotify(auth_manager=auth_manager)
            self.sp.current_user()  # valida o token / força login na primeira vez
            self.disponivel = True
            self._status("Spotify conectado")
        except Exception as e:
            self.disponivel = False
            self._status(f"Spotify: falha ao conectar ({e})")

    def _status(self, msg):
        print(f"[Spotify] {msg}")  # log de diagnóstico no console
        if self.on_status_change:
            try:
                self.on_status_change(msg)
            except Exception:
                pass

    # -------------------------------------------------------------
    # DISPOSITIVOS
    # -------------------------------------------------------------
    def _obter_device_ativo(self):
        try:
            devices = self.sp.devices().get("devices", [])
            print(f"[Spotify] Dispositivos encontrados: {[(d.get('name'), d.get('is_active')) for d in devices]}")
            for d in devices:
                if d.get("is_active"):
                    return d["id"]
            if devices:
                return devices[0]["id"]  # nenhum ativo -> usa o primeiro disponível
        except Exception as e:
            print(f"[Spotify] Erro ao listar dispositivos: {e}")
        return None

    # -------------------------------------------------------------
    # SORTEIO DE FAIXA
    # -------------------------------------------------------------
    def _obter_total_faixas(self, playlist_uri):
        """Quantidade de faixas da playlist (com cache em memória).
        Retorna 0 se não conseguir descobrir."""
        if playlist_uri in self._totais_playlists:
            return self._totais_playlists[playlist_uri]

        try:
            # fields="total" + limit=1: baixa só o contador, não a lista inteira
            resultado = self.sp.playlist_items(
                playlist_uri, fields="total", limit=1, additional_types=("track",)
            )
            total = int(resultado.get("total", 0) or 0)
        except Exception as e:
            print(f"[Spotify] Não foi possível contar as faixas de {playlist_uri}: {e}")
            return 0

        if total > 0:
            self._totais_playlists[playlist_uri] = total
        return total

    def _sortear_offset(self, playlist_uri):
        """Devolve {'position': N} com N aleatório, ou None se não der pra sortear."""
        if not self.aleatorio:
            return None
        total = self._obter_total_faixas(playlist_uri)
        if total <= 1:
            return None
        posicao = random.randrange(total)
        print(f"[Spotify] Sorteando faixa {posicao + 1} de {total}")
        return {"position": posicao}

    # -------------------------------------------------------------
    # CONTROLE DE PLAYBACK (assíncrono)
    # -------------------------------------------------------------
    def tocar_playlist(self, playlist_uri):
        """Troca para a playlist informada. Não bloqueia a UI."""
        threading.Thread(
            target=self._tocar_playlist_thread, args=(playlist_uri,), daemon=True
        ).start()

    def _tocar_playlist_thread(self, playlist_uri):
        if not self.disponivel or not playlist_uri:
            if not self.disponivel:
                self._status("Spotify: não conectado")
            return

        with self._lock:
            print(f"[Spotify] Solicitado: {playlist_uri} | Atual: {self.playlist_atual_uri}")
            # Sem dedupe por playlist: toda troca de estado sorteia uma faixa
            # nova, inclusive quando o estado volta para a mesma playlist.

            try:
                self.device_id = self._obter_device_ativo()
                print(f"[Spotify] Dispositivo selecionado: {self.device_id}")
                if not self.device_id:
                    self._status("Spotify: nenhum dispositivo ativo encontrado")
                    return

                offset = self._sortear_offset(playlist_uri)
                try:
                    self.sp.start_playback(
                        device_id=self.device_id,
                        context_uri=playlist_uri,
                        offset=offset,
                    )
                except spotipy.exceptions.SpotifyException:
                    # A faixa sorteada pode estar indisponível na região / ser
                    # um arquivo local: nesse caso cai de volta no começo.
                    if offset is None:
                        raise
                    print("[Spotify] Faixa sorteada recusada, tocando do início.")
                    self.sp.start_playback(device_id=self.device_id, context_uri=playlist_uri)

                # Shuffle ligado DEPOIS do start_playback: assim ele não
                # interfere no offset, mas as próximas faixas saem embaralhadas.
                if self.aleatorio:
                    try:
                        self.sp.shuffle(True, device_id=self.device_id)
                    except Exception as e:
                        print(f"[Spotify] Não foi possível ativar o shuffle: {e}")

                self.playlist_atual_uri = playlist_uri
                self._status("Spotify: playlist alterada")
            except spotipy.exceptions.SpotifyException as e:
                self._status(f"Spotify: erro ao tocar playlist ({e})")
            except Exception as e:
                self._status(f"Spotify: erro inesperado ({e})")

    def pausar(self):
        threading.Thread(target=self._pausar_thread, daemon=True).start()

    def _pausar_thread(self):
        if not self.disponivel:
            return
        try:
            self.sp.pause_playback(device_id=self.device_id)
        except Exception:
            pass

    def retomar(self):
        threading.Thread(target=self._retomar_thread, daemon=True).start()

    def _retomar_thread(self):
        if not self.disponivel:
            return
        try:
            self.sp.start_playback(device_id=self.device_id)
        except Exception:
            pass

    def proxima_faixa(self):
        threading.Thread(target=self._proxima_faixa_thread, daemon=True).start()

    def _proxima_faixa_thread(self):
        if not self.disponivel:
            return
        try:
            self.sp.next_track(device_id=self.device_id)
        except Exception:
            pass

    def faixa_anterior(self):
        threading.Thread(target=self._faixa_anterior_thread, daemon=True).start()

    def _faixa_anterior_thread(self):
        if not self.disponivel:
            return
        try:
            self.sp.previous_track(device_id=self.device_id)
        except Exception:
            pass

    def definir_volume(self, percent):
        """Ajusta o volume (0-100) no dispositivo ativo do Spotify."""
        threading.Thread(target=self._definir_volume_thread, args=(percent,), daemon=True).start()

    def _definir_volume_thread(self, percent):
        if not self.disponivel:
            return
        try:
            self.sp.volume(int(percent), device_id=self.device_id)
        except Exception:
            pass

    def obter_info_faixa_atual(self):
        """Retorna {'titulo': 'Artista - Faixa', 'capa_url': str|None} da
        reprodução atual, ou None se indisponível. Chamada síncrona (rede) —
        use a partir de uma thread de background, não da UI."""
        if not self.disponivel:
            return None
        try:
            playback = self.sp.current_playback()
            if playback and playback.get("item"):
                item = playback["item"]
                nome = item.get("name", "")
                artistas = ", ".join(a["name"] for a in item.get("artists", []))
                titulo = f"{artistas} - {nome}" if artistas else nome

                capa_url = None
                imagens = item.get("album", {}).get("images", [])
                if imagens:
                    # imagens vêm ordenadas da maior pra menor; a última é a menor
                    # (evita baixar uma imagem grande à toa para uma miniatura)
                    capa_url = imagens[-1]["url"]

                return {
                    "titulo": titulo,  # mantido por compatibilidade
                    "faixa": nome,
                    "artista": artistas,
                    "capa_url": capa_url,
                    "progress_ms": playback.get("progress_ms") or 0,
                    "duration_ms": item.get("duration_ms") or 0,
                    "is_playing": bool(playback.get("is_playing")),
                }
        except Exception:
            pass
        return None

    def baixar_imagem(self, url):
        """Baixa os bytes de uma imagem (ex: capa de álbum) a partir de uma URL.
        Chamada síncrona (rede) — use a partir de uma thread de background."""
        if not url:
            return None
        try:
            import requests
            resp = requests.get(url, timeout=6)
            if resp.status_code == 200:
                return resp.content
        except Exception:
            pass
        return None

    def listar_playlists_usuario(self):
        """Retorna [{'name': ..., 'uri': ...}, ...] com todas as playlists
        visíveis para o usuário logado (próprias + seguidas). Chamada síncrona
        (rede) — use a partir de uma thread de background, não da UI."""
        if not self.disponivel:
            return []

        playlists = []
        try:
            resultado = self.sp.current_user_playlists(limit=50)
            while resultado:
                for pl in resultado.get("items", []):
                    if pl and pl.get("uri"):
                        playlists.append({"name": pl.get("name", "(sem nome)"), "uri": pl["uri"]})
                resultado = self.sp.next(resultado) if resultado.get("next") else None
        except Exception as e:
            self._status(f"Spotify: erro ao listar playlists ({e})")

        return playlists
