"""
playlist_config.py
-------------------
Persistência simples (JSON) do mapeamento estado -> playlist do Spotify,
escolhido pelo usuário através da janela de configuração (config_window.py).
"""

import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "playlists_config.json")

ESTADOS = [
    "DOCKED",
    "SUPERCRUISE",
    "COMBAT",
    "NORMAL",
    "PLANETARY",
    "SRV",
    "ONFOOT",
    "ONFOOT_COMBAT",
]

NOMES_ESTADOS = {
    "DOCKED": "Docado",
    "SUPERCRUISE": "Supercruise",
    "COMBAT": "Combate",
    "NORMAL": "Voo normal",
    "PLANETARY": "Superfície planetária",
    "SRV": "Dirigindo o SRV",
    "ONFOOT": "A pé",
    "ONFOOT_COMBAT": "Combate a pé",
}

PADRAO = {estado: "" for estado in ESTADOS}


def carregar_config():
    """Lê playlists_config.json. Se não existir ou estiver corrompido,
    retorna o padrão (todos os estados sem playlist definida)."""
    print(f"[PlaylistConfig] Procurando config em: {CONFIG_PATH}")
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                dados = json.load(f)
            config = dict(PADRAO)
            config.update({k: v for k, v in dados.items() if k in PADRAO})
            print(f"[PlaylistConfig] Config carregada: {config}")
            return config
        except Exception as e:
            print(f"[PlaylistConfig] Erro ao ler config existente: {e}")
    else:
        print("[PlaylistConfig] Arquivo não existe ainda, usando padrão vazio")
    return dict(PADRAO)


def salvar_config(config):
    """Grava o mapeamento estado -> URI da playlist em disco."""
    print(f"[PlaylistConfig] Salvando em: {CONFIG_PATH}")
    print(f"[PlaylistConfig] Conteúdo: {config}")
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print("[PlaylistConfig] Salvo com sucesso")
