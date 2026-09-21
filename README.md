# ED HUD Audio — Overlay de Spotify para Elite Dangerous

Um HUD flutuante, no estilo cockpit do Elite Dangerous, que troca a playlist
tocada no Spotify automaticamente de acordo com o que você está fazendo no
jogo: docado, em supercruise, em combate (de nave ou a pé), na superfície de
um planeta, dirigindo o SRV, etc.

O HUD lê o journal do próprio jogo (os arquivos que o Elite Dangerous grava
em `Saved Games\Frontier Developments\Elite Dangerous`) e reage aos eventos
em tempo real — não precisa de nenhum mod ou injeção no jogo.

## Pré-requisitos

- **Windows** (o overlay usa `ctypes` e janela sem borda no estilo do
  Windows; não foi testado em Linux/macOS).
- **Python 3.10+**.
- **Conta Spotify Premium.** A Web API do Spotify só permite controlar a
  reprodução (trocar playlist, pausar, pular faixa) com Premium — numa
  conta free, o app conecta mas nenhum comando de playback funciona.
- Um **dispositivo Spotify ativo** antes de abrir o HUD: o app do Spotify
  aberto e logado no PC (ou celular, se estiver no Spotify Connect). A API
  comanda um player que já existe via Spotify Connect, ela não transmite
  áudio diretamente.

## Instalação

1. Clone o repositório e instale as dependências:

   ```bash
   git clone <url-do-seu-repositorio>
   cd <pasta-do-repositorio>
   pip install -r requirements.txt
   ```

2. Crie um app no [Spotify Developer Dashboard](https://developer.spotify.com/dashboard):
   - **App name**: qualquer nome (ex: "ED HUD Audio").
   - Em **Redirect URIs**, adicione exatamente:
     ```
     http://127.0.0.1:8888/callback
     ```
     (se você usar uma porta diferente, ajuste também a variável de
     ambiente `SPOTIPY_REDIRECT_URI` no passo seguinte, para as duas
     baterem certinho.)
   - Depois de criado, copie o **Client ID** e o **Client Secret**.

3. Defina as variáveis de ambiente com esses valores. No PowerShell:

   ```powershell
   setx SPOTIPY_CLIENT_ID "seu_client_id_aqui"
   setx SPOTIPY_CLIENT_SECRET "seu_client_secret_aqui"
   ```

   `SPOTIPY_REDIRECT_URI` só precisa ser definida se você não usou a URI
   padrão acima. Depois de usar `setx`, feche e reabra o terminal para as
   variáveis passarem a valer.

4. Rode o HUD:

   ```bash
   python ed_overlay_spotify.py
   ```

   Na primeira execução, uma janela do navegador vai abrir pedindo pra você
   autorizar o app na sua conta Spotify. Depois disso, o token fica salvo
   localmente em `.spotify_cache` (esse arquivo é ignorado pelo git — veja
   `.gitignore` — porque ele guarda credenciais da sua sessão, não deve ser
   commitado nem compartilhado).

## Configurando as playlists

Clique no ícone ⚙ no HUD (ou use o atalho configurado) para abrir a janela
de configuração. Ela lista as playlists reais da sua conta Spotify e deixa
você escolher uma para cada estado do jogo. A escolha é salva em
`playlists_config.json`, criado automaticamente na primeira vez que você
salva — esse arquivo também é ignorado pelo git, porque contém as URIs das
*suas* playlists, não faz sentido versionar. Use
`playlists_config.example.json` como referência do formato, se quiser
editar manualmente.

## Atalhos e controles

- Clique e arraste o HUD para reposicionar — a posição é salva
  automaticamente em `hud_estado.json` (também ignorado pelo git) e
  restaurada na próxima vez que você abrir.
- Use os atalhos configurados em `registrar_atalhos()` no código para
  aumentar/diminuir o HUD, mostrar/esconder, etc. — ajuste as teclas ali se
  quiserem outras combinações.
- Os botões ⏮ ❚❚ ⏭ no HUD controlam a reprodução diretamente.

## Um detalhe importante: fullscreen exclusivo

O overlay é uma janela `topmost` do Windows. Isso funciona em **borderless
windowed** (recomendado para o Elite Dangerous de qualquer forma, por
questões de troca de janela). Em **fullscreen exclusivo**, o jogo desenha
por cima de tudo, incluindo overlays do Windows, então o HUD fica
escondido atrás do jogo. Se você joga em fullscreen exclusivo, troque para
borderless windowed nas configurações de vídeo do Elite Dangerous.

## Estrutura do projeto

| Arquivo | O quê |
|---|---|
| `ed_overlay_spotify.py` | Janela do HUD, leitura do journal, lógica de estados do jogo |
| `spotify_manager.py` | Integração com a Web API do Spotify (spotipy) |
| `playlist_config.py` | Persistência do mapeamento estado → playlist |
| `config_window.py` | Janela de configuração das playlists |
| `requirements.txt` | Dependências Python |
| `playlists_config.example.json` | Exemplo do formato do arquivo gerado em runtime |

## Arquivos gerados em runtime (não versionados)

Estes arquivos são criados automaticamente quando você usa o HUD e estão
no `.gitignore` de propósito — cada um guarda algo pessoal (token, escolha
de playlist, posição de tela), não faz sentido no repositório:

- `.spotify_cache` — token OAuth da sua sessão Spotify
- `playlists_config.json` — suas playlists escolhidas por estado
- `hud_estado.json` — posição e escala do HUD na sua tela

## Licença

Adicione aqui a licença de sua escolha (ex: MIT) antes de publicar,
criando um arquivo `LICENSE` na raiz do repositório. Sem isso, por padrão,
o código fica sob direitos autorais exclusivos seus e tecnicamente
ninguém pode reutilizá-lo, mesmo estando público no GitHub.
