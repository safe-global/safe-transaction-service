![Build Status](https://github.com/safe-global/safe-transaction-service/workflows/Python%20CI/badge.svg?branch=master)
[![Coverage Status](https://coveralls.io/repos/github/safe-global/safe-transaction-service/badge.svg?branch=master)](https://coveralls.io/github/safe-global/safe-transaction-service?branch=master)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)
![Python 3.11](https://img.shields.io/badge/Python-3.11-blue.svg)
![Django 4](https://img.shields.io/badge/Django-4-blue.svg)
[![Docker Image Version (latest semver)](https://img.shields.io/docker/v/safeglobal/safe-transaction-service?label=Docker&sort=semver)](https://hub.docker.com/r/safeglobal/safe-transaction-service)

# Safe Transaction Service
Keeps track of transactions sent via Safe contracts. It uses events and
[tracing](https://openethereum.github.io/JSONRPC-trace-module) to index the txs.

Transactions are detected in an automatic way, so there is no need of informing the service about the transactions
as in previous versions of the *Transaction Service*.

Transactions can also be sent to the service to allow offchain collecting of signatures or informing the owners about
a transaction that is pending to be sent to the blockchain.

[Swagger (Mainnet version)](https://safe-transaction-mainnet.safe.global/)
[Swagger (Göerli version)](https://safe-transaction-goerli.safe.global/)

## Index of contents

- [Docs](https://docs.safe.global/safe-core-api/service-architecture)
- [Deploying the service](https://github.com/safe-global/safe-infrastructure)

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
when [SafeL2 version](https://github.com/safe-global/safe-contracts/blob/v1.3.0/contracts/GnosisSafeL2.sol) is used. **Only
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

For more parameters check [base.py](config/settings/base.py) file.

### Setup for a custom network

- If the network is not supported yet [contracts can be deployed using the deployment instructions
](https://github.com/safe-global/safe-contracts/tree/v1.3.0/contracts)
and then a PR should be provided [adding the deployment block number and the address](https://github.com/safe-global/safe-eth-py/blob/master/gnosis/safe/addresses.py) (address will be the same for every network).
- Only `ProxyFactory` and `GnosisSafeL2` must be configured. `+L2` must be added to the `Safe L2` contract versions, so the service knows the contract can be indexed using events. For us to accept the PR network must be on https://github.com/ethereum-lists/chains .
- You can always set this up later using the **admin panel** if your network is not supported, going to the **Master Copies** and **Proxy Factories**.
- **We recommend** using event indexing for every network where transaction fees are not relevant, so a tracing node is not required and everything can be indexed using events with the `Safe L2` version.


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

## Use admin interface
Services come with a basic administration web ui (provided by Django) by default on http://localhost:8000/admin/

A user must be created to get access:
```bash
docker exec -it safe-transaction-service-web-1 python manage.py createsuperuser
```

## Safe Contract ABIs and addresses
- [v1.3.0](https://github.com/safe-global/safe-deployments/blob/main/src/assets/v1.3.0/gnosis_safe.json)
- [v1.3.0 L2](https://github.com/safe-global/safe-deployments/blob/main/src/assets/v1.3.0/gnosis_safe_l2.json)
- [Other related contracts and previous Safe versions](https://github.com/safe-global/safe-deployments/blob/main/src/assets)

## Service maintenance

Service can run into some issues when running in production:

### Indexing issues
You can tell there are indexing issues if:
- Executed transactions are missing from the API (`all-transactions`, `multisig-transactions`, `module-transactions`... endpoints). If you use the [Safe{Wallet} Web client](https://github.com/safe-global/safe-wallet-web) you should check what is the current state of the Safe Client Gateway cache as it might have outdated data.
- Asset transfers (ERC20/721) are missing from `all-transactions` or `transfers` endpoints.
- You see error logs such as "Cannot remove owner" or similar inconsistent errors when `worker-indexer` is processing decoded data.

There are multiple options for this. Connect to either `web` or `worker` instances. Running commands inside of `tmux` is recommended
(installed by default):
- `python manage.py check_index_problems`: it will try to automatically fix missing transactions.
Tokens related transactions (ERC20/721) will not be fixed with this method. This method will take a while, as it needs to compare
database data with blockchain data for every Safe.
- `python manage.py reindex_master_copies --from-block-number X --addresses 0x111 0x222`: if you know the first problematic block,
it's faster if you trigger a manual reindex. `--addresses` argument is optional, but if you know the problematic Safes providing
them will make reindexing **way** faster, as only those Safes will be reindexed (instead of the entire collection).

If you see ERC20/ERC721 transfers missing:
- `python manage.py reindex_erc20 --from-block-number X --addresses 0x111 0x222`: same logic as with `reindex_master_copies`.

## FAQ
### Why `/v1/safes/{address}` endpoint shows a nonce that indicates that a transaction was executed but the transaction is not shown or marked as executed in the other endpoints?
`/v1/safes/{address}` endpoint uses `eth_call` from the RPC to get the current information for a Safe, so there's
no delay and as soon as a transaction is executed it will be updated. The other endpoints rely on polling, indexing
decoding and processing of traces/events and take longer (shouldn't be more than half a minute).

### How do you handle reorgs?
When indexed every block is marked as `not confirmed` unless it has some depth (configured via `ETH_REORG_BLOCKS` environment variable).
`Not confirmed` blocks are checked periodically to check if the blockchain `blockHash` for that `number`
changed before it reaches the desired number of `confirmations`, if that's the case, all blocks from that block and the transactions related
are deleted and indexing is restarted to the last `confirmed` block.

### If I add my chain to [safe-eth-py](https://github.com/safe-global/safe-eth-py/blob/master/gnosis/safe/addresses.py) will you support it?
No, for a chain to be supported we need to set up a dedicated infra for that network
and [have a proper RPC](https://docs.safe.global/safe-core-api/rpc-requirements)

### How can I interact with service?
Aside from using standard HTTP requests:
- [Safe{Core} API Kit](https://github.com/safe-global/safe-core-sdk/tree/main/packages/api-kit)
- [Safe-eth-py](https://github.com/safe-global/safe-eth-py)
- [Safe CLI](https://github.com/5afe/safe-cli): It has a `tx-service` mode to gather offchain signatures.

### What chains do you officially support?
https://docs.safe.global/safe-core-api/available-services

### What means banned field in SafeContract model?
The `banned` field in the `SafeContract` model is used to prevent indexing of certain Safes that have an unsupported `MasterCopy` or unverified proxies that have issues during indexing. This field does not remove the banned Safe and indexing can be resumed once the issue has been resolved.

## Troubleshooting

### Issues installing grpc on a Mac M1

If you face issues installing the `grpc` dependency locally (required by this project) on a M1 chip, set `GRPC_PYTHON_BUILD_SYSTEM_OPENSSL=1` and `GRPC_PYTHON_BUILD_SYSTEM_ZLIB=1` and then try to install the dependency again.

## Contributors
[See contributors](https://github.com/safe-global/safe-transaction-service/graphs/contributors)
