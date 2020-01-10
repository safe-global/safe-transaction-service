[![Build Status](https://travis-ci.org/gnosis/safe-transaction-service.svg?branch=master)](https://travis-ci.org/gnosis/safe-transaction-service)
[![Coverage Status](https://coveralls.io/repos/github/gnosis/safe-transaction-service/badge.svg?branch=master)](https://coveralls.io/github/gnosis/safe-transaction-service?branch=master)
![Python 3.8](https://img.shields.io/badge/Python-3.8-blue.svg)
![Django 2.2](https://img.shields.io/badge/Django-2.2-blue.svg)

# Gnosis Transaction Service
Keeps track of transactions sent via Gnosis Safe contracts. It uses events and 
[tracing](https://wiki.parity.io/JSONRPC-trace-module).

Transactions are detected in an automatic way, so there is no need of informing the service about the transactions as in
previous versions of the *Transaction Service*

[Swagger (Mainnet version)](https://safe-transaction.gnosis.io/)
[Swagger (Rinkeby version)](https://safe-transaction.rinkeby.gnosis.io/)

## Index of contents

- [Docs](https://gnosis-safe.readthedocs.io/en/latest/services/transactions.html)

## Contributors
- Denís Graña (denis@gnosis.pm)
- Giacomo Licari (giacomo.licari@gnosis.pm)
- Uxío Fuentefría (uxio@gnosis.pm)
