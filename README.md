![Build Status](https://github.com/gnosis/safe-transaction-service/workflows/Python%20CI/badge.svg?branch=master)
[![Coverage Status](https://coveralls.io/repos/github/gnosis/safe-transaction-service/badge.svg?branch=master)](https://coveralls.io/github/gnosis/safe-transaction-service?branch=master)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)
![Python 3.10](https://img.shields.io/badge/Python-3.10-blue.svg)
![Django 3](https://img.shields.io/badge/Django-3-blue.svg)
[![Docker Image Version (latest semver)](https://img.shields.io/docker/v/safeglobal/safe-transaction-service?label=Docker&sort=semver)](https://hub.docker.com/r/safeglobal/safe-transaction-service)

# Gnosis Transaction Service
Keeps track of transactions sent via Gnosis Safe contracts. It uses events and
[tracing](https://openethereum.github.io/JSONRPC-trace-module) to index the txs.

Transactions are detected in an automatic way, so there is no need of informing the service about the transactions
as in previous versions of the *Transaction Service*.

Transactions can also be sent to the service to allow offchain collecting of signatures or informing the owners about
a transaction that is pending to be sent to the blockchain.

[Swagger (Mainnet version)](https://safe-transaction.gnosis.io/)
[Swagger (Rinkeby version)](https://safe-transaction.rinkeby.gnosis.io/)

## Index of contents

- [Docs](https://docs.gnosis.io/safe/docs/services_transactions/)

## Setup for development
Use a virtualenv if possible:

```bash
python -m venv venv
```

Then enter the virtualenv and install the dependencies:

```bash
source venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install -f
cp .env.dev .env
./run_tests.sh
```

## Setup for development using docker
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

## Setup for production (event indexing)
Since **version 3.0.0** transaction service can be configured to rely on **event indexing**
when [SafeL2 version](https://github.com/gnosis/safe-contracts/blob/v1.3.0/contracts/GnosisSafeL2.sol) is used. **Only
contracts from v1.3.0 onwards with L2 events will be indexed.**

An example environment file can be used for the L2 setup:
```bash
cp .env.l2.sample .env
```

Edit `.env` file to add `ETHEREUM_NODE_URL` (on the example a `Polygon` public node is used)
and remember to modify `DJANGO_SECRET_KEY` to **use a strong key**. The rest of the
configuration does not need to be modified. Then:

```bash
docker-compose build --force-rm
docker-compose up
```

If the network is not supported yet [contracts can be deployed using the deployment instructions
](https://github.com/gnosis/safe-contracts/tree/v1.3.0/contracts)
and then a PR should be provided to this service [adding the deployment block number and the address (address
will be the same for every network)](safe_transaction_service/history/management/commands/setup_service.py). Only
`ProxyFactory` and `GnosisSafeL2` must be configured. `+L2` must be added to the Safe contract versions, so the service
knows the contract can be indexed using events.

For more parameters check [base.py](config/settings/base.py) file.

## Setup for production (tracing mode)
This is the recommended configuration for running a production Transaction service. `docker-compose` is required
for running the project.

``bash
cp .env.tracing.sample .env
``

Configure the parameters needed on `.env`. These parameters **need to be changed**:
- `DJANGO_SECRET_KEY`: Use a **strong key**.
- `ETHEREUM_NODE_URL`: Http/s address of a ethereum node. It can be the same than `ETHEREUM_TRACING_NODE_URL`.
- `ETHEREUM_TRACING_NODE_URL`: Http/s address of an OpenEthereum node with
[tracing enabled](https://openethereum.github.io/JSONRPC-trace-module).

If you don't want to use `trace_filter` for the internal tx indexing and just rely on `trace_block`, set:
- `ETH_INTERNAL_NO_FILTER=1`

For more parameters check [base.py](config/settings/base.py) file.

Then:
```bash
docker-compose build --force-rm
docker-compose up
```

The service should be running in `localhost:8000`. You can test everything is set up:

```bash
curl 'http://localhost:8000/api/v1/about/'
```

You can go to http://localhost:5555/ to check the status of the task queue, also you can configure
[prometheus metrics](https://flower.readthedocs.io/en/latest/prometheus-integration.html).

For example, to set up a Göerli node:

Run an OpenEthereum node in your local computer:
```bash
openethereum --chain goerli --tracing on --db-path=/media/ethereum/openethereum --unsafe-expose
```

Edit `.env` so docker points to the host OpenEthereum node:
```
ETHEREUM_NODE_URL=http://172.17.0.1:8545
ETHEREUM_TRACING_NODE_URL=http://172.17.0.1:8545
```

Then:
```bash
docker-compose build --force-rm
docker-compose up
```

## Setup for private network
Instructions for production still apply, but some additional steps are required:
- Deploy the last version of the [Safe Contracts](https://github.com/gnosis/safe-contracts) on your private network.
- [Add their addresses and the number of the block they were deployed
](safe_transaction_service/history/management/commands/setup_service.py) (to optimize initial indexing).
Service is currently configured to support _Mainnet_, _Rinkeby_, _Goerli_, _Kovan_, _xDai_, _Polygon_, _EWC_...
- If you have a custom `network id` you can change this line
`ethereum_network = ethereum_client.get_network()` to `ethereum_network_id = ethereum_client.w3.net.version` and use
the `network id` instead of the `Enum`.
- Only contracts that need to be configured are the **ProxyFactory** that will be used to deploy the contracts and
the **GnosisSafe/GnosisSafeL2**.

## Use admin interface
Services come with a basic administration web ui (provided by Django) by default on http://localhost:8000/admin/

A user must be created to get access:
```bash
docker exec -it safe-transaction-service-web-1 python manage.py createsuperuser
```

## Safe Contract ABIs and addresses
- [v1.3.0](https://github.com/gnosis/safe-deployments/blob/main/src/assets/v1.3.0/gnosis_safe.json)
- [v1.3.0 L2](https://github.com/gnosis/safe-deployments/blob/main/src/assets/v1.3.0/gnosis_safe_l2.json)
- [Other related contracts and previous Safe versions](https://github.com/gnosis/safe-deployments/blob/main/src/assets)


## Troubleshooting

### Issues installing grpc on a Mac M1

If you face issues installing the `grpc` dependency locally (required by this project) on a M1 chip, set `GRPC_PYTHON_BUILD_SYSTEM_OPENSSL=1` and `GRPC_PYTHON_BUILD_SYSTEM_ZLIB=1` and then try to install the dependency again.

## Contributors
[See contributors](https://github.com/gnosis/safe-transaction-service/graphs/contributors)
