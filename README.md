# Radar da Carteira

Aplicação web local para organizar ações, REITs, ETFs e FIIs, consultando cotação e histórico de dividendos nas páginas públicas do Investidor10.

## Executar

No PowerShell:

```powershell
.\run.ps1
```

Depois acesse `http://127.0.0.1:8080`.

O banco SQLite é criado automaticamente em `data/portfolio.db`. A aplicação não exige bibliotecas Python externas.

## Categorias e rotas

- Stocks internacionais: `/stocks/{ticker}/`
- REITs internacionais: `/reits/{ticker}/`
- ETFs internacionais: `/etfs-global/{ticker}/`
- Ações brasileiras: `/acoes/{ticker}/`
- Fundos imobiliários brasileiros: `/fiis/{ticker}/`

O coletor usa somente páginas públicas. Mudanças no HTML ou bloqueios do site de origem podem exigir ajustes. Evite atualizações em intervalos muito curtos e confira os termos de uso da fonte.
