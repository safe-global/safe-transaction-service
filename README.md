[![Build Status](https://travis-ci.com/gnosis/safe-transaction-service.svg?branch=master)](https://travis-ci.com/gnosis/safe-transaction-service)
[![Coverage Status](https://coveralls.io/repos/github/gnosis/safe-transaction-service/badge.svg?branch=master)](https://coveralls.io/github/gnosis/safe-transaction-service?branch=master)
![Python 3.8](https://img.shields.io/badge/Python-3.8-blue.svg)
![Django 3](https://img.shields.io/badge/Django-3-blue.svg)

# Gnosis Transaction Service
Keeps track of transactions sent via Gnosis Safe contracts. It uses events and
[tracing](https://openethereum.github.io/JSONRPC-trace-module) to index the txs.

Transactions are detected in an automatic way, so there is no need of informing the service about the transactions as in
previous versions of the *Transaction Service*.

Transactions can also be sent to the service to allow offchain collecting of signatures or informing the owners about
a transaction that is pending to be sent to the blockchain.

[Swagger (Mainnet version)](https://safe-transaction.gnosis.io/)
[Swagger (Rinkeby version)](https://safe-transaction.rinkeby.gnosis.io/)

## Index of contents

- [Docs](https://docs.gnosis.io/safe/docs/services_transactions/)

## Setup for production
This is the recommended configuration for running a production Transaction service. `docker-compose` is required
for running the project.

Configure the parameters needed on `.env`. These parameters **need to be changed**:
- `ETHEREUM_NODE_URL`: Http/s address of a ethereum node. It can be the same than `ETHEREUM_TRACING_NODE_URL`.
- `ETHEREUM_TRACING_NODE_URL`: Http/s address of an OpenEthereum node with
[tracing enabled](https://openethereum.github.io/JSONRPC-trace-module).

If you need the Usd conversion for tokens don't forget to configure:
- `ETH_UNISWAP_FACTORY_ADDRESS`: Checksummed address of Uniswap Factory contract.
- `ETH_KYBER_NETWORK_PROXY_ADDRESS`: Checksummed address of Kyber Network Proxy contract.

If you don't want to use `trace_filter` for the internal tx indexing and just rely on `trace_block`, set:
- `ETH_INTERNAL_NO_FILTER=1`

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
- Add their addresses and the number of the block they were deployed (to optimize initial indexing) to
`safe_transaction_service/history/management/commands/setup_service.py`. Service is currently configured to support
_Mainnet_, _Rinkeby_, _Goerli_ and _Kovan_.
- If you have a custom `network id` you can change this line
`ethereum_network = ethereum_client.get_network()` to `ethereum_network_id = ethereum_client.w3.net.version` and use
the `network id` instead of the `Enum`.
- Only contracts that need to be configured are the **ProxyFactory** that will be used to deploy the contracts and
the **GnosisSafe**.


Add a new method using the addresses and block numbers for your network.
```python
def setup_my_network(self):
    SafeMasterCopy.objects.get_or_create(address='0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F',
                                             defaults={
                                                 'initial_block_number': 9084503,
                                                 'tx_block_number': 9084503,
                                             })
    ProxyFactory.objects.get_or_create(address='0x76E2cFc1F5Fa8F6a5b3fC4c8F4788F0116861F9B',
                                           defaults={
                                               'initial_block_number': 9084508,
                                               'tx_block_number': 9084508,
                                           })
```

Replace `handle` method for:
```python
    def handle(self, *args, **options):
        for task in self.tasks:
            _, created = task.create_task()
            if created:
                self.stdout.write(self.style.SUCCESS('Created Periodic Task %s' % task.name))
            else:
                self.stdout.write(self.style.SUCCESS('Task %s was already created' % task.name))

        self.stdout.write(self.style.SUCCESS('Setting up Safe Contract Addresses'))
        self.setup_my_network()
```

## Use admin interface
Services come with a basic administration web ui (provided by Django). A user must be created first to
get access:
```bash
docker exec -it safe-transaction-service_web_1 bash
python manage.py createsuperuser
```

Then go to the web browser and navigate to http://localhost:8000/admin/

## Contributors
- Denís Graña (denis@gnosis.pm)
- Giacomo Licari (giacomo.licari@gnosis.pm)
- Uxío Fuentefría (uxio@gnosis.pm)
