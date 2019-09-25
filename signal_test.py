import os
import signal


def raise_task(signum, frame):
    raise Exception('hola')


def raise_task(request):
    def fn(signum, frame):
        print('Received SIGTERM on task')
        raise OSError(f'SIGTERM Received for {request}')
    return fn

signal.signal(signal.SIGTERM, raise_task('hola'))


print(os.getpid())

while True:
    pass
