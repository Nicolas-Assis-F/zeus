# Zeus

Assistente pessoal persistente com persona, memória e iniciativa.

## Estado atual

Fundação inicial, criada em 18/09/2026. Há memória explícita em SQLite, comandos para registrar, consultar, corrigir e esquecer fatos, processo persistente e configuração de serviço. Ainda não há modelo de IA, conversa natural, agendamento, voz, câmeras ou integração doméstica. O processo não envia mensagens nem toma decisões nesta versão.

O desenvolvimento acontece no computador de Nicolas com Codex. O X99 é o destino de execução. A interface futura poderá ser acessada pelo navegador de outro computador, sem exigir monitor no servidor.

## Executar localmente

Requer Python 3.10 ou superior. Esta etapa usa apenas a biblioteca padrão, sem instalação de pacotes.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m zeus check
PYTHONPATH=src python3 -m zeus remember tratamento senhor
PYTHONPATH=src python3 -m zeus recall tratamento
PYTHONPATH=src python3 -m zeus run
```

Ctrl+C encerra o processo. Os dados ficam em `~/.local/state/zeus`, ou sob `XDG_STATE_HOME` quando configurado. Use `--state-dir CAMINHO` antes do subcomando para isolar uma execução de teste. Nenhum dado pessoal deve ir para o Git.

`forget` remove o registro da memória ativa; não é uma ferramenta de apagamento forense e não remove cópias de segurança anteriores.

## Documentação

- [Instalação da máquina e acesso remoto](docs/INSTALACAO.md)
- [Desenvolvimento aqui e execução no Zeus](docs/DESENVOLVIMENTO_E_DEPLOY.md)
- [Persona e próxima entrega](docs/PERSONA_E_PROXIMA_ENTREGA.md)
- [Diário e decisões](docs/DIARIO.md)
- `docs/referencia/`: plano mestre e histórico anterior, preservados como referência. As instruções atuais de instalação e execução estão nos guias acima.

O repositório é local. Nenhum remoto foi criado ou publicado. Não há servidor configurado nesta etapa.
