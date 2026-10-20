# MaisProdutive — integração experimental Yoosee

Objetivo: acessar câmeras próprias de locais distintos pelo navegador, sem VPN,
e posteriormente detectar pessoas e emitir alertas.

## Estado real

- Implementado: cliente HTTP de login e consulta paginada das câmeras, baseado no
  SDK Gwell publicado; painel local; diagnóstico de conectividade.
- Verificado: testes automatizados com respostas sintéticas e requisições HTTP
  reais ao painel local. Esses testes não comprovam compatibilidade com a nuvem.
- **Não verificado:** autenticação de uma conta real, listagem real de câmeras ou
  compatibilidade com o firmware 37.0.14 mostrado pelo usuário.
- **Não implementado:** transporte P2P de vídeo, reprodução no navegador,
  detecção de pessoas, notificações e hospedagem pública com autenticação.

O painel não apresenta vídeos ou câmeras simuladas. Ele só lista câmeras recebidas
da API e informa que o vídeo permanece indisponível.

## Executar

Python 3.10 ou posterior, somente biblioteca padrão. Sem dependências para instalar.

```sh
cd /workspace/maisprodutive
python -m unittest discover -s tests -v
python server.py --port 8080
```

O servidor escuta apenas em loopback. O painel é uma bancada local e **não está
preparado para exposição pública**. Não faça encaminhamento de porta ou exposição
remota antes de acrescentar HTTPS e autenticação de usuários. A interface de
onboarding não oferece visualização web desse endereço local.

## Configuração do SDK

Configure no processo do servidor, usando as configurações seguras do ambiente:

| Variável | Finalidade |
| --- | --- |
| `YOOSEE_APP_ID` | Identificação válida do aplicativo, fornecida pelo serviço Gwell |
| `YOOSEE_APP_TOKEN` | Token correspondente à identificação do aplicativo |
| `YOOSEE_PACKAGE` | Nome de pacote registrado para esse aplicativo; padrão `com.yoosee` |
| `YOOSEE_APP_VERSION` | Versão SDK com quatro componentes; padrão `00.00.00.01`, apenas para pesquisa |
| `YOOSEE_API_HOST` | Um dos quatro hosts documentados no cliente; padrão `api3.cloud-links.net` |

O SDK publicado exige identificação de aplicativo **além do login do usuário**.
Não há credenciais de aplicativo válidas confirmadas neste projeto. Os valores
de teste antigos do exemplo não são incluídos nem tratados como válidos.
O pacote e a versão devem corresponder ao cadastro Gwell; os padrões não
comprovam compatibilidade com o aplicativo oficial atual.

Depois de configurar esses dados, o painel permite testar o login da conta própria.
A senha não é gravada no repositório, nos logs ou em armazenamento do navegador.
As sessões ficam na memória por até 20 minutos; sair apaga a sessão local, sem
invocar o logout remoto do aplicativo oficial. Reiniciar o servidor apaga todas.

Para usar a CLI, configure também `YOOSEE_USERNAME` e `YOOSEE_PASSWORD` no ambiente:

```sh
python yoosee.py probe
python yoosee.py devices
```

Não passe senhas em argumentos de shell, arquivos versionados ou mensagens do chat.
O cliente precisa da senha real em memória para calcular o hash exigido pelo SDK;
um placeholder de segredo substituído apenas por proxy HTTPS não funciona para
esse cálculo local. Nunca copie valores de segredos para este README.

## Rede e bloqueios

O cliente usa somente HTTPS com verificação de certificado e de hostname. Não
segue redirecionamentos, pois o protocolo legado usa parâmetros de URL para
autenticação. As exceções expostas não contêm URLs, sessões ou hashes de senha.

Destinos HTTP identificados no SDK:

- `api1.cloudlinks.cn`
- `api2.cloudlinks.cn`
- `api3.cloud-links.net`
- `api4.cloud-links.net`

O diagnóstico atual não conseguiu conectar aos serviços testados: o proxy retornou
403 no túnel HTTPS. Salvar uma lista de domínios no rascunho não aplica a alteração
à máquina e não comprova que a nuvem aceita o protocolo legado.

Para obter o app atual, a página do APKPure aponta para o pacote `com.yoosee` e
para `download.yoosee.com`. O download do APK/XAPK não foi concluído. A assinatura
do app atual não foi verificada. Não foi instalado nem executado um APK.

## Próximo marco de validação

1. Obter o aplicativo atual por fonte verificável e confirmar sua assinatura.
2. Verificar se a autenticação e os dados de aplicativo atuais são compatíveis
   com o SDK publicado; atualizar o cliente somente com evidência do protocolo.
3. Com rede liberada e credenciais inseridas de forma segura, testar uma única
   autenticação e uma consulta de câmeras, sem repetição automática de logins.
4. Implementar e testar o transporte P2P: o SDK disponível inclui somente
   bibliotecas Android ARM/ARM64, incompatíveis diretamente com o host Linux x86_64.
   Seria necessário um runtime Android compatível ou uma implementação própria
   do protocolo. O ambiente atual não expõe `/dev/kvm` ou dispositivos binder.
5. Só depois de receber quadros reais: converter vídeo para o navegador, implantar
   autenticação/HTTPS para acesso online e integrar detecção e alertas.

Detalhes e fontes em [docs/research.md](docs/research.md).
