# Radar da Carteira

Aplicação web local para acompanhar uma carteira de investimentos com cotações, dividendos, patrimônio, projeções e sugestões quantitativas para novos aportes.

O projeto roda com **Python + SQLite + HTML/CSS/JavaScript**, sem framework e sem dependências Python externas obrigatórias.

## Funcionalidades

- Cadastro e atualização de ativos em banco SQLite local.
- Consulta de cotação, P/VP e histórico de dividendos nas páginas públicas do Investidor10.
- Separação por categorias:
  - Stocks internacionais
  - REITs internacionais
  - ETFs internacionais
  - Ações brasileiras
  - Fundos imobiliários brasileiros
- Gestão de carteira com quantidade de ativos, patrimônio em BRL e USD e gráficos de composição.
- Tabelas de dividendos por categoria, com D.Y. bruto e líquido para ativos internacionais.
- Comparativo de alocação atual x recomendada para FIIs.
- Planejamento de aportes para carteira nacional e internacional.
- Páginas de gerenciamento para FIIs, ações brasileiras, stocks internacionais, REITs e ETFs.
- Instalação opcional como serviço `systemd` em Raspberry Pi/Linux.

## Executar no Windows

No PowerShell, dentro da pasta do projeto:

```powershell
.\run.ps1
```

Depois acesse:

```text
http://127.0.0.1:8080/
```

## Executar manualmente

```bash
python server.py
```

Por padrão, o servidor usa:

```text
HOST=127.0.0.1
PORT=8080
```

Você pode alterar com variáveis de ambiente:

```bash
PORTFOLIO_HOST=0.0.0.0 PORTFOLIO_PORT=8080 python3 server.py
```

## Instalar no Raspberry Pi ou Linux

Copie o projeto para o Raspberry Pi e execute:

```bash
chmod +x install_raspberry.sh
sudo ./install_raspberry.sh
```

O instalador:

- copia o projeto para `/opt/investment-portfolio-app`;
- cria o banco em `data/portfolio.db`, se ainda não existir;
- configura o servidor em `0.0.0.0:8080`;
- cria e inicia o serviço `investment-portfolio-app.service`;
- habilita inicialização automática no boot.

Comandos úteis:

```bash
sudo systemctl status investment-portfolio-app
sudo systemctl restart investment-portfolio-app
journalctl -u investment-portfolio-app -f
```

Na rede local, acesse:

```text
http://IP_DO_RASPBERRY:8080/
```

## Páginas principais

- `/` - visão geral da carteira e ativos monitorados.
- `/manage.html` - banco de ativos e posições.
- `/fiis-management.html` - carteira local de fundos imobiliários.
- `/stocks-management.html` - carteira local de ações brasileiras.
- `/international-stocks-management.html` - carteira local de stocks internacionais.
- `/reits-management.html` - carteira local de REITs internacionais.
- `/etfs-management.html` - carteira local de ETFs internacionais.
- `/contribution-plan.html` - planejamento de aportes.

## Banco de dados

O banco SQLite fica em:

```text
data/portfolio.db
```

Ele é criado e migrado automaticamente pelo `server.py`.

## Metodologia de projeções

Na seção **Melhor perspectiva para novos aportes**, a aplicação exibe:

- **D.Y. aparado**: usa os últimos 7 anos completos, removendo o maior e o menor ano quando há histórico suficiente.
- **D.Y. ponderado**: usa os últimos 7 anos completos com pesos maiores para anos mais recentes.

A pontuação quantitativa usa:

```text
50% média entre D.Y. aparado e D.Y. ponderado
20% recorrência
20% estabilidade
10% evolução anual
```

Para ativos internacionais, a visão líquida considera retenção fixa estimada de 30% sobre dividendos.

## Fonte de dados

O coletor usa páginas públicas do Investidor10:

- Stocks internacionais: `/stocks/{ticker}/`
- REITs internacionais: `/reits/{ticker}/`
- ETFs internacionais: `/etfs-global/{ticker}/`
- Ações brasileiras: `/acoes/{ticker}/`
- Fundos imobiliários brasileiros: `/fiis/{ticker}/`

Mudanças no HTML, instabilidade ou bloqueios da fonte podem exigir ajustes no coletor. Evite atualizações em intervalos muito curtos e confira os termos de uso da fonte.

## Observação

As sugestões de aporte são quantitativas e servem como apoio à análise. Elas não são recomendação de investimento.
