[![Build Status](https://travis-ci.org/gnosis/safe-transaction-service.svg?branch=master)](https://travis-ci.org/gnosis/safe-transaction-service)
[![Coverage Status](https://coveralls.io/repos/github/gnosis/safe-transaction-service/badge.svg?branch=master)](https://coveralls.io/github/gnosis/safe-transaction-service?branch=master)
![Python 3.8](https://img.shields.io/badge/Python-3.8-blue.svg)
![Django 3](https://img.shields.io/badge/Django-3-blue.svg)

# Gnosis Transaction Service
Keeps track of transactions sent via Gnosis Safe contracts. It uses events and 
[tracing](https://wiki.parity.io/JSONRPC-trace-module) to index the txs.

Transactions are detected in an automatic way, so there is no need of informing the service about the transactions as in
previous versions of the *Transaction Service*.

Transactions can also be sent to the service to allow offchain collecting of signatures or informing the owners about
a transaction that is pending to be sent to the blockchain.

[Swagger (Mainnet version)](https://safe-transaction.gnosis.io/)
[Swagger (Rinkeby version)](https://safe-transaction.rinkeby.gnosis.io/)

## Index of contents

- [Docs](https://gnosis-safe.readthedocs.io/en/latest/services/transactions.html)


## Setup for production
This is the recommended configuration for running a production Transaction service. `docker-compose` is required
for running the project.

Configure the parameters needed on `.env`. These parameters **need to be changed**:
- `ETHEREUM_NODE_URL`: Http/s address of a ethereum node. It can be the same than `ETHEREUM_TRACING_NODE_URL`.
- `ETHEREUM_TRACING_NODE_URL`: Http/s address of a Ethereum Parity node with
[tracing enabled](https://wiki.parity.io/JSONRPC-trace-module).

If you need the Usd conversion for tokens don't forget to configure:
- `ETH_UNISWAP_FACTORY_ADDRESS`: Checksummed address of Uniswap Factory contract.
- `ETH_KYBER_NETWORK_PROXY_ADDRESS`: Checksummed address of Kyber Network Proxy contract.

For more parameters check `base.py` file.

Then:
```bash
docker-compose build --force-rm
docker-compose up
```

The service should be running in `localhost:8000`. You can test everything is set up:

```bash
curl 'http://localhost:8000/api/v1/about/'
```

For example, to set up a Göerli node:

Run a Parity node in your local computer:
```bash
parity --chain goerli --tracing on --db-path=/media/ethereum/parity --unsafe-expose
```

Edit `.env` so docker points to he host Parity:
```
ETHEREUM_NODE_URL=http://172.17.0.1:8545
ETHEREUM_TRACING_NODE_URL=http://172.17.0.1:8545
```

Then:
```bash
docker-compose build --force-rm
docker-compose up
```

## Contributors
- Denís Graña (denis@gnosis.pm)
- Giacomo Licari (giacomo.licari@gnosis.pm)
- Uxío Fuentefría (uxio@gnosis.pm)
