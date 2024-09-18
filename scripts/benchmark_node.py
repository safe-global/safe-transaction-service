import time
from contextlib import contextmanager

from gevent.pool import Pool
from safe_eth.eth import EthereumClient


@contextmanager
def timing(function: str = ""):
    start = time.time()
    yield
    print(function, "Elapsed:", time.time() - start)


if __name__ == "__main__":
    from gevent import monkey

    monkey.patch_all()  # noqa
    pool = Pool(200)
    e = EthereumClient("http://localhost:8545")
    blocks_to_fetch = list(range(12773522 - 10000, 12773522))

    with timing("Batch get blocks"):
        e.get_blocks(blocks_to_fetch)

    # with timing('Secuential get blocks'):
    #     for block in blocks_to_fetch:
    #         e.get_block(block)

    with timing("Parallel get blocks"):
        jobs = [pool.spawn(e.get_block, block) for block in blocks_to_fetch]
        pool.join()
