# Tradutor Ren'Py

Aplicativo desktop em português para extrair, traduzir e revisar os textos de
jogos Ren'Py. Inspirado no fluxo de tabela, busca e revisão do
[The Sims 4 Translator, de voky1](https://github.com/voky1/sims4-translator).

![Editor de tradução](docs/editor.png)

## Recursos

- Seleção do executável `.exe` e identificação da pasta `game` ao lado dele.
- Extração de arquivos RPA 2.0, 3.0 e 3.2 em uma pasta de projeto separada.
- Leitura de roteiros `.rpy` e descompilação de `.rpyc` com o unrpyc incluído.
- Diálogos, menus, textos de interface, chamadas `_()` e nomes de personagens.
- Valores de texto de `.yml` e `.yaml`, incluindo listas, documentos múltiplos,
  textos multilinha e âncoras. Chaves, números e booleanos ficam preservados.
- Editor com original e tradução, contexto, busca e filtros por tipo e estado.
- Estados **Pendente**, **Traduzido**, **Revisado** e **Verificar tags**.
- Validação de marcadores comuns como `[player]`, `{b}…{/b}` e `%(score)d`.
- Projeto JSON para salvar e continuar a revisão, além de importação/exportação CSV.
- Exportação de um catálogo Ren'Py e de cópias traduzidas dos arquivos YAML.

Esta versão usa tradução manual e importação/exportação. Não precisa de serviços
online nem de chaves de API.

## Instalação e execução

Requer Python 3.11 ou superior. A interface é desktop e precisa de uma sessão gráfica.

Com [uv](https://docs.astral.sh/uv/), as versões são fixadas em `uv.lock`:

```sh
uv sync --locked
uv run --locked renpy-translator
```

Ou, no Windows, usando Python e PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m renpy_translator
```

No Linux/macOS com Python:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m renpy_translator
```

O tradutor roda nesses sistemas; o seletor desta versão espera a distribuição
Windows do jogo, com um `.exe` e uma pasta `game` no mesmo diretório.

## Como usar

1. Clique em **Selecionar jogo .exe** e escolha o executável do jogo.
2. Escolha uma pasta **fora da pasta do jogo** para salvar o projeto e informe
   o identificador do idioma, por exemplo `portuguese_br`.
3. Aguarde a extração. O programa cria uma nova subpasta com `projeto.json`,
   `traducoes.csv` e `extraidos/`. Avisos de arquivos não lidos aparecem no painel inferior.
4. Selecione uma linha e digite no campo **Tradução**. Preserve as variáveis e tags.
5. Use **Revisar e avançar** ou `Ctrl+Enter`. Alterar uma tradução remove sua revisão.
   A opção **Aplicar a textos Ren'Py iguais** reutiliza a tradução nas outras ocorrências.
6. Use **Salvar** (`Ctrl+S`). Para continuar depois, abra `projeto.json` em **Abrir projeto**.
7. Em **Gerar tradução**, escolha todos os textos traduzidos ou somente os revisados.
   A saída fica em uma nova pasta; o programa não instala nem altera o jogo automaticamente.
8. Feche o jogo, faça backup de `game` e copie o conteúdo de `game/` da exportação
   para a pasta `game` do jogo, seguindo o `LEIA-ME.txt` gerado.

Textos pendentes continuam no idioma original. A exportação Ren'Py ativa o idioma
na próxima inicialização; a CLI permite desativar esse comportamento.
Arquivos YAML exportados mantêm a estrutura e substituem os arquivos originais
de mesmo caminho quando você instala a tradução. Valores técnicos de YAML também
podem aparecer na lista: traduza apenas os valores que o jogo apresenta ao usuário.

Para usar planilhas ou outro editor, clique em **Exportar CSV**, edite a coluna
`traducao` e importe o arquivo de volta. Mantenha `id` e `original` intactos.
A coluna `revisado` aceita `sim` ou `nao`; tags inválidas impedem marcar uma linha
como revisada. O CSV usa UTF-8 com BOM, separador vírgula e campos multilinha entre aspas.
O `traducoes.csv` criado na extração é a lista inicial; **Exportar CSV** gera a versão
atualizada após suas edições.

## Linha de comando

```sh
uv run renpy-translator-cli extrair /caminho/Jogo.exe --projeto /projetos/jogo --idioma portuguese_br
uv run renpy-translator-cli exportar-csv /projetos/jogo/projeto.json /projetos/textos.csv
uv run renpy-translator-cli importar-csv /projetos/jogo/projeto.json /projetos/textos.csv
uv run renpy-translator-cli exportar /projetos/jogo/projeto.json --destino /traducoes/jogo --somente-revisados
```

Os destinos de extração e exportação devem ser pastas novas. A opção `--nao-ativar`
de `exportar` gera apenas os arquivos de tradução, sem forçar o idioma inicial.

## Compatibilidade

- O catálogo usa `translate <idioma> strings`, com a tradução de strings nativa
  do Ren'Py para diálogos, menus e interface. Textos Ren'Py idênticos compartilham
  a tradução; traduções divergentes são sinalizadas ao exportar. YAML permite
  traduções distintas por ocorrência.
- Esta versão não gera blocos de diálogo por identificador. Traduções existentes
  no mesmo idioma podem conflitar com o catálogo; roteiros já traduzidos podem
  ter prioridade sobre os textos originais.
- A leitura de `.rpyc` usa o unrpyc para Ren'Py moderno, validado com um roteiro
  real do Ren'Py 8.2. Versões antigas, obfuscação e formatos RPA personalizados
  podem não funcionar. Falhas são mostradas no projeto, sem executar o jogo.
- A leitura de `.rpy` cobre a sintaxe usual de diálogos e interface. Monólogos
  com aspas triplas e textos construídos dinamicamente exigem tratamento adicional.
- YAML é lido como dados; somente valores escalares de texto entram na tradução.
  Arquivos devem estar em UTF-8. Comentários e âncoras são preservados; valores
  editados são escritos como strings entre aspas.
- A validação verifica a preservação dos marcadores reconhecidos. A revisão humana
  continua necessária para sentido, contexto e formatação visual no jogo.

## Desenvolvimento e testes

```sh
uv sync --locked --extra dev
uv run --locked --extra dev ruff check src tests scripts
uv run --locked --extra dev ruff format --check src tests scripts
uv run --locked --extra dev pytest
```

Na nuvem ou em Linux sem tela, execute os testes com Qt em modo offscreen:

```sh
QT_QPA_PLATFORM=offscreen XDG_CACHE_HOME=/tmp/renpy-translator-cache uv run --locked --extra dev pytest
```

Os testes cobrem RPA e prefixos, caminhos de extração, RPYC real, Ren'Py/YAML,
tags, revisão na interface, persistência JSON/CSV e exportação sem alterar o jogo.
A validação na nuvem é feita em Linux com Qt offscreen; o executável Windows e
a instalação em um jogo específico devem ser verificados no Windows.

## Gerar aplicativo distribuível

No Windows, execute:

```powershell
uv sync --locked --extra bundle
uv run --locked --extra bundle python scripts/build_desktop.py
```

O aplicativo fica em `dist/TradutorRenpy/TradutorRenpy.exe`. Distribua a pasta inteira.
Ela inclui `worker/`, o descompilador que roda separado da interface.
PyInstaller gera o aplicativo para o sistema onde o comando é executado:
um build no Linux não produz um executável Windows.

## Créditos

A interface e o fluxo de revisão são inspirados no projeto de voky1; o código
da aplicação foi desenvolvido para este repositório.
A leitura de roteiros compilados usa
[unrpyc](https://github.com/CensoredUsername/unrpyc), com origem, commit e licenças
preservados em `src/renpy_translator/_vendor/unrpyc/`.
