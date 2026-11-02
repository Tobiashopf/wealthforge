# Roadmap

Wealthforge 0.1 covers the basics: assets of every class, buys and sales,
valuations, income, automatic B3 and US quotes, the USD/BRL rate and an
overview of net worth and allocation. This is the work planned next, roughly
in order. Estimates are for one person working with an AI coding assistant.

## Next up

- [ ] **Net worth history** (~5 h): store a daily snapshot of every holding and
      draw net worth and allocation over time on the overview page.
- [ ] **Edit transactions, valuations and income** (~2 h): today a wrong record
      has to be deleted and typed again.
- [ ] **Liabilities** (~4 h): mortgages and other debts, linked to the asset they
      finance, so the overview shows net equity and true net worth.
- [ ] **Property costs and net yield** (~4 h): condo fees, IPTU, maintenance and
      vacancy for real estate, with gross and net rental yield per property.
- [ ] **Target allocation and rebalancing** (~4 h): set a target per asset class
      or type and see how much to buy or sell to get back on target.

## Data in and out

- [ ] **CSV import** (~4 h): import trades from a spreadsheet or broker export,
      with a preview step and duplicate detection.
- [ ] **Export and backup** (~2 h): download everything as CSV/JSON and restore
      from a backup file.
- [ ] **Corporate actions** (~3 h): splits, reverse splits and bonus shares
      (bonificações) that change quantity without changing cost.

## Prices and currencies

- [ ] **Crypto quotes** (~2 h): CoinGecko provider for BTC, ETH and others.
- [ ] **More currencies** (~2 h): EUR and GBP through the PTAX "CotacaoMoeda"
      endpoints, with the currency list driven by the data.
- [ ] **Fixed income accrual** (~5 h): update CDI-, Selic- and IPCA-linked bonds
      automatically from the Banco Central SGS series instead of by hand.
- [ ] **Scheduled refresh** (~2 h): refresh quotes on startup and once a day
      while the app is open.
- [ ] **Historical backfill** (~3 h): fetch past prices so the history chart is
      complete from the first trade.

## Reports

- [ ] **Monthly realized gains report** (~3 h): sales per month with gain or
      loss, as a starting point for the yearly tax return.
- [ ] **Income calendar** (~2 h): dividends, rent and distributions by month,
      with a 12-month total per asset.

## Product polish

- [ ] **Portuguese interface** (~3 h): translate the UI (pt-BR) and let the user
      choose the language.
- [ ] **Windows installer** (~3 h): a single executable built with PyInstaller,
      plus a Start-menu shortcut that opens the app.
- [ ] **Docker image** (~1 h) for people who run it on a home server.
- [ ] **Accessibility pass** (~2 h): keyboard navigation, focus states, screen
      reader labels for the allocation bars.

Ideas and bug reports are welcome in the
[issues](https://github.com/Tobiashopf/wealthforge/issues).
