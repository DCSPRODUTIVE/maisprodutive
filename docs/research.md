# Evidências da investigação — 20/10/2026

## Fontes consultadas

- [GwellDemo, conta indicada pelo demo antigo](https://github.com/jwkj/GwellDemo).
  README com atualizações até 2019; exemplos de login, sessão, consulta e P2P.
- [GwellDemo antigo](https://github.com/dxsdyhm/GwellDemo).
- [GWNet para iOS](https://github.com/GWTimes/GWNet).
- [Página Yoosee no APKPure](https://apkpure.com/yoosee/com.yoosee).
  A página acessível anuncia Gwell, pacote `com.yoosee`, versões 6.45/6.45.1 e
  aponta para `https://download.yoosee.com`. Isso é informação do catálogo,
  não inspeção de um APK ou confirmação da versão instalada no celular.
- [YooFree](https://github.com/Wennington123/YooFree): cliente local; seu README
  não comprova login remoto na nuvem Yoosee.

Nenhum código de terceiros foi executado para autenticar uma conta ou acessar uma
câmera. A decompilação é estática. O decompilador CFR 0.152 foi obtido pelo Maven
Central e seu SHA-256 conferido com o checksum publicado no mesmo repositório.

## Artefatos inspecionados

Obtidos por HTTPS em `raw.githubusercontent.com/jwkj/GwellDemo/master/app/libs/`:

| Arquivo | SHA-256 observado |
| --- | --- |
| libhttp-release.aar | `8277901ab2476aa810e3ff069599414f016db3f746239fd4c5586a68a9259b91` |
| p2p-core-release.aar | `11d6c2032ab52ce8502dcbca66f203929397af2c9920d58c29388713fabf8d5b` |

Esses hashes identificam os arquivos baixados; não equivalem a assinatura do
fabricante. Artefatos e fontes decompiladas permanecem fora do checkout, em
`/workspace/scratch/yoosee-research`, sem redistribuição das bibliotecas no projeto.

## Camada HTTP

Classes inspecionadas: `HttpService`, `HttpMethods`, `HttpSender`, `HttpRegistrant`,
`ServicePath`, `LoginGResult`, `LoginResult`, `LoadDeviceResult`, `DeviceSync`, `MD5`.

- Login: POST `Users/LoginCheck.ashx`, com parâmetros na query, incluindo `User`,
  `Pwd`, `VersionFlag`, `SessionID2` e `AnonymousId`.
- Parâmetros comuns: `AppID`, `AppToken`, `Language`, `AppOS=3`, `AppName`,
  `AppVersion`, `PackageName` e `ApiVersion=1`.
- O hash do SDK antigo é MD5 hexadecimal em maiúsculas. Sua implementação usa
  quantidade de caracteres UTF-16 como comprimento de bytes UTF-8; o cliente
  experimental reproduz esse comportamento para senhas não ASCII.
- IDs de conta numéricos iniciados em zero são convertidos para inteiro de 32
  bits com bit de sinal. A resposta faz a conversão inversa.
- Sessão: `UserID`, `SessionID`, `SessionID2`, `P2PVerifyCode1`, `P2PVerifyCode2`;
  há também uma entidade com nomes equivalentes dentro de `data`.
- Consulta: POST `Relationship/LoadDeviceInfo.ashx`, com `PreDeviceID`,
  `RequestCount`, `MyUpgradeFlag`, `UpgCheckList`, `NotReturnDeleted` e sessão.
- Dispositivos incluem `devId`, `remarkName`, `secretKey` e metadados. Apenas
  identificador e nome são retornados ao painel; segredos não são repassados.

A presença de duas entidades de resposta não comprova que ambas são aceitas hoje.
O cliente rejeita respostas desconhecidas, erros e sessões incompletas. Não troca
automaticamente de servidor após uma falha de login nem tenta adivinhar senhas.

O SDK antigo contém código que aceita certificados/hostnames sem validação. Essa
prática **não foi reproduzida**: o cliente usa a validação TLS padrão do Python.

## Vídeo/P2P

`p2p-core-release.aar` inclui `libmediaplayer.so`, `libp2pav.so`, `libSDL.so`,
`libmp4v2.so`, nas arquiteturas `armeabi` e `arm64-v8a`. A inspeção ELF com
`readelf -d` identifica dependências Android, como `libandroid.so`, `liblog.so`,
`libEGL.so` e `libGLESv2.so`. A classe `MediaPlayer` declara métodos JNI nativos
de conexão, controle e vídeo. Copiar essa biblioteca para Python não implementa
essas funções no Linux x86_64.

O README descreve P2P 3.0 com `localAreaIp=0` para comunicação fora da LAN. Isso
indica suporte remoto no SDK histórico; não prova passagem por CGNAT ou suporte
ao firmware atual. Ainda não foram enviados pacotes P2P ou recebidos quadros.

## Resultados atuais

Testes automatizados usam fixtures sintéticas e chamadas reais somente ao servidor
local. Não representam login ou vídeo real. O diagnóstico de rede separado registra
a disponibilidade dos quatro hosts sem credenciais. Rede liberada, identificação
de aplicativo válida e credenciais de usuário continuam necessárias para o teste
real. Nenhuma detecção de pessoas ou notificação foi implementada.
