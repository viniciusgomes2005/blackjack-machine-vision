# NEXT_STEPS

Este documento resume o que foi discutido e validado na sessao de hoje, o estado atual do projeto e o que falta para sair do controle manual e chegar em uma rodada automatizada confiavel.

## 1. Estado Atual

O projeto tem tres frentes principais:

1. Visao computacional para reconhecer cartas, fichas e sinais de mao.
2. Bridge Modbus entre o PC e o Universal Robots.
3. Fluxo de jogo de Blackjack coordenando camera, decisao e comandos do robo.

Hoje a parte mais validada foi a comunicacao manual com o robo via Modbus. A automacao completa ainda nao esta pronta.

## 2. Comunicacao Com o Robo

O IP real do controlador UR usado hoje foi:

```text
10.103.18.245
```

O IP do PC na rede do robo usado para modo servidor foi:

```text
10.103.18.6
```

Foram testados dois modos de comunicacao:

### 2.1 Modo direto para o robo

Neste modo o PC conecta diretamente no Modbus server do controlador UR:

```powershell
python ur_robot_bridge.py --direct-to-robot
```

Ou usando comandos one-shot:

```powershell
python ur_robot_bridge.py --command hit --hold 0.5 --no-interactive
python ur_robot_bridge.py --command stand --hold 2 --no-interactive
python ur_robot_bridge.py --command double --hold 0.5 --no-interactive
```

O mapa padrao escrito no modo direto e:

| Sinal | Endereco |
| --- | --- |
| startprog | 128 |
| hit | 129 |
| double | 130 |
| stand | 131 |
| splitAB | 132 |
| splitBC | 133 |
| splitAC | 134 |

Foi observado que a escrita em holding registers funciona, por exemplo:

```text
stand standard_addr=131 holding=[1] coil=[False]
```

Isso significa que a comunicacao TCP com o controlador funciona, mas os coils nao aceitam escrita. O caminho funcional atual e via holding register.

### 2.2 Modo servidor no PC

Neste modo o PC sobe um servidor Modbus e o robo deveria conectar no PC:

```powershell
python ur_robot_bridge.py --server-mode --pc-host 10.103.18.6 --no-ur-read --diagnose-start
```

Esse comando funcionou e subiu o servidor em:

```text
10.103.18.6:31415
```

Tambem manteve `startprog=HI` corretamente no servidor do PC.

Ponto importante: nao e possivel abrir dois servidores ao mesmo tempo na mesma porta. Se um terminal estiver rodando `--diagnose-start`, outro comando em `--server-mode` falhara com porta em uso.

## 3. Comandos Manuais Que Funcionaram

### 3.1 Start da rodada

Modo direto:

```powershell
python ur_robot_bridge.py --no-ur-read --startprog
```

Observacao: com as alteracoes atuais, comandos one-shot como `--startprog` entram em modo direto por padrao, mesmo que `--direct-to-robot` nao seja passado.

### 3.2 Hit

Para pedir carta:

```powershell
python ur_robot_bridge.py --command hit --hold 0.5 --no-interactive
```

Se o robo precisar de mais tempo para reconhecer:

```powershell
python ur_robot_bridge.py --command hit --hold 2 --no-interactive
```

### 3.3 Double

`double` significa dobrar a aposta. No fluxo do robo:

- o jogador recebe uma carta;
- a mao atual termina automaticamente;
- `standcont` deve ser incrementado dentro do programa PolyScope.

Comando:

```powershell
python ur_robot_bridge.py --command double --hold 0.5 --no-interactive
```

Ou segurando mais:

```powershell
python ur_robot_bridge.py --command double --hold 2 --no-interactive
```

### 3.4 Stand como pulso

Para encerrar a fase do jogador e permitir a revelacao da carta fechada do dealer, normalmente o robo precisa ver:

1. `stand=True`
2. depois `stand=False`

Comando com pulso:

```powershell
python ur_robot_bridge.py --command stand --hold 2 --no-interactive
```

Esse comando sobe `stand`, espera `2s` e baixa.

### 3.5 Stand mantido em HI

Foi identificado que em alguns pontos do fluxo, especialmente para finalizar a fase do dealer, `stand` precisa ficar em `1` e nao voltar automaticamente para `0`.

Foi adicionado:

```powershell
python ur_robot_bridge.py --command stand --keep-high --no-interactive
```

Para baixar depois:

```powershell
python ur_robot_bridge.py --set stand=false --no-interactive
```

No prompt direto:

```powershell
python ur_robot_bridge.py --direct-to-robot
```

Comandos dentro do prompt:

```text
hold stand
set stand false
```

## 4. Fluxo Manual Validado do Jogo

Foi validado manualmente um fluxo parecido com:

1. Iniciar rodada com `startprog`.
2. Robo distribui cartas.
3. Jogador manda `hit`, `stand`, `double` conforme decisao manual.
4. Quando jogador manda `stand`, o robo consegue revelar a carta fechada do dealer.
5. Na fase do dealer:
   - se dealer estiver abaixo de 17, mandar `hit`;
   - quando dealer deve parar, manter `stand=HI` usando `--keep-high` ou `hold stand`.

Exemplo discutido:

```text
Jogador: 8 + 8 = 16
Dealer: 9 + ?; depois revelou 5
Dealer: 9 + 5 = 14
```

Nesse caso, pela regra comum de Blackjack, dealer deve comprar carta, entao o proximo comando seria:

```powershell
python ur_robot_bridge.py --command hit --hold 2 --no-interactive
```

Depois, se dealer chegar a 17 ou mais:

```powershell
python ur_robot_bridge.py --command stand --keep-high --no-interactive
```

## 5. Variaveis Internas do PolyScope

Foram discutidas as variaveis:

```text
splitcont
standcont
```

Essas variaveis vivem no programa do robo, nao no Python.

### 5.1 splitcont

`splitcont` conta quantos splits existem na rodada.

Valores:

```text
0 = sem split, 1 mao para jogar
1 = um split, 2 maos para jogar
2 = dois splits, 3 maos para jogar
```

### 5.2 standcont

`standcont` conta quantas maos do jogador ja foram encerradas.

Ele deve aumentar quando:

- jogador da `stand`;
- jogador da `double`, porque double encerra a mao depois de uma carta.

Ele nao deve aumentar em `hit`.

### 5.3 Inicializacao obrigatoria

O PolyScope precisa inicializar no inicio de cada rodada:

```text
splitcont := 0
standcont := 0
```

Se o robo diz que `splitcont` nao foi definido, isso precisa ser corrigido diretamente no programa PolyScope. Alterar Python nao corrige variavel interna nao definida no robo.

## 6. Problemas Identificados no Programa do Robo

### 6.1 Varios `if` independentes

O pseudocodigo atual tem uma estrutura parecida com:

```python
if hit == True:
    ...

if double == True:
    ...

if stand == True:
    standcont = standcont + 1
```

Isso e perigoso porque os sinais sao nivel, nao evento de borda. Se dois sinais ficarem `True` ao mesmo tempo, o robo pode executar duas acoes na mesma iteracao.

Ideal no PolyScope:

- garantir que apenas um sinal esteja `True`;
- depois de consumir um sinal, esperar ele voltar para `False`;
- se possivel, estruturar como `if / else if` logico, nao varios `if` independentes.

### 6.2 `stand` tem dois usos diferentes

`stand` e usado para:

1. Encerrar a fase do jogador e permitir revelar carta do dealer.
2. Encerrar a fase do dealer/finalizar rodada.

Esses dois usos exigem comportamento diferente:

- Para revelar carta do dealer: `stand` precisa subir e depois baixar.
- Para finalizar fase do dealer: `stand` pode precisar ficar alto.

Por isso foi adicionado `--keep-high`.

### 6.3 Correcoes no Python nao alteram PolyScope

Mudancas feitas neste repositorio alteram apenas o lado PC:

- `ur_robot_bridge.py`
- visao computacional
- comandos Modbus
- testes/documentacao

Elas nao alteram automaticamente:

- variaveis do PolyScope;
- waypoints;
- ordem dos blocos do programa;
- mapeamento de I/O na instalacao do UR;
- loops internos do programa do robo.

Essas partes precisam ser corrigidas no teach pendant/PolyScope ou por um fluxo de import/export do programa UR.

## 7. Estado da Visao Computacional

### 7.1 Quadrado da area de mao

O quadrado de referencia da mao foi alterado de amarelo para vermelho.

O codigo passou a usar:

```python
HAND_ZONE_COLOR = "red_tape"
```

em `config.py`.

### 7.2 Dataset `Sinais/`

Foi testada a pasta `Sinais/` com arquivos normais e arquivos com prefixo `T`.

Os arquivos `T*.jpg` foram tratados como imagens de teste.

Resultado observado nos `T*.jpg`:

```text
T1Dedo1.jpg: 2
T1Dedo2.jpg: 1
T1Dedo3.jpg: 4
T1Dedo4.jpg: 1
T1Dedo5.jpg: 1
T1Dedo6.jpg: 1
T1Dedo7.jpg: 1
T2Dedo1.jpg: 2
T2Dedo2.jpg: 2
T2Dedo3.jpg: 2
T2Dedo4.jpg: 2
T3Dedo1.jpg: 3
T3Dedo2.jpg: 3
T3Dedo3.jpg: 3
T3Dedo4.jpg: 3
T4Dedo1.jpg: 4
T4Dedo2.jpg: 4
T4Dedo3.jpg: 4
T4Dedo4.jpg: 4
T5Dedo1.jpg: 5
T5Dedo2.jpg: 5
T5Dedo3.jpg: 5
TVazio1.jpg: 1
TVazio2.jpg: 1
TVazio3.jpg: 1
TVazio4.jpg: 1
TVazio5.jpg: 0
```

Erros importantes:

- alguns `1Dedo` foram supercontados;
- varios `TVazio` viraram `1`;
- o detector ainda confunde vazio/ruido/braco com mao.

### 7.3 Classificador por `Sinais/`

Foi identificado um problema serio: o classificador por dataset de `Sinais/` fazia o teste parecer perfeito porque usava a propria pasta como base de comparacao.

Isso cria vazamento de treino/teste.

Foi adicionada a flag:

```python
USE_HAND_DATASET_CLASSIFIER = False
```

O classificador por dataset esta desligado por padrao.

## 8. O Que Falta Para Automatizar

### 8.1 Integrar leitura de `busyIO`

Hoje muitos comandos sao manuais com `--hold`.

Automacao correta precisa:

1. Esperar `busyIO=LO`.
2. Subir um sinal (`hit`, `stand`, `double`, etc.).
3. Esperar `busyIO=HI`, indicando que o robo aceitou.
4. Baixar o sinal quando apropriado.
5. Esperar `busyIO=LO` novamente antes da proxima decisao.

Sem isso, o sistema depende de tempos fixos e pode falhar se o robo estiver atrasado.

### 8.2 Integrar pulso de `foto`

O robo pulsa `foto` quando uma carta e virada.

A automacao precisa:

1. Detectar borda de subida de `foto`.
2. Capturar frame da camera.
3. Rodar reconhecimento de carta.
4. Atualizar estado do jogo.

Hoje isso ainda nao esta integrado de ponta a ponta com o fluxo do robo.

### 8.3 Melhorar reconhecimento de sinais de mao

O detector atual por contorno e concavidade e fragil.

Problemas:

- falso positivo em `Vazio`;
- `1 dedo` as vezes vira 2 ou 4;
- mudancas de luz/pose/crop quebram regras ajustadas manualmente.

Recomendacao:

1. Separar primeiro "tem mao" vs "vazio".
2. Depois contar dedos apenas se existe mao valida.
3. Considerar MediaPipe Hands ou um classificador treinado de verdade.
4. Manter `T*.jpg` como holdout fixo para teste, nunca como treino.

### 8.4 Corrigir teste de dataset

O teste `tests/test_hand_sign_dataset.py` atualmente nao entende bem prefixos `T`.

Ele interpreta arquivos `T1Dedo...` como esperado `None`, o que bagunca a suite quando esses arquivos entram em `Sinais/`.

O teste deve ser alterado para:

- aceitar prefixo opcional `T`;
- calcular esperado a partir de `T1Dedo`, `T2Dedo`, ..., `TVazio`;
- talvez separar treino e teste explicitamente.

### 8.5 Automatizar decisao do dealer

Depois de revelar a carta fechada do dealer:

- se dealer < 17: mandar `hit`;
- se dealer >= 17: manter `stand=HI` para finalizar.

Essa regra ainda esta manual.

### 8.6 Automatizar decisao do jogador

Opcoes:

1. Ler gesto da mao.
2. Usar estrategia basica de Blackjack.
3. Permitir override manual.

No momento, os comandos testados foram manuais.

## 9. Ordem Recomendada de Proximas Tarefas

### Passo 1: Congelar protocolo manual funcional

Documentar e manter funcionando:

```powershell
python ur_robot_bridge.py --no-ur-read --startprog
python ur_robot_bridge.py --command hit --hold 2 --no-interactive
python ur_robot_bridge.py --command stand --hold 2 --no-interactive
python ur_robot_bridge.py --command double --hold 2 --no-interactive
python ur_robot_bridge.py --command stand --keep-high --no-interactive
python ur_robot_bridge.py --set stand=false --no-interactive
```

### Passo 2: Corrigir PolyScope

No programa do robo:

1. Inicializar `splitcont := 0`.
2. Inicializar `standcont := 0`.
3. Garantir que esses contadores resetem a cada nova rodada.
4. Evitar multiplos `if` disparando na mesma iteracao.
5. Garantir que o robo espere o sinal voltar para `False` quando necessario.

### Passo 3: Ler `busyIO` e `foto`

Sem `busyIO`/`foto`, automacao e baseada em tempo fixo.

Implementar primeiro um script diagnostico:

- mostra `busyIO`;
- mostra `foto`;
- loga transicoes;
- confirma se o PC consegue ler saidas do robo.

### Passo 4: Criar orquestrador de rodada manual-assistido

Antes de visao completa, criar um script que:

1. Pergunta cartas manualmente no terminal.
2. Manda comandos para o robo.
3. Usa `busyIO` para sincronizar.
4. Controla corretamente jogador/dealer.

Isso valida o fluxo antes de depender de camera.

### Passo 5: Melhorar visao de cartas

Integrar captura no pulso `foto`.

Validar:

- carta do jogador;
- carta aberta do dealer;
- carta fechada revelada depois;
- cartas adicionais do dealer.

### Passo 6: Melhorar visao de mao

Depois que o fluxo do robo estiver confiavel:

- corrigir `Vazio`;
- validar `T*.jpg`;
- talvez substituir heuristica por MediaPipe ou classificador real.

## 10. Comandos Uteis

### Prompt direto

```powershell
python ur_robot_bridge.py --direct-to-robot
```

Dentro:

```text
status
hit
stand
double
hold stand
set stand false
quit
```

### Ver status direto

```text
status
```

### Start

```powershell
python ur_robot_bridge.py --no-ur-read --startprog
```

### Hit

```powershell
python ur_robot_bridge.py --command hit --hold 2 --no-interactive
```

### Stand pulso

```powershell
python ur_robot_bridge.py --command stand --hold 2 --no-interactive
```

### Stand mantido

```powershell
python ur_robot_bridge.py --command stand --keep-high --no-interactive
```

### Baixar stand

```powershell
python ur_robot_bridge.py --set stand=false --no-interactive
```

### Double

```powershell
python ur_robot_bridge.py --command double --hold 2 --no-interactive
```

### Servidor no PC

```powershell
python ur_robot_bridge.py --server-mode --pc-host 10.103.18.6 --no-ur-read
```

### Diagnostico de start no servidor do PC

```powershell
python ur_robot_bridge.py --server-mode --pc-host 10.103.18.6 --no-ur-read --diagnose-start
```

## 11. Riscos Atuais

1. O programa PolyScope ainda pode estar consumindo sinais de forma sensivel a nivel e nao a borda.
2. `stand` tem semantica dupla, o que exige cuidado para subir e baixar no momento certo.
3. Sem `busyIO`, comandos podem ser enviados enquanto o robo nao esta pronto.
4. A visao de mao ainda nao esta robusta para automacao.
5. O classificador antigo por `Sinais/` deve continuar desligado por padrao.
6. Testes com imagens de treino nao devem ser usados como prova de acerto real.

## 12. Proxima Meta Concreta

A proxima meta mais segura e:

```text
Automatizar uma rodada com cartas digitadas manualmente e comandos sincronizados por busyIO/foto, sem depender ainda da visao de mao.
```

Isso isola o problema:

- se falhar, e fluxo Modbus/PolyScope;
- se passar, entao o robo e o protocolo estao prontos;
- depois disso, a visao pode ser conectada com menos incerteza.

---

## 13. Sessao posterior a implementacao da logica correta do Blackjack

Esta secao foi adicionada apos a implementacao do motor correto de Blackjack no
codigo. A partir daqui, os proximos passos assumem que a regra local do jogo ja
esta funcional e validada por testes automatizados.

O estado atual e:

- `blackjack_engine.py` contem a regra e o loop do Blackjack.
- `blackjack_manual_simulator.py` permite simular rodadas sem camera e sem robo.
- `main.py --simulate-round` permite simular rodadas com imagem da mesa, imagens
  de sinais de mao ou cartas informadas por argumento.
- A ponte Modbus existe em `ur_robot_bridge.py`, mas ainda precisa ser conectada
  ao loop completo da rodada.
- Falta integrar o fluxo de camera ao vivo com os pulsos `foto`/`busyIO` do
  robo.
- Falta adicionar a logica de `startprog` por sinal de mao.

## 14. Proximo objetivo principal

Integrar tres camadas em um unico fluxo:

```text
visao computacional -> motor de Blackjack -> comunicacao com robo UR
```

O fluxo final desejado e:

1. Jogador faz sinal de inicio.
2. Visao reconhece esse sinal.
3. PC envia `startprog` ao robo.
4. Robo distribui cartas iniciais.
5. Robo pulsa `foto` nos momentos em que cartas devem ser reconhecidas.
6. PC reconhece as cartas.
7. Motor de Blackjack decide quais acoes sao legais.
8. Jogador faz sinais de mao para `hit`, `stand`, `split` ou `double`.
9. PC valida a acao no motor.
10. Se a acao for legal, PC envia o sinal ao robo.
11. Robo executa o movimento.
12. PC atualiza o estado da rodada.
13. Quando todas as maos do jogador encerram, dealer joga.
14. PC resolve cada mao contra o dealer.

## 15. Logica de Start Program por 4 dedos

Falta adicionar a logica de `Start program`.

Essa logica substitui a etapa fisica de o jogador jogar a ficha na mesa. Como o
projeto ainda nao tem uma logica confiavel para detectar a aposta inicial, o
inicio da rodada deve ser feito por sinal de mao:

```text
Antes da rodada comecar: 4 dedos esticados = startprog
Durante a rodada do jogador: 4 dedos esticados = stand
```

Isso exige uma leitura contextual:

- se o estado do jogo for `waiting_start`, 4 dedos deve gerar `startprog`;
- se o estado do jogo for `player_turn`, 4 dedos deve gerar `stand`.

Implementacao sugerida:

1. Adicionar um estado de alto nivel no orquestrador, por exemplo:
   - `waiting_start`;
   - `initial_deal`;
   - `player_turn`;
   - `dealer_turn`;
   - `finished`.
2. No estado `waiting_start`, chamar `hand_sign_vision.analyze_hand_image`.
3. Se detectar 4 dedos de forma estavel, enviar `startprog`.
4. Aguardar `busyIO` subir para confirmar que o robo aceitou o inicio.
5. Baixar `startprog`.
6. Entrar em `initial_deal`.

## 16. Variaveis que o PC deve enviar ao robo

Os sinais enviados ao robo devem continuar alinhados com `ur_robot_bridge.py`.

| Variavel | Direcao | Register atual | Quando enviar |
| --- | --- | --- | --- |
| `startprog` | PC -> robo | 128 | inicio da rodada |
| `hit` | PC -> robo | 129 | acao legal `hit` aceita pelo motor |
| `double` | PC -> robo | 130 | acao legal `double` aceita pelo motor |
| `stand` | PC -> robo | 131 | acao legal `stand` aceita pelo motor |
| `splitAB` | PC -> robo | 132 | split fisico entre posicoes A/B |
| `splitBC` | PC -> robo | 133 | split fisico entre posicoes B/C |
| `splitAC` | PC -> robo | 134 | split fisico entre posicoes A/C |

Observacao importante:

O motor de Blackjack conhece apenas a acao logica `split`. A traducao para
`splitAB`, `splitBC` ou `splitAC` deve acontecer no orquestrador fisico, porque
depende da posicao real da mao na mesa e de como o PolyScope espera receber o
split.

## 17. Variaveis que o robo deve devolver ao PC

| Variavel | Direcao | Uso |
| --- | --- | --- |
| `busyIO` | robo -> PC | indica que o robo esta ocupado/executando movimento |
| `foto` | robo -> PC | indica que a carta esta pronta para captura pela camera |

`busyIO`

Deve ser usado para sincronizacao. O PC so deve enviar uma nova acao quando o
robo estiver pronto.

Fluxo recomendado:

1. PC aguarda `busyIO == LO`.
2. PC envia sinal da acao.
3. PC aguarda `busyIO == HI`.
4. PC baixa o sinal enviado.
5. PC aguarda `busyIO == LO` novamente.

`foto`

Deve ser usado para captura de cartas.

Fluxo recomendado:

1. Robo vira uma carta.
2. Robo pulsa `foto`.
3. PC detecta borda de subida de `foto`.
4. PC captura frame da camera.
5. PC reconhece a carta.
6. PC adiciona a carta ao estado da rodada.

## 18. Integracao por arquivo

### `blackjack_engine.py`

Responsabilidade:

- manter regra do jogo;
- validar acoes legais;
- aplicar transicoes de estado;
- controlar split/double/hit/stand;
- controlar turno do dealer;
- resolver resultado.

O que precisa receber:

- cartas iniciais reconhecidas;
- cartas compradas pelo jogador;
- cartas compradas pelo dealer;
- acoes externas do jogador.

O que deve devolver:

- estado atual da rodada;
- mao ativa;
- acoes legais;
- eventos da rodada;
- resultado final.

Nao deve receber Modbus diretamente. Ele deve continuar independente do robo.

### `main.py`

Responsabilidade atual:

- pipeline principal de visao;
- simulacao com imagens;
- simulacao com cartas por argumento;
- ponto natural para futuramente virar o orquestrador principal.

Proximo passo:

- adicionar um modo de orquestracao real, por exemplo `--robot-round`;
- esse modo deve integrar camera, motor e `ur_robot_bridge.py`.

O que deve puxar da camera:

- cartas do jogador;
- carta aberta do dealer;
- cartas futuras apos `hit`, `double` e `split`;
- carta fechada do dealer apos revelacao;
- sinais de mao.

O que deve enviar ao robo:

- `startprog`;
- `hit`;
- `stand`;
- `double`;
- `splitAB`/`splitBC`/`splitAC`.

O que deve receber do robo:

- `busyIO`;
- `foto`.

### `blackjack_manual_simulator.py`

Responsabilidade:

- validar regra e loop sem camera;
- simular cenarios manuais;
- ajudar a reproduzir bugs de regra.

Nao deve ser ligado ao robo. Ele e uma bancada de teste.

### `DealerBotMain.py`

Responsabilidade atual:

- ler camera;
- reconhecer sinal de mao;
- converter dedos para acao;
- opcionalmente enviar pulso direto ao robo.

Proximo passo:

- deixar de ser apenas um emissor simples de pulso;
- passar a respeitar o estado do motor;
- implementar a leitura contextual de 4 dedos:
  - antes da rodada: `startprog`;
  - durante a rodada: `stand`.

Variaveis importantes:

- `HandDecision.fingers`;
- `HandDecision.action`;
- `HandDecision.robot_signal`.

### `hand_sign_vision.py`

Responsabilidade:

- reconhecer o numero de dedos;
- detectar area vermelha;
- retornar `1`, `2`, `3`, `4`, `5` ou vazio.

Integracao futura:

- usar estabilizacao antes de aceitar uma acao;
- diferenciar significado de 4 dedos pelo estado do jogo;
- melhorar robustez das imagens `T*.jpg` e `Vazio`.

Mapeamento contextual desejado:

| Estado do jogo | Dedos | Acao |
| --- | --- | --- |
| `waiting_start` | 4 | `startprog` |
| `player_turn` | 1 | `hit` |
| `player_turn` | 2 | `split` |
| `player_turn` | 3 | `double` |
| `player_turn` | 4 | `stand` |

### `card_vision.py`

Responsabilidade:

- detectar cartas nas ROIs;
- ler rank e naipe;
- retornar cartas no formato aceito por `blackjack_engine.py`.

Proximo passo:

- conectar captura no pulso `foto`;
- garantir que cada pulso gere exatamente uma carta nova;
- diferenciar em qual mao a carta deve ser inserida:
  - mao ativa do jogador;
  - primeira/segunda mao de split;
  - dealer aberto;
  - dealer hole revelada.

### `single_card_vision.py`

Responsabilidade:

- reconhecer uma carta isolada em uma ROI calibrada.

Uso futuro possivel:

- ser usado no momento do pulso `foto`, caso a carta esteja sempre em uma rampa
  ou posicao fixa antes de ser entregue pelo robo.

### `chip_vision.py`

Responsabilidade:

- detectar fichas;
- calcular aposta;
- otimizar fichas.

Estado atual:

- a regra correta de Blackjack implementada nao depende de aposta para decidir
  `win`, `lose` ou `push`.

Proximo passo:

- decidir se a aposta entrara apenas como informacao visual ou se sera integrada
  ao resultado financeiro da rodada.

Enquanto isso nao existir, `startprog` por 4 dedos substitui a deteccao da ficha
inicial.

### `game_state.py`

Responsabilidade atual:

- guardar estado visual simples da rodada;
- registrar cartas vistas;
- evitar duplicatas recentes.

Proximo passo:

- avaliar se `GameState` deve ser mantido como estado visual separado ou se deve
  passar a armazenar tambem uma referencia ao `BlackjackRound`.

Recomendacao:

- manter `blackjack_engine.BlackjackRound` como fonte da verdade da regra;
- usar `GameState` apenas para informacoes visuais e debug.

### `robot_commands.py`

Responsabilidade atual:

- converter acoes textuais em comandos simples.

Proximo passo:

- alinhar este arquivo com os sinais reais do PolyScope;
- decidir se ele continuara gerando dicionarios de comandos abstratos ou se sera
  substituido por chamadas diretas a `ur_robot_bridge.py`.

### `ur_robot_bridge.py`

Responsabilidade:

- comunicar com o controlador UR via Modbus/TCP;
- publicar ou escrever sinais;
- oferecer modo servidor PC e modo direto para o robo.

Proximo passo:

- expor uma API simples para o orquestrador:
  - `start_program()`;
  - `send_action("hit")`;
  - `send_action("stand")`;
  - `send_action("double")`;
  - `send_action("splitAB")`;
  - `wait_busy(False)`;
  - `wait_foto_rising()`.

Tambem precisa confirmar:

- enderecos finais no PolyScope;
- se `foto` e `busyIO` estao legiveis pelo PC;
- se os sinais sao coils, holding registers, input registers ou discrete inputs
  na configuracao final.

### `MODBUS/ur_dealerbot_pseudocode.py`

Responsabilidade:

- representar o comportamento esperado do programa PolyScope.

Proximo passo:

- confirmar se o programa real ainda bate com esse pseudocodigo;
- ajustar pontos divergentes, principalmente:
  - quando `foto` pulsa;
  - quando `busyIO` sobe/desce;
  - como splits sao consumidos;
  - como `stand` encerra jogador e dealer.

### `MODBUS/modbus_vision_skeleton.py`

Responsabilidade:

- esqueleto antigo/conceitual.

Proximo passo:

- usar apenas como referencia historica;
- preferir integrar o fluxo real via `ur_robot_bridge.py`.

## 19. Orquestrador final sugerido

Criar um fluxo em `main.py` ou em um arquivo orquestrador futuro que siga esta
estrutura:

```text
estado = waiting_start

loop:
    se estado == waiting_start:
        ler sinal de mao
        se 4 dedos estavel:
            enviar startprog
            estado = initial_deal

    se estado == initial_deal:
        aguardar pulsos foto
        reconhecer cartas iniciais
        criar BlackjackRound
        estado = player_turn

    se estado == player_turn:
        obter mao ativa do motor
        ler sinal de mao
        converter dedos em acao
        validar acao no motor
        se acao legal:
            enviar comando ao robo
            aguardar busyIO/foto conforme necessario
            reconhecer cartas novas se houver
            atualizar motor
        se todas maos encerradas:
            estado = dealer_turn

    se estado == dealer_turn:
        revelar carta fechada
        reconhecer carta
        enquanto dealer < 17:
            enviar hit ao robo
            aguardar foto
            reconhecer carta
            atualizar motor
        resolver rodada
        estado = finished

    se estado == finished:
        imprimir resultado
        aguardar novo start
```

## 20. Plano de implementacao recomendado

### Etapa 1: Start por 4 dedos

Implementar primeiro:

- estado `waiting_start`;
- reconhecimento estavel de 4 dedos;
- envio de `startprog`;
- confirmacao por `busyIO`.

Essa etapa valida a substituicao da ficha inicial pelo gesto de mao.

### Etapa 2: Captura por `foto`

Conectar:

- `wait_foto_rising()`;
- captura de frame;
- `card_vision.py` ou `single_card_vision.py`;
- adicao da carta no motor.

### Etapa 3: Acoes do jogador validadas pelo motor

Antes de enviar qualquer sinal ao robo:

1. ler gesto;
2. converter para acao;
3. consultar `legal_player_actions`;
4. se ilegal, ignorar e pedir nova acao;
5. se legal, enviar ao robo e aplicar no motor.

### Etapa 4: Split fisico

Mapear `split` logico para:

- `splitAB`;
- `splitAC`;
- `splitBC`.

Esse mapeamento precisa considerar:

- mao ativa;
- numero de splits ja feitos;
- posicao fisica das cartas na mesa;
- fluxo real do PolyScope.

### Etapa 5: Dealer automatico

Depois que todas as maos do jogador encerram:

- revelar hole card;
- reconhecer carta;
- usar `dealer_action`;
- enviar `hit` enquanto dealer < 17;
- parar automaticamente em 17 ou mais;
- resolver rodada.

### Etapa 6: Resultado e reset

Ao finalizar:

- imprimir resultado por mao;
- salvar log da rodada;
- limpar sinais Modbus;
- voltar para `waiting_start`;
- esperar novo gesto de 4 dedos.

## 21. Criterios para considerar integrado

O projeto pode ser considerado integrado quando:

1. `pytest -q` continua passando.
2. `blackjack_manual_simulator.py` reproduz os cenarios de regra.
3. `main.py --simulate-round` funciona com imagens salvas.
4. O robo responde a `startprog` por gesto de 4 dedos antes da rodada.
5. O PC le `busyIO` e `foto` de forma confiavel.
6. Cada pulso `foto` gera uma carta reconhecida e inserida na mao correta.
7. Acoes ilegais sao rejeitadas sem acionar o robo.
8. `split`, `double`, `hit` e `stand` movimentam o robo e atualizam o motor.
9. Dealer joga automaticamente ate 17.
10. Resultado final bate com as regras do documento.
